# brainsolpi

The Pi side of brainSOL, a dual axis solar tracker demo. One Python process runs the control loop at
50 Hz, talks to the UNO over USB and serves the web app and its live data on port 8080. Without a
board it runs a simulation of the whole tracker, so everything works on any PC.

The web app lives in the `brainsol` repo and is hosted at sol.swimmingbrain.dev.

## Try it

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```
uv sync
uv run brainsolpi demo
```

It prints the address to open and an admin pin for this run, listens on this computer only and
keeps nothing after Ctrl+C. For development with your own folders and a fixed pin:

```
uv run brainsolpi run --driver sim --pin 2468 --config-dir tmp/config --data-dir tmp/data
```

On the Pi you set the pin with `brainsolpi setpin`.

## Commands

| command | what it does |
|---|---|
| `brainsolpi run` | the tracker and the web server. `--driver auto` (default) uses the board when one answers within 6 s and the sim otherwise, `--driver sim`, `bridge` or `fake` pick one |
| `brainsolpi demo` | the sim on this computer with a pin for the run, nothing is kept |
| `brainsolpi doctor` | a step by step check for the day the hardware arrives: port, firmware, frame rate, each light sensor, the BH1750, the servos, then the exact next steps. `--fake` tries it on a simulated board |
| `brainsolpi flash` | uploads `firmware/brainsol_bridge.hex` with avrdude, at 57600 baud once more when 115200 fails, then waits for the board to say hello |
| `brainsolpi setpin` | asks for the admin pin twice and stores a salted hash, a running tracker takes it over |
| `brainsolpi centre` | holds both servos at 1500 us while you mount the horns |

`doctor`, `flash` and `centre` need the board alone. When the `brainsolpi` service runs they stop it
first and start it again at the end, sudo may ask for your password for that.

## The first start on the real hardware

The default calibration comes from the simulated phone light and will not fit the real sensors, and
nobody knows where the head sits before the servos got their first pulse. So a board without a
saved calibration, or without a pose the servos really reached, starts in `hold`. Without a pose the
servos stay off until the head has to move, then they start at pan 0 tilt 90, where `brainsolpi
centre` puts the horns. The event log in the admin tools says why. Saving the calibration in the
calibrate tab ends the hold and the tracker goes on in auto, picking a mode ends it as well.
`brainsolpi doctor` ends with these steps for your setup.

Settings and state are in `~/.config/brainsolpi/`, experiments and recordings in
`~/.local/share/brainsolpi/` (on Windows in `%APPDATA%` and `%LOCALAPPDATA%`).

## Tests

```
uv run pytest
```

The tests run the controller in the simulation from hundreds of poses, drive the bridge driver
against a fake board that speaks the serial protocol, talk to the server over a real WebSocket and
run ten simulated minutes of random commands.

## Docs

- [docs/protocol.md](docs/protocol.md) the serial protocol to the UNO and the protocol to the browsers

## License

MIT, see [LICENSE](LICENSE).
