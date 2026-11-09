# Parts

brainSOL is built from the Keyestudio KS0530 solar tracking kit, a Raspberry Pi 3B+ or 4 and a 3D printed
body.
No extra screws, no glue and no tools besides the two screwdrivers of the kit are needed.

## From the kit

| part | count | what it does |
|---|---|---|
| Keyestudio UNO | 1 | reads the sensors and drives the servos, runs the bridge firmware |
| servo, 9 g class | 2 | pan (the lower one) and tilt (the upper one) |
| single arm servo horn | 2 | one from each servo bag, with its centre screw |
| photoresistor module | 4 | the light sensors L, R, U and D around the panel |
| BH1750 light sensor module | 1 | lux on the panel plane, for the power estimate and the experiments |
| solar panel | 1 | sits in the head, it is not wired by default |
| 3 pin cable, F to F, 200 mm | 4 of 7 | the four photoresistor modules |
| 4 pin cable, F to F, 350 mm | 1 | the BH1750 |
| USB A to B cable | 1 | Pi to UNO, power and data |
| M3x8 flat head screw | 21 of 29 | feet, neck floor, ears, UNO and bezel |
| M3x14 flat head screw | 1 of 4 | pivot of the right ear |
| small screwdrivers | 2 | the only tools you need |

## Stays in the box

- The LCD, the DHT11, the buzzer, the button, the LED, the charging modules and the battery holder.
- The acrylic and wood boards and the black servo bracket, the printed body replaces them.
- All brass pillars, the M3 nuts, the M4 screws and nuts, the LEGO style pins and the cable ties.
- 3 of the 3 pin cables, the short 4 pin cable, the M to F cable.
- 8 M3x8 and 3 M3x14 screws, the other horns and the small screws of the servo bags.

## What else you need

| part | note |
|---|---|
| Raspberry Pi 3B+ or Pi 4 | runs the control loop, the web server and the simulation. The tray was drawn around the 3B+, a Pi 4 has the same size and the same four holes |
| micro SD card | 16 GB or more, for Raspberry Pi OS Lite 64 bit |
| power supply | the official Raspberry Pi supply or a better one: 5.1 V 2.5 A micro USB for a Pi 3B+, 5.1 V 3 A USB C for a Pi 4. The Pi powers the UNO and both servos through USB. Its plug does not fit through the cable notch of the tray, see step 3 of `hardware/ASSEMBLY.md` |
| matte PLA, light warm grey or white | about 275 g: tray, lid and the fit test |
| matte PLA, charcoal | about 175 g: neck halves, head back shell, bezel, both ears, the four feet |
| copper or bronze PLA | under 1 g of parts for the two caps, a 2 g job with the purge |
| a lamp or a phone torch | for the calibration and the demo |
| a computer with an SD card reader | to write the SD card once |

The filament amounts and print times are estimates from the model, about 450 g and about 11.5 hours for
everything, see `hardware/PRINTING.md`. Bambu Studio gives the real numbers. The body was designed for a
Bambu Lab A1 mini, every part fits in 175 x 175 x 175 mm.

## Optional

### INA219 module, for measured panel power

The kit has nothing that measures the panel current, so the tracker estimates the power from the light on
the BH1750, the panel area and an efficiency of 15 %. An INA219 breakout with the usual 0.1 ohm shunt
measures voltage and current for real. The firmware finds it on address 0x40 by itself and the page then
shows the power as measured.

- Wiring to the UNO: VCC to a V pin, GND to a G pin, SDA to the S pin of A4, SCL to the S pin of A5, four
  female to female jumper wires. It shares the I2C bus with the BH1750.
- Wiring to the panel: panel plus to VIN+, VIN- through a load resistor to panel minus, panel minus also to
  GND. Without a load no current flows. Keyestudio does not say what the panel delivers, a 47 ohm resistor
  rated 1 W is a careful start for a small panel.
- The panel lead ends in a PH2.0 plug, a PH2.0 socket with wires saves cutting it.
- The body was not designed for it: there is no holder and the cable budget of the neck has no room planned
  for the panel lead. Try it on the table first.

### A short USB A to B cable

The kit cable is long. The tray winds the spare around two posts, a 30 cm cable is tidier.

### Anti slip pads

Four small rubber pads under the printed feet keep the tracker in place on a smooth table.
