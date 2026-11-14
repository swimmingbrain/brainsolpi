"""draw the wiring page of the tracker and print it to docs/wiring.pdf

    python wiring.py                  finds edge or chrome by itself
    python wiring.py --browser PATH   for a browser it does not find
    python wiring.py --svg FILE       also keeps the page as svg

only the standard library, the pdf comes from a headless print of the page
the pins follow firmware/brainsol_bridge/brainsol_bridge.ino, the font is
geist serif from cad/assets/geist_serif_regular.ttf, the same as on the web page
"""

import argparse
import base64
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = HERE / "cad" / "assets" / "geist_serif_regular.ttf"
# times only fills in for the omega, geist serif has no greek, like on the web page
FAMILY = "'Geist Serif', 'Times New Roman', Times, serif"
OUT = HERE.parent / "docs" / "wiring.pdf"

# a4 landscape, everything below is in mm
PAGE_W, PAGE_H = 297.0, 210.0
FRAME = (20.0, 10.0, 287.0, 200.0)

INK = "#000000"
# the one colour on the page, every V wire carries the 5 v supply
POWER = "#b5452f"

WIRE_W = 0.35
BOX_W = 0.5
DASH = "1.8 1.2"

# text sizes, geist serif caps are 0.71 of the size
CAP = 0.71
NAME = 3.4
SUB = 2.8
PIN = 2.8
WIRE = 2.6
CABLE = 2.8
# cable names sit this far above the first wire of their cable
CABLE_UP = 5.0

# rows are 4 mm apart, like a header scaled up
P = 4.0


def wire_colour(name):
    return POWER if name in ("V", "5.1 V") else INK


class Sheet:
    def __init__(self):
        self.items = []

    def line(self, pts, colour=INK, width=WIRE_W, dashed=False):
        d = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        dash = f' stroke-dasharray="{DASH}"' if dashed else ""
        self.items.append(f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
                          f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')

    def rect(self, x0, y0, x1, y1, width=BOX_W, dashed=False):
        dash = f' stroke-dasharray="{DASH}"' if dashed else ""
        self.items.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" '
                          f'fill="#ffffff" stroke="{INK}" stroke-width="{width}"{dash}/>')

    def text(self, x, y, s, size, anchor="start", colour=INK, mid=False):
        # mid puts the middle of the caps on y instead of the baseline
        if mid:
            y += CAP / 2 * size
        self.items.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" '
                          f'fill="{colour}">{escape(s)}</text>')

    def terminal(self, x, y):
        self.items.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.6" fill="#ffffff" stroke="{INK}" stroke-width="0.3"/>')

    def junction(self, x, y):
        self.items.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.75" fill="{INK}"/>')

    def svg(self):
        body = "\n".join(self.items)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}mm" height="{PAGE_H}mm" '
                f'viewBox="0 0 {PAGE_W} {PAGE_H}" font-family="{FAMILY}">\n'
                f'<rect width="{PAGE_W}" height="{PAGE_H}" fill="#ffffff"/>\n{body}\n</svg>\n')


def part(sh, box, lines, left=(), right=(), top=(), dashed=False, text_x=None, text_y=None):
    """a box with its name, a few short lines and labelled pins on its edges,
    left and right are (label, y) pairs and top is (label, x)"""
    x0, y0, x1, y1 = box
    sh.rect(x0, y0, x1, y1, dashed=dashed)
    tx = x0 + 3.0 if text_x is None else text_x
    ty = y0 + 6.0 if text_y is None else text_y
    for i, s in enumerate(lines):
        sh.text(tx, ty + i * 5.0, s, NAME if i == 0 else SUB)
    for label, y in left:
        sh.terminal(x0, y)
        sh.text(x0 + 1.8, y, label, PIN, mid=True)
    for label, y in right:
        sh.terminal(x1, y)
        sh.text(x1 - 1.8, y, label, PIN, anchor="end", mid=True)
    for label, x in top:
        sh.terminal(x, y0)
        sh.text(x, y0 + 1.6 + CAP * PIN, label, PIN, anchor="middle")


def bundle(sh, x0, x1, rows, names, cable, dashed=False):
    """parallel wires of one cable, each wire named once, the cable named above them"""
    cx = (x0 + x1) / 2
    for y, n in zip(rows, names):
        sh.line([(x0, y), (x1, y)], colour=wire_colour(n), dashed=dashed)
        sh.text(cx, y - 0.8, n, WIRE, anchor="middle", colour=wire_colour(n))
    if cable:
        sh.text(cx, rows[0] - CABLE_UP, cable, CABLE, anchor="middle")


def rows(first, n):
    return [first + i * P for i in range(n)]


def draw():
    sh = Sheet()

    # frame of the sheet
    fx0, fy0, fx1, fy1 = FRAME
    sh.rect(fx0, fy0, fx1, fy1, width=0.7)

    # the uno in the middle, sensors to the right, pi and servos to the left
    ux0, ux1 = 104.0, 154.0
    dx0, dx1 = 188.0, 226.0
    mid = (ux1 + dx0) / 2

    # right edge of the uno: the analog g v s headers and the i2c header
    photo = [
        ("A0", "photoresistor L", "left, 1 dot", 30.0),
        ("A1", "photoresistor R", "right, 2 dots", 50.0),
        ("A2", "photoresistor U", "top, 3 dots", 70.0),
        ("A3", "photoresistor D", "bottom, 4 dots", 90.0),
    ]
    a4, a5 = rows(118.0, 3), rows(134.0, 3)
    i2c = rows(158.0, 4)

    uno_right = []
    for header, _, _, y in photo:
        uno_right += list(zip("GVS", rows(y, 3)))
    uno_right += list(zip("GVS", a4)) + list(zip("GVS", a5))
    uno_right += list(zip(("GND", "VCC", "SDA", "SCL"), i2c))

    # left edge of the uno: usb socket and the two servo headers
    usb_y = 60.0
    d9, d10 = rows(110.0, 3), rows(130.0, 3)
    uno_left = [("USB B", usb_y)] + list(zip("GVS", d9)) + list(zip("GVS", d10))

    part(sh, (ux0, 22.0, ux1, 178.0), ["Keyestudio UNO", "slide switch on 5 V"],
         left=uno_left, right=uno_right, text_x=ux0 + 4.0, text_y=29.0)
    # header names next to their pins, as printed on the board
    for header, _, _, y in photo:
        sh.text(ux1 - 7.0, y + P, header, PIN, anchor="end", mid=True)
    sh.text(ux1 - 7.0, a4[1], "A4", PIN, anchor="end", mid=True)
    sh.text(ux1 - 7.0, a5[1], "A5", PIN, anchor="end", mid=True)
    sh.text(ux0 + 7.0, d9[1], "D9", PIN, mid=True)
    sh.text(ux0 + 7.0, d10[1], "D10", PIN, mid=True)

    # light sensors, one 3 pin cable each
    for header, name, where, y in photo:
        r = rows(y, 3)
        bundle(sh, ux1, dx0, r, "GVS", "3 pin cable")
        part(sh, (dx0, y - 4.0, dx1, y + 12.0), [name, where], left=list(zip("GVS", r)),
             text_x=dx0 + 7.0, text_y=y + 3.2)

    # bh1750 on the i2c header, 4 pin cable straight through
    bundle(sh, ux1, dx0, i2c, ("G", "V", "SDA", "SCL"), "4 pin cable, 350 mm")
    part(sh, (dx0, i2c[0] - 4.0, dx1, i2c[-1] + 4.0), ["BH1750", "light sensor", "I2C 0x23"],
         left=list(zip(("G", "V", "SDA", "SCL"), i2c)), text_x=dx0 + 12.0, text_y=i2c[0] + 2.4)

    # optional ina219 with the panel and a load, all dashed
    ina = (dx0, 113.0, dx1, 147.0)
    vin_minus, vin_plus = a4[1], a5[1]
    ina_left = [("VCC", a4[1]), ("SDA", a4[2]), ("GND", a5[0]), ("SCL", a5[2])]
    for label, y in ina_left:
        n = {"VCC": "V", "GND": "G"}.get(label, label)
        sh.line([(ux1, y), (dx0, y)], colour=wire_colour(n), dashed=True)
        sh.text(mid, y - 0.8, n, WIRE, anchor="middle", colour=wire_colour(n))
    sh.text(mid, a4[0] - CABLE_UP, "jumper wires", CABLE, anchor="middle")

    # panel minus goes back to a free G pin over the top of the ina219
    route_y = 108.0
    node_x = 248.0
    res = (232.0, 242.0)
    panel = (254.0, 114.0, 281.0, 146.0)
    sh.line([(ux1, a4[0]), (dx0 - 4.0, a4[0]), (dx0 - 4.0, route_y), (node_x, route_y), (node_x, vin_minus)],
            dashed=True)
    sh.text(mid, a4[0] - 0.8, "G", WIRE, anchor="middle")

    part(sh, ina, ["INA219", "optional", "I2C 0x40"], left=ina_left,
         right=[("VIN-", vin_minus), ("VIN+", vin_plus)], dashed=True, text_x=dx0 + 12.0, text_y=129.0)

    # load resistor in the VIN- line
    sh.line([(dx1, vin_minus), (res[0], vin_minus)], dashed=True)
    sh.rect(res[0], vin_minus - 1.6, res[1], vin_minus + 1.6, width=WIRE_W, dashed=True)
    sh.line([(res[1], vin_minus), (panel[0], vin_minus)], dashed=True)
    sh.junction(node_x, vin_minus)
    sh.text((res[0] + res[1]) / 2, vin_minus + 6.0, "load 47 \u03a9, 1 W", SUB, anchor="middle")

    sh.line([(dx1, vin_plus), (panel[0], vin_plus)], dashed=True)
    lead_x = (dx1 + panel[0]) / 2
    sh.text(lead_x, vin_plus - 0.8, "+", WIRE, anchor="middle")
    sh.text(lead_x, vin_plus - CABLE_UP, "panel lead", CABLE, anchor="middle")

    part(sh, panel, ["solar", "panel"], left=[("-", vin_minus), ("+", vin_plus)], dashed=True,
         text_x=panel[0] + 6.0, text_y=129.0)

    # servos on the left, their own leads
    lx0, lx1 = 30.0, 72.0
    for name, where, r in (("pan servo", "the lower one", d9), ("tilt servo", "the upper one", d10)):
        part(sh, (lx0, r[0] - 4.0, lx1, r[-1] + 4.0), [name, where],
             right=list(zip(("brown", "red", "orange"), r)), text_x=lx0 + 3.0, text_y=r[0] + 3.2)
        bundle(sh, lx1, ux0, r, "GVS", "servo lead")

    # the pi, fed by its own supply, feeds the uno over usb
    pi = (24.0, 46.0, 72.0, 68.0)
    feed_x = 40.0
    part(sh, pi, ["Raspberry Pi 4 or 3B+"], top=[("power in", feed_x)], right=[("USB A", usb_y)],
         text_x=pi[0] + 3.0, text_y=56.5)
    bundle(sh, pi[2], ux0, [usb_y], ["USB"], "USB A to B cable")

    supply = (24.0, 16.0, 98.0, 32.0)
    part(sh, supply, ["power supply", "5.1 V, 3 A USB C (Pi 4) or 2.5 A micro USB (Pi 3B+)"],
         text_x=supply[0] + 3.0, text_y=22.5)
    sh.terminal(feed_x, supply[3])
    sh.line([(feed_x, supply[3]), (feed_x, pi[1])], colour=POWER)
    sh.text(feed_x + 2.0, 38.5, "5.1 V", WIRE, colour=POWER)
    sh.text(feed_x + 2.0, 42.5, "supply cable", CABLE)

    sh.text(lx0, 160.0, "left, right, top and bottom seen from behind the tracker", SUB)

    # title block, lower right corner of the frame
    tx0, ty0 = fx1 - 70.0, fy1 - 20.0
    sh.rect(tx0, ty0, fx1, fy1, width=0.7)
    sh.line([(fx1 - 24.0, ty0), (fx1 - 24.0, fy1)], width=0.35)
    sh.line([(tx0, ty0 + 10.0), (fx1 - 24.0, ty0 + 10.0)], width=0.35)
    sh.text(tx0 + 3.0, ty0 + 7.4, "brainSOL", 5.0)
    sh.text(tx0 + 3.0, ty0 + 17.0, "wiring", 4.2)
    sh.text(fx1 - 12.0, ty0 + 11.0, "sheet 1 of 1", 2.8, anchor="middle")
    return sh.svg()


def page_html(svg):
    font = base64.b64encode(FONT.read_bytes()).decode("ascii")
    return ('<!doctype html>\n<html><head><meta charset="utf-8"><title>brainSOL wiring</title>\n<style>\n'
            f'@font-face {{ font-family: "Geist Serif"; src: url(data:font/ttf;base64,{font}) format("truetype"); }}\n'
            f'@page {{ size: {PAGE_W}mm {PAGE_H}mm; margin: 0; }}\n'
            'html, body { margin: 0; padding: 0; background: #ffffff; }\n'
            f'body {{ width: {PAGE_W}mm; height: {PAGE_H}mm; overflow: hidden; }}\n'
            'svg { display: block; }\n'
            f'</style></head><body>\n{svg}</body></html>\n')


def find_browser(given):
    if given:
        return given
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    sys.exit("no edge or chrome found, pass one with --browser")


def print_pdf(browser, html, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wiring-", ignore_cleanup_errors=True) as tmp:
        page = Path(tmp) / "wiring.html"
        page.write_text(html, encoding="utf-8")
        cmd = [browser, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={Path(tmp) / 'profile'}", "--no-pdf-header-footer",
               "--virtual-time-budget=5000", f"--print-to-pdf={out}", page.as_uri()]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if not out.exists():
        sys.exit("the browser wrote no pdf")


def main():
    ap = argparse.ArgumentParser(description="print the wiring page to docs/wiring.pdf")
    ap.add_argument("--browser", help="path of edge, chrome or chromium")
    ap.add_argument("--svg", type=Path, help="also write the page as svg here")
    ap.add_argument("--out", type=Path, default=OUT, help="the pdf to write")
    args = ap.parse_args()
    if not FONT.exists():
        sys.exit(f"missing font {FONT}")
    svg = draw()
    if args.svg:
        args.svg.write_text(svg, encoding="utf-8", newline="\n")
    print_pdf(find_browser(args.browser), page_html(svg), args.out.resolve())
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
