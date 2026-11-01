# Protocols

brainSOL has two links. The Pi talks to the UNO over a serial line, and browsers talk to the Pi over
HTTP and a WebSocket. Both are plain text, so you can watch them with a serial monitor or the browser
dev tools.

Angles are degrees. Times are unix seconds with the milliseconds as decimals. A number that is
missing is `null`, never NaN. Fields marked as an addition go beyond the shared blueprint, the web
app may ignore them.

## Pi and UNO

115200 baud, 8N1, ASCII lines that end in `\n`. A `\r` is ignored wherever it sits. A line has at
most 96 characters. The sketch and its own description are in `firmware/`.

### From the UNO

| line | meaning |
|---|---|
| `I,brainsol,<fw>,<caps>` | identity, once after boot and as the answer to `?`. `fw` is a version like `1.0.0`, `caps` a bit field: 1 BH1750 found, 2 INA219 found |
| `S,<seq>,<l>,<r>,<u>,<d>,<lux10>,<mv>,<ua>,<pan_us>,<tilt_us>,<flags>` | sample frame at the report rate, 50 per second by default, the first one a period after the identity |
| `P,<n>` | answer to a ping, `n` comes back as sent |
| `E,<code>,<text>` | error, see below |

Fields of the sample frame:

- `seq` counts 0 to 65535 and wraps. It also counts frames the firmware had to skip because its
  transmit buffer was full, so a gap means lost frames. The Pi counts them and shows the total as
  `drop` in the `sys` frame. A gap is not an error.
- `l r u d` are the sums of 8 ADC readings of A0 to A3, 0 to 8184.
- `lux10` is lux times 10, 0 without a BH1750.
- `mv` is the panel voltage in mV and `ua` the panel current in microamps, 0 without an INA219.
  `ua` can be negative.
- `pan_us tilt_us` are the pulses going out right now, 0 while the servos are detached.
- `flags`: 1 servos attached, 2 no `M` for 1500 ms, 4 still slewing to the target.

The error lines and their texts:

| line | when |
|---|---|
| `E,1,unknown command` | the first field is not one of the letters below, or longer than one character |
| `E,1,wrong field count` | the letter is known but the number of fields is not |
| `E,1,bad number` | a value is not an optional minus and 1 to 9 digits, or a ping number not 1 to 20 digits |
| `E,1,bad character` | the line held a byte that is not printable ASCII |
| `E,2,line too long` | the line had more than 96 characters, the rest up to the newline is thrown away |

### To the UNO

| line | meaning |
|---|---|
| `?` | ask for the identity line |
| `M,<pan_us>,<tilt_us>` | servo targets, clamped to 500 to 2500 |
| `D` | detach both servos, the head goes limp |
| `R,<hz>` | report rate, clamped to 1 to 100, the next frame comes one new period later |
| `L,<us>` | slew cap in us per 10 ms, clamped to 1 to 200, default 30 |
| `P,<n>` | ping, `n` has 1 to 20 digits |

The letters may be lower case. A line that is not understood changes nothing, empty lines are
ignored.

### Rules on the board

- The board never moves on its own.
- An `M` while the servos are detached attaches them right at the commanded pulse, after boot and
  after a `D` too. Later targets are approached with the slew cap.
- If no `M` arrives for 1500 ms the board holds the last target and sets flag 2. The flag is also set
  before the first `M` and after a `D`, it only clears with the next `M`.
- A sensor that is missing at boot is looked for again every 3 s, one that fails three reads in a
  row reports 0. Its bit in `caps` only changes in the next identity line.
- A half line left from an earlier session is glued to the next line, which then answers `E,1`. The
  line after that works again.

### What the Pi does

- Opening the port resets the UNO through DTR. The Pi waits up to 5 s for the identity line. It
  sends `?` after 2.5 s of silence, right away when frames come without an identity (the board did
  not reset), again after an `E` line (the `?` was glued to a half line) and again after every
  second without an answer. Only then it sends anything else.
- Right after the identity it sends `R` and `L` from the settings, then the held pose as the first
  `M`. That pose comes from the state file, so the head does not jump on start. A first start
  without such a pose is described under `s` below.
- While running it sends `M` whenever a pulse changes and at least every 0.5 s, so the watchdog flag
  never comes up during normal work. A flag 2 on an attached board that keeps coming back while the
  Pi sends means commands get lost, the Pi logs that once.
- It sends `?` every 5 s and takes the caps from the answer.
- An identity line nobody asked for, or a `seq` that starts again near 0, means the board restarted
  by itself, mostly because the servos pulled its supply down. The Pi logs it and sends `R`, `L` and
  the held pose again, so the servos attach right where the head is.
- No bytes for 2 s, or a read or write error, ends the session. The Pi closes the port and tries
  again after 0.5, 1, 2, 4 and then every 5 s. The control loop shows `fault` and `link: down`
  meanwhile and holds the pose.
- An `E,1` in the first 2 s after a connect is a half line left over from before and is ignored.
- On Linux the port is locked while the Pi has it open, so a second program cannot read half the
  lines. `brainsolpi flash`, `doctor` and `centre` stop the `brainsolpi` service while they need the
  board and start it again afterwards. The sudo rules of `deploy/install.sh` allow that without a
  password.

## Pi and browsers

The server listens on port 8080. Everything under `/api/` answers JSON and carries
`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET, OPTIONS`,
`Access-Control-Allow-Headers: *` and `Cache-Control: no-store`, so the web app on GitHub Pages can
reach the Pi. Requests are limited to 64 kB.

### HTTP

| path | answer |
|---|---|
| `GET /api/info` | `{name, version, proto, driver, caps, viewers, uptime}` |
| `GET /api/history?span=900` | the last `span` seconds of the 1 Hz history, see below |
| `GET /api/experiments` | list of `{id, kind, ts, summary}`, newest first |
| `GET /api/experiments/<id>` | one result as `{id, kind, ts, summary, result}` |
| `GET /api/experiments/<id>.csv` | the rows of one result as CSV |
| `GET /api/record.csv?token=...` | the current or last recording, admins only |
| `OPTIONS /api/...` | 204 with the headers above, for browsers that ask first |
| `GET /healthz` | the text `ok` |
| `GET /ws` | the WebSocket |
| `GET /config.json` | `{"pi": "self"}` when there is a web folder, so a page loaded from the Pi talks to the Pi it came from |
| anything else | files from the `web` folder, `index.html` for page routes |

- `name` is the tracker name from the settings, `brainsol` by default. `driver` is `sim` or
  `bridge`, the fake board counts as `bridge`. `caps` is `{lux, pv, simlight}`. `viewers` counts the
  open WebSockets and `uptime` is the time since the service started, in seconds.
- History: `{t0, dt, cols, rows}`. `cols` is `["pan","tilt","lvl","lux","pmw","off","gain"]`, row
  `i` is the second `t0 + i * dt` and `dt` is 1. The buffer holds 6 hours, `span` goes from 1 to
  21600. A second the service missed is a row of nulls. Before the first row `t0` is now.
- `summary` of an experiment: cosine `{r2, peak, amb}`, compare `{gain, spread}`, step
  `{settle, overshoot}`. `id` looks like `cosine-20261114-153000`, a second one in the same second
  gets `-2`.
- CSV columns: cosine `delta,lux,fit`, compare `round,fixed,tracked,gain`, step
  `t,ex,ey,pan,tilt`.
- The recording has one row per tick of the 50 Hz loop with the columns `t,mode,st,pan,tilt,vp,vt,
  L,R,U,D,raw_l,raw_r,raw_u,raw_d,ex,ey,lvl,lux,pmw,off,gain`, `t` in seconds since the start of the
  recording. It stops by itself after an hour.
- Errors on `/api/` are `{err}` with the HTTP status, for example 400 for a `span` that is no
  number, 404 for an unknown experiment and 403 for a recording without a valid token.
- Files under `/_app/immutable/` are cached for a year, everything else with `no-cache`. A missing
  file with an extension in its name is a 404, a path without one gets `index.html`.
- Without a web folder every page path answers a short text that says where the built web app goes
  (`web` in the repo, or `--web`) and that the hosted page needs a tunnel address.

### WebSocket

JSON text frames, the field `t` names the type. On connect the server sends `hello`, then the last
`sys` frame and the last `scan` if there is one. Frames up to 8 kB are taken, binary frames, broken
JSON and unknown types are ignored. The server pings every 20 s and drops a browser that stops
answering.

#### Server to browser

```
hello  {t:"hello", proto:1, name, version, driver:"sim"|"bridge",
        caps:{lux, pv, simlight}, admin:false, rate, cfg}
s      {t:"s", ts, mode, st, pan, tilt, vp, vt, ldr:[L,R,U,D], raw:[l,r,u,d],
        ex, ey, lvl, lux, pmw, pv, gain, off, tgt, sun, sim}
sys    {t:"sys", viewers, admins, cpu, temp, mem, up, hz, jit, drv, link, fw, rec, act, drop}
ack    {t:"ack", id, ok:true, data?} or {t:"ack", id, ok:false, err, msg}
auth   {t:"auth", ok:true, token, exp} or {t:"auth", ok:false, err, msg, wait}
cfg    {t:"cfg", cfg}
scan   {t:"scan", id, pan:[...], tilt:[...], v:[[...]], done, best, stopped?, err?}
exp    {t:"exp", id, kind, phase, progress, result, err?}
evt    {t:"evt", ts, lvl:"info"|"warn"|"error", msg}
```

`hello` and `cfg`:

- `cfg` is `{limits:{pan:[lo,hi], tilt:[lo,hi]}, park:{pan,tilt}, site:{lat,lon,heading},
  panel:{w,h,eff}, baffle:1.2, params:{kp:{v,min,max,step}, ...}}`. Panel size is in mm, `eff` is
  0 to 1, `heading` is the compass bearing the device front faces. `params` holds every tunable of
  the controller, the range of `ref_pan` and `ref_tilt` follows the soft limits.
- The tunables and their defaults: `kp` 90, `vmax` 60, `amax` 240, `dead_in` 0.025, `dead_out`
  0.05, `tau` 0.12, `min_light` 0.08, `zenith_band` 6, `ref_pan` 0, `ref_tilt` 90, `rate` 20. A lit
  room with the lamp off gives a mean level of about 0.06, that is why `min_light` sits at 0.08.
- `hello` comes again when the board reports other sensors, with `admin` true for an admin. `cfg`
  goes to everyone when a setting changes, at most five times a second while a slider moves.

`s`, the state frame, sent `rate` times per second (5 to 30, default 20):

- `ts` unix seconds. `mode` is `auto`, `manual`, `sun`, `hold`, `park` or `demo`.
- `st` is one of `tracking`, `locked`, `lowlight`, `limit`, `moving`, `idle`, `scanning`,
  `measuring`, `calibrating`, `fault`. During an activity `mode` stays the mode the head goes back
  to and `st` says what the activity does. When the loop aims at an estimated light it says
  `moving` and `tgt` shows where it aims. `fault` means no link to the board or an internal error,
  the head holds meanwhile.
- `pan tilt` the commanded pose, `vp vt` the axis speeds in degrees per second, one decimal.
- `ldr` the filtered levels 0 to 1, made linear in light before they are normalised, `raw` the
  0 to 8184 sums, `ex ey` the errors and `lvl` the mean level, three decimals. Before the first
  sample from the board these are null, the lists then hold four nulls.
- `lux` from the BH1750, null without one or without a link. `pmw` the panel power in mW, measured
  with an INA219, else estimated from lux. `pv` `{v, ma}` in volts and milliamps with an INA219,
  else null.
- `gain` against a fixed panel at the reference pose, `off` the estimated angle between the panel
  normal and the light, both null in low light and without a link.
- `tgt` `{pan, tilt}` of a move, null while the loop tracks or holds.
- `sun` in sun mode, null in the other modes: `az el` seen from the device (azimuth clockwise from
  its front), and as an addition `caz` the compass azimuth and `t` the time of the sun clock, which
  runs ahead in time lapse.
- `sim` `{az, el, on, lux, amb}` with the sim driver, `lux` is the direct light, null otherwise.

The first start of a real board: when the settings hold no saved calibration for the board, or the
state file no pose the servos really reached, the tracker starts in `hold` with `st` `idle`, whatever
mode was saved. Without a pose no pulse goes out at all, the servos stay off. The first request that
moves the head (a mode, a target, the joystick, a scan, an experiment, the polarity step) switches
them on at pan 0 tilt 90, 1500 us with the default calibration, which is where `brainsolpi centre`
mounts the horns. `st` is `moving` for half a second while they get there. Saving a calibration ends
the hold and the tracker goes on in the saved mode, `auto` on a new Pi, picking a mode ends it as
well. Admins get the reasons as `evt` lines at the start and again when they unlock. The sim never
holds like this.

`sys`, once per second:

- `viewers` the open WebSockets, `admins` how many of them are unlocked.
- `cpu` percent of the whole machine, `temp` the SoC temperature in degrees Celsius, `mem` percent
  of memory in use. Each is null where the platform does not say.
- `up` seconds since the service started.
- `hz` the measured loop rate and `jit` the standard deviation of the tick intervals in ms, both
  over the last second.
- `drv` `sim` or `bridge`, `link` `ok` or `down`, `fw` the firmware version or null for the sim.
- `rec` true while recording, `act` `scan`, `exp`, `calib` or null.
- `drop` serial frames lost since the start, always 0 with the sim. This field is an addition.

`ack` and `auth`:

- `err` in a failed `ack` is a short code: `admin` (viewers cannot do this), `bad` (a field is
  missing or out of range), `busy` (an activity runs, no link to the board, too many commands),
  `unknown` (no such op) or `unsupported` (not with this driver or on this platform). `msg` says
  the details in plain English, it is an addition.
- A failed `auth` has `err` `pin` (wrong pin, locked, or no pin set on the Pi) or `token` (unknown
  or expired token, or the pin changed). `wait` is the number of seconds until the next try is
  allowed, 0 when there is no lock. `msg` says the details, it is an addition. When `brainsolpi
  setpin` changes the pin while the service runs, every admin gets such a frame with `token` and
  is a viewer again.
- `exp` in a good `auth` is when the token runs out, unix seconds.

`scan`:

- `v[i][j]` is the light at `tilt[i]` and `pan[j]`, null until the cell was visited. With a BH1750
  the values are lux with one decimal, else the mean level with three.
- A frame goes out at the start and after every cell. `best` `{pan, tilt, v}` is the brightest cell
  so far.
- The last frame has `done: true`. A scan that was stopped or failed adds `stopped: true` and `err`,
  both additions. In `auto` the head ends facing the brightest cell.

`exp`:

- `phase` is `lock`, `sweep`, `fit`, `ref`, `track`, `offset`, `release`, `done` or `error`,
  `progress` goes from 0 to 1 with three decimals. `result` is null until `done`. On `error` the
  frame adds `err`, an addition.
- The results, also inside `/api/experiments/<id>`:
  - cosine: `{peak, amb, r2, points:[[delta, lux], ...]}` plus `fit` (the fitted curve at the same
    angles), `offset` (the pointing error the fit took out, degrees) and `lock`
  - compare: `{gain, spread, rounds:[{fixed, tracked}, ...]}` plus `gain` per round, `sd` and `ref`
  - step: `{settle, overshoot, samples:[[t, ex, ey, pan, tilt], ...]}` plus `overshoot_pct`,
    `offset`, `lock` and `final`. `settle` is null when there was no lock within 8 s.
- cosine and compare need a BH1750.

`evt` goes to admins only: mode changes, link up and down, board restarts, calibration steps,
scans and experiments, recordings, admins that unlock, and the notes of a first start.

#### Browser to server

```
auth   {t:"auth", pin} or {t:"auth", token}
cmd    {t:"cmd", id, op, ...}
```

| op | fields | who | `data` of a good ack |
|---|---|---|---|
| `ping` | | anyone | `{ts}` |
| `mode` | `mode` | admin | `{mode}` |
| `target` | `pan` -180 to 180, `tilt` -90 to 270 | admin, switches to manual, clamped to the soft limits | `{pan, tilt}` as clamped |
| `rate` | `pan, tilt`, clamped to -1 to 1 | admin, joystick, switches to manual, runs out after 400 ms without a refresh | none |
| `set` | `key, value` | admin, one setting | `{key, value}` |
| `site` | `lat, lon, heading` | admin | `{lat, lon, heading}` |
| `sun` | `speed` 1 to 3600, optional `date` | admin, switches to sun mode | `{speed, t}` |
| `scan` | optional `step` 5 to 45, default 15 | admin | `{id, cells}` |
| `exp` | `kind` `cosine`, `compare` or `step` | admin | `{id, kind}` |
| `stop` | | admin, ends the running activity | `{stopped}` |
| `calib` | `step`, optional `values` | admin | see below |
| `simlight` | `az, el`, optional `on, lux` 0 to 200000, `amb` 0 to 100000 | admin, sim driver only | `{az, el, on, lux, amb}` |
| `rec` | `on` | admin | `{file}` when it starts, `{}` when it stops |
| `sys` | `action` `restart`, `reboot` or `shutdown` | admin | `{action}` |

Details:

- `set` takes the tunables `kp vmax amax dead_in dead_out tau min_light zenith_band ref_pan
  ref_tilt rate`. As an addition it also takes `pan_min pan_max tilt_min tilt_max park_pan
  park_tilt panel_w panel_h panel_eff`. `dead_in` has to stay below `dead_out`, the soft limits keep
  at least 10 degrees between both ends.
- `sun`: `date` is an ISO date or date and time. A date alone keeps the time of day, a time without
  a zone is the local time of the Pi. Speed 1 without a date is the real clock again. `t` in the ack
  is the time of the sun clock.
- `simlight`: `az` is wrapped into -180 to 180, `el` comes as -90 to 90 and is kept to 0 to 90. It
  is refused in sun mode, the sun moves the light there.
- `calib` steps: `dark` and `bright` capture the raw sums for a second (sensors covered, then a
  lamp on them) and answer when done with `{dark, bright, span, inverted, weak}` plus the captured
  values, `busy` after 60 s. The head brakes through the normal limiter meanwhile. `values` sets
  them directly as `{L, R, U, D}` or a list in that order. `zero` stores the pulses going out now as
  the servo centre and answers `{pan_us, tilt_us, pan, tilt}`, `values` may give `{pan_us, tilt_us}`
  instead, without them it is refused while the servos are still off. `polarity` turns each axis 4 degrees each
  way under a fixed lamp and learns the sign of the loop, it needs light and the head at least 11
  degrees away from flat, and answers `{sx, sy, dx, dy}`. `save` writes the calibration to the
  settings and `reset` goes back to the defaults, both answer like `dark`. Nothing is kept over a
  restart without `save`. The sim and the real board have their own calibration, the fake board
  uses the one of the sim. The first `save` of a board names the measuring steps that did not run.
- `sys`: `restart` restarts the service in place, `reboot` and `shutdown` run `sudo -n systemctl
  reboot` and `poweroff`, so they need the sudoers rule that `deploy/install.sh` writes, and only
  work on the Pi.
- Viewers are read only, admin needs the pin. Five wrong tries lock the pin for 30 s, the lock
  doubles each time up to an hour, a good pin resets it. A token lasts 12 hours, survives reconnects
  and restarts of the service. Without a pin set on the Pi every login is refused.

Rate limit and queues:

- Every browser has a budget of commands that refills with 40 per second and holds at most 80. A
  command over the budget is answered with `ok:false`, `err` `busy` and the `msg` "too many commands,
  slow down", a `rate` command over it is dropped without an answer, the next one comes soon enough.
- Every browser has its own queue of 32 frames. When it reads too slowly old state frames are
  dropped first, then older `sys`, `scan`, `cfg`, `exp` and `evt` frames that a newer one of the same
  kind makes worthless. Only the newest `sys` and `cfg` wait at any time. A browser with 256 frames
  waiting is closed.
- All browsers are closed together when the service stops.
