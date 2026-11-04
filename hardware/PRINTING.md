# Printing the brainSOL body

Printer: Bambu Lab A1 mini, 0.4 mm nozzle, matte PLA. Every part fits in 175 x 175 x 175 mm, lies on one
flat face and prints without supports. The STL files in `export/stl/` are already in print orientation, so
just drop them on the plate. The STEP files in `export/step/` have the same orientation. The 3MF files in
`export/3mf/` are ready plates, one colour per plate.

## Print the fit test first

`export/stl/fit_test.stl` plus one `cap.stl` take about half an hour by the estimate below. Check them with the
real parts before you start the big prints, see `MEASURE.md`. If something is too tight or too loose, change
the value in `cad/params.py`, run `uv run build.py` (`MEASURE.md` says where its environment should go) and
print the test again.

The face of the fit test on the plate carries `swim` over `FTM-NES`, cut like the signature on the lid and at
its sizes. Turn the plate over and look at it before the three hour lid print, see below.

## The signature on the lid

The lid top carries an engraved signature behind the small sun mark: `swimmingbrain.dev`, below it the FHV
mark, a thin rule and the class tag. It reads upright for someone standing in front of the tracker and sits
on the centre line, like the sun mark and the neck. See `renders/lid_signature.png` and, as it lies on the
plate, `renders/print/lid_first_layer.png`.

It is cut 0.6 mm deep, three layers, into the face that lies on the plate, so it prints in the first layers and
comes out crisp. Inter SemiBold with 7.3 mm x height for the name line, JetBrains Mono ExtraBold with 6.6 mm
caps for the tag. These sizes are the smallest at which every stroke and join is at least 0.9 mm wide and every
counter and gap between letters at least 0.8 mm. `reports/checks.md` measures this on the lid mesh at every
build. 2.4 mm of solid lid stay behind the letters.

What to watch on the first layer:

- Clean the plate and do not touch it where the lid goes. The letters are the first thing the nozzle draws.
- The first layer must not be squashed. If the letters of the fit test sample come out closed or the counters
  of `s` and `B` are gone, the nozzle is too close to the plate, run the bed levelling and the flow
  calibration of the printer again.
- Keep the elephant foot compensation from the list below, it keeps the letters at their width.
- The floor of each letter is the fourth layer, printed as a short bridge over the letter. The widest spot is
  2.8 mm across, so the floor stays flat, but it shows the lines of the bridge instead of the plate texture.
  That is normal and helps the letters stand out.

To make it stand out more, rub dark acrylic paint into the letters with a cloth or a stiff brush, wait a
minute, then wipe the face with a slightly damp paper towel drawn flat across the lid. The paint stays in
the letters, the matte top wipes clean. Dark furniture wax or a wax crayon rubbed in and buffed off works
the same way and is easier to undo. Try it on the fit test sample first.

Someone building their own tracker sets `SIG_ON = False` in `cad/params.py` and gets a plain lid with only the
sun mark. The texts, sizes, depth and position are the `SIG_` values next to it.

## Colours

- body, light warm grey or white matte PLA: tray, lid, fit test
- dark, charcoal matte PLA: neck halves, head back shell, bezel, both ears, the four feet
- accent, copper PLA: the two caps on the hinge, a 2 g job, any copper or bronze filament works

## Parts and orientation

| part | count | face on the bed | why |
|---|---|---|---|
| tray | 1 | floor | outside walls print as clean vertical walls |
| lid | 1 | top face | the visible top comes off the textured plate, columns and posts grow upward |
| foot | 4 | the face that touches the tray | the countersink opens upward |
| neck_front | 1 | front face | visible face comes off the plate, all pockets open upward |
| neck_back | 1 | back face | same as the front half |
| head_back | 1 | back face | visible back comes off the plate, pegs and ribs grow upward |
| head_bezel | 1 | front face | the front with the eyes comes off the plate |
| ear_horn | 1 | inner face | layers run along the ear, so the load never pulls layers apart |
| ear_pivot | 1 | inner face | same as the horn ear |
| cap | 2 | outer face | the visible face is the smooth plate side |
| fit_test | 1 | plate | print first |

## Estimated filament and time

The numbers come from the model with a simple flow estimate, Bambu Studio gives the real ones. The table is
refreshed by every `uv run build.py`.

<!-- print table start -->
| part | count | colour | layer mm | infill | grams | minutes |
|---|---|---|---|---|---|---|
| tray | 1 | body | 0.2 | 15 % gyroid | 140.2 | 213 |
| lid | 1 | body | 0.2 | 15 % gyroid | 114.2 | 175 |
| foot | 4 | dark | 0.2 | 100 % concentric | 2.0 | 5 |
| neck_front | 1 | dark | 0.2 | 25 % gyroid | 28.8 | 47 |
| neck_back | 1 | dark | 0.2 | 25 % gyroid | 24.9 | 40 |
| head_back | 1 | dark | 0.2 | 15 % gyroid | 59.5 | 89 |
| head_bezel | 1 | dark | 0.2 | 15 % gyroid | 46.3 | 70 |
| ear_horn | 1 | dark | 0.16 | 40 % gyroid | 5.6 | 11 |
| ear_pivot | 1 | dark | 0.16 | 40 % gyroid | 5.6 | 11 |
| cap | 2 | accent | 0.12 | 100 % concentric | 0.4 | 1 |
| fit_test | 1 | body | 0.2 | 15 % gyroid | 19.8 | 31 |
| total | | | | | 447.5 | 693 |
<!-- print table end -->

## Slicer settings that matter

Start from the Bambu Studio profile for matte PLA on the A1 mini with the 0.4 mm nozzle and change these:

- Wall loops 4, top shell layers 5, bottom shell layers 4. The tap holes need the solid walls around them.
- Infill gyroid. Use the percent from the table: 15 for the big shells, 25 for the neck halves, 40 for the
  ears, 100 for feet and caps.
- Layer height 0.2 mm, 0.16 mm for the ears, 0.12 mm for the caps.
- Supports off. Every overhang is 45 degrees or less and the widest bridge is under 17 mm.
- Elephant foot compensation 0.15 mm. The horn pockets, eyes and countersinks sit on the bed face and must
  keep their size.
- Seam position aligned and placed at the back, so on the tray it lands on the rear wall and on the head on
  the lower edge.
- Outer wall speed about 80 mm/s for an even matte finish, the rest can stay at the profile speeds.
- Ironing off, matte PLA hides the top lines well and ironing makes it shiny.
- Brim off. If the tray lifts at a corner, add a 3 mm brim on the outer edge only.
- Textured PEI plate, bed 55 C, nozzle 220 C for most matte PLA.

## After printing

- Run an M3 screw once into every tap hole before assembly. The kit screws cut their own thread, the
  first pass is the hardest.
- If the alignment pins of the neck halves do not slide into their holes, scrape the holes with the tip of
  a screwdriver.
- The caps press into their recess, three small ribs hold them. Do not glue them, you need to reach the
  screws under them.
