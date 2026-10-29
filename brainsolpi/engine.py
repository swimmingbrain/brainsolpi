from __future__ import annotations

import asyncio
import logging
import statistics
import threading
import time
from collections import deque
from pathlib import Path

from . import PROTO, __version__
from .activities import Activity
from .config import Settings
from .controller import AutoLoop, Tracker
from .derived import gain, light_estimate, measured_mw, offset_deg, panel_mw
from .drivers.base import Driver
from .drivers.protocol import CAP_LUX, CAP_PV, FLAG_ATTACHED, FLAG_WATCHDOG
from .history import History, Recorder
from .jsonio import r1, r2, r3
from .kinematics import ServoMap, clamp
from .modes import AUTO, MODES, STOP, Manual, Mode, make_mode
from .motion import Motion
from .state import StateStore
from .store import ExperimentStore
from .sun import SunClock
from .sysinfo import SysInfo

log = logging.getLogger(__name__)

DT = 0.02
# no fresh frame for this long and the link counts as down
STALE_S = 0.5
# the board holds the last target and flags a watchdog after 1.5 s, resend well before that
KEEPALIVE_S = 0.5
# the pose is written at most this often, and only once the head is still
SAVE_EVERY_S = 10.0


class CommandError(Exception):
    # code is the short word the web app turns into a sentence in its own language:
    # admin, bad, busy, unknown or unsupported, the text says the details
    def __init__(self, msg: str, code: str = "bad"):
        super().__init__(msg)
        self.code = code


class Sink:
    # where the engine sends frames, the websocket hub implements it, tests record into it

    def publish(self, msg: dict, kind: str) -> None:
        pass

    def publish_admins(self, msg: dict) -> None:
        pass

    def counts(self) -> tuple[int, int]:
        return 0, 0

    def caps_changed(self) -> None:
        pass


class Ticker:
    # a thread with a precise sleep wakes the loop every period, the schedule adds up
    # period by period so late wakeups do not pile up into drift

    def __init__(self, period: float):
        self.period = period
        self.event = asyncio.Event()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ticker")
        self._thread.start()

    def _run(self) -> None:
        nxt = time.perf_counter()
        while not self._halt.is_set():
            nxt += self.period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.25:
                # the machine stalled, start a fresh schedule instead of racing to catch up
                nxt = time.perf_counter()
            try:
                self._loop.call_soon_threadsafe(self.event.set)
            except RuntimeError:
                return

    async def wait(self) -> None:
        await self.event.wait()
        self.event.clear()

    def stop(self) -> None:
        self._halt.set()


class Engine:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        driver: Driver,
        *,
        store: ExperimentStore | None = None,
        data_dir: Path | None = None,
        wall=time.time,
        sink: Sink | None = None,
        sysinfo: SysInfo | None = None,
    ):
        self.settings = settings
        self.state = state
        self.driver = driver
        self.wall = wall
        self.sink = sink or Sink()
        self.sysinfo = sysinfo
        self.store = store or ExperimentStore(None)
        self.params = settings.params
        self.tracker = Tracker(self.params)
        self.loop = AutoLoop(self.tracker)
        self.profile = driver.profile
        self.calib = settings.calib(self.profile)
        self.calib_saved = True
        self._apply_calib()
        lp, lt = settings.pan_limits, settings.tilt_limits
        # the first command goes out at the saved pose so the head does not jump
        self.motion = Motion(clamp(state.pan, *lp), clamp(state.tilt, *lt))
        self.mode: Mode = make_mode(state.mode if state.mode in MODES else "auto")
        self._entered = False
        self.activity: Activity | None = None
        self.sun_clock = SunClock(wall)
        self.sun: dict | None = None
        self.history = History()
        self.recorder = Recorder(data_dir / "recordings") if data_dir is not None else None
        self.last_scan: dict | None = None
        self.last_sys: dict | None = None
        self.on_sys = None
        if driver.has_simlight:
            driver.set_light(**state.sim)
        driver.settle_at(self.pan_map.to_us(self.motion.pan), self.tilt_map.to_us(self.motion.tilt))

        self.frame = None
        self.frame_t = -1e9
        self.link = False
        self.lux: float | None = None
        self.st = "idle"
        self.cstate = "idle"
        self.tgt: tuple[float, float] | None = None
        self.pushing = 0
        self.stopping = False
        self.now = 0.0
        self.started: float | None = None
        self.ticks = 0
        self.errors = 0
        self.overruns = 0
        self.hz: float | None = None
        self.jit: float | None = None
        self.events: deque[dict] = deque(maxlen=20)
        self._caps = self.caps()
        self._times: deque[float] = deque(maxlen=51)
        self._last_us: tuple[int, int] | None = None
        self._last_send = -1e9
        self._force_send = True
        self._wd_warned = -1e9
        self._link_t = -1e9
        self._next_pub = 0.0
        self._next_sys = 0.0
        self._next_cfg = 0.0
        self._next_flush = 0.0
        self._next_save = 0.0
        self._cfg_dirty = False
        self._hist_sec: int | None = None
        self._acc = [0, 0.0, 0, 0.0]
        self._crash_logged = 0

    # setup

    def _apply_calib(self) -> None:
        c = self.calib
        self.tracker.calibrate(c["dark"], c["bright"], c["sx"], c["sy"])
        self.pan_map = ServoMap.from_dict(c["pan"])
        self.tilt_map = ServoMap.from_dict(c["tilt"])

    def caps(self) -> dict:
        ident = self.driver.ident
        bits = ident.caps if ident is not None else 0
        return {"lux": bool(bits & CAP_LUX), "pv": bool(bits & CAP_PV), "simlight": self.driver.has_simlight}

    @property
    def fw(self) -> str | None:
        ident = self.driver.ident
        if ident is None or self.driver.has_simlight:
            return None
        return ident.fw

    # the tick

    def tick(self, now: float) -> None:
        # nothing may escape from here, the loop has to keep its beat whatever happens
        if self.started is None:
            self.started = now
            self._next_pub = now
            # the first status waits a second so the loop rate is already measured
            self._next_sys = now + 1.0
        self.now = now
        self.ticks += 1
        self._timing(now)
        try:
            self._control(now)
        except Exception:
            self._crash("control")
        try:
            self._outputs(now)
        except Exception:
            self._crash("outputs")

    def _crash(self, where: str) -> None:
        self.errors += 1
        if self._crash_logged < 5 or self.errors % 500 == 0:
            self._crash_logged += 1
            log.exception("error in the %s step, the loop keeps running", where)
        self.st = "fault"
        self.motion.stop_now()
        if self.activity is not None:
            act = self.activity
            self.activity = None
            act.cancel("internal error, see the log")

    def _timing(self, now: float) -> None:
        times = self._times
        if times and now - times[-1] > 1.5 * DT:
            self.overruns += 1
        times.append(now)

    def _rate_stats(self) -> None:
        # real loop rate and the spread of the tick intervals over the last second
        times = list(self._times)
        if len(times) < 10:
            return
        span = times[-1] - times[0]
        if span <= 0:
            return
        self.hz = (len(times) - 1) / span
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.jit = statistics.pstdev(gaps) * 1000.0

    def _control(self, now: float) -> None:
        drv = self.driver
        for lvl, msg in drv.drain_events():
            self.event(lvl, msg)
        f = drv.poll(now)
        if f is not None:
            self.frame = f
            self.frame_t = now
        link = drv.link_ok and self.frame is not None and now - self.frame_t < STALE_S
        if link != self.link:
            self._link_change(link)
        if not self.link:
            # without a board the head cannot move, the pose stays where it was
            self.motion.stop_now()
            self.st = self.cstate = "fault"
            self.tgt = None
            self._send(now)
            return
        f = self.frame
        bits = drv.ident.caps if drv.ident is not None else 0
        self.lux = f.lux10 / 10.0 if bits & CAP_LUX else None
        self.tracker.sense(f.raw, DT)
        # the flag is also up before the first command and after a detach, only an attached
        # board that keeps flagging while we send means our commands get lost
        if (
            f.flags & FLAG_WATCHDOG
            and f.flags & FLAG_ATTACHED
            and now - self._link_t > 3.0
            and now - self._last_send < 0.2
            and now - self._wd_warned > 30.0
        ):
            self._wd_warned = now
            self._force_send = True
            self.event("warn", "the board says our commands stopped arriving, sending again")
        if not self._entered:
            self._entered = True
            self.mode.enter(self, now)
        if self.stopping:
            req = STOP
        elif self.activity is not None:
            req = self.activity.step()
            if self.activity is not None and self.activity.done:
                self.activity = None
        else:
            req = self.mode.step(self, now)
        self._apply(req)
        self.st = self.activity.st if self.activity is not None else self.cstate
        self._send(now)

    def _apply(self, req: tuple) -> None:
        p = self.params
        lp, lt = self.settings.pan_limits, self.settings.tilt_limits
        amax = p["amax"]
        m = self.motion
        kind = req[0]
        if kind == "auto":
            self.cstate, self.pushing = self.loop.step(m, DT, amax, p["vmax"], lp, lt)
            self.tgt = self.loop.aim
            return
        # any other request ends a running aim move, the next auto start looks afresh
        self.loop.reset()
        if kind == "seek":
            _, pan, tilt, vmax = req
            pan = clamp(pan, *lp)
            tilt = clamp(tilt, *lt)
            vmax = p["vmax"] if vmax is None else min(vmax, p["vmax"])
            arrived = m.seek(pan, tilt, vmax, DT, amax, lp, lt)
            self.pushing = 0
            self.tgt = (pan, tilt)
            self.cstate = "idle" if arrived else "moving"
        else:
            _, vx, vy = req
            self.pushing = m.step(vx, vy, DT, amax, lp, lt)
            self.tgt = None
            if self.pushing:
                self.cstate = "limit"
            elif m.still and vx == 0.0 and vy == 0.0:
                self.cstate = "idle"
            else:
                self.cstate = "moving"

    def _send(self, now: float) -> None:
        us = (self.pan_map.to_us(self.motion.pan), self.tilt_map.to_us(self.motion.tilt))
        if self._force_send or us != self._last_us or now - self._last_send >= KEEPALIVE_S:
            self.driver.move(*us)
            self._last_us = us
            self._last_send = now
            self._force_send = False

    def _link_change(self, link: bool) -> None:
        self.link = link
        if link:
            self._force_send = True
            self._link_t = self.now
            self.tracker.reset_filter()
            fw = self.fw
            what = f"firmware {fw}" if fw else self.driver.name
            self.event("info", f"link up, {what}")
            caps = self.caps()
            if caps != self._caps:
                self._caps = caps
                self.sink.caps_changed()
        else:
            self.event("warn", "link down, no frames from the board")
            if self.activity is not None:
                act = self.activity
                self.activity = None
                act.cancel("the link to the board was lost")

    # outputs

    def _outputs(self, now: float) -> None:
        wall = self.wall()
        self._history(wall)
        if self.recorder is not None and self.recorder.on:
            if not self.recorder.add(now, self._rec_row()):
                self.event("info", "recording stopped at its length limit")
        if now >= self._next_pub:
            period = 1.0 / self.params["rate"]
            self._next_pub += period
            if self._next_pub < now:
                self._next_pub = now + period
            self.sink.publish(self.state_frame(wall), "s")
        if now >= self._next_sys:
            self._next_sys += 1.0
            if self._next_sys < now:
                self._next_sys = now + 1.0
            self.last_sys = self.sys_frame()
            self.sink.publish(self.last_sys, "sys")
            caps = self.caps()
            if caps != self._caps:
                # a sensor plugged in later only shows in a fresh identity line
                self._caps = caps
                self.sink.caps_changed()
        if self._cfg_dirty and now >= self._next_cfg:
            self._cfg_dirty = False
            self._next_cfg = now + 0.2
            self.sink.publish({"t": "cfg", "cfg": self.settings.cfg()}, "cfg")
        if self.settings.dirty and now >= self._next_flush:
            self._next_flush = now + 1.0
            self.settings.save()
        if now >= self._next_save and self.motion.still:
            self._next_save = now + SAVE_EVERY_S
            self.save_state()

    def _history(self, wall: float) -> None:
        acc = self._acc
        if self.link:
            acc[0] += 1
            acc[1] += self.tracker.lvl
            if self.lux is not None:
                acc[2] += 1
                acc[3] += self.lux
        sec = int(wall)
        if self._hist_sec is None:
            self._hist_sec = sec
            return
        if sec == self._hist_sec:
            return
        lvl = acc[1] / acc[0] if acc[0] else None
        lux = acc[3] / acc[2] if acc[2] else None
        off, g = self.offset_gain()
        self.history.push(
            self._hist_sec, (self.motion.pan, self.motion.tilt, lvl, lux, self.power(lux), off, g)
        )
        self._acc = [0, 0.0, 0, 0.0]
        self._hist_sec = sec

    def offset_gain(self) -> tuple[float | None, float | None]:
        t = self.tracker
        if not self.link or not t.seeded or t.lowlight:
            return None, None
        off = offset_deg(t.ex, t.ey)
        m = self.motion
        rp, rt = self.params["ref_pan"], self.params["ref_tilt"]
        if self.cstate in ("tracking", "locked", "limit"):
            g = gain(m.pan, m.tilt, rp, rt)
        else:
            # outside the closed loop the light direction comes from the sensor balance
            g = gain(m.pan, m.tilt, rp, rt, light_estimate(m.pan, m.tilt, t.ex, t.ey))
        return off, g

    def power(self, lux: float | None) -> float | None:
        f = self.frame
        bits = self.driver.ident.caps if self.driver.ident is not None else 0
        if not self.link or f is None:
            return None
        if bits & CAP_PV:
            return measured_mw(f.mv, f.ua)
        panel = self.settings.panel
        return panel_mw(lux, panel["w"], panel["h"], panel["eff"])

    def _rec_row(self) -> tuple:
        t = self.tracker
        m = self.motion
        f = self.frame
        raw = f.raw if f is not None else (None, None, None, None)
        off, g = self.offset_gain()
        return (
            self.mode.name, self.st, m.pan, m.tilt, m.vp, m.vt, *t.f, *raw,
            t.ex, t.ey, t.lvl, self.lux, self.power(self.lux), off, g,
        )

    def state_frame(self, wall: float | None = None) -> dict:
        wall = self.wall() if wall is None else wall
        t = self.tracker
        m = self.motion
        f = self.frame
        seeded = t.seeded
        off, g = self.offset_gain()
        bits = self.driver.ident.caps if self.driver.ident is not None else 0
        pv = None
        if bits & CAP_PV and f is not None and self.link:
            pv = {"v": r3(f.mv / 1000.0), "ma": r2(f.ua / 1000.0)}
        sim = None
        if self.driver.has_simlight:
            light = self.driver.light
            sim = {"az": r1(light.az), "el": r1(light.el), "on": light.on, "lux": r1(light.lux), "amb": r1(light.amb)}
        sun = None
        if self.sun is not None:
            s = self.sun
            sun = {"az": r1(s["az"]), "el": r1(s["el"]), "caz": r1(s["caz"]), "t": s["t"]}
        lux = self.lux if self.link else None
        return {
            "t": "s",
            "ts": round(wall, 3),
            "mode": self.mode.name,
            "st": self.st,
            "pan": r1(m.pan),
            "tilt": r1(m.tilt),
            "vp": r1(m.vp),
            "vt": r1(m.vt),
            "ldr": [r3(x) for x in t.f] if seeded else [None, None, None, None],
            "raw": list(f.raw) if f is not None else [None, None, None, None],
            "ex": r3(t.ex) if seeded else None,
            "ey": r3(t.ey) if seeded else None,
            "lvl": r3(t.lvl) if seeded else None,
            "lux": r1(lux),
            "pmw": r2(self.power(lux)),
            "pv": pv,
            "gain": r3(g),
            "off": r1(off),
            "tgt": {"pan": r1(self.tgt[0]), "tilt": r1(self.tgt[1])} if self.tgt is not None else None,
            "sun": sun,
            "sim": sim,
        }

    def sys_frame(self) -> dict:
        self._rate_stats()
        viewers, admins = self.sink.counts()
        info = self.sysinfo.sample() if self.sysinfo is not None else {"cpu": None, "temp": None, "mem": None}
        up = int(self.now - self.started) if self.started is not None else 0
        return {
            "t": "sys",
            "viewers": viewers,
            "admins": admins,
            "cpu": r1(info["cpu"]),
            "temp": r1(info["temp"]),
            "mem": r1(info["mem"]),
            "up": up,
            "hz": r1(self.hz),
            "jit": r2(self.jit),
            "drv": self.driver.name,
            "link": "ok" if self.link else "down",
            "fw": self.fw,
            "rec": bool(self.recorder is not None and self.recorder.on),
            "act": self.activity.kind if self.activity is not None else None,
            "drop": getattr(self.driver, "dropped", 0),
        }

    def hello(self, admin: bool = False) -> dict:
        return {
            "t": "hello",
            "proto": PROTO,
            "name": self.settings.data["name"],
            "version": __version__,
            "driver": self.driver.name,
            "caps": self.caps(),
            "admin": admin,
            "rate": self.params["rate"],
            "cfg": self.settings.cfg(),
        }

    def event(self, lvl: str, msg: str) -> None:
        level = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}.get(lvl, logging.INFO)
        log.log(level, "%s", msg)
        evt = {"t": "evt", "ts": round(self.wall(), 3), "lvl": lvl, "msg": msg}
        self.events.append(evt)
        self.sink.publish_admins(evt)

    def save_state(self) -> None:
        st = self.state
        st.pan = self.motion.pan
        st.tilt = self.motion.tilt
        st.mode = self.mode.name
        if self.driver.has_simlight and not isinstance(self.mode, MODES["sun"]):
            st.sim = self.driver.light_state()
        st.save()

    # commands, the websocket layer checks the input and calls these

    def _switch_mode(self, name: str) -> None:
        if self._entered:
            self.mode.leave(self)
        self.mode = make_mode(name)
        self._entered = False
        self.state.mode = name
        self.event("info", f"mode {name}")

    def _end_activity(self, why: str) -> None:
        if self.activity is not None:
            act = self.activity
            self.activity = None
            act.cancel(why)

    def set_mode(self, name: str) -> None:
        if name not in MODES:
            raise CommandError(f"unknown mode {name}")
        self._end_activity("stopped by a mode change")
        if name != self.mode.name or name == "manual":
            self._switch_mode(name)

    def _manual(self) -> Manual:
        self._end_activity("stopped by manual control")
        if not isinstance(self.mode, Manual):
            self._switch_mode("manual")
        return self.mode

    def set_target(self, pan: float, tilt: float) -> tuple[float, float]:
        lp, lt = self.settings.pan_limits, self.settings.tilt_limits
        pan, tilt = clamp(pan, *lp), clamp(tilt, *lt)
        self._manual().set_target(pan, tilt)
        return pan, tilt

    def set_rate(self, pan: float, tilt: float) -> None:
        self._manual().set_rate(clamp(pan, -1.0, 1.0), clamp(tilt, -1.0, 1.0), self.now)

    def set_value(self, key: str, value) -> float:
        try:
            v = self.settings.set_value(key, value)
        except ValueError as e:
            raise CommandError(str(e)) from None
        self.tracker.configure(self.params)
        self._cfg_dirty = True
        return v

    def set_site(self, lat, lon, heading) -> dict:
        try:
            site = self.settings.set_site(lat, lon, heading)
        except ValueError as e:
            raise CommandError(str(e)) from None
        self._cfg_dirty = True
        return site

    def set_sun(self, speed: float, start=None) -> None:
        self.sun_clock.set(speed, start)
        if self.mode.name != "sun":
            self.set_mode("sun")
        elif self._entered:
            # recompute right away so the new clock shows on the next frame
            self.mode._next = -1e9

    def set_simlight(self, az=None, el=None, on=None, lux=None, amb=None) -> dict:
        if not self.driver.has_simlight:
            raise CommandError("simlight needs the sim driver", "unsupported")
        if self.mode.name == "sun":
            raise CommandError("the sun moves the light in sun mode, pick another mode first", "busy")
        self.driver.set_light(az=az, el=el, on=on, lux=lux, amb=amb)
        return self.driver.light_state()

    def set_rec(self, on: bool) -> dict:
        if self.recorder is None:
            raise CommandError("recording needs a data folder", "unsupported")
        if on:
            path = self.recorder.start(self.now)
            self.event("info", f"recording to {path.name}")
            return {"file": path.name}
        self.recorder.stop()
        self.event("info", "recording stopped")
        return {}

    def start_activity(self, act: Activity) -> Activity:
        if self.stopping:
            raise CommandError("the tracker is shutting down", "busy")
        if self.activity is not None:
            raise CommandError(f"a {self.activity.kind} is running, stop it first", "busy")
        if not self.link:
            raise CommandError("no link to the board", "busy")
        act.start()
        self.activity = act
        return act

    def stop_activity(self) -> bool:
        if self.activity is None:
            return False
        self._end_activity("stopped")
        return True

    def light_value(self) -> float | None:
        # what a scan maps, lux on the panel plane when there is a sensor, else the mean level
        if self.lux is not None:
            return self.lux
        return self.tracker.lvl if self.tracker.seeded else None

    def mark_cfg(self) -> None:
        self._cfg_dirty = True

    def set_calibration(self, calib: dict, saved: bool) -> None:
        old_pan, old_tilt = self.pan_map, self.tilt_map
        pulses = (old_pan.to_us(self.motion.pan), old_tilt.to_us(self.motion.tilt))
        self.calib = calib
        self.calib_saved = saved
        self._apply_calib()
        if self.pan_map == old_pan and self.tilt_map == old_tilt:
            # only the sensor side changed, the head keeps its speed and the limiter brakes it
            return
        # a new servo mapping must not move the head, so the pose follows the pulses, the old
        # speeds mean nothing in the new angles
        lp, lt = self.settings.pan_limits, self.settings.tilt_limits
        self.motion.pan = clamp(self.pan_map.to_angle(pulses[0]), *lp)
        self.motion.tilt = clamp(self.tilt_map.to_angle(pulses[1]), *lt)
        self.motion.stop_now()
        self._force_send = True

    # running

    def begin_stop(self) -> None:
        self.stopping = True
        self._end_activity("the tracker is shutting down")

    def shutdown(self) -> None:
        self._end_activity("the tracker is shutting down")
        if self.recorder is not None:
            self.recorder.stop()
        self.motion.stop_now()
        self._force_send = True
        try:
            self._send(self.now)
        except Exception:
            log.exception("last servo command failed")
        self.save_state()
        if self.settings.dirty:
            self.settings.save()

    async def run(self, stop: asyncio.Event) -> None:
        ticker = Ticker(DT)
        ticker.start()
        deadline = None
        try:
            while True:
                await ticker.wait()
                now = time.perf_counter()
                if stop.is_set():
                    # stop motion with the normal deceleration instead of freezing mid swing
                    if deadline is None:
                        self.begin_stop()
                        deadline = now + 0.6
                    if self.motion.still or now > deadline:
                        break
                self.tick(now)
        finally:
            ticker.stop()
            self.shutdown()


__all__ = ["AUTO", "STOP", "CommandError", "DT", "Engine", "Sink"]
