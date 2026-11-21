import asyncio
import socket
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from brainsolpi import brain as brain_mod
from brainsolpi import tools
from brainsolpi.auth import Auth, hash_pin
from brainsolpi.brain import Brain
from brainsolpi.cli import build_parser
from brainsolpi.commands import Commands
from brainsolpi.config import Settings
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import DT, CommandError, Engine
from brainsolpi.hub import Hub
from brainsolpi.jsonio import read_json
from brainsolpi.server import make_app
from brainsolpi.state import StateStore
from brainsolpi.store import ExperimentStore
from brainsolpi.sysinfo import SysInfo

# 09:20 local time on the simulated day of the planner, two hours ahead of utc
NOW = int(datetime(2025, 6, 4, 7, 20, tzinfo=timezone.utc).timestamp())


def plan_state(**over):
    st = {
        "now": NOW, "speed": 60.0, "paused": False,
        "site": {"utc_offset_h": 2.0, "heading": 180.0},
        "day": {"date": "2025-06-04"},
        "sun": {"az": 120.0, "az_rel": -60.0, "el": 35.0, "up": True},
        "pose": {"pan": 30.0, "tilt": 50.0, "offset": 20.0, "why": "light"},
        "meas": {"dni": 800.0, "dhi": 100.0},
        # the planner sends much more, the pi reads only its few fields
        "path_today": {"t": list(range(500))},
    }
    for key, value in over.items():
        st[key] = value
    return st


class FakeBrain:
    # the brain server in small: a recipe route, the planner page with big files and its state

    def __init__(self):
        self.state = plan_state()
        self.down = False
        self.seen = []
        self.script = b"console.log('plan');\n" * 15000
        self.font = bytes(range(256)) * 1600
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_post("/recipe", self.recipe)
        app.router.add_get("/plan", self.slash)
        app.router.add_get("/plan/", self.page)
        app.router.add_get("/plan/app.js", self.js)
        app.router.add_get("/plan/font.woff2", self.woff)
        app.router.add_get("/plan/api/state", self.plan)
        app.router.add_post("/plan/api/speed", self.speed)
        app.router.add_get("/slow", self.slow)
        self.server = TestServer(app)

    async def __aenter__(self):
        await self.server.start_server()
        self.url = str(self.server.make_url("")).rstrip("/")
        return self

    async def __aexit__(self, *exc):
        await self.server.close()

    async def health(self, request):
        return web.json_response({"ok": True, "model": "fake"})

    async def recipe(self, request):
        self.seen.append(request)
        body = await request.text()
        return web.json_response(
            {"got": body, "ct": request.headers.get("Content-Type"), "query": request.query_string,
             "cookie": request.headers.get("Cookie")},
            headers={"Access-Control-Allow-Origin": "https://elsewhere"},
        )

    async def slash(self, request):
        # what a static mount does without the slash, an absolute address of the brain itself
        raise web.HTTPTemporaryRedirect(str(request.url.with_path("/plan/")))

    async def page(self, request):
        return web.Response(text="<!doctype html><title>plan</title>", content_type="text/html")

    async def js(self, request):
        return web.Response(body=self.script, content_type="application/javascript")

    async def woff(self, request):
        return web.Response(body=self.font, content_type="font/woff2")

    async def plan(self, request):
        if self.down:
            return web.json_response({"ok": False, "error": "nicht bereit"}, status=503)
        return web.json_response(self.state)

    async def speed(self, request):
        return web.json_response({"ok": True, "speed": (await request.json())["speed"]})

    async def slow(self, request):
        await asyncio.sleep(2.0)
        return web.Response(text="late")


class Stack:
    # the pi with the sim driver, its page server and a brain at the given address

    def __init__(self, tmp_path, url=None):
        self.driver = SimDriver(seed=1)
        self.hub = Hub()
        self.brain = Brain(url)
        self.engine = Engine(
            Settings(), StateStore(None), self.driver, store=ExperimentStore(tmp_path / "exp"),
            data_dir=tmp_path, sink=self.hub, sysinfo=SysInfo(), brain=self.brain,
        )
        self.hub.engine = self.engine
        self.auth = Auth(hash_pin("2468", iterations=2000))
        self.commands = Commands(self.engine)
        self.app = make_app(self.engine, self.hub, self.auth, self.commands, None)

    async def __aenter__(self):
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.engine.run(self.stop))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        return self

    async def __aexit__(self, *exc):
        self.stop.set()
        await asyncio.wait_for(self.task, 5)
        await self.hub.close_all()
        await self.client.close()
        await self.brain.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_get_and_post_go_through_unchanged(tmp_path):
    async with FakeBrain() as fb, Stack(tmp_path, fb.url) as s:
        c = s.client
        info = await (await c.get("/api/info")).json()
        assert info["brain"] is True
        r = await c.get("/brain/health")
        assert r.status == 200 and await r.json() == {"ok": True, "model": "fake"}
        assert r.headers["Access-Control-Allow-Origin"] == "*"
        # a script and a font of some hundred kB come back byte for byte with their type
        r = await c.get("/brain/plan/app.js")
        assert r.status == 200 and await r.read() == fb.script
        assert r.headers["Content-Type"].startswith("application/javascript")
        r = await c.get("/brain/plan/font.woff2")
        assert await r.read() == fb.font and r.headers["Content-Type"] == "font/woff2"
        assert len(fb.font) > 400_000 and len(fb.script) > 300_000
        r = await c.get("/brain/plan/")
        assert "<title>plan</title>" in await r.text() and r.headers["Content-Type"].startswith("text/html")
        # a redirect of the brain points into the pi again
        r = await c.get("/brain/plan", allow_redirects=False)
        assert r.status == 307 and r.headers["Location"] == "/brain/plan/"
        # the state of the planner is bigger than the pi takes from a browser, it passes all the same
        st = await (await c.get("/brain/plan/api/state")).json()
        assert st["pose"]["pan"] == 30.0 and len(st["path_today"]["t"]) == 500

        token, _ = s.auth.issue()
        r = await c.post(f"/brain/recipe?x=1&token={token}&y=two", data="Tomaten, ab 17 Uhr Strom",
                         headers={"Content-Type": "text/plain; charset=utf-8"})
        assert r.status == 200
        got = await r.json()
        assert got["got"] == "Tomaten, ab 17 Uhr Strom"
        assert got["ct"] == "text/plain; charset=utf-8"
        # the token stays on the pi, the rest of the query goes on as it came
        assert got["query"] == "x=1&y=two"
        # the cross origin rules are the pi's, not the brain's
        assert r.headers["Access-Control-Allow-Origin"] == "*"
        assert "POST" in r.headers["Access-Control-Allow-Methods"]
        r = await c.options("/brain/recipe")
        assert r.status == 204 and "POST" in r.headers["Access-Control-Allow-Methods"]
        # a json body is passed on as well
        r = await c.post(f"/brain/recipe?token={token}", json={"prompt": "basil", "lang": "de"})
        assert (await r.json())["got"] == '{"prompt": "basil", "lang": "de"}'


async def test_a_post_needs_the_admin_token(tmp_path):
    async with FakeBrain() as fb, Stack(tmp_path, fb.url) as s:
        c = s.client
        r = await c.post("/brain/recipe", json={"prompt": "basil"})
        assert r.status == 403 and (await r.json())["err"] == "admin"
        r = await c.post("/brain/recipe?token=wrong", json={"prompt": "basil"})
        assert r.status == 403
        assert fb.seen == []
        # reading is open like the other read routes of the pi
        assert (await c.get("/brain/health")).status == 200


async def test_the_plan_page_link_puts_the_token_into_a_cookie(tmp_path):
    async with FakeBrain() as fb, Stack(tmp_path, fb.url) as s:
        c = s.client
        token, _ = s.auth.issue()
        r = await c.get(f"/brain/plan/?token={token}", allow_redirects=False)
        assert r.status == 303 and r.headers["Location"] == "/brain/plan/"
        cookie = r.cookies["brainsol_token"]
        assert cookie.value == token and cookie["httponly"] and cookie["path"] == "/brain/"
        # the posts of the planner page carry the cookie, the brain never sees it
        r = await c.post("/brain/plan/api/speed", json={"speed": 600})
        assert r.status == 200 and (await r.json())["speed"] == 600
        r = await c.post("/brain/recipe", data="x")
        assert (await r.json())["cookie"] is None


async def test_without_a_brain_it_answers_offline_and_refuses_the_mode(tmp_path):
    async with Stack(tmp_path) as s:
        c = s.client
        assert (await (await c.get("/api/info")).json())["brain"] is False
        r = await c.get("/brain/health")
        body = await r.json()
        assert r.status == 503 and body["err"] == "offline" and "setbrain" in body["msg"]
        r = await c.post("/brain/recipe", json={})
        assert r.status == 503
        ack = await s.commands.handle({"id": 1, "op": "mode", "mode": "plan"}, True)
        assert ack["ok"] is False and ack["err"] == "unsupported" and "--brain" in ack["msg"]
        assert s.engine.mode.name != "plan"


async def test_a_brain_that_is_gone_or_too_slow(tmp_path, monkeypatch):
    async with Stack(tmp_path, f"http://127.0.0.1:{free_port()}") as s:
        r = await s.client.get("/brain/health")
        body = await r.json()
        assert r.status == 502 and body["err"] == "offline" and body["msg"]
    monkeypatch.setattr(brain_mod, "WAIT_S", 0.3)
    async with FakeBrain() as fb, Stack(tmp_path, fb.url) as s:
        t0 = time.monotonic()
        r = await s.client.get("/brain/slow")
        assert r.status == 504 and (await r.json())["err"] == "timeout"
        assert time.monotonic() - t0 < 1.5


async def test_the_head_follows_the_pose_of_the_plan_and_the_lamp_becomes_its_sun(tmp_path):
    async with FakeBrain() as fb, Stack(tmp_path, fb.url) as s:
        eng = s.engine
        assert s.driver.light.lux == 900
        eng.set_mode("plan")
        end = time.monotonic() + 6
        while time.monotonic() < end:
            await asyncio.sleep(0.1)
            if (round(eng.motion.pan, 1), round(eng.motion.tilt, 1)) == (30, 50):
                break
        assert (eng.motion.pan, eng.motion.tilt) == pytest.approx((30, 50), abs=0.05)
        light = s.driver.light
        assert (light.az, light.el, light.on) == (-60, 35, True)
        assert (light.lux, light.amb) == pytest.approx((88000, 11000))
        f = eng.state_frame()
        assert f["mode"] == "plan" and f["tgt"] == {"pan": 30.0, "tilt": 50.0}
        assert f["plan"] == {
            "ok": True, "lost": False, "up": True, "date": "2025-06-04", "time": "09:20",
            "offset": 20.0, "why": "light", "speed": 60.0, "paused": False,
        }
        assert f["sun"] == {"az": -60.0, "el": 35.0, "caz": 120.0, "t": NOW}
        # the lamp is the plan's while it runs, it goes back to where it was afterwards
        with pytest.raises(CommandError):
            eng.set_simlight(az=10)
        eng.set_mode("hold")
        await asyncio.sleep(0.1)
        assert s.driver.light.lux == 900 and eng.state_frame()["plan"] is None


def sim_with(sim, url, **kw):
    s = sim(**kw)
    s.engine.brain = Brain(url)
    return s


async def test_poses_beyond_this_head_are_clamped_to_its_limits(sim):
    async with FakeBrain() as fb:
        s = sim_with(sim, fb.url, pose=(0, 90), mode="hold")
        s.engine.set_mode("plan")
        s.run(DT)
        fb.state = plan_state(pose={"pan": 120.0, "tilt": 190.0, "offset": 0, "why": "sun"})
        assert await s.engine.brain.poll()
        s.run(5)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (88, 176)
        fb.state = plan_state(pose={"pan": -95.0, "tilt": -10.0})
        assert await s.engine.brain.poll()
        s.run(6)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (-88, 4)
        await s.engine.brain.close()


async def test_without_an_answer_the_head_holds_then_parks_and_picks_up_again(sim):
    async with FakeBrain() as fb:
        s = sim_with(sim, fb.url, pose=(0, 90), mode="hold")
        b = s.engine.brain
        s.engine.set_mode("plan")
        s.run(DT)
        assert await b.poll()
        s.run(3)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (30, 50)
        fb.down = True
        assert not await b.poll()
        # nine seconds without a fresh answer, the head keeps the last pose of the plan
        s.run(6)
        f = s.engine.state_frame()
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (30, 50)
        assert f["plan"]["ok"] is False and f["plan"]["lost"] is False
        # past ten seconds it parks, the mode stays on
        s.run(5)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)
        f = s.engine.state_frame()
        assert f["mode"] == "plan" and f["plan"]["lost"] is True
        fb.down = False
        fb.state = plan_state(pose={"pan": -20.0, "tilt": 70.0})
        assert await b.poll()
        s.run(3)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (-20, 70)
        assert s.engine.state_frame()["plan"]["lost"] is False
        await b.close()


async def test_the_head_parks_at_night_in_the_simulation(sim):
    async with FakeBrain() as fb:
        s = sim_with(sim, fb.url, pose=(40, 40), mode="hold")
        s.engine.set_mode("plan")
        s.run(DT)
        fb.state = plan_state(sun={"az_rel": 170.0, "el": -12.0, "up": False},
                              pose={"pan": 0.0, "tilt": 90.0, "offset": 0.0, "why": "night"},
                              meas={"dni": 0.0, "dhi": 0.0})
        assert await s.engine.brain.poll()
        s.run(4)
        assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)
        assert not s.driver.light.on
        assert s.engine.state_frame()["plan"]["up"] is False
        await s.engine.brain.close()


async def test_before_the_first_answer_the_head_holds_where_it_is(sim):
    s = sim_with(sim, f"http://127.0.0.1:{free_port()}", pose=(40, 40), mode="hold")
    s.engine.set_mode("plan")
    s.run(DT)
    assert not await s.engine.brain.poll()
    s.run(5)
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (40, 40)
    assert s.engine.state_frame()["plan"]["ok"] is False
    # ten seconds without any answer and it parks all the same
    s.run(8)
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)
    await s.engine.brain.close()


def test_a_saved_plan_mode_without_a_brain_starts_in_auto():
    state = StateStore(None)
    state.mode = "plan"
    eng = Engine(Settings(), state, SimDriver(seed=1))
    assert eng.mode.name == "auto"
    assert any("plan mode" in e["msg"] for e in eng.events)
    eng = Engine(Settings(), state, SimDriver(seed=1), brain=Brain("jetson:8000"))
    assert eng.mode.name == "plan"


def test_the_brain_address_lives_in_the_settings_and_on_the_command_line(tmp_path):
    assert Settings().brain == ""
    s = Settings(data={"brain": "jetson:8000/"})
    assert s.brain == "http://jetson:8000" and s.problems == []
    s = Settings(data={"brain": "ftp://jetson"})
    assert s.brain == "" and len(s.problems) == 1
    args = build_parser().parse_args(["run", "--brain", "http://jetson:8000"])
    assert args.brain == "http://jetson:8000"
    assert build_parser().parse_args(["run"]).brain is None
    assert build_parser().parse_args(["run", "--brain", ""]).brain == ""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--brain", "http://a b"])
    # setbrain keeps it between runs, off takes it away
    cfg = tmp_path / "cfg"
    assert tools.setbrain(SimpleNamespace(address="http://jetson:8000", config_dir=str(cfg))) == 0
    assert read_json(cfg / "settings.json")["brain"] == "http://jetson:8000"
    assert Settings.load(cfg / "settings.json").brain == "http://jetson:8000"
    args = build_parser().parse_args(["setbrain", "off", "--config-dir", str(cfg)])
    assert tools.setbrain(args) == 0
    assert read_json(cfg / "settings.json")["brain"] == ""
