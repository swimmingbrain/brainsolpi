# Protocols

brainSOL has two links. The Pi talks to the UNO over a serial line, and browsers talk to the Pi over
HTTP and a WebSocket. Both are plain text, so you can watch them with a serial monitor or the browser
dev tools.

Angles are degrees. Times are unix seconds with the milliseconds as decimals. A number that is
missing is `null`, never NaN.

## Pi and UNO

115200 baud, 8N1, ASCII lines that end in `\n`. A `\r` before it is ignored. A line has at most 96
characters.

### From the UNO

| line | meaning |
|---|---|
| `I,brainsol,<fw>,<caps>` | identity, once after boot and as the answer to `?`. `fw` is a version like `1.0.0`, `caps` a bit field: 1 BH1750 found, 2 INA219 found |
| `S,<seq>,<l>,<r>,<u>,<d>,<lux10>,<mv>,<ua>,<pan_us>,<tilt_us>,<flags>` | sample frame at the report rate, 50 per second by default |
| `P,<n>` | answer to a ping, `n` is echoed as sent |
| `E,<code>,<text>` | error or notice, code 1 bad command, 2 line too long |

Fields of the sample frame:

- `seq` counts 0 to 65535 and wraps. It also counts frames the firmware had to skip because its
  transmit buffer was full, so a gap means lost frames. The Pi counts them and shows the total as
  `drop` in the `sys` frame. A gap is not an error.
- `l r u d` are the sums of 8 ADC readings of A0 to A3, 0 to 8184.
- `lux10` is lux times 10, 0 without a BH1750.
- `mv` is the panel voltage in mV and `ua` the panel current in microamps, 0 without an INA219.
  `ua` can be negative.
- `pan_us tilt_us` are the pulses going out right now, 0 while the servos are detached.
- `flags`: 1 servos attached, 2 command watchdog expired, 4 still slewing to the target.

### To the UNO

| line | meaning |
|---|---|
| `?` | ask for the identity line |
| `M,<pan_us>,<tilt_us>` | servo targets, clamped to 500 to 2500 |
| `D` | detach both servos, the head goes limp |
| `R,<hz>` | report rate, 1 to 100, other values are clamped |
| `L,<us>` | slew cap in us per 10 ms, 1 to 200, default 30, other values are clamped |
| `P,<n>` | ping, `n` has 1 to 20 digits |

### Rules on the board

- The board never moves on its own.
- An `M` while the servos are detached attaches them right at the commanded pulse, after boot and
  after a `D` too. Later targets are approached with the slew cap.
- If no `M` arrives for 1500 ms the board holds the last target and sets flag 2. The flag is also set
  before the first `M` and after a `D`, it only clears with the next `M`.
- A sensor that is plugged in later is found by the board, but its bit only shows in the next
  identity line.
- Unknown lines get `E,1,...`.

### What the Pi does

- Opening the port resets the UNO through DTR. The Pi waits up to 5 s for the identity line and
  sends `?` once after 2.5 s of silence. Only then it sends anything else.
- Right after the identity it sends `R` and `L` from the settings, then the held pose as the first
  `M`. That pose comes from the state file, so the head does not jump on start.
- While running it sends `M` whenever a pulse changes and at least every 0.5 s, so the watchdog flag
  never comes up during normal work. A flag 2 on an attached board that keeps coming back while the
  Pi sends means commands get lost, the Pi logs that once.
- It sends `?` every 5 s and takes the caps from the answer.
- No bytes for 2 s, or a read or write error, ends the session. The Pi closes the port and tries
  again after 0.5, 1, 2, 4 and then every 5 s. The control loop shows `fault` and `link: down`
  meanwhile and holds the pose.
- An `E,1` in the first 2 s after a connect is a half line left over from before and is ignored.

## Pi and browsers

The server listens on port 8080. Everything under `/api/` answers JSON and carries
`Access-Control-Allow-Origin: *`, so the web app on GitHub Pages can reach the Pi.

### HTTP

| path | answer |
|---|---|
| `GET /api/info` | `{name, version, proto, driver, caps, viewers, uptime}` |
| `GET /api/history?span=900` | the last `span` seconds of the 1 Hz history, see below |
| `GET /api/experiments` | list of `{id, kind, ts, summary}`, newest first |
| `GET /api/experiments/<id>` | one result as `{id, kind, ts, summary, result}` |
| `GET /api/experiments/<id>.csv` | the rows of one result as CSV |
| `GET /api/record.csv?token=...` | the current or last recording, admins only |
| `GET /healthz` | the text `ok` |
| `GET /ws` | the WebSocket |
| `GET /config.json` | `{"pi": "self"}`, so a page loaded from the Pi talks to the Pi it came from |
| anything else | files from the `web` folder, `index.html` for page routes |

- `uptime` is the time since the service started, in seconds.
- History: `{t0, dt, cols, rows}`. `cols` is `["pan","tilt","lvl","lux","pmw","off","gain"]`, row
  `i` is the second `t0 + i * dt` and `dt` is 1. The buffer holds 6 hours, `span` goes from 1 to
  21600. A second the service missed is a row of nulls.
- Errors on `/api/` are `{err}` with the HTTP status, for example 404 for an unknown experiment and
  403 for a recording without a valid token.
- A missing file with an extension in its name is a 404, a path without one gets `index.html`.

### WebSocket

JSON text frames, the field `t` names the type. On connect the server sends `hello`, then the last
`sys` frame and the last `scan` if there is one.

#### Server to browser

```
hello  {t:"hello", proto:1, name:"brainsol", version, driver:"sim"|"bridge",
        caps:{lux, pv, simlight}, admin:false, rate:20, cfg}
s      {t:"s", ts, mode, st, pan, tilt, vp, vt, ldr:[L,R,U,D], raw:[l,r,u,d],
        ex, ey, lvl, lux, pmw, pv, gain, off, tgt, sun, sim}
sys    {t:"sys", viewers, admins, cpu, temp, mem, up, hz, jit, drv, link, fw, rec, act, drop}
ack    {t:"ack", id, ok:true, data?} or {t:"ack", id, ok:false, err, msg}
auth   {t:"auth", ok:true, token, exp} or {t:"auth", ok:false, err, msg, wait}
cfg    {t:"cfg", cfg}
scan   {t:"scan", id, pan:[...], tilt:[...], v:[[...]], done, best}
exp    {t:"exp", id, kind, phase, progress, result}
evt    {t:"evt", ts, lvl:"info"|"warn"|"error", msg}
```

`hello` and `cfg`:

- `cfg` is `{limits:{pan:[lo,hi], tilt:[lo,hi]}, park:{pan,tilt}, site:{lat,lon,heading},
  panel:{w,h,eff}, baffle:1.2, params:{kp:{v,min,max,step}, ...}}`. Panel size is in mm, `eff` is
  0 to 1, `heading` is the compass bearing the device front faces. `params` holds every tunable of
  the controller, the range of `ref_pan` and `ref_tilt` follows the soft limits.
- `hello` comes again when the board reports other sensors, and `cfg` goes to everyone when a
  setting changes.

`s`, the state frame, sent `rate` times per second (5 to 30, default 20):

- `ts` unix seconds. `mode` is `auto`, `manual`, `sun`, `hold`, `park` or `demo`.
- `st` is one of `tracking`, `locked`, `lowlight`, `limit`, `moving`, `idle`, `scanning`,
  `measuring`, `calibrating`, `fault`. During an activity `mode` stays the mode the head goes back
  to and `st` says what the activity does. When the loop aims at an estimated light it says
  `moving` and `tgt` shows where it aims.
- `pan tilt` the commanded pose, `vp vt` the axis speeds in degrees per second, one decimal.
- `ldr` the filtered levels 0 to 1, made linear in light before they are normalised, `raw` the
  0 to 8184 sums, `ex ey` the errors and `lvl` the mean level, three decimals.
- `lux` from the BH1750, `pmw` the panel power in mW (measured with an INA219, else estimated from
  lux), `pv` `{v, ma}` in volts and milliamps with an INA219, else null.
- `gain` against a fixed panel at the reference pose, `off` the estimated angle between the panel
  normal and the light, both null in low light.
- `tgt` `{pan, tilt}` of a move, null while the loop tracks or holds.
- `sun` `{az, el, caz, t}` in sun mode: `az el` seen from the device (azimuth clockwise from its
  front), `caz` the compass azimuth and `t` the time of the sun clock, which runs ahead in time
  lapse. Null in the other modes.
- `sim` `{az, el, on, lux, amb}` with the sim driver, `lux` is the direct light, null otherwise.

`sys`, once per second:

- `cpu` percent of the whole machine, `temp` the SoC temperature in degrees Celsius, `mem` percent
  of memory in use. Each is null where the platform does not say.
- `up` seconds since the service started.
- `hz` the measured loop rate and `jit` the standard deviation of the tick intervals in ms.
- `drv` `sim` or `bridge`, `link` `ok` or `down`, `fw` the firmware version or null for the sim.
- `rec` true while recording, `act` `scan`, `exp`, `calib` or null.
- `drop` serial frames lost since the start, always 0 with the sim. This field is an addition.

`ack` and `auth`:

- `err` in a failed `ack` is a short code: `admin` (viewers cannot do this), `bad` (a field is
  missing or out of range), `busy` (an activity runs, no link to the board, too many commands),
  `unknown` (no such op) or `unsupported` (not with this driver or on this platform). `msg` says
  the details in plain English.
- A failed `auth` has `err` `pin` (wrong pin, locked, or no pin set on the Pi) or `token` (unknown
  or expired token, or the pin changed). `wait` is the number of seconds until the next try is
  allowed, 0 when there is no lock. `msg` says the details.
- `exp` in a good `auth` is when the token runs out, unix seconds.

`scan`:

- `v[i][j]` is the light at `tilt[i]` and `pan[j]`, null until the cell was visited. With a BH1750
  the values are lux, else the mean level.
- A frame goes out after every cell. `best` is the brightest cell so far.
- The last frame has `done: true`. A scan that was stopped or failed adds `stopped: true` and `err`.

`exp`:

- `phase` is `lock`, `sweep`, `fit`, `ref`, `track`, `offset`, `release`, `done` or `error`,
  `progress` goes from 0 to 1. `result` is null until `done`. On `error` the frame adds `err`.
- The results, also inside `/api/experiments/<id>`:
  - cosine: `{peak, amb, r2, points:[[delta, lux], ...]}` plus `fit` (the fitted curve at the same
    angles), `offset` (the pointing error the fit took out, degrees) and `lock`
  - compare: `{gain, spread, rounds:[{fixed, tracked}, ...]}` plus `gain` per round, `sd` and `ref`
  - step: `{settle, overshoot, samples:[[t, ex, ey, pan, tilt], ...]}` plus `overshoot_pct`,
    `offset`, `lock` and `final`. `settle` is null when there was no lock within 8 s.

#### Browser to server

```
auth   {t:"auth", pin} or {t:"auth", token}
cmd    {t:"cmd", id, op, ...}
```

| op | fields | who |
|---|---|---|
| `ping` | | anyone, `data:{ts}` |
| `mode` | `mode` | admin |
| `target` | `pan, tilt` | admin, switches to manual, clamped to the soft limits |
| `rate` | `pan, tilt` each -1 to 1 | admin, joystick, switches to manual, runs out after 400 ms without a refresh |
| `set` | `key, value` | admin, one tunable |
| `site` | `lat, lon, heading` | admin |
| `sun` | `speed` 1 to 3600, optional `date` | admin, switches to sun mode |
| `scan` | optional `step` 5 to 45, default 15 | admin |
| `exp` | `kind` `cosine`, `compare` or `step` | admin |
| `stop` | | admin, ends the running activity |
| `calib` | `step`, optional `values` | admin |
| `simlight` | `az, el`, optional `on, lux, amb` | admin, sim driver only |
| `rec` | `on` | admin |
| `sys` | `action` `restart`, `reboot` or `shutdown` | admin |

Details:

- `set` takes the tunables `kp vmax amax dead_in dead_out tau min_light zenith_band ref_pan
  ref_tilt rate`. As an addition it also takes `pan_min pan_max tilt_min tilt_max park_pan
  park_tilt panel_w panel_h panel_eff`. `dead_in` has to stay below `dead_out`.
- `sun`: `date` is an ISO date or date and time. A date alone keeps the time of day, a time without
  a zone is the local time of the Pi. Speed 1 without a date is the real clock again.
- `calib` steps: `dark` and `bright` capture the raw sums for a second (sensors covered, then a
  lamp on them) and answer when done, `values` sets them directly as `{L, R, U, D}` or a list in
  that order. `zero` stores the pulses going out now as the servo centre, `values` may give
  `{pan_us, tilt_us}` instead. `polarity` turns each axis 4 degrees each way under a fixed lamp and
  learns the sign of the loop, it needs the head at least 11 degrees away from flat. `save` writes
  the calibration to the settings, `reset` goes back to the defaults. Nothing is kept over a restart
  without `save`. The sim and the real board have their own calibration.
- `sys`: `restart` restarts the service, `reboot` and `shutdown` need a sudoers rule for
  `systemctl reboot` and `systemctl poweroff` and only work on the Pi.
- Viewers are read only, admin needs the pin. Five wrong tries lock the pin for 30 s, the lock
  doubles each time up to an hour, a good pin resets it. A token lasts 12 hours, survives reconnects
  and restarts of the service.
- A client may send about 40 commands per second. Every client has a small queue, when it reads too
  slowly old state frames are dropped first, and a client that stops reading is closed.
