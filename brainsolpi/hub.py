from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from typing import TYPE_CHECKING

from .engine import Sink
from .jsonio import dumps

if TYPE_CHECKING:
    from .engine import Engine

log = logging.getLogger(__name__)

# frames a newer one of the same kind makes worthless, the oldest of these go first
SUPERSEDED = ("sys", "scan", "cfg", "exp", "evt")
# at most one of these waits per client
COALESCE = ("sys", "cfg")


class Client:
    _ids = itertools.count(1)

    def __init__(self, ws, addr: str = ""):
        self.ws = ws
        self.addr = addr
        self.id = next(self._ids)
        self.queue: deque[tuple[str, str]] = deque()
        self.wake = asyncio.Event()
        self.admin = False
        self.closed = False
        self.dropped = 0
        self.task: asyncio.Task | None = None
        # command budget, refilled over time so a stuck joystick cannot flood the loop
        self.budget = 80.0
        self.budget_t = 0.0


class Hub(Sink):
    # every frame is turned into text once and the same string goes to every client,
    # each client has its own small queue and writer so a slow one only hurts itself

    MAX_QUEUE = 32
    MAX_HARD = 256

    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self.engine: Engine | None = None

    def add(self, ws, addr: str = "") -> Client:
        c = Client(ws, addr)
        self.clients.add(c)
        c.task = asyncio.get_running_loop().create_task(self._writer(c))
        return c

    async def remove(self, c: Client) -> None:
        self.clients.discard(c)
        c.closed = True
        c.wake.set()
        if c.task is not None and c.task is not asyncio.current_task():
            c.task.cancel()
            try:
                await c.task
            except (asyncio.CancelledError, Exception):
                pass

    async def close_all(self) -> None:
        for c in list(self.clients):
            try:
                await asyncio.wait_for(c.ws.close(code=1001, message=b"server shutting down"), 1.0)
            except Exception:
                pass
            await self.remove(c)

    # the sink side, called from the control loop

    def publish(self, msg: dict, kind: str) -> None:
        if not self.clients:
            return
        text = dumps(msg)
        for c in self.clients:
            self.push(c, kind, text)

    def publish_admins(self, msg: dict) -> None:
        admins = [c for c in self.clients if c.admin]
        if not admins:
            return
        text = dumps(msg)
        for c in admins:
            self.push(c, msg.get("t", "evt"), text)

    def counts(self) -> tuple[int, int]:
        return len(self.clients), sum(1 for c in self.clients if c.admin)

    def caps_changed(self) -> None:
        if self.engine is None:
            return
        for c in self.clients:
            self.send(c, self.engine.hello(c.admin), "hello")

    # queues

    def send(self, c: Client, msg: dict, kind: str) -> None:
        self.push(c, kind, dumps(msg))

    def push(self, c: Client, kind: str, text: str) -> None:
        if c.closed:
            return
        q = c.queue
        if kind in COALESCE and q:
            # only the newest status of its kind matters, an older one still waiting goes
            for i, (k, _) in enumerate(q):
                if k == kind:
                    del q[i]
                    break
        if len(q) >= self.MAX_QUEUE and not self._drop_one(q, kind):
            if len(q) >= self.MAX_HARD:
                # nothing left to drop and still full, the client is gone in all but name
                c.closed = True
                c.wake.set()
                log.info("client %s stopped reading, closing it", c.id)
                return
        q.append((kind, text))
        c.wake.set()

    def _drop_one(self, q: deque, incoming: str) -> bool:
        for i, (k, _) in enumerate(q):
            if k == "s":
                del q[i]
                return True
        newest = {}
        for i, (k, _) in enumerate(q):
            newest[k] = i
        for i, (k, _) in enumerate(q):
            if k in SUPERSEDED and (k == incoming or newest[k] > i):
                del q[i]
                return True
        return False

    async def _writer(self, c: Client) -> None:
        try:
            while not c.closed:
                if not c.queue:
                    c.wake.clear()
                    await c.wake.wait()
                    continue
                _, text = c.queue.popleft()
                await c.ws.send_str(text)
        except asyncio.CancelledError:
            c.closed = True
            raise
        except Exception as e:
            log.debug("client %s writer ended: %s", c.id, e)
        c.closed = True
        if not c.ws.closed:
            try:
                await c.ws.close()
            except Exception:
                pass
