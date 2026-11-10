# Checklist for the seminar talk

A plan for the network, a test the evening before, a five minute demo and what to do when something fails.

## The network plan

University WiFi usually keeps devices apart: your laptop cannot reach the Pi there, and `.local` names do
not work. So the Pi and the laptop do not use it at all.

1. **A phone hotspot for the Pi and the laptop.** Teach the Pi the hotspot at home, with the hotspot
   switched on:

   ```
   sudo nmcli device wifi connect "<hotspot name>" password "<password>"
   sudo nmcli connection modify "<hotspot name>" connection.autoconnect-priority 10
   ```

   The Pi then joins the hotspot whenever it is in range and prefers it over the home WiFi. Connect the
   laptop to the same hotspot.

2. **The tunnel, so the audience can watch on their own phones.** With a Cloudflare Tunnel or a Tailscale
   Funnel (`deploy/tunnel.md`) the Pi gets an https address. Anyone can then open
   `https://sol.swimmingbrain.dev/?pi=solpi.swimmingbrain.dev` on mobile data or the university WiFi. The
   tunnel runs over the hotspot, every phone that watches costs about 7 KB per second of upload, 30 phones
   about 1.7 Mbit/s. The audience can only watch, without the pin nobody changes anything.

3. **The offline plan: the page served by the Pi.** When the internet fails, the laptop still reaches the
   Pi through the hotspot. Open `http://brainsol.local:8080`, or the address of the Pi that the hotspot
   settings of the phone list under connected devices. This needs the web app on the Pi, run
   `deploy/web.sh` at home beforehand.

4. **The last resort: the simulation.** When the Pi does not come up at all, the page runs the built in
   simulation in the browser. With no internet either, `uv run brainsolpi demo` on the laptop runs the
   whole tracker simulated and serves the page itself, if the web app is in the `web` folder of the repo on
   the laptop.

## The evening before

- [ ] Run `deploy/update.sh` on the Pi, then `brainsolpi doctor`. Every step ok, no low voltage warning.
- [ ] Power supply, the USB cable and the phone torch are packed. The official supply of the Pi, 5.1 V
      2.5 A micro USB for a Pi 3B+ or 5.1 V 3 A USB C for a Pi 4, not a phone charger.
- [ ] Switch the hotspot on, power the Pi and check that the laptop opens `http://brainsol.local:8080`.
- [ ] On a phone with mobile data only, open the tunnel address and check that the chip says Live.
- [ ] Unlock the admin tools, so you know the pin still works. Open the Connection tab and look at the QR
      code under Share with the audience. It should hold the public address with `?pi=`.
- [ ] Set the site in the Sun group of the Control tab to the room of the talk, with the direction the
      front of the tracker will face.
- [ ] Run the calibration again under light like in the room, if you can. Capture bright with the torch
      close.
- [ ] Try presentation mode on the projector or a big screen, the button is in the top bar.
- [ ] Run a sky scan and the Cosine law experiment once, so the Scan tab already has a map and Results in
      the Experiments tab of the admin tools already has a curve to show, in case the live run is cut short.
- [ ] Charge the phone that makes the hotspot and the phone that is the light. Switch off the auto lock of
      the light phone.

## Five minutes of demo

| time | what you do | what you say |
|---|---|---|
| 0:00 | Show the QR code from Share with the audience in the Connection tab | everyone can watch live on their own phone |
| 0:30 | Switch to presentation mode, the live 3D twin fills the screen | the twin moves exactly like the real head next to me, the chip says Live |
| 1:00 | Move the phone torch slowly around the tracker. On the simulation drag the lamp in the 3D view | four light sensors around the panel, each with a shade wall, the head turns until all four see the same |
| 1:45 | Point at the Light balance | the dot drifts to the brighter side, the tracker turns until it sits in the middle, the dead band stops it from hunting |
| 2:15 | Scan tab, grid step 30 degrees, Start scan | the head visits the sky and maps the light, about a minute, then it points at the brightest spot |
| 3:15 | Experiments tab, Cosine law, Start | it locks on the light and tilts away in steps of 5 degrees: 25 degrees off still gives 91 %, 60 degrees off only half |
| 4:00 | Once the experiment says done, it takes well under a minute: Control tab, Sun group, time lapse One hour per second, Go. A mode change would stop a running experiment | sun mode does not measure, it computes where the sun is for this place and follows it, a day in a few seconds |
| 4:30 | Experiments tab, Show its curve and the CSV under Last experiment | the cosine law result: the measured points, the fitted curve and its R squared, the same numbers as a CSV for the paper |

While the scan and the experiment run, talk about the parts: the UNO only reads sensors and drives servos,
the Pi runs the control loop at 50 Hz and the web server, and the page is the same everywhere.

## When something fails

| what happens | what you do |
|---|---|
| the chip says Simulation on the projector | the page has no tracker. Open `http://brainsol.local:8080` from the hotspot, or carry on with the simulation, every feature works there too |
| the audience page stays on the simulation | the tunnel or the internet is down. Show it on the projector only and say so |
| the head does not move | the state shows why: too dark means more light, holding means pick a mode in the Control tab, at a limit means the light is out of reach |
| the head runs away from the light | the directions are wrong for this setup. Calibrate tab, Find the directions, Save calibration, takes half a minute |
| the head jitters or the board restarts | the supply is too weak. Use the official supply, see `docs/troubleshooting.md`, or switch to the simulation |
| the pin is locked after wrong tries | wait, the time is shown. The talk goes on as a viewer meanwhile |
| a scan or an experiment takes too long | Stop in its tab, the head goes back to its mode |
| nothing works at all | `uv run brainsolpi demo` on the laptop and the simulation on the projector |
