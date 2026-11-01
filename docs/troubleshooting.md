# Troubleshooting

Each entry says what you see, why it happens and what to do. Two commands help almost always:

```
brainsolpi doctor
journalctl -u brainsolpi -n 50
```

The first checks the board, the sensors and the servos step by step and ends with the next steps for
your setup. The second shows the last 50 lines of the tracker service. The event log in the System tab of
the admin tools shows the same events while you watch.

## Nothing moves after the first start

**What you see:** the service runs, the page is live, but the head does not move and the state says holding.

**Why:** a board without a saved calibration starts in `hold`. If no pose was ever driven, not even a pulse
goes out, the servos stay off until the head has to move. The event log says so.

**Fix:** go through the calibration in the Calibrate tab and press Save calibration, the tracker then goes
on in auto. Picking a mode in the Control tab ends the hold as well. See `docs/first-start.md`.

## No board found

**What you see:** the log says `no serial port found` or `no board answered within 6 s, falling back to the
sim driver`. The System tab says Driver simulation.

**Why:** the USB cable is not plugged in, it is a charge only cable, or the UNO still runs the code it came
with and never sends the brainSOL identity line. A serial monitor in another window can also hold the port.

**Fix:**

1. `ls /dev/ttyACM* /dev/ttyUSB*` should show `/dev/ttyACM0` (a clone board shows `/dev/ttyUSB0`). If
   not, try the cable of the kit and another USB port.
2. Flash the bridge firmware: `brainsolpi flash`.
3. Close every serial monitor, then run `brainsolpi doctor`.

You do not have to restart anything. While the service runs the simulation it looks for a board every 3 s
and restarts into the real board as soon as one answers. A board without the bridge firmware is left alone,
`brainsolpi flash` stops and starts the service and then the board is found.

## The servos jitter, the board restarts or the Pi reports low voltage

**What you see:** the head twitches, the event log says `the board restarted by itself`, or
`brainsolpi doctor`, `deploy/install.sh` or `deploy/update.sh` warn about low voltage. `journalctl -k`
shows `Undervoltage detected!`.

**Why:** the Pi powers the UNO and both servos through the USB cable. Its power supply has to carry all of
it. When the 5 V input of the Pi sags below about 4.63 V, the Pi notices it and sets a flag, that is the low
voltage warning. USB devices then get too little, the UNO resets and the servos lose their pulse for a
moment. A 9 g servo draws a few hundred mA while it moves and up to 850 mA when it stalls.

**Fix:**

1. Use the official 5.1 V 2.5 A micro USB supply of the Pi 3B+ or a better one. A phone charger, a laptop
   port or a long thin cable is not enough.
2. Plug the UNO straight into the Pi, not through a hub.
3. Check the flag again after a reboot: `vcgencmd get_throttled` should say `throttled=0x0`. A value like
   `0x50005` means low voltage happened since the start.
4. Check that both servo plugs sit firmly with brown on G.

The motion limits already keep the current low: the Pi caps speed and acceleration, the board moves a pulse
by at most 30 us every 10 ms, so a servo never gets a big jump, and the soft limits stop the head before the
ends of its range. Lower Top speed and Acceleration in the Tuning tab make the peaks even smaller.

## The head runs to a limit and stays there

**What you see:** the head turns away from the light until the state says at a limit.

**Why:** the loop pushes the wrong way. Either a servo turns the other way than the software thinks, or the
cables of two sensors are swapped. The default directions come from the simulation, the real build can
differ.

**Fix:**

1. Run `brainsolpi doctor`. In the light sensor step it says for example `R reacted instead of L, the cables
   on A0 and A1 look swapped`. Fix the cables as it says.
2. In the Calibrate tab run Find the directions: tilt the head up first if it lies flat (the button Tilt it up
   does that), keep the lamp still in front of the head and press Find directions. The tracker turns each
   axis a little and learns which way is which.
3. Press Save calibration.

## Tracking is lazy in a bright room

**What you see:** with the lamp the tracker follows well, under room lights or near a window it turns only a
little or not at all.

**Why:** the tracker turns each sensor reading into a level between 0 and 1, where 0 is the light of Capture
dark and 1 the light of Capture bright. The error that moves the head is the difference of two opposite
sensors over their sum, for left and right that is `(R - L) / (R + L)`. A room light adds the same amount to
every sensor. The sum grows, the difference does not, so the error gets small. An example: the lamp gives R
0.6 and L 0.3, the error is 0.33. Room light that adds 0.4 to both gives 1.0 and 0.7, the error is only
0.18. And a sensor that gets more light than at Capture bright stops at 1, then the difference vanishes
completely.

**Fix:**

1. Run Capture bright again with the lamp close in front of the head, so bright is the most light the
   sensors will see in this room.
2. Use a strong light close to the tracker, a phone torch at 30 to 50 cm works well, and keep room lights
   off the sensors where you can.
3. If it still reacts late, lower Move above in the Tuning tab a little, the head then starts at a smaller
   error.

## One sensor reads nothing

**What you see:** in the Calibrate tab one of the four bars stays at 0 or at the full length and does not
change when you cover the sensor. The doctor says `L did not react, check its cable on A0 and the 5 V switch
on the board`.

**Why:** the 3 pin cable sits the wrong way round on one end. The module and the UNO both have G V S pins, and
the cable has to connect G to G, V to V and S to S. The other usual cause is the slide switch of the UNO on
3.3 V.

**Fix:** note the colour of the wire on the G pin of the module and put the same colour on the G row of the
UNO, see `docs/wiring.md`. Set the slide switch to 5 V. Then run the doctor again.

## The page says simulation

**What you see:** the chip in the top bar says Simulation and the status bar says `simulation in this
browser` or `simulation, <address> does not answer`.

**Why:** the page has no tracker address, or the tracker does not answer at the address it has. The page then
runs the simulation in the browser, so the talk can go on. A different case: the chip says Live, but the
System tab says Driver simulation. Then the page reaches the Pi and the Pi itself runs the simulation,
because no board answered, see No board found above.

**Fix:** open the page with the address of the tracker, for example
`https://sol.swimmingbrain.dev/?pi=solpi.swimmingbrain.dev`, or set it in the Connection tab of the admin
tools. Check on the Pi that the service runs: `systemctl status brainsolpi`.

## The hosted page cannot reach the Pi

**What you see:** the status bar says `simulation, brainsol.local needs https`, and the page explains that the
browser blocks the plain address.

**Why:** the hosted page comes over https. A page loaded over https may only open secure connections,
`https://` and `wss://`. The Pi answers plain `http://` and `ws://` on port 8080, so the browser blocks it
before anything leaves the laptop. This is called mixed content and no setting in the page can allow it.

**Fix:** either give the Pi an https address through a tunnel, `deploy/tunnel.md` shows Cloudflare Tunnel
and Tailscale Funnel, or open the copy of the page that the Pi serves itself at `http://brainsol.local:8080`.
That page is plain http, so it may talk `ws://`. It needs the web app on the Pi, `deploy/web.sh` puts it
there.

## The pin is locked

**What you see:** `Too many wrong tries. The next try is possible in ...`.

**Why:** five wrong tries lock the pin for 30 s. Every further lock doubles the wait, up to an hour. A right
pin resets it.

**Fix:** wait and type the right pin. If nobody knows it, set a new one on the Pi with `brainsolpi setpin`.
The running service takes it over within a few seconds and logs every admin out.

## The panel does not fit the head

**What you see:** the panel does not drop into the pocket of the bezel, or it rattles in it.

**Why:** Keyestudio does not give the size of the panel, the CAD uses an estimate of 125 x 85 x 2.5 mm.

**Fix:** measure the panel, put the values into `hardware/cad/params.py`, build again and reprint the parts
that `hardware/MEASURE.md` names. Put the same width and height into the tracker settings too, as
`hardware/MEASURE.md` shows, the power estimate uses them.

## brainsolpi: command not found

**Why:** `deploy/install.sh` links the command into `~/.local/bin`, and Raspberry Pi OS puts that folder on
the path at login.

**Fix:** log out and in once. Until then use `~/brainsolpi/.venv/bin/brainsolpi`.

## Flashing fails

**What you see:** avrdude says `not in sync` or `programmer is not responding`.

**Why:** another program holds the port, the cable has no data wires, or an old bootloader wants another
speed.

**Fix:** close every serial monitor and run `brainsolpi flash` again, it already tries 115200 and then 57600
baud. If it still fails, press the reset button of the UNO right when avrdude starts.
