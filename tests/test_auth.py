import pytest

from brainsolpi.auth import NO_PIN, Auth, hash_pin, pin_problem, verify_pin

FAST = 2000


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(pin="2468", tokens=None, saved=None):
    clock = Clock()
    auth = Auth(hash_pin(pin, iterations=FAST), tokens=tokens, clock=clock,
                on_tokens=(lambda s: saved.append(s)) if saved is not None else None)
    return auth, clock


def test_hash_is_salted_and_verifies():
    a = hash_pin("2468", iterations=FAST)
    b = hash_pin("2468", iterations=FAST)
    assert a != b
    assert a.startswith("pbkdf2_sha256$2000$")
    assert verify_pin("2468", a) and verify_pin("2468", b)
    assert not verify_pin("2469", a)
    assert not verify_pin("2468", "garbage")
    assert not verify_pin("2468", "md5$1$00$00")


def test_pin_rules():
    assert pin_problem("2468") is None
    assert pin_problem("123")
    assert pin_problem(" 2468")
    assert pin_problem("12\n34")


def test_no_pin_means_no_admin():
    auth = Auth("")
    assert not auth.enabled
    assert auth.check("2468") == {"t": "auth", "ok": False, "err": "pin", "msg": NO_PIN, "wait": 0}


def test_good_pin_gives_a_twelve_hour_token():
    auth, clock = make()
    out = auth.check("2468")
    assert out["ok"] and out["token"]
    assert out["exp"] == clock.t + 12 * 3600
    assert auth.verify_token(out["token"]) == clock.t + 12 * 3600


def test_five_wrong_tries_lock_for_30_s_then_doubling():
    auth, clock = make()
    for i in range(4):
        out = auth.check("0000")
        assert not out["ok"] and out["wait"] == 0
    out = auth.check("0000")
    assert out["wait"] == 30
    # even the right pin is refused while locked
    out = auth.check("2468")
    assert not out["ok"] and out["wait"] == 30
    clock.t += 30.5
    for _ in range(5):
        out = auth.check("0000")
    assert out["wait"] == 60
    clock.t += 61
    for _ in range(5):
        out = auth.check("0000")
    assert out["wait"] == 120
    clock.t += 121
    assert auth.check("2468")["ok"]
    # a success resets the doubling
    for _ in range(5):
        out = auth.check("0000")
    assert out["wait"] == 30


def test_lock_doubling_is_capped():
    auth, clock = make()
    for _ in range(12):
        for _ in range(5):
            out = auth.check("0000")
        clock.t += out["wait"] + 1
    assert out["wait"] == 3600


def test_token_reuse_across_connections_and_expiry():
    saved = []
    auth, clock = make(saved=saved)
    token = auth.check("2468")["token"]
    again = auth.resume(token)
    assert again["ok"] and again["token"] == token
    # a restart reads the tokens back from the state file
    restored = Auth(auth.pin_hash, tokens=saved[-1], clock=clock)
    assert restored.resume(token)["ok"]
    assert token not in str(saved[-1])
    clock.t += 12 * 3600 + 1
    assert not restored.resume(token)["ok"]
    assert not auth.resume("madeup")["ok"]
    assert not auth.resume(None)["ok"]


async def test_login_runs_off_the_loop():
    auth, _ = make()
    assert (await auth.login("2468"))["ok"]
    out = await auth.login("1111")
    assert not out["ok"]
    assert not (await auth.login(12345))["ok"]


@pytest.mark.parametrize("bad", [None, 1234, "", "x" * 300])
def test_odd_pins_are_just_wrong(bad):
    auth, _ = make()
    assert not auth.check(bad)["ok"]
