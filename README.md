# brainsolpi

The Pi side of brainSOL, a dual axis solar tracker demo. One Python process runs the control loop at
50 Hz, talks to the UNO over USB and serves the web app and its live data on port 8080. Without a
board it runs a simulation of the whole tracker, so everything works on any PC.

The web app lives in the `brainsol` repo and is hosted at sol.swimmingbrain.dev.

## Try it

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```
uv sync
uv run brainsolpi run --driver sim --pin 2468
```

Then open `http://localhost:8080/api/info`, or point the web app at `localhost:8080`. The pin on the
command line is for development, on the Pi you set one with `brainsolpi setpin`.

## Commands

| command | what it does |
|---|---|
| `brainsolpi run` | the tracker and the web server. `--driver auto` (default) uses the board when one answers within 6 s and the sim otherwise, `--driver sim`, `bridge` or `fake` pick one |
| `brainsolpi doctor` | a step by step check for the day the hardware arrives: port, firmware, frame rate, each light sensor, the BH1750, the servos. `--fake` tries it on a simulated board |
| `brainsolpi flash` | uploads `firmware/brainsol_bridge.hex` with avrdude |
| `brainsolpi setpin` | asks for the admin pin twice and stores a salted hash |
| `brainsolpi centre` | holds both servos at 1500 us while you mount the horns |

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
