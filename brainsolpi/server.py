from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from . import PROTO, __version__, paths
from .auth import Auth
from .brain import BrainError
from .commands import Commands
from .engine import Engine
from .hub import Client, Hub
from .jsonio import dumps

log = logging.getLogger(__name__)

MAX_SPAN = 6 * 3600
# commands per second a client may send on average, with some burst on top
CMD_RATE = 40.0
CMD_BURST = 80.0
# a recipe pasted into the planner page may be bigger than anything the pi itself takes
BRAIN_BODY_MAX = 2 * 1024 * 1024
# the admin token for the posts of the planner page opened through the pi
TOKEN_COOKIE = "brainsol_token"

ENGINE = web.AppKey("engine", Engine)
HUB = web.AppKey("hub", Hub)
AUTH = web.AppKey("auth", Auth)
COMMANDS = web.AppKey("commands", Commands)
WEB = web.AppKey("web", object)
STARTED = web.AppKey("started", float)


def json_response(data, status: int = 200) -> web.Response:
    return web.Response(text=dumps(data), status=status, content_type="application/json")


def is_brain_path(path: str) -> bool:
    return path == "/brain" or path.startswith("/brain/")


@web.middleware
async def api_headers(request: web.Request, handler):
    # the web app on github pages talks to the pi from another origin, the same for the brain
    # behind the pi, which also takes posts
    is_api = request.path.startswith("/api/")
    is_brain = is_brain_path(request.path)
    if (is_api or is_brain) and request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            if is_brain:
                resp = json_response({"err": "bad", "msg": e.reason}, e.status)
            elif is_api:
                resp = json_response({"err": e.reason}, e.status)
            else:
                raise
        except Exception:
            log.exception("request %s failed", request.path)
            resp = json_response({"err": "internal error"}, 500)
    if is_api or is_brain:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS" if is_brain else "GET, OPTIONS"
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
            # the page then finds the brain server under /brain and offers the plan mode
            "brain": eng.brain.url is not None,
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


def brain_error(status: int, code: str, msg: str) -> web.Response:
    # the error shape of the recipe server, so the page reads both the same way
    return json_response({"err": code, "msg": msg}, status)


def _without_token(query: str) -> str:
    # the admin token is for the pi, the brain never sees it. the rest stays as it came
    return "&".join(p for p in query.split("&") if p and p.split("=", 1)[0] != "token")


async def _body(request: web.Request) -> bytes | None:
    if not request.body_exists:
        return None
    if request.content_length is not None and request.content_length > BRAIN_BODY_MAX:
        raise web.HTTPRequestEntityTooLarge(BRAIN_BODY_MAX, request.content_length,
                                            reason="the request is too big for the brain")
    data = bytearray()
    async for chunk in request.content.iter_chunked(64 * 1024):
        data += chunk
        if len(data) > BRAIN_BODY_MAX:
            raise web.HTTPRequestEntityTooLarge(BRAIN_BODY_MAX, len(data), reason="the request is too big for the brain")
    return bytes(data)


async def brain_pass(request: web.Request) -> web.StreamResponse:
    # everything under /brain goes on to the brain server, the answer comes back as it is
    brain = request.app[ENGINE].brain
    if brain.url is None:
        return brain_error(503, "offline", "no brain server is set on this pi, start it with --brain or run "
                                           "brainsolpi setbrain on the pi")
    auth = request.app[AUTH]
    given = request.query.get("token")
    token = given or request.cookies.get(TOKEN_COOKIE)
    exp = auth.verify_token(token)
    if request.method not in ("GET", "HEAD") and exp is None:
        return brain_error(403, "admin", "admin only, the token is missing or expired")
    path = request.rel_url.raw_path[len("/brain"):] or "/"
    query = _without_token(request.rel_url.raw_query_string)
    if given and request.method == "GET" and exp is not None:
        # the planner page opened from the plant tab: the token moves into a cookie for its own
        # posts and out of the address bar
        resp = web.Response(status=303, headers={"Location": f"/brain{path}{'?' + query if query else ''}"})
        resp.set_cookie(TOKEN_COOKIE, given, max_age=max(1, int(exp - time.time())), path="/brain/",
                        httponly=True, samesite="Lax")
        return resp
    body = await _body(request)
    try:
        status, headers, data = await brain.forward(request.method, path, query, request.headers, body)
    except BrainError as e:
        return brain_error(e.status, e.code, e.msg)
    return web.Response(status=status, body=data, headers=headers)


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
        f"Run deploy/web.sh in the repo, it puts the built web app into {where}, then reload. "
        "Or start the service with --web and the folder of a build.\n"
        "The hosted page at https://sol.swimmingbrain.dev reaches this Pi only through a tunnel "
        "address with https, a Tailscale Funnel for example, the readme shows how.\n"
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
    app.router.add_route("*", "/brain", brain_pass)
    app.router.add_route("*", "/brain/{tail:.*}", brain_pass)
    static = _static(root)
    app.router.add_get("/", static)
    app.router.add_get("/{path:.*}", static)
    return app
