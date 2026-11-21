import asyncio
import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from brainsolpi.auth import Auth, hash_pin
from brainsolpi.commands import Commands
from brainsolpi.config import Settings
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import Engine
from brainsolpi.hub import Hub
from brainsolpi.server import make_app
from brainsolpi.state import StateStore
from brainsolpi.store import ExperimentStore
from brainsolpi.sysinfo import SysInfo


class Stack:
    def __init__(self, tmp_path, web_dir=None):
        self.settings = Settings()
        self.driver = SimDriver(seed=1)
        self.hub = Hub()
        self.engine = Engine(
            self.settings, StateStore(None), self.driver,
            store=ExperimentStore(tmp_path / "exp"), data_dir=tmp_path, sink=self.hub, sysinfo=SysInfo(),
        )
        self.hub.engine = self.engine
        self.auth = Auth(hash_pin("2468", iterations=2000))
        self.sys_calls = []
        self.commands = Commands(self.engine, on_sys=lambda a: self.sys_calls.append(a))
        self.app = make_app(self.engine, self.hub, self.auth, self.commands, web_dir)

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


async def recv(ws, t, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = await asyncio.wait_for(ws.receive(), end - time.monotonic())
        data = json.loads(msg.data)
        if data["t"] == t:
            return data
    raise AssertionError(f"no {t} frame")


async def ack(ws, cid, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        data = json.loads((await asyncio.wait_for(ws.receive(), end - time.monotonic())).data)
        if data["t"] == "ack" and data["id"] == cid:
            return data
    raise AssertionError(f"no ack for {cid}")


async def test_http_endpoints(tmp_path):
    async with Stack(tmp_path) as s:
        c = s.client
        r = await c.get("/healthz")
        assert r.status == 200 and await r.text() == "ok"
        r = await c.get("/api/info")
        info = await r.json()
        assert r.headers["Access-Control-Allow-Origin"] == "*"
        assert set(info) == {"name", "version", "proto", "driver", "caps", "viewers", "uptime", "brain"}
        assert info["driver"] == "sim" and info["proto"] == 1 and info["brain"] is False
        assert info["caps"] == {"lux": True, "pv": False, "simlight": True}
        await asyncio.sleep(2.2)
        h = await (await c.get("/api/history?span=900")).json()
        assert h["cols"] == ["pan", "tilt", "lvl", "lux", "pmw", "off", "gain"]
        assert h["dt"] == 1 and len(h["rows"]) >= 1 and isinstance(h["t0"], int)
        assert (await c.get("/api/history?span=abc")).status == 400
        assert await (await c.get("/api/experiments")).json() == []
        r = await c.get("/api/experiments/nope")
        assert r.status == 404 and r.headers["Access-Control-Allow-Origin"] == "*"
        assert (await c.get("/api/record.csv")).status == 403
        r = await c.options("/api/info")
        assert r.status == 204 and r.headers["Access-Control-Allow-Origin"] == "*"
        assert (await c.get("/api/unknown")).status == 404
        r = await c.get("/")
        text = await r.text()
        assert "not installed" in text
        # the folder it looks in and the way the hosted page gets here
        assert "web" in text and "tunnel" in text and "/api/info" in text
        assert "deploy/web.sh" in text
        # the guides are gone, the hint stands on its own and names the readme
        assert "Funnel" in text and "readme" in text and ".md" not in text


async def test_websocket_session(tmp_path):
    async with Stack(tmp_path) as s:
        ws = await s.client.ws_connect("/ws")
        hello = json.loads((await ws.receive()).data)
        assert hello["t"] == "hello"
        assert hello["proto"] == 1 and hello["name"] == "brainsol" and hello["driver"] == "sim"
        assert hello["admin"] is False and hello["rate"] == 20
        assert hello["caps"]["simlight"] is True
        cfg = hello["cfg"]
        assert cfg["limits"] == {"pan": [-88.0, 88.0], "tilt": [4.0, 176.0]}
        assert cfg["park"] == {"pan": 0.0, "tilt": 90.0}
        assert cfg["baffle"] == 1.2
        assert cfg["params"]["kp"] == {"v": 90.0, "min": 10.0, "max": 300.0, "step": 1.0}

        # state frames at the configured rate
        t0 = time.monotonic()
        n = 0
        while time.monotonic() - t0 < 1.5:
            data = json.loads((await ws.receive()).data)
            if data["t"] == "s":
                n += 1
                assert data["sim"] is not None and len(data["raw"]) == 4
        assert 25 <= n <= 33
        sysf = await recv(ws, "sys")
        assert sysf["drv"] == "sim" and sysf["link"] == "ok" and sysf["viewers"] == 1

        # viewers are read only but may ping
        await ws.send_json({"t": "cmd", "id": 1, "op": "mode", "mode": "hold"})
        a = await ack(ws, 1)
        assert a["ok"] is False and a["err"] == "admin"
        await ws.send_json({"t": "cmd", "id": "p", "op": "ping"})
        a = await ack(ws, "p")
        assert a["ok"] and abs(a["data"]["ts"] - time.time()) < 5

        # wrong pin, then the right one
        await ws.send_json({"t": "auth", "pin": "1111"})
        out = await recv(ws, "auth")
        assert out["ok"] is False and out["wait"] == 0 and out["err"] == "pin"
        await ws.send_json({"t": "auth", "pin": "2468"})
        out = await recv(ws, "auth")
        assert out["ok"] is True and out["exp"] > time.time() + 11 * 3600
        token = out["token"]

        await ws.send_json({"t": "cmd", "id": 2, "op": "mode", "mode": "hold"})
        assert (await ack(ws, 2))["ok"]
        f = await recv(ws, "s")
        assert f["mode"] == "hold"
        await ws.send_json({"t": "cmd", "id": 3, "op": "target", "pan": 20, "tilt": 70})
        a = await ack(ws, 3)
        assert a["ok"] and a["data"] == {"pan": 20.0, "tilt": 70.0}
        await ws.send_json({"t": "cmd", "id": 4, "op": "set", "key": "kp", "value": 999})
        a = await ack(ws, 4)
        assert not a["ok"] and a["err"] == "bad" and "kp" in a["msg"]
        await ws.send_json({"t": "cmd", "id": 5, "op": "simlight", "az": 400, "el": 30, "on": True})
        a = await ack(ws, 5)
        assert a["ok"] and a["data"]["az"] == 40
        await ws.send_json({"t": "cmd", "id": 6, "op": "dance"})
        assert (await ack(ws, 6))["err"] == "unknown"
        await ws.send_json({"t": "cmd", "id": 7, "op": "sys", "action": "restart"})
        assert (await ack(ws, 7))["ok"] and s.sys_calls == ["restart"]

        # a second browser reuses the token and both see the new settings
        ws2 = await s.client.ws_connect("/ws")
        await recv(ws2, "hello")
        await ws2.send_json({"t": "auth", "token": token})
        out = await recv(ws2, "auth")
        assert out["ok"] and out["token"] == token
        await ws2.send_json({"t": "cmd", "id": 8, "op": "set", "key": "kp", "value": 120})
        a = await ack(ws2, 8)
        assert a["ok"] and a["data"] == {"key": "kp", "value": 120.0}
        c1 = await recv(ws, "cfg")
        c2 = await recv(ws2, "cfg")
        assert c1["cfg"]["params"]["kp"]["v"] == c2["cfg"]["params"]["kp"]["v"] == 120
        sysf = await recv(ws, "sys")
        assert sysf["viewers"] == 2 and sysf["admins"] == 2

        # recording and its download
        await ws.send_json({"t": "cmd", "id": 9, "op": "rec", "on": True})
        assert (await ack(ws, 9))["ok"]
        await asyncio.sleep(0.5)
        r = await s.client.get(f"/api/record.csv?token={token}")
        assert r.status == 200
        lines = (await r.text()).splitlines()
        assert lines[0].startswith("t,mode,st,pan") and len(lines) > 5
        await ws.close()
        await ws2.close()


async def test_scan_and_experiment_over_the_websocket(tmp_path):
    async with Stack(tmp_path) as s:
        ws = await s.client.ws_connect("/ws")
        await recv(ws, "hello")
        await ws.send_json({"t": "auth", "pin": "2468"})
        assert (await recv(ws, "auth"))["ok"]
        while (await recv(ws, "s"))["st"] == "fault":
            pass
        await ws.send_json({"t": "cmd", "id": 1, "op": "scan", "step": 45})
        a = await ack(ws, 1)
        assert a["ok"] and a["data"]["cells"] == 20, a
        msg = await recv(ws, "scan")
        assert msg["id"] == a["data"]["id"] and len(msg["v"]) == 4 and len(msg["v"][0]) == 5
        await ws.send_json({"t": "cmd", "id": 2, "op": "exp", "kind": "step"})
        a = await ack(ws, 2)
        assert not a["ok"] and a["err"] == "busy" and "scan" in a["msg"]
        await ws.send_json({"t": "cmd", "id": 3, "op": "stop"})
        assert (await ack(ws, 3))["data"] == {"stopped": True}
        # the closing scan frame went out before the ack
        last = s.engine.last_scan
        assert last["done"] is True and last["stopped"] is True
        await ws.send_json({"t": "cmd", "id": 4, "op": "calib", "step": "zero"})
        a = await ack(ws, 4)
        assert a["ok"] and a["data"]["pan"] == 0
        await ws.send_json({"t": "cmd", "id": 5, "op": "calib", "step": "reset"})
        assert (await ack(ws, 5))["ok"]
        await ws.close()


@pytest.fixture
def web_dir(tmp_path):
    d = tmp_path / "web"
    (d / "_app" / "immutable").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>brainSOL</title>", encoding="utf-8")
    (d / "_app" / "immutable" / "a.js").write_text("console.log(1)", encoding="utf-8")
    (d / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (d / "config.json").write_text('{"pi": ""}', encoding="utf-8")
    return d


async def test_static_files_with_index_fallback(tmp_path, web_dir):
    async with Stack(tmp_path, web_dir) as s:
        c = s.client
        r = await c.get("/")
        assert "brainSOL" in await r.text()
        r = await c.get("/some/page")
        assert r.status == 200 and "brainSOL" in await r.text()
        r = await c.get("/_app/immutable/a.js")
        assert r.status == 200 and "immutable" in r.headers["Cache-Control"]
        assert (await c.get("/favicon.svg")).status == 200
        r = await c.get("/config.json")
        assert await r.json() == {"pi": "self"}
        assert (await c.get("/missing.js")).status == 404
        assert (await c.get("/../secret.txt")).status in (404, 403, 400)
        r = await c.get("/%2e%2e/%2e%2e/etc/passwd")
        # the path is normalised inside the web folder, at most the index comes back
        assert r.status in (404, 403, 400) or "brainSOL" in await r.text()
