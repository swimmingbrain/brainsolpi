from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
from yarl import URL

from .config import parse_address

if TYPE_CHECKING:
    from .engine import Engine

log = logging.getLogger(__name__)

# the language model behind the recipe is slow, a pass through waits this long for its answer
WAIT_S = 150.0
# the plan mode asks the planner for its state this often and gives one answer this long
POLL_S = 1.0
STATE_WAIT_S = 5.0
# how often the poller looks whether the plan mode started
IDLE_S = 0.25
# no answer from the planner for this long and the head parks, the plan mode stays on
LOST_S = 10.0
STATE_PATH = "/plan/api/state"
# a planner page, its script or a font is a few hundred kB, nothing the brain sends gets near this
ANSWER_MAX = 16 * 1024 * 1024

# what goes on to the brain and what comes back of the headers, the rest stays on the pi
SEND_HEADERS = ("Content-Type", "Accept", "Accept-Language")
KEEP_HEADERS = ("Content-Type", "Cache-Control", "Content-Disposition")


class BrainError(Exception):
    # status and err follow the error shape of the recipe server, msg says the details
    def __init__(self, status: int, code: str, msg: str):
        super().__init__(msg)
        self.status = status
        self.code = code
        self.msg = msg


class Brain:
    # the brain server on another machine, the planner and the recipe chatbot. the page only
    # talks to the pi, the pi passes its requests on and the plan mode reads the planner here

    def __init__(self, url: str | None = None):
        self.url = parse_address(url) if url else None
        self._session: aiohttp.ClientSession | None = None
        self._wake: asyncio.Event | None = None
        # the newest answer of the planner state and a counter that grows with every answer
        self.plan: dict | None = None
        self.seq = 0
        # whether the last ask for the state got an answer, None before the first, and why not
        self.answers: bool | None = None
        self.why = ""

    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # no cookies of the brain end up here, every browser gets its own answer
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def local(self, location: str) -> str:
        # a redirect of the brain points into it, seen from the browser that is under /brain
        if self.url and location.startswith(self.url):
            location = location[len(self.url):] or "/"
        if location.startswith("/") and not location.startswith("//"):
            return f"/brain{location}"
        return location

    # the pass through

    async def forward(self, method: str, path: str, query: str, headers, body: bytes | None,
                      wait: float | None = None) -> tuple[int, dict, bytes]:
        if self.url is None:
            raise BrainError(503, "offline", "no brain server is set on this pi")
        wait = WAIT_S if wait is None else wait
        url = URL(f"{self.url}{path}{'?' + query if query else ''}", encoded=True)
        send = {k: headers[k] for k in SEND_HEADERS if k in headers}
        try:
            async with self.session().request(
                method, url, data=body or None, headers=send, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=wait),
            ) as r:
                if r.content_length is not None and r.content_length > ANSWER_MAX:
                    raise BrainError(502, "offline", "the answer of the brain is too big to pass on")
                data = bytearray()
                async for chunk in r.content.iter_chunked(64 * 1024):
                    data += chunk
                    if len(data) > ANSWER_MAX:
                        raise BrainError(502, "offline", "the answer of the brain is too big to pass on")
                out = {k: r.headers[k] for k in KEEP_HEADERS if k in r.headers}
                if "Location" in r.headers:
                    out["Location"] = self.local(r.headers["Location"])
                return r.status, out, bytes(data)
        except asyncio.TimeoutError:
            raise BrainError(504, "timeout", f"the brain did not answer within {wait:.0f} s") from None
        except (aiohttp.ClientError, OSError) as e:
            raise BrainError(502, "offline", f"the brain at {self.url} does not answer, {e}") from None

    # the plan mode

    def wake(self) -> None:
        # the plan mode just started, the first ask goes out right away
        if self._wake is not None:
            self._wake.set()

    async def poll(self) -> bool:
        try:
            async with self.session().get(
                f"{self.url}{STATE_PATH}", timeout=aiohttp.ClientTimeout(total=STATE_WAIT_S)
            ) as r:
                if r.status != 200:
                    raise ValueError(f"it answered with status {r.status}")
                data = await r.json(content_type=None)
            if not isinstance(data, dict):
                raise ValueError("the state is no json object")
        except asyncio.TimeoutError:
            return self._lost(f"no answer within {STATE_WAIT_S:.0f} s")
        except (aiohttp.ClientError, OSError, ValueError) as e:
            return self._lost(str(e) or type(e).__name__)
        self.plan = data
        self.seq += 1
        self.answers = True
        return True

    def _lost(self, why: str) -> bool:
        self.answers = False
        self.why = why
        return False

    async def follow(self, eng: Engine) -> None:
        # asks the planner for its state about once a second while the plan mode runs
        if self.url is None:
            return
        self._wake = asyncio.Event()
        was = None
        while True:
            if eng.mode.name == "plan":
                try:
                    await self.poll()
                except Exception:
                    # nothing may end the poller, the plan mode would hang on its last answer
                    log.exception("asking the brain for the plan failed")
                    self._lost("internal error, see the log")
                if self.answers != was:
                    if self.answers:
                        eng.event("info", f"the brain at {self.url} answers, the head follows the plan")
                    else:
                        eng.event("warn", f"the brain at {self.url} does not answer, {self.why}. the head holds "
                                          f"and parks after {LOST_S:.0f} s, the plan mode goes on when it is back")
                    was = self.answers
                wait = POLL_S
            else:
                was = None
                wait = IDLE_S
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), wait)
            except asyncio.TimeoutError:
                pass
