# The day the kit arrives

The Pi already runs the tracker service from `docs/setup.md`, so far with the simulation. This page goes
through everything in order, from the first measurement to the first real tracking. Plan a day: the prints
take most of it.

## 1. Measure and print the fit test

The body was designed from photos, a few sizes are guesses. Print `hardware/export/stl/fit_test.stl` and one
`cap.stl` first, about half an hour by the estimate, and check the real parts against it. Measure the solar
panel too, its size is an estimate of 125 x 85 x 2.5 mm. `hardware/MEASURE.md` lists every value, how to
measure it and which parts to reprint when it changes.

## 2. Print the body

`hardware/PRINTING.md` has the orientation, the colours, the slicer settings and an estimate of filament and
time per part, about 450 g and 11.5 hours in total. The 3MF files in `hardware/export/3mf/` are ready plates,
one colour each.

## 3. Flash the bridge firmware

While the prints run, lay the electronics out on the table. Plug the UNO into a USB port of the Pi with the
kit cable, nothing else on it yet. The service does the rest by itself:

1. within about 15 s it notices a port that opens but never answers the brainSOL hello
2. it checks that the USB ids are those of an UNO R3 with the ATmega16U2 chip, `lsusb` shows them, the kit
   board should say `2341:0043`
3. it writes `firmware/brainsol_bridge.hex` with avrdude, that takes about half a minute
4. the board says hello and the service restarts with it

Follow it with `journalctl -u brainsolpi -f`, or in the event log of the System tab if the admin tools are
unlocked. Afterwards the System tab says Driver UNO board. The tracker starts in hold with the servos off,
nothing moves until the next steps.

If the service says it left the board alone, if flashing failed, or if you turned `serial.autoflash` off,
flash it by hand:

```
brainsolpi flash
```

It stops the service, writes the same hex with avrdude, waits for the board to say hello and starts the
service again. The last line looks like `the board answers: I,brainsol,1.0.0,0`.

## 4. Check everything with the doctor

Still on the table, plug in everything as `docs/wiring.md` shows: the four photoresistor modules on A0 to A3,
the BH1750 on the I2C header, the pan servo on D9 and the tilt servo on D10. Mind the G V S order and set the
slide switch of the UNO to 5 V. The servos have no horns yet, so they can turn freely.

```
brainsolpi doctor
```

It goes through six steps and tells you what to do in each:

1. serial port: finds the board
2. firmware: the version and which I2C sensors answered
3. sample frames: should be about 50 per second with nothing lost
4. light sensors: you cover each sensor with a finger in turn, it spots a dead or a swapped cable
5. BH1750 light sensor: a lux value above 0 in a lit room
6. servos: both turn a few degrees and come back, you confirm it

It ends with a summary and the exact next steps for your setup. Fix whatever it reports and run it again
until every step says ok. It also warns when the Pi saw low voltage, then change the power supply first:
the official 5.1 V 2.5 A micro USB supply for a Pi 3B+, the official 5.1 V 3 A USB C supply for a Pi 4.

## 5. Centre the servos

```
brainsolpi centre
```

Both servos go to 1500 us, the middle of their range. That is pan 0 and tilt 90 in the software. Wait until
they stop, press Ctrl+C. `centre` stores this pose, so the tracker later starts right there. Do not turn the
servo shafts by hand from now on, the horns go on in this position during the assembly.

Only `centre`, the doctor and the tracker on the real board store a pose. The weeks of simulation before do
not count, the sim keeps a pose of its own, so before this step the board knows nothing about the head.

## 6. Assemble

Shut the Pi down with `sudo poweroff`, wait until the green light stops blinking and pull the power plug.
Then follow `hardware/ASSEMBLY.md`. Its step 2 is what you just did, skip it. All screws come from the kit,
the two screwdrivers of the kit are the only tools. Read step 3 of the assembly before you start: the plug of
the power cable does not fit through the notch in the back wall.

## 7. Calibrate

Plug the power supply back in. After about a minute the service runs. It starts in `hold`, because no
calibration is saved for this board yet, and the servos hold the centre that `centre` stored. The event log
explains why it holds.

Open `http://brainsol.local:8080`, click the lock icon in the top bar and unlock the admin tools with the pin.
Open the Calibrate tab. At the top, Light sensors shows the raw reading of each sensor live, more light
means a longer bar. Below, Step by step has five steps. Go through them in order, nothing is kept until the
last one saves it.

1. **Cover the sensors.** Put a hand or a cap over all four sensors, then press Capture dark. Grey marks
   on the bars show the dark readings.
2. **Light them up.** Hold the lamp close in front of the head so it shines on all four sensors, then press
   Capture bright. Use the brightest light the tracker will see, a phone torch at 20 to 30 cm works. The
   step says whether all four see a clear difference. A sensor that hardly changes points to a cable or a
   lamp that misses it. A sensor that reads lower in light is fine, the tracker handles it.
3. **Centre the servos.** Use the nudge buttons, one degree at a time, until the panel lies flat and its
   front faces forward. Then press Store as centre. That pose is pan 0 and tilt 90 from now on. It fixes the
   small offset left from the steps of the horn spline.
4. **Find the directions.** The head must not lie flat for this step, press Tilt it up first. Keep the lamp
   still in front of the head and press Find directions. The tracker turns each axis a few degrees and learns
   which way is which. It reports each axis as wired or turned around.
5. **Save.** Press Save calibration. The hold ends and the tracker goes on in auto.

If something went wrong, Start over with Back to defaults and go through the steps again.

## 8. First tracking with the phone light

Dim the room lights. Switch on the torch of your phone and hold it about 40 cm in front of the tracker.

- Move it slowly to the left and to the right, up and down. The head follows and comes to rest facing the
  light, the state on the page changes from tracking to on the light.
- Watch the Light balance on the page: the dot drifts toward the brighter side and the tracker turns until
  it sits in the middle.
- Move the light behind the tracker. Pan only turns from about -90 to 90 degrees, so the panel tips over the
  top past flat to face backward.
- Switch the torch off. The state says too dark and the head holds.

## What good looks like

- The status bar shows a loop of about 50 Hz.
- The head moves smoothly, comes to rest on the light and stays there, no hunting back and forth.
- The Off target tile reads a few degrees once it rests.
- The Gain tile is above 1 when the light is far from the fixed reference pose.
- The doctor reports about 50 frames per second with nothing lost.
- No `board restarted by itself` events and no low voltage warnings.
- The Cosine law experiment in the Experiments tab fits with an R squared close to 1.

If it does not look like this, `docs/troubleshooting.md` has the usual causes. A head that runs away from the
light needs Find the directions again.
