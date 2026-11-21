#!/usr/bin/env bash
# builds the host test of the bridge sketch with the pc compiler and runs it twice,
# once from a clock of zero and once across the wrap of micros() and millis().
# then the same for the variant with the panel on a4, the sketch built with PANEL_A4
# usage: firmware/test/run.sh        (set CXX to use another compiler than c++)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

cxx="${CXX:-c++}"
# -Wno-format: on a pc uint32_t is not unsigned long like on the avr, the format
# strings are checked by the avr build instead
flags=(-std=c++17 -O1 -Wall -Wextra -Wno-format -I "$here")
$cxx "${flags[@]}" "$here/bridge_test.cpp" -o "$out/bridge_test"
$cxx "${flags[@]}" -DPANEL_A4 "$here/bridge_test.cpp" -o "$out/bridge_test_a4"

"$out/bridge_test"
"$out/bridge_test" wrap
"$out/bridge_test_a4"
"$out/bridge_test_a4" wrap
