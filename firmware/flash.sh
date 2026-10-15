#!/usr/bin/env bash
# writes the brainsol bridge firmware to the keyestudio uno with avrdude
#
# usage: firmware/flash.sh [port]
#   without a port it takes the first arduino it finds under /dev/serial/by-id,
#   then /dev/ttyACM*, then /dev/ttyUSB*
#   BRAINSOL_HEX=/path/to/other.hex firmware/flash.sh flashes another hex file
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hex="${BRAINSOL_HEX:-$here/brainsol_bridge.hex}"

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'flash: %s\n' "$*" >&2
  exit 1
}

find_port() {
  local p
  for p in /dev/serial/by-id/*[Aa]rduino* /dev/ttyACM* /dev/ttyUSB*; do
    # an unmatched pattern stays as literal text, -e filters that out
    if [ -e "$p" ]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

command -v avrdude >/dev/null 2>&1 || fail "avrdude is missing, install it with: sudo apt install avrdude"
[ -r "$hex" ] || fail "no hex file at $hex"

port="${1:-}"
if [ -z "$port" ]; then
  if ! port="$(find_port)"; then
    fail "no board found. plug the uno in with the usb cable and try again, or name the port: $0 /dev/ttyACM0"
  fi
fi
[ -e "$port" ] || fail "the port $port does not exist"
if [ ! -r "$port" ] || [ ! -w "$port" ]; then
  fail "no access to $port. add your user to the dialout group with: sudo usermod -aG dialout $USER, then log out and in again"
fi

# the tracker service keeps the port open and avrdude needs it alone
service_stopped=0
restart_service() {
  if [ "$service_stopped" = 1 ]; then
    say "starting the brainsolpi service again"
    sudo systemctl start brainsolpi || say "could not start the service, try: sudo systemctl start brainsolpi"
  fi
}
trap restart_service EXIT

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet brainsolpi 2>/dev/null; then
  say "stopping the brainsolpi service while flashing, sudo may ask for your password"
  sudo systemctl stop brainsolpi
  service_stopped=1
fi

if command -v fuser >/dev/null 2>&1 && fuser "$port" >/dev/null 2>&1; then
  fail "another program has $port open, close it first (a serial monitor perhaps)"
fi

say "flashing $hex"
say "to the board on $port"

# the uno bootloader talks at 115200 baud. some older clones use 57600, so that is the
# second try. -D skips the chip erase, the bootloader cannot do it and does not need it
flashed=0
for baud in 115200 57600; do
  if avrdude -p atmega328p -c arduino -P "$port" -b "$baud" -D -U "flash:w:$hex:i"; then
    flashed=1
    break
  fi
  say "no luck at $baud baud"
done

if [ "$flashed" != 1 ]; then
  fail "avrdude could not talk to the board. check the usb cable, press the reset button on the uno right before you run this script again, or name the port by hand"
fi

say "flash done, waiting for the board to say hello"

# opening the port resets the uno, after the bootloader the sketch sends its identity line
hello=""
if command -v timeout >/dev/null 2>&1; then
  stty -F "$port" 115200 cs8 -cstopb -parenb raw -echo 2>/dev/null || true
  hello="$(timeout 6 grep -a -m 1 '^I,brainsol' < "$port" || true)"
fi

if [ -n "$hello" ]; then
  say "the board answers: $hello"
else
  say "the board did not answer within 6 s. that can be fine, check it with: brainsolpi doctor"
fi
