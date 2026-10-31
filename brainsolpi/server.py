from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from . import PROTO, __version__, paths
from .auth import Auth
from .commands import Commands
from .engine import Engine
from .hub import Client, Hub
from .jsonio import dumps

log = logging.getLogger(__name__)

MAX_SPAN = 6 * 3600
# commands per second a client may send on average, with some burst on top
CMD_RATE = 40.0
CMD_BURST = 80.0

ENGINE = web.AppKey("engine", Engine)
HUB = web.AppKey("hub", Hub)
AUTH = web.AppKey("auth", Auth)
COMMANDS = web.AppKey("commands", Commands)
WEB = web.AppKey("web", object)
STARTED = web.AppKey("started", float)


def json_response(data, status: int = 200) -> web.Response:
    return web.Response(text=dumps(data), status=status, content_type="application/json")


@web.middleware
async def api_headers(request: web.Request, handler):
    # the web app on github pages talks to the pi from another origin
    is_api = request.path.startswith("/api/")
    if is_api and request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            if not is_api:
                raise
            resp = json_response({"err": e.reason}, e.status)
        except Exception:
            log.exception("request %s failed", request.path)
            resp = json_response({"err": "internal error"}, 500)
    if is_api:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


async def info(request: web.Request) -> web.Response:
    eng = request.app[ENGINE]
    hub = request.app[HUB]
    return json_response(
        {
            "name": eng.settings.data["name"],
            "version": __version__,
            "proto": PROTO,
            "driver": eng.driver.name,
            "caps": eng.caps(),
            "viewers": hub.counts()[0],
            "uptime": int(time.monotonic() - request.app[STARTED]),
        }
    )


async def history(request: web.Request) -> web.Response:
    eng = request.app[ENGINE]
    try:
        span = float(request.query.get("span", "900"))
    except ValueError:
        raise web.HTTPBadRequest(reason="span must be a number of seconds") from None
    if span != span:
        raise web.HTTPBadRequest(reason="span must be a number of seconds")
    span = max(1, min(MAX_SPAN, int(span)))
    # six hours of rows is a big json, build it off the loop
    text = await asyncio.get_running_loop().run_in_executor(None, lambda: dumps(eng.history.span(span, time.time())))
    return web.Response(text=text, content_type="application/json")


async def experiments(request: web.Request) -> web.Response:
    return json_response(request.app[ENGINE].store.list())


async def experiment(request: web.Request) -> web.Response:
    store = request.app[ENGINE].store
    name = request.match_info["name"]
    if name.endswith(".csv"):
        text = store.csv(name[:-4])
        if text is None:
            raise web.HTTPNotFound(reason="no such experiment")
        return web.Response(
            text=text,
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    data = store.get(name)
    if data is None:
        raise web.HTTPNotFound(reason="no such experiment")
    return json_response(data)


async def record(request: web.Request) -> web.Response:
    eng = request.app[ENGINE]
    if request.app[AUTH].verify_token(request.query.get("token")) is None:
        raise web.HTTPForbidden(reason="admin only, the token is missing or expired")
    rec = eng.recorder
    if rec is None or rec.path is None or not rec.path.exists():
        raise web.HTTPNotFound(reason="nothing recorded yet")
    await asyncio.get_running_loop().run_in_executor(None, rec.flush)
    return web.FileResponse(
        rec.path,
        headers={
            "Content-Type": "text/csv",
            "Content-Disposition": f'attachment; filename="{rec.path.name}"',
        },
    )


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def _allow(c: Client) -> bool:
    now = time.monotonic()
    c.budget = min(CMD_BURST, c.budget + (now - c.budget_t) * CMD_RATE)
    c.budget_t = now
    if c.budget < 1.0:
        return False
    c.budget -= 1.0
    return True


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    eng, hub, auth, cmds = app[ENGINE], app[HUB], app[AUTH], app[COMMANDS]
    # no compression, it would cost cpu per client and per frame on the pi
    ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=8192, compress=False)
    await ws.prepare(request)
    c = hub.add(ws, request.remote or "")
    hub.send(c, eng.hello(False), "hello")
    if eng.last_sys is not None:
        hub.send(c, eng.last_sys, "sys")
    if eng.last_scan is not None:
        hub.send(c, eng.last_scan, "scan")
    tasks: set[asyncio.Task] = set()
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            kind = data.get("t")
            if kind == "auth":
                task = asyncio.create_task(_auth(hub, eng, auth, c, data))
            elif kind == "cmd":
                if not _allow(c):
                    if data.get("op") != "rate":
                        hub.send(c, {"t": "ack", "id": data.get("id"), "ok": False, "err": "busy", "msg": "too many commands, slow down"}, "ack")
                    continue
                task = asyncio.create_task(_cmd(hub, cmds, c, data))
            else:
                continue
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        for t in tasks:
            t.cancel()
        await hub.remove(c)
    return ws


async def _auth(hub: Hub, eng: Engine, auth: Auth, c: Client, data: dict) -> None:
    if "token" in data and data.get("pin") is None:
        out = auth.resume(data.get("token"))
    else:
        out = await auth.login(data.get("pin"))
    fresh = bool(out.get("ok")) and not c.admin
    if out.get("ok"):
        c.admin = True
        if fresh:
            eng.event("info", f"admin unlocked from {c.addr or 'a browser'}")
    hub.send(c, out, "auth")
    if fresh:
        # the notes of a first start went out before anyone could read them
        eng.remind()


async def _cmd(hub: Hub, cmds: Commands, c: Client, data: dict) -> None:
    ack = await cmds.handle(data, c.admin)
    if not c.closed:
        hub.send(c, ack, "ack")


def no_web_text(root: Path | None) -> str:
    # what someone sees who opens the address the install script printed before the web app
    # was copied over, the hosted page cannot help with a plain http address
    where = root or (paths.repo_root() / "web" if paths.repo_root() else Path("web"))
    return (
        "brainSOL is running, but the web app is not installed on this Pi.\n"
        f"Copy the built web app of the brainsol repo into {where} and reload, "
        "or start the service with --web and the folder of the build.\n"
        "The hosted page at https://sol.swimmingbrain.dev reaches this Pi only through a tunnel "
        "address with https, see deploy/tunnel.md.\n"
        "The live data is at /api/info and /ws.\n"
    )


def _static(root: Path | None):
    index = root / "index.html" if root is not None else None

    async def handler(request: web.Request) -> web.StreamResponse:
        if request.match_info.get("path", "").startswith("api/"):
            raise web.HTTPNotFound(reason="no such endpoint")
        if root is None or not index.is_file():
            return web.Response(text=no_web_text(root), content_type="text/plain")
        rel = request.match_info.get("path", "")
        if rel == "config.json":
            # a page loaded from the pi talks to the pi it came from, whatever the build says
            return web.json_response({"pi": "self"}, headers={"Cache-Control": "no-cache"})
        target = index
        if rel:
            try:
                cand = (root / rel).resolve()
                cand.relative_to(root)
            except (ValueError, OSError):
                raise web.HTTPNotFound() from None
            if cand.is_file():
                target = cand
            elif cand.is_dir() and (cand / "index.html").is_file():
                target = cand / "index.html"
            elif "." in Path(rel).name and not rel.endswith(".html"):
                # a missing asset is a real 404, only page routes fall back to index.html
                raise web.HTTPNotFound()
        resp = web.FileResponse(target)
        if "/immutable/" in f"/{rel}":
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    return handler


def make_app(engine: Engine, hub: Hub, auth: Auth, commands: Commands, web_dir: Path | None) -> web.Application:
    app = web.Application(middlewares=[api_headers], client_max_size=64 * 1024)
    app[ENGINE] = engine
    app[HUB] = hub
    app[AUTH] = auth
    app[COMMANDS] = commands
    root = web_dir.resolve() if web_dir is not None else None
    app[WEB] = root
    app[STARTED] = time.monotonic()
    app.router.add_get("/api/info", info)
    app.router.add_get("/api/history", history)
    app.router.add_get("/api/experiments", experiments)
    app.router.add_get("/api/experiments/{name}", experiment)
    app.router.add_get("/api/record.csv", record)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", healthz)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/ws", ws_handler)
    static = _static(root)
    app.router.add_get("/", static)
    app.router.add_get("/{path:.*}", static)
    return app
