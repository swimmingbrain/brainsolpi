# brainsol bridge firmware

The Keyestudio UNO in brainSOL does not track anything by itself. The Raspberry Pi runs the
control loop. The UNO is only the hands and the eyes of the Pi: it reads the four light
sensors and the I2C sensors, drives the two servos and talks a small line protocol over the
USB cable.

| file | what it is |
|---|---|
| `brainsol_bridge/brainsol_bridge.ino` | the sketch |
| `brainsol_bridge.hex` | the sketch built for the UNO, ready to flash |
| `brainsol_bridge.build.txt` | how the hex was built, flash and RAM use, checksum |
| `flash.sh` | writes the hex to the board from the Pi |
| `test/` | a host test that runs the sketch on a PC against fake hardware |

## What the sketch does

- Every frame it sums 8 readings of each light sensor, so a value goes from 0 to 8184. The
  first reading after each channel switch is thrown away. The ADC runs in the background, the
  loop never waits for it.
- It looks for a BH1750 light sensor on 0x23 and then on 0x5C, puts it in continuous high
  resolution mode and reads it about every 150 ms.
- It looks for an INA219 on 0x40 and reads the bus voltage and the shunt voltage, again about
  every 150 ms. The current assumes the usual 0.1 ohm shunt of the common modules.
- A sensor that is missing at boot is looked for again every 3 s. A sensor that fails three
  reads in a row counts as unplugged and reports 0.
- Every I2C transfer has a 3 ms timeout, so a stuck or half plugged sensor cannot hang the board.
- It sends a sample frame 50 times per second by default. When the transmit buffer has no room
  for a whole frame, the frame is skipped instead of waiting. `seq` still counts up, so the Pi
  sees the gap.
- The servos stay off (no pulses, signal lines low) until the first `M` command. That command
  attaches both servos right at the commanded pulse, so nothing jumps to the middle first.
  After that the pulses move toward each new target by at most the slew cap every 10 ms.
- `D` lets both servos go. It waits for the end of a running pulse, so the servo never sees a
  pulse that is cut short. The next `M` attaches again right at its own pulse.
- The board never moves on its own. When no `M` arrives for 1500 ms it keeps the last target
  and raises flag 2. The next `M` clears the flag.

## Pin map

The pins are the ones of the stock kit wiring.

| pin | part | note |
|---|---|---|
| A0 | left photoresistor module | analog, 3 pin cable G V S |
| A1 | right photoresistor module | |
| A2 | up photoresistor module | |
| A3 | down photoresistor module | |
| A4 | I2C SDA | BH1750, optional INA219 |
| A5 | I2C SCL | |
| D9 | pan servo, the lower one | orange signal, red plus, brown ground |
| D10 | tilt servo, the upper one | |

The slide switch for the V pins must be on 5 V. The names L, R, U and D belong to the panel
frame of the head: L sits on the left of the panel seen from behind, U above it.

## Protocol

115200 baud, 8N1, ASCII lines that end with `\n`. A `\r` before the `\n` is ignored. A line has
at most 96 characters.

From the UNO to the Pi:

| line | meaning |
|---|---|
| `I,brainsol,1.0.0,<caps>` | identity, once after boot and as the answer to `?`. caps: 1 BH1750 found, 2 INA219 found |
| `S,<seq>,<l>,<r>,<u>,<d>,<lux10>,<mv>,<ua>,<pan_us>,<tilt_us>,<flags>` | sample frame, see below |
| `P,<n>` | answer to a ping, `n` comes back exactly as it was sent |
| `E,<code>,<text>` | code 1: unknown command, wrong field count, bad number or bad character. code 2: line too long |

Fields of the sample frame:

| field | meaning |
|---|---|
| `seq` | counts 0 to 65535 and wraps, also for skipped frames |
| `l r u d` | sums of 8 ADC readings of A0 to A3, 0 to 8184 |
| `lux10` | lux times 10, 0 without a BH1750 |
| `mv` | panel voltage in mV, 0 without an INA219 |
| `ua` | panel current in microamps, can be negative, 0 without an INA219 |
| `pan_us tilt_us` | the pulses going out right now, 0 while detached |
| `flags` | 1 servos attached, 2 no `M` for 1500 ms, 4 still on the way to the target |

From the Pi to the UNO:

| line | meaning |
|---|---|
| `?` | send the identity line |
| `M,<pan_us>,<tilt_us>` | servo targets, clamped to 500 to 2500 |
| `D` | detach both servos |
| `R,<hz>` | report rate, clamped to 1 to 100 |
| `L,<us>` | slew cap in us per 10 ms, clamped to 1 to 200, default 30 |
| `P,<n>` | ping, `n` is 1 to 20 digits |

The command letters may also be lower case, which helps when you type them by hand. Numbers
are plain decimal: an optional minus and 1 to 9 digits, no spaces. A line that is not
understood changes nothing.

Opening the serial port resets the UNO. The Pi waits for the `I` line, up to 5 s, before it
sends anything. If the port was already open and no `I` line comes, send `?`.

A line can be cut in half, for example by a Pi program that died in the middle of a write. The
half stays in the board and the next line you send is glued to it. To start clean, send `?` and
wait for the `I` line. If a half line was waiting, the glued line is never a valid command, the
board answers with an `E` line and changes nothing. Then send `?` once more, the `I` line comes
and the board is clean. The bridge driver of the Pi does exactly this.

Never send a lone `\n` to start clean. It finishes the half line, and a half line can be a valid
command of its own: `M,1500,15` cut from `M,1500,1500` sends the tilt servo to the end of its
range.

## Flash it from the Pi

The install script offers this when a board is plugged in. By hand:

```
cd ~/brainsolpi
firmware/flash.sh
```

The script finds the port by itself (`/dev/serial/by-id`, then `/dev/ttyACM*`, then
`/dev/ttyUSB*`). Give it a port if you have more than one board: `firmware/flash.sh /dev/ttyACM1`.
It stops the `brainsolpi` service while it flashes and starts it again afterwards, so sudo may ask
for your password. At the end it waits for the identity line and prints it. The Python package
has `brainsolpi flash` for the same job.

It needs `avrdude` (`sudo apt install avrdude`) and the user in the `dialout` group.

## Flash it from a PC

With the Arduino IDE 2: open `brainsol_bridge/brainsol_bridge.ino`, pick the board
"Arduino Uno" and the port, then press Upload. The IDE already has the Servo library, Wire is
part of the board package.

With arduino-cli:

```
arduino-cli core install arduino:avr
arduino-cli lib install Servo
arduino-cli compile --fqbn arduino:avr:uno --warnings all firmware/brainsol_bridge
arduino-cli upload --fqbn arduino:avr:uno -p COM5 firmware/brainsol_bridge
```

Use your own port instead of `COM5` (`arduino-cli board list` shows it, on Linux it looks like
`/dev/ttyACM0`). To flash the prebuilt hex without building:

```
avrdude -p atmega328p -c arduino -P COM5 -b 115200 -D -U flash:w:firmware/brainsol_bridge.hex:i
```

## Check it with a serial monitor

Close everything else that uses the port, also the `brainsolpi` service
(`sudo systemctl stop brainsolpi`). Open a serial monitor at 115200 baud with the line ending set
to "Newline" (or "Both NL & CR"). On the Pi the miniterm of pyserial in the venv works too, `-e`
shows what you type and Ctrl+] quits:

```
~/brainsolpi/.venv/bin/python -m serial.tools.miniterm -e /dev/ttyACM0 115200
```

Then:

1. Right after the port opens the board resets. About a second later the first line is the
   identity, for example `I,brainsol,1.0.0,1` with a BH1750 plugged in.
2. Then sample frames scroll by, 50 per second:
   `S,812,4211,4185,3990,4302,1834,0,0,0,0,2`. Cover one photoresistor with a finger and its
   value changes a lot. The last field is 2 because nobody sends `M` yet.
3. Type `R,1` to slow the frames down to one per second, that makes the rest easier to read.
4. Type `P,42` and the answer is `P,42`.
5. Type `?` and the identity line comes again.
6. Type `M,1500,1500` and both servos move to the middle. The next frames show `1500,1500` and
   flags 1. After 1.5 s without another `M` the flags turn to 3, the servos stay where they are.
7. Type `M,1800,1500`. The pan servo turns and `pan_us` climbs in steps of 30 us per 10 ms.
   While it is on the way the flags include 4.
8. Type `D`. The servos go limp, the frames show `0,0` for the pulses.
9. Type `hello` and the answer is `E,1,unknown command`. Type `M,abc,1` and the answer is
   `E,1,bad number`.
10. Type `R,50` to go back to the normal rate.

## Build note

The hex in this folder was built with arduino-cli 1.6.0 and the arduino:avr 1.8.8 core, see
`brainsol_bridge.build.txt` for the exact command, the warnings and the numbers. In short:
10440 of 32256 bytes of flash and 796 of 2048 bytes of RAM for global variables. When you change
the sketch, build it again, copy `brainsol_bridge.ino.hex` from the output folder over
`brainsol_bridge.hex` and update the note.

## Host test

`firmware/test/run.sh` builds the sketch with the C++ compiler of the PC against small stand ins
for the Arduino core, the Servo library, Wire, the ADC and the UART, and runs it twice: once from a
clock of zero and once across the wrap of `micros()` and `millis()`. It checks the protocol line by
line, the frame format, the report rate, the slew, the watchdog, the detach, the sensors coming
and going and the transmit buffer. On the Pi it needs `g++` (`sudo apt install g++`). It cannot
check what only real hardware shows, see the list below.

## Things to keep in mind on the real hardware

- The Pi powers the UNO and both servos through the USB cable, there is no second supply. That
  needs the official 5.1 V 2.5 A micro USB supply of the Pi 3B+ or a better one. A 9 g servo draws
  a few hundred mA while it moves and up to 850 mA when it stalls. The tracker keeps that low: the
  Pi caps speed and acceleration, the board moves a pulse by at most 30 us every 10 ms, so a servo
  never gets a big jump, and the soft limits stop the head 2 degrees before the ends of its range.
  If the board still resets when the servos move (a new `I` line shows up) or the Pi reports low
  voltage, the supply is too weak, see `docs/troubleshooting.md`.
- While the bootloader runs after a reset (about one second) the servo pins float. Most servos
  ignore that, a 10 kilo ohm resistor from each signal line to ground makes it certain.
- The servo pulses come from a timer interrupt. Serial and I2C interrupts can delay a pulse edge
  by a few microseconds, that is a fraction of a degree.
