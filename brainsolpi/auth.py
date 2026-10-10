from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import os
import secrets
import time
from typing import Callable

ITERATIONS = 120_000
TOKEN_TTL = 12 * 3600
MAX_TRIES = 5
LOCK_S = 30.0
# doubling stops at an hour, the owner can always restart the service to clear it
LOCK_MAX = 3600.0
PIN_MIN = 4
PIN_MAX = 32

NO_PIN = "no pin is set on the tracker, run brainsolpi setpin on the pi"


def hash_pin(pin: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt if salt is not None else os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, its, salt, digest = stored.split("$")
        iterations = int(its)
        salt_b = bytes.fromhex(salt)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256" or not 1000 <= iterations <= 10_000_000:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt_b, iterations)
    return hmac.compare_digest(dk.hex(), digest)


def pin_problem(pin: str) -> str | None:
    if not isinstance(pin, str) or not PIN_MIN <= len(pin) <= PIN_MAX:
        return f"the pin needs {PIN_MIN} to {PIN_MAX} characters"
    if not pin.isprintable() or pin.strip() != pin:
        return "the pin cannot start or end with spaces or hold control characters"
    return None


def _token_key(token: str) -> str:
    # only a hash of each token is kept, so the state file alone does not let anyone in
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Auth:
    def __init__(
        self,
        pin_hash: str | None,
        tokens: list | None = None,
        clock: Callable[[], float] = time.time,
        on_tokens: Callable[[list], None] | None = None,
    ):
        self.pin_hash = pin_hash or ""
        self.clock = clock
        self.on_tokens = on_tokens
        self.fails = 0
        self.lock_until = 0.0
        self.lock_len = LOCK_S
        self.tokens: dict[str, float] = {}
        now = clock()
        for item in tokens or []:
            try:
                key, exp = item[0], float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if exp > now:
                self.tokens[key] = exp

    @property
    def enabled(self) -> bool:
        return bool(self.pin_hash)

    def wait(self) -> int:
        left = self.lock_until - self.clock()
        return int(math.ceil(left)) if left > 0 else 0

    def _fail(self) -> dict:
        self.fails += 1
        if self.fails >= MAX_TRIES:
            self.fails = 0
            self.lock_until = self.clock() + self.lock_len
            wait = self.wait()
            self.lock_len = min(self.lock_len * 2.0, LOCK_MAX)
            return {"t": "auth", "ok": False, "err": f"wrong pin, locked for {wait} s", "wait": wait}
        left = MAX_TRIES - self.fails
        return {"t": "auth", "ok": False, "err": f"wrong pin, {left} tries left", "wait": 0}

    def _refused(self) -> dict | None:
        if not self.enabled:
            return {"t": "auth", "ok": False, "err": NO_PIN, "wait": 0}
        wait = self.wait()
        if wait > 0:
            return {"t": "auth", "ok": False, "err": f"too many wrong pins, try again in {wait} s", "wait": wait}
        return None

    def _success(self) -> dict:
        self.fails = 0
        self.lock_len = LOCK_S
        token, exp = self.issue()
        return {"t": "auth", "ok": True, "token": token, "exp": int(exp * 1000)}

    def check(self, pin) -> dict:
        refused = self._refused()
        if refused is not None:
            return refused
        if not isinstance(pin, str) or not verify_pin(pin, self.pin_hash):
            return self._fail()
        return self._success()

    async def login(self, pin) -> dict:
        # the hash takes a noticeable moment on a pi, so it runs off the event loop
        refused = self._refused()
        if refused is not None:
            return refused
        if not isinstance(pin, str) or len(pin) > 256:
            return self._fail()
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, verify_pin, pin, self.pin_hash)
        refused = self._refused()
        if refused is not None:
            return refused
        return self._success() if ok else self._fail()

    def issue(self) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        exp = self.clock() + TOKEN_TTL
        self.tokens[_token_key(token)] = exp
        self._changed()
        return token, exp

    def verify_token(self, token) -> float | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        now = self.clock()
        expired = [k for k, e in self.tokens.items() if e <= now]
        for k in expired:
            del self.tokens[k]
        if expired:
            self._changed()
        return self.tokens.get(_token_key(token))

    def resume(self, token) -> dict:
        exp = self.verify_token(token)
        if exp is None:
            return {"t": "auth", "ok": False, "err": "the token is unknown or expired, log in with the pin", "wait": 0}
        return {"t": "auth", "ok": True, "token": token, "exp": int(exp * 1000)}

    def forget_all(self) -> None:
        self.tokens.clear()
        self._changed()

    def state(self) -> list:
        return [[k, e] for k, e in self.tokens.items()]

    def _changed(self) -> None:
        if self.on_tokens is not None:
            self.on_tokens(self.state())
