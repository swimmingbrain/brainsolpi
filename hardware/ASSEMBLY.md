# Building the brainSOL tracker

You need the printed parts (see `PRINTING.md`), the Raspberry Pi with its official supply or a better one
(5.1 V 2.5 A micro USB for a Pi 3B+, 5.1 V 3 A USB C for a Pi 4), and from the kit: the Keyestudio UNO, two servos with their horn bags, four
photoresistor modules, the BH1750 module, the solar panel, four 3 pin cables, the long 4 pin cable (350 mm),
the USB A to B cable, the screws and the two screwdrivers. No glue, no soldering, no other tools.

The Pi powers the UNO and both servos through the USB cable, so a weaker supply is the most common cause of
trouble later, see `docs/troubleshooting.md`. The Pi should already run the tracker service, see
`docs/setup.md`.

Look at `renders/exploded.png` once before you start. It shows every part in the order you put it together.

## Screws

| screw | count | where |
|---|---|---|
| M3x8 flat head | 21 of 29 | 4 feet, 2 neck floor, 4 ears, 3 UNO, 8 bezel |
| M3x14 flat head | 1 of 4 | pivot of the right ear |
| servo horn screw | 2 | one from each servo bag, for the two horns |

All M3 screws cut their own thread in the plastic. Turn them in slowly and stop as soon as the head sits.
One more turn strips the thread.

## Wiring

| cable | part end | UNO end |
|---|---|---|
| 3 pin, photoresistor L (one dot in the head) | L module, left edge seen from behind | A0, G V S |
| 3 pin, photoresistor R (two dots) | R module, right edge seen from behind | A1, G V S |
| 3 pin, photoresistor U (three dots) | U module, top edge | A2, G V S |
| 3 pin, photoresistor D (four dots) | D module, bottom edge | A3, G V S |
| 4 pin | BH1750 GND VCC SDA SCL | the GND VCC SDA SCL header at the far end of the UNO |
| pan servo lead | lower servo | D9, brown on G |
| tilt servo lead | upper servo | D10, brown on G |
| USB A to B | Pi, lower USB port next to the Ethernet jack | UNO USB socket |
| Pi power | wall plug | micro USB (Pi 3B+) or USB C (Pi 4) on the Pi, cable out through the notch in the back wall, see step 3 |

G must meet G on both ends of every 3 pin cable. Note the colour of the wire on the G pin of the module and
put the same colour on the G row of the UNO. Set the small slide switch on the UNO to 5 V.

Left and right are always seen from behind the tracker, the same way the software sees it. Standing in front
of the panel, L is on your right.

## Steps

### 1. Prepare the parts

1. Run one M3x8 screw into every tap hole once and take it out again: the two bosses under the neck back
   half, the four lid columns, the three UNO posts, the eight bezel bosses and the two holes in the end of
   each ear. Do the same with the M3x14 in the hub of the right ear. The first pass is the hard one.
2. Press the alignment pins of the back neck half into the holes of the front half once, then pull them
   apart again.

### 2. Centre the servos

The horns must go on while both servos stand in their centre position. Do this before any horn touches a
spline.

1. Plug the USB B end of the kit cable into the UNO and the A end into the Pi. Plug the pan servo into D9 and
   the tilt servo into D10, brown on G. Set the slide switch on the UNO to 5 V.
2. Power the Pi and log in. The service writes the bridge firmware to a fresh UNO by itself, see
   `docs/first-start.md`, otherwise flash it once with `brainsolpi flash`. `brainsolpi doctor` then checks the board, the servos and every sensor
   you plugged in, `docs/first-start.md` shows how to test all of them on the table first. Both commands stop
   the tracker service while they need the board and start it again at the end.
3. Run `brainsolpi centre`. Both servos go to 1500 us, that is pan 0 and tilt 90. It asks you to mount the
   horns now. Here they go on later, in steps 5 and 7, so wait until both servos stop and press Ctrl+C.
   `centre` stores this pose, so the tracker later starts right there without a jump.
4. Shut the Pi down with `sudo poweroff`, wait until the green light stops blinking, pull the power plug and
   unplug the servos. From now on do not turn the servo shafts by hand.

### 3. Fill the tray

See `renders/inside_base.png`.

1. Set the Pi onto its four pins in the tray, USB ports toward the front, then push it down until it sits
   flat on the standoffs.
2. The power cable has to get from the wall plug outside to the Pi inside, but the notch at the bottom of
   the back wall is only 4.5 mm wide. It passes the cable, no plug fits through it, neither the micro USB
   plug of a Pi 3B+ nor the USB C plug of a Pi 4. Pick one of two ways:
   - Widen the notch to about 13 x 10 mm (width x height) with a file or a craft knife, so the plug of the
     supply goes through from outside. Push the plug in, plug it into the Pi, lead the cable back along the
     floor and lay it into the bottom of the notch.
   - Or cut the supply cable, lead the cut end in through the notch and join both ends again inside, with
     solder and heat shrink or with a small screw terminal, each wire to the one of the same colour. Check
     with a multimeter that 5 V arrives with the right polarity before the Pi sees it. Then plug the micro USB or USB C plug into the Pi and
     lead the cable back along the floor to the notch.

   The plug and the joint stay inside either way.
3. Plug the A end of the USB cable into the lower USB port next to the Ethernet jack. Wind the spare cable
   around the two low posts in the front bay, two or three turns, and leave the B end about 15 cm long.

### 4. Close the neck

See `renders/neck_open.png`.

1. Lay the back neck half on the table, the open side up.
2. Lay the pan servo into the lower pocket, spline down through the round opening at the bottom, the tabs
   in their slots. Its lead leaves at the far end. Bend it up beside the case, over the top of the servo and
   into the cable column, the open channel along the side wall with the small round boss.
3. Lay the tilt servo into the upper pocket, spline out through the big round hole in the side wall, tabs in
   their slots. Its lead leaves at the lower end, lay it down the channel into the column.
4. Lay the four 3 pin cables and the 4 pin cable into the column from the top entry down to the bottom. Mark
   each 3 pin cable with a piece of tape: L, R, U, D. Pull them so that about 20 mm hang out at the bottom and
   the rest sticks out of the top. The photoresistor cables are short, there is about 10 mm to spare, so do
   not leave more than 25 mm at the bottom.
5. Take the front half. Thread every cable end that hangs out at the bottom through the long hole in its
   floor, together with the two servo leads. Press the halves together, pins in holes, no cable caught in the
   seam.
6. Turn the neck upside down and drive two M3x8 through the floor into the back half.

### 5. Put the neck on the lid

1. Lay the lid right side up across two stacks of books, so you can reach under the turret area.
2. From below, press one single arm horn into the pocket under the lid, hub up through the round hole, arm
   pointing away from the curved slot. The pocket holds it.
3. From above, set the neck onto the lid: spline into the horn hub, all cables and both leads through the
   curved slot. The neck has to face the front of the lid, the side with the small sun mark, where the
   engraved signature reads upright. The spline only meshes in steps of about 15 degrees, take the step
   closest to straight ahead. The calibration step "Centre the servos" fixes the rest.
4. Hold the neck and drive the horn screw from below through the horn into the spline. The neck sits on the
   lid and turns with a light drag, it cannot lift off.

### 6. Hang the UNO under the lid

1. Turn the lid upside down onto the books, the neck hangs between the two stacks. Plug the cables into the UNO: L to A0, R to A1, U to A2, D to A3, the 4 pin cable to
   the I2C header, pan servo to D9, tilt servo to D10.
2. Plug the USB B end from the tray into the UNO.
3. Lay the UNO onto its three posts, components toward the lid, the analog header block under the turret.
   Drive three M3x8 through the board holes into the posts.

### 7. Put the ears on

1. Turn the lid right side up and stand it on the table.
2. Press the second single arm horn into the pocket on the inner face of the left ear, hub toward the neck.
3. The tilt servo is centred, so the head will lie flat. Hold the left ear straight up and slide it over the
   ring on the left side of the neck, spline into the horn hub. Drive the horn screw through the hole in the
   middle of the ear hub.
4. Slide the right ear over the ring on the right side, also straight up. Drive the M3x14 through its hub
   until the head sits in the countersink. The screw threads into the ear and turns with it in the neck, so
   the ear stays free.

### 8. Build the head

See `renders/head_inside.png`.

1. Pull all five cables out of the top of the neck and through the slot in the middle of the back shell,
   from behind.
2. Set the back shell onto the ends of the two ears, slot between the ears, and drive four M3x8 from inside
   the shell into the ear ends. The head now lies flat and level.
3. Plug each 3 pin cable onto its module, G to G. Set each module onto its two pegs, sensor end toward the
   edge: one dot L, two dots R, three dots U, four dots D. The BH1750 goes into the top right corner seen from
   behind, its window next to the panel corner.
4. Lay the cables flat on the floor toward the slot. Push the spare length back down into the neck, a short
   loop of about 35 mm between the neck top and the back of the head is enough for the full tilt range.
5. Leave the protective film on the back of the panel. Coil its lead and tuck it into a free corner behind
   the panel. Lay the panel onto the ribs, face up.
6. Lay the bezel over the panel so the panel drops into its pocket. Hold it and drive the eight M3x8 from
   behind through the back shell into the bezel.
7. Press the two copper caps into the ear hubs.

### 9. Close the base

1. Lower the lid onto the tray. The lid skirt slides inside the tray wall, the four fingers find the Pi
   holes, the coiled USB cable stays in the front bay. Nothing may get caught in the gap.
2. Lay the tracker on its back on a towel. Put a foot on each corner of the tray floor, countersink outward,
   and drive four M3x8 through each foot and the floor into the lid columns.
3. Stand it up. The gap between lid and tray should be an even dark line all round.

### 10. First run

1. Plug the power supply into the Pi. After about a minute the tracker service runs. It starts in `hold`,
   because no calibration is saved for this board yet. `brainsolpi centre` stored the centre pose in step 2,
   so the servos hold the head right there, panel flat and facing forward. Without that pose no pulse goes
   out at all until a calibration step or a mode moves the head.
2. Open `http://brainsol.local:8080`, click the lock icon in the top bar and unlock the admin tools with the
   pin.
3. In the Calibrate tab go through "Step by step" in order: Capture dark, Capture bright, Store as centre,
   Find directions, Save calibration. `docs/first-start.md` explains each step.
4. After the save the hold ends and the tracker follows the light in auto.

The servos hold their last pulse as long as the UNO has power, also while the service is stopped. Turn the
head by hand only with the power plug of the Pi pulled out.

## Taking it apart

Undo the feet screws and lift the lid off the tray, the whole turret with the UNO comes with the lid. The
USB cable stays plugged in. The caps come out with a screwdriver tip in the small notch at their lower edge.
