# What to measure when the kit arrives

The body is designed around the photos and the usual sizes of these parts. A few numbers are guesses. Measure
them with calipers, put the real values into `cad/params.py` and run the build again. Measure in millimetres,
to one decimal.

## Order

1. Print `export/stl/fit_test.stl` and one `cap.stl` (about twenty minutes).
2. Measure the parts below and check them against the fit test.
3. Change `cad/params.py`, run `uv run build.py`, read `reports/checks.md`.
4. Reprint only the parts named in the last column.

## The list

| what | how to measure | parameter in `cad/params.py` | now | reprint |
|---|---|---|---|---|
| solar panel width and height | outer edge to outer edge of the panel board | `PANEL_W`, `PANEL_H` | 125.0, 85.0 | head_back, head_bezel, neck_front, neck_back (the tilt axis height follows the panel height) |
| solar panel thickness | at the edge, with the tape film still on | `PANEL_T` | 2.5 | head_bezel |
| where the panel wires leave the back | distance from the nearest corner | nothing yet, there is room for the lead behind the panel | | |
| servo case | length along the tabs, width, height from bottom to top cover | `SERVO_L`, `SERVO_W`, `SERVO_H` | 22.9, 12.2, 22.7 | neck_front, neck_back, fit_test |
| servo tabs | height of the tab underside above the case bottom, tab thickness, tab length past the case | `SERVO_TAB_Z`, `SERVO_TAB_T`, `SERVO_TAB_LEN` | 15.6, 2.5, 4.7 | neck_front, neck_back |
| servo output | spline axis to the near case end, radius of the round boss, boss face above the case bottom, spline length | `SERVO_SHAFT_FROM_END`, `SERVO_BOSS_R`, `SERVO_BOSS_TOP`, `SERVO_SPLINE_LEN` | 5.9, 5.9, 26.4, 3.2 | neck halves, lid, ear_horn, both ears if the boss moves |
| servo lead | which end it leaves and how high above the case bottom | `SERVO_LEAD_Z` | 4.5, far end | neck halves |
| single arm horn | hub diameter, height from arm underside to hub end, arm thickness, centre to tip, width at hub and tip | `HORN_HUB_D`, `HORN_TOTAL_H`, `HORN_ARM_T`, `HORN_SINGLE_LEN`, `HORN_ARM_W0`, `HORN_ARM_W1` | 7.0, 3.8, 1.6, 15.5, 6.0, 4.0 | lid, ear_horn |
| photoresistor module | board length, width, thickness | `MOD_L`, `MOD_W`, `MOD_T` | 32.0, 24.0, 1.6 | head_back, head_bezel |
| module holes | hole diameter, centre distance between the two holes, distance from the sensor end of the board to the hole centres | `MOD_HOLE_D`, `MOD_HOLE_SPACING`, `MOD_HOLE_FROM_SENSOR_END` | 4.9, 16.0, 20.0 | head_back, head_bezel |
| photoresistor | centre to the sensor end of the board, diameter, height of its top above the board | `LDR_FROM_END`, `LDR_D`, `LDR_TOP` | 6.3, 5.0, 2.5 | head_bezel, head_back |
| tallest part on the module | header with a plug on it, above the board top | `MOD_PARTS_H` | 4.0 | head_back, head_bezel |
| bh1750 chip | centre of the sensor window to the board end without the header | `BH_CHIP_FROM_END` | 12.8 | head_bezel, head_back |
| plug on the module header | from the board edge to the end of the plug where the wire leaves it | `PLUG_REACH` | 14.5 | report only |
| 3 pin cable | tip to tip, and the bare wire between the two plugs | `PHOTO_CABLE`, `CABLE_LEN_INCLUDES_PLUGS` | 200, tip to tip | report only |
| uno analog block | from the usb end of the board to the A0 column, from the analog edge to the G, V and S rows | `UNO_A0_U`, `UNO_GVS_W` | 47.5, 12.1, 9.6, 7.0 | lid |
| uno digital block and i2c header | same for D9, D10 and the GND VCC SDA SCL pins | `UNO_D9_U`, `UNO_D10_U`, `UNO_DGVS_W`, `UNO_I2C_U`, `UNO_I2C_W` | see file | report only |
| uno usb socket | span along the short edge, how far it sticks out | `UNO_USB_W`, `UNO_USB_OVERHANG` | 34 to 46, 6.3 | lid |
| usb plugs of the kit cable | length of each plug with its strain relief | `USB_A_PLUG`, `USB_B_PLUG` | 40, 40 | check the inside render only |
| tap holes | which of the three holes on the fit test takes a kit M3x8 screw firmly without splitting | `M3_TAP` | 2.65 | every part with screws |
| pi pin | the Pi slides onto the printed pin without force and does not wobble | `PI_PIN_D` | 2.45 | tray |
| cap | the cap presses in and stays, the screwdriver tip gets it out | `CAP_D` | 12.0 | both ears, or only the cap |

## Things the fit test answers

- Servo frame: the servo drops in with its spline up and the tabs sit in the notches. If it is tight, raise
  `FIT_SLIDE` or measure the case again.
- Horn pocket: the horn presses in and does not turn. Loose means `FIT_SNUG` down by 0.05, tight means up.
  The servo spline must reach through the hub hole into the horn while the horn lies in the pocket.
- Peg pair: a module slides over both pegs and lies flat on the shoulders.
- Tap holes: one notch is 2.6, two notches 2.65, three notches 2.7.
- Pi pin and cap: see the table.
- Panel corner: the corner of the real panel drops into the pocket and the lip covers about 2 mm of the edge.

## Running the build again

Inside `hardware/` run `uv run build.py`. It rebuilds every part, runs the checks, writes `export/`,
`renders/` and `reports/`, and refreshes the table in `PRINTING.md`. `uv run build.py --quick` skips the
renders and uses a coarser sweep, good for trying a value. The exit code is 1 when a check fails, the reason
is at the top of `reports/checks.md`.

This folder sits in a synced cloud folder. uv puts its virtual environment into `hardware/.venv`, almost a
gigabyte of small files, and the sync client chokes on it. Keep the environment outside the synced folder:

```
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\brainsol-hw-venv"
uv run build.py
```
