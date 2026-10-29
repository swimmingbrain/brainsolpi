# Printing the brainSOL body

Printer: Bambu Lab A1 mini, 0.4 mm nozzle, matte PLA. Every part fits in 175 x 175 x 175 mm, lies on one
flat face and prints without supports. The STL files in `export/stl/` are already in print orientation, so
just drop them on the plate. The STEP files in `export/step/` have the same orientation. The 3MF files in
`export/3mf/` are ready plates, one colour per plate.

## Print the fit test first

`export/stl/fit_test.stl` plus one `cap.stl` take about twenty minutes. Check them with the real parts before
you start the big prints, see `MEASURE.md`. If something is too tight or too loose, change the value in
`cad/params.py`, run `uv run build.py` and print the test again.

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
| lid | 1 | body | 0.2 | 15 % gyroid | 114.7 | 176 |
| foot | 4 | dark | 0.2 | 100 % concentric | 2.0 | 5 |
| neck_front | 1 | dark | 0.2 | 25 % gyroid | 28.8 | 47 |
| neck_back | 1 | dark | 0.2 | 25 % gyroid | 24.9 | 40 |
| head_back | 1 | dark | 0.2 | 15 % gyroid | 59.5 | 89 |
| head_bezel | 1 | dark | 0.2 | 15 % gyroid | 46.3 | 70 |
| ear_horn | 1 | dark | 0.16 | 40 % gyroid | 5.5 | 10 |
| ear_pivot | 1 | dark | 0.16 | 40 % gyroid | 5.5 | 10 |
| cap | 2 | accent | 0.12 | 100 % concentric | 0.4 | 1 |
| fit_test | 1 | body | 0.2 | 15 % gyroid | 18.0 | 28 |
| total | | | | | 446.0 | 691 |
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
