import asyncio
import json

from brainsolpi.hub import Hub


class FakeWs:
    def __init__(self, stuck=False):
        self.sent = []
        self.closed = False
        self.gate = asyncio.Event()
        if not stuck:
            self.gate.set()

    async def send_str(self, text):
        await self.gate.wait()
        self.sent.append(text)

    async def close(self, code=1000, message=b""):
        self.closed = True


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_one_encoding_reaches_every_client():
    hub = Hub()
    a, b = FakeWs(), FakeWs()
    ca, cb = hub.add(a), hub.add(b)
    hub.publish({"t": "s", "pan": float("nan")}, "s")
    await settle()
    assert a.sent == b.sent == ['{"t":"s","pan":null}']
    assert a.sent[0] is b.sent[0]
    await hub.remove(ca)
    await hub.remove(cb)


async def test_admin_only_messages():
    hub = Hub()
    a, b = FakeWs(), FakeWs()
    ca, cb = hub.add(a), hub.add(b)
    cb.admin = True
    hub.publish_admins({"t": "evt", "msg": "x"})
    await settle()
    assert a.sent == [] and len(b.sent) == 1
    assert hub.counts() == (2, 1)
    await hub.remove(ca)
    await hub.remove(cb)


async def test_slow_client_keeps_a_bounded_queue_and_loses_old_state_frames_first():
    hub = Hub()
    slow = FakeWs(stuck=True)
    c = hub.add(slow)
    hub.send(c, {"t": "ack", "id": 1}, "ack")
    for i in range(500):
        hub.publish({"t": "s", "i": i}, "s")
        if i % 50 == 0:
            hub.publish({"t": "sys", "i": i}, "sys")
    assert len(c.queue) <= Hub.MAX_QUEUE
    kinds = [k for k, _ in c.queue]
    # the ack survived, only one sys is left, the newest state frames are kept
    assert kinds.count("ack") == 1
    assert kinds.count("sys") == 1
    last = json.loads(c.queue[-1][1])
    assert last == {"t": "s", "i": 499}
    slow.gate.set()
    await settle()
    assert json.loads(slow.sent[-1])["i"] == 499
    await hub.remove(c)


async def test_a_dead_client_is_closed_instead_of_growing_forever():
    hub = Hub()
    dead = FakeWs(stuck=True)
    c = hub.add(dead)
    for i in range(Hub.MAX_HARD + 10):
        hub.send(c, {"t": "ack", "id": i}, "ack")
    assert c.closed
    assert len(c.queue) <= Hub.MAX_HARD
    await hub.remove(c)


async def test_other_clients_do_not_wait_for_a_stuck_one():
    hub = Hub()
    stuck, fine = FakeWs(stuck=True), FakeWs()
    cs, cf = hub.add(stuck), hub.add(fine)
    for i in range(100):
        hub.publish({"t": "s", "i": i}, "s")
        await settle()
    assert len(fine.sent) == 100
    assert stuck.sent == []
    await hub.remove(cs)
    await hub.remove(cf)
