# brainSOL hardware checks

Written by `uv run build.py`. Do not edit by hand, run the build again instead.

## Result

All checks passed.

## Parts

| part | count | size on the bed mm | closed solid | watertight | fits | steep overhang mm2 | widest bridge mm | thin wall share | grams | minutes |
|---|---|---|---|---|---|---|---|---|---|---|
| tray | 1 | 156.0 x 156.0 x 41.2 | yes | yes | yes | 0.0 | 0.3 | 0.1 % | 140.2 | 213 |
| lid | 1 | 156.0 x 156.0 x 44.8 | yes | yes | yes | 0.0 | 10.0 | 1.1 % | 114.2 | 175 |
| foot | 4 | 14.0 x 14.0 x 3.0 | yes | yes | yes | 0.0 | 0.0 | 0.1 % | 2.0 | 5 |
| neck_front | 1 | 52.0 x 73.0 x 30.0 | yes | yes | yes | 0.0 | 6.2 | 0.8 % | 28.8 | 47 |
| neck_back | 1 | 52.0 x 70.6 x 18.0 | yes | yes | yes | 0.0 | 6.2 | 0.3 % | 24.9 | 40 |
| head_back | 1 | 164.0 x 113.0 x 10.1 | yes | yes | yes | 0.0 | 0.2 | 0.8 % | 59.5 | 89 |
| head_bezel | 1 | 164.0 x 113.0 x 12.0 | yes | yes | yes | 0.0 | 0.0 | 2.3 % | 46.3 | 70 |
| ear_horn | 1 | 26.0 x 32.2 x 12.0 | yes | yes | yes | 0.0 | 16.1 | 0.0 % | 5.6 | 11 |
| ear_pivot | 1 | 26.0 x 32.2 x 12.0 | yes | yes | yes | 0.0 | 16.5 | 0.0 % | 5.6 | 11 |
| cap | 2 | 11.8 x 12.1 x 1.6 | yes | yes | yes | 0.0 | 0.4 | 7.5 % | 0.4 | 1 |
| fit_test | 1 | 104.0 x 56.0 x 10.0 | yes | yes | yes | 0.0 | 7.8 | 3.0 % | 19.8 | 31 |

Steep overhang counts downward faces steeper than 45 degrees and wider than 3 mm. Thin wall share is the
part of the surface where a ray straight into the part leaves it again within 1.6 mm, most of it sits on
chamfered edges and the lip of the bezel, which are thin on purpose.

## Interference

Pan swept from -90 to 90 in steps of 10 degrees, tilt from 0 to 180 in steps of 10, 361 poses for head against base.

| pair | largest overlap mm3 | smallest gap mm |
|---|---|---|
| base and neck | 0.000 | the foot rides on the lid, contact |
| neck and head | 0.000 | 0.50 at tilt 130 |
| base and head | 0.000 | 3.00 at pan -90, tilt 0 |

Static pairs inside each group (printed parts against each other and against the kit keep outs): no overlap above 1.0 mm3.

## Signature on the lid

Inter SemiBold at 7.3 mm x height (9.7 mm caps) for the name line, JetBrains Mono ExtraBold at 6.6 mm cap height for the class tag, the fhv mark 8.8 mm tall. 0.6 mm deep, 126.8 x 26.3 mm, front edge at y = 48.0.
Measured on the lid mesh, sliced half way down the recess.

| value | measured | limit |
|---|---|---|
| narrowest stroke or join | 0.91 mm | 0.9 |
| narrowest counter, gap or wall between recesses | 0.84 mm | 0.8 |
| solid lid behind the floor | 2.4 mm | 2.0 |
| clear distance to an edge, a hole or the sun mark | 9.1 mm | 3.0 |
| widest span: name line, tag, fhv mark, rule | 2.6, 2.6, 2.8, 1.0 mm | about 3.0 |
| pieces and holes | 35 and 10, the same as the font outlines | the same |

Strokes: the recess shrunk by half the limit keeps every piece whole. Islands: the recess grown by half
the limit lets no two pieces meet and closes no counter. Before the cut each letter is closed by 0.40 mm, so
the notches where a bowl meets a stem and the slivers inside M and N, all too thin to print, go with the
letter.

## Sensor eyes

Shade wall height above the photoresistor face 6.1 mm over a sensor width of 5.0 mm, k = 1.22, the simulation uses 1.20.

## Cable budget

Lengths in mm between the backs of the plug housings. The kit length is read as tip to tip, so the wire between the plug housings is shorter by two housings.
Free segments are measured for the worst pose and get an allowance for bends.

| cable | uno to slot | through the neck | service loop | inside the head | needed | available | slack | worst pose |
|---|---|---|---|---|---|---|---|---|
| photoresistor L to A0 | 19.8 | 76.6 | 36.1 | 29.9 | 162.3 | 172.0 | 9.7 | pan 90, tilt 0 |
| photoresistor R to A1 | 17.4 | 76.6 | 36.1 | 29.9 | 160.0 | 172.0 | 12.0 | pan 90, tilt 0 |
| photoresistor U to A2 | 17.4 | 76.6 | 36.1 | 15.9 | 146.0 | 172.0 | 26.0 | pan -90, tilt 0 |
| photoresistor D to A3 | 19.8 | 76.6 | 36.1 | 15.9 | 148.3 | 172.0 | 23.7 | pan -90, tilt 0 |
| bh1750 to SDA SCL | 28.7 | 76.6 | 36.1 | 51.4 | 192.9 | 322.0 | 129.1 | pan -90, tilt 0 |
| tilt servo to D10 | 54.5 | 57.5 | 0.0 | 0.0 | 118.4 | 236.0 | 117.6 | pan 90 |
| pan servo to D9 | 52.1 | 74.4 | 0.0 | 0.0 | 132.9 | 236.0 | 103.1 | pan 90 |

## Fasteners

| screw | where | count |
|---|---|---|
| M3x8 flat head | foot through the tray floor into a lid column | 4 |
| M3x8 flat head | foot floor of the neck into the back half | 2 |
| M3x8 flat head | back shell into the end of each ear plate | 4 |
| M3x8 flat head | back shell into the bezel bosses | 8 |
| M3x8 flat head | uno onto its posts under the lid | 3 |
| M3x14 flat head | pivot of the right ear, turns in the neck | 1 |
| servo horn screw | pan horn under the lid and tilt horn in the left ear | 2 |

| type | used | in the kit | spare |
|---|---|---|---|
| M3x8 flat head | 21 | 29 | 8 |
| M3x14 flat head | 1 | 4 | 3 |
| M3 nut | 0 | 6 | 6 |
| M4x8 round head | 0 | 2 | 2 |
| servo horn screw | 2 | 2 | 0 |

## Web files

| file | bytes | triangles |
|---|---|---|
| base.glb | 563876 | 18684 |
| neck.glb | 210808 | 6766 |
| head.glb | 370796 | 11836 |
| panel.glb | 1616 | 12 |
| together | 1147096 | 37298 |

