# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.1"]
# ///
"""the picture steps of the readme, docs/steps-1.png to docs/steps-3.png

    uv run build.py      first, it writes the renders and renders/marks.json this script uses
    uv run sheets.py     then this, the lettering is osifont from cad/assets like on the drawings
    uv run sheets.py --font path/to/osifont.ttf

the sheets look like pages of a workshop manual: paper, a frame, thin lines between the steps,
numbered balloons and one colour for what each step is about
"""

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
RENDERS = HERE / "renders"
DOCS = HERE.parent / "docs"
FONT = HERE / "cad" / "assets" / "osifont.ttf"

# everything is drawn at twice the size and scaled down at the end, so the lines get smooth edges
K = 2
WIDTH = 1600
MARGIN = 26  # paper outside the frame
HEAD = 84  # the row with the balloon and the text of a step
PAD = 22
TITLE_H = 64

# the same paper and ink as cad/render.py, so a render sits on the sheet without a seam
PAPER = (242, 239, 232)
INK = (38, 36, 31)
HAIR = (150, 145, 136)
ORANGE = (255, 139, 75)

FRAME_W = 3
LINE_W = 2.6  # the pen of the drawn pictures
THIN_W = 1.6  # leader lines and hairlines

# render file or drawn picture and the text of each step
STEPS = [
    ("print/fit_test", "Print the fit test first"),
    ("print/plates", "Then the six plates in three colours"),
    ("sd card", "Write Raspberry Pi OS Lite to the card"),
    ("terminal", "Run the install script, choose a pin"),
    ("inside_base", "Plug in the UNO, wire, run the doctor"),
    ("neck_open", "Centre the servos before the horns"),
    ("rear_three_quarter", "Only the cable fits through the notch"),
    ("exploded", "Build it with the drawings"),
    ("page", "Power on, open brainsol.local:8080"),
    ("lock", "Unlock the admin tools with your pin"),
    ("bars", "Calibrate it with a lamp"),
    ("head_over_the_top", "It follows the light"),
]

# each sheet as columns of step numbers, a column with one step gets a tall picture
SHEETS = [
    [[1, 3], [2, 4]],
    [[5, 6, 7], [8]],
    [[9, 11], [10, 12]],
]
PICTURE_H = 500


def s(v):
    return round(v * K)


class Pen:
    """draws in the units of the final sheet on a canvas K times larger"""

    def __init__(self, img, fonts):
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.fonts = fonts

    def line(self, pts, fill=INK, width=LINE_W):
        self.d.line([(s(x), s(y)) for x, y in pts], fill=fill, width=s(width), joint="curve")
        # round ends
        r = s(width) / 2
        for x, y in (pts[0], pts[-1]):
            self.d.ellipse((s(x) - r, s(y) - r, s(x) + r, s(y) + r), fill=fill)

    def rect(self, x0, y0, x1, y1, fill=None, outline=INK, width=LINE_W, radius=0):
        box = (s(x0), s(y0), s(x1), s(y1))
        if radius:
            self.d.rounded_rectangle(box, s(radius), fill=fill, outline=outline, width=s(width))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=s(width))

    def circle(self, x, y, r, fill=None, outline=INK, width=LINE_W):
        self.d.ellipse((s(x - r), s(y - r), s(x + r), s(y + r)), fill=fill, outline=outline,
                       width=s(width) if outline else 0)

    def arc(self, x, y, r, a0, a1, fill=INK, width=LINE_W):
        self.d.arc((s(x - r), s(y - r), s(x + r), s(y + r)), a0, a1, fill=fill, width=s(width))

    def poly(self, pts, fill=None, outline=INK, width=LINE_W):
        self.d.polygon([(s(x), s(y)) for x, y in pts], fill=fill, outline=outline, width=s(width) if outline else 0)

    def text(self, x, y, t, font="text", fill=INK, anchor="ls"):
        self.d.text((s(x), s(y)), t, font=self.fonts[font], fill=fill, anchor=anchor)

    def length(self, t, font="text"):
        return self.d.textlength(t, font=self.fonts[font]) / K

    def arrow(self, x0, y0, x1, y1, fill=INK, width=LINE_W, head=16):
        """a line with a narrow filled head at x1, y1 like on a drawing"""
        a = math.atan2(y1 - y0, x1 - x0)
        bx, by = x1 - head * math.cos(a), y1 - head * math.sin(a)
        self.line([(x0, y0), (bx, by)], fill, width)
        w = head * 0.3
        self.poly([(x1, y1), (bx + w * math.sin(a), by - w * math.cos(a)), (bx - w * math.sin(a), by + w * math.cos(a))],
                  fill=fill, outline=None)

    def leader(self, x0, y0, x1, y1, label, right=True):
        """a thin line from a dot on the part to a short shoulder with the label"""
        self.circle(x0, y0, 3.2, fill=INK, outline=None)
        sx = x1 + (30 if right else -30)
        self.line([(x0, y0), (x1, y1), (sx, y1)], width=THIN_W)
        if right:
            self.text(sx + 8, y1 + 7, label, "small")
        else:
            self.text(sx - 8, y1 + 7, label, "small", anchor="rs")

    def balloon(self, x, y, n, r=22, font="num"):
        self.circle(x, y, r, fill=PAPER, width=2.2)
        self.text(x, y + 1, str(n), font, anchor="mm")


def load_marks():
    f = RENDERS / "marks.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def content_box(img, pad=0.04):
    """the part of a render that is not plain paper, with a little room around it"""
    bg = Image.new("RGB", img.size, PAPER)
    diff = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 2 else 0)
    box = diff.getbbox() or (0, 0, img.width, img.height)
    w, h = box[2] - box[0], box[3] - box[1]
    m = pad * max(w, h)
    return (max(0, box[0] - m), max(0, box[1] - m), min(img.width, box[2] + m), min(img.height, box[3] + m))


def feather(w, h, r):
    """a mask that fades out over r pixels at the border, so a shadow cut by the crop runs out softly"""
    ramp = [min(1.0, (i + 0.5) / r) for i in range(r)]
    col = Image.new("L", (1, h), 255)
    row = Image.new("L", (w, 1), 255)
    for i, a in enumerate(ramp):
        v = round(255 * a * a * (3 - 2 * a))
        col.putpixel((0, i), v)
        col.putpixel((0, h - 1 - i), v)
        row.putpixel((i, 0), v)
        row.putpixel((w - 1 - i, 0), v)
    return ImageChops.multiply(col.resize((w, h)), row.resize((w, h)))


def place(pen, name, x, y, w, h, marks, box=None):
    """put a render into the area, returns a function that maps its pixels to sheet units"""
    img = Image.open(RENDERS / f"{name}.png").convert("RGB")
    box = box or content_box(img)
    src = img.crop(tuple(round(v) for v in box))
    scale = min(w / src.width, h / src.height)
    sw, sh = src.width * scale, src.height * scale
    ox, oy = x + (w - sw) / 2, y + (h - sh) / 2
    pen.img.paste(src.resize((s(sw), s(sh)), Image.LANCZOS), (s(ox), s(oy)), feather(s(sw), s(sh), s(28)))

    def to_sheet(p):
        return ox + (p[0] - box[0]) * scale, oy + (p[1] - box[1]) * scale

    return to_sheet, marks.get(name, {})


# the drawn pictures, each in an area x, y, w, h of the sheet

def sd_card(pen, x, y, w, h):
    cw, ch = 240, 316
    x0, y0 = x + (w - cw) / 2, y + (h - ch) / 2 + 36
    cut = 50
    outline = [(x0, y0), (x0 + cw - cut, y0), (x0 + cw, y0 + cut), (x0 + cw, y0 + ch), (x0, y0 + ch)]
    pen.poly(outline, fill=PAPER)
    # the write protect slider on the left edge
    pen.rect(x0 - 8, y0 + 100, x0, y0 + 144, width=THIN_W)
    # the contacts along the top
    for i in range(7):
        cx = x0 + 24 + i * 23
        pen.rect(cx, y0 + 20, cx + 12, y0 + 64, width=THIN_W)
    # the label
    lx0, ly0, lx1, ly1 = x0 + 26, y0 + 104, x0 + cw - 26, y0 + ch - 28
    pen.rect(lx0, ly0, lx1, ly1, width=THIN_W)
    for i, t in enumerate(("Raspberry Pi", "OS Lite", "64 bit")):
        pen.text((lx0 + lx1) / 2, ly0 + 54 + i * 40, t, "pic", anchor="ms")
    # what goes on the card
    pen.arrow(x0 + cw / 2, y0 - 96, x0 + cw / 2, y0 - 12, fill=ORANGE, width=3.4, head=22)


def terminal(pen, x, y, w, h):
    tw, th = min(w - 40, 640), 330
    x0, y0 = x + (w - tw) / 2, y + (h - th) / 2
    pen.rect(x0, y0, x0 + tw, y0 + th, fill=PAPER)
    pen.line([(x0, y0 + 46), (x0 + tw, y0 + 46)], width=THIN_W)
    pen.text(x0 + 20, y0 + 32, "pi@brainsol", "small")
    lines = ["$ deploy/install.sh", "[sudo] password:", "new admin pin:", "done, open in a browser",
             "http://brainsol.local:8080"]
    ty = y0 + 104
    for i, t in enumerate(lines):
        pen.text(x0 + 30, ty + i * 48, t, "pic")
    # the command is the step
    lw = pen.length(lines[0], "pic")
    pen.line([(x0 + 30, ty + 10), (x0 + 30 + lw, ty + 10)], fill=ORANGE, width=3.4)


def lock(pen, x, y, w, h):
    cx = x + w / 2
    bw, bh = 170, 128
    by = y + h / 2 - 70
    # the shackle, open and turned up on the right
    r = 50
    sx = cx - r
    pen.line([(sx, by), (sx, by - 52)], fill=ORANGE, width=6)
    pen.arc(cx, by - 52, r, 180, 360, fill=ORANGE, width=6)
    pen.line([(cx + r, by - 52), (cx + r, by - 30)], fill=ORANGE, width=6)
    pen.rect(cx - bw / 2, by, cx + bw / 2, by + bh, fill=PAPER, radius=10)
    pen.circle(cx, by + 50, 12)
    pen.line([(cx, by + 62), (cx, by + 92)])
    # the pin field
    fy = by + bh + 56
    for i in range(4):
        fx = cx + (i - 1.5) * 64
        pen.rect(fx - 24, fy - 26, fx + 24, fy + 26, width=THIN_W)
        pen.circle(fx, fy, 7, fill=INK, outline=None)


def bars(pen, x, y, w, h):
    """the light sensor bars of the calibrate tab, a dark mark and a bright one from the lamp"""
    x0, x1 = x + 120, x + w - 70
    step = 86
    y0 = y + (h - 3 * step) / 2 + 20
    levels = [(0.74, 0.16, 0.86), (0.66, 0.13, 0.81), (0.83, 0.2, 0.93), (0.6, 0.11, 0.77)]
    for i, (name, (fill, dark, bright)) in enumerate(zip("LRUD", levels)):
        cy = y0 + i * step
        pen.text(x0 - 40, cy, name, "pic", anchor="mm")
        pen.rect(x0, cy - 15, x1, cy + 15, width=THIN_W)
        # the reading as a hatched bar, like a section on a drawing
        fx = x0 + (x1 - x0) * fill
        k = x0
        while k < fx + 30:
            a, b = max(k, x0), min(k + 30, fx)
            if a < b:
                ya = cy + 15 - (a - k)
                yb = cy + 15 - (b - k)
                pen.line([(a, max(ya, cy - 15)), (b, max(yb, cy - 15))], width=1.2)
            k += 12
        pen.line([(fx, cy - 15), (fx, cy + 15)], width=THIN_W)
        for at, col in ((dark, INK), (bright, ORANGE)):
            mx = x0 + (x1 - x0) * at
            pen.line([(mx, cy - 26), (mx, cy + 26)], fill=col, width=3.4)
    # what the two marks are
    mx_d = x0 + (x1 - x0) * levels[0][1]
    mx_b = x0 + (x1 - x0) * levels[0][2]
    pen.line([(mx_d, y0 - 30), (mx_d, y0 - 52)], width=THIN_W)
    pen.text(mx_d, y0 - 62, "dark", "small", anchor="ms")
    pen.line([(mx_b, y0 - 30), (mx_b, y0 - 52)], width=THIN_W)
    pen.text(mx_b, y0 - 62, "lamp", "small", anchor="ms")


def page(pen, x, y, w, h, marks):
    """the page of the pi, a browser window with the twin of the tracker turning to the lamp"""
    bw, bh = min(w - 30, 700), min(h - 10, 470)
    x0, y0 = x + (w - bw) / 2, y + (h - bh) / 2
    pen.rect(x0, y0, x0 + bw, y0 + bh, fill=PAPER)
    pen.rect(x0 + 16, y0 + 12, x0 + bw - 16, y0 + 50, width=THIN_W, radius=19)
    pen.text(x0 + 38, y0 + 39, "brainsol.local:8080", "small")
    pen.text(x0 + 28, y0 + 92, "The panel faces the light.", "pic")
    to_sheet, m = place(pen, "page_twin", x0 + 150, y0 + 104, bw - 180, bh - 120, marks)
    ray(pen, to_sheet, m, (x0 + 40, y0 + 120, x0 + bw - 40, y0 + bh - 30))


def edge_point(px, py, lx, ly, area):
    """from the panel toward the lamp until the edge of the area (x0, y0, x1, y1)"""
    x0, y0, x1, y1 = area
    t = math.inf
    for d, p, lo, hi in ((lx - px, px, x0, x1), (ly - py, py, y0, y1)):
        if d > 1e-9:
            t = min(t, (hi - p) / d)
        if d < -1e-9:
            t = min(t, (lo - p) / d)
    return px + (lx - px) * t, py + (ly - py) * t


def ray(pen, to_sheet, m, area):
    """a lamp at the edge of the area where the panel looks, and one orange ray to the panel"""
    if "panel" not in m or "lamp" not in m:
        return
    px, py = to_sheet(m["panel"])
    lx, ly = edge_point(px, py, *to_sheet(m["lamp"]), area)
    lamp_glyph(pen, lx, ly)
    d = math.hypot(px - lx, py - ly)
    sx, sy = lx + (px - lx) / d * 22, ly + (py - ly) / d * 22
    pen.line([(sx, sy), (px, py)], fill=ORANGE, width=3)
    pen.circle(px, py, 5, fill=ORANGE, outline=None)


def lamp_glyph(pen, x, y, r=11):
    """a small lamp, a circle with short rays"""
    pen.circle(x, y, r, fill=PAPER, width=2.2)
    for k in range(8):
        a = k * math.pi / 4
        pen.line([(x + (r + 6) * math.cos(a), y + (r + 6) * math.sin(a)),
                  (x + (r + 13) * math.cos(a), y + (r + 13) * math.sin(a))], width=2.0)


def chain(pen, a, b, dash=(26, 6, 4, 6)):
    """a thin dash dot line from a to b"""
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
    t, k = 0.0, 0
    while t < d:
        n = dash[k % 4]
        if k % 2 == 0:
            e = min(t + n, d)
            pen.line([(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * e, a[1] + uy * e)], fill=HAIR, width=THIN_W)
        t += n
        k += 1


def picture(pen, n, x, y, w, h, marks):
    name = STEPS[n - 1][0]
    if name == "sd card":
        return sd_card(pen, x, y, w, h)
    if name == "terminal":
        return terminal(pen, x, y, w, h)
    if name == "lock":
        return lock(pen, x, y, w, h)
    if name == "bars":
        return bars(pen, x, y, w, h)
    if name == "page":
        return page(pen, x, y, w, h, marks)
    to_sheet, m = place(pen, name, x, y, w, h, marks)
    if name == "rear_three_quarter" and "notch" in m:
        cx, cy = to_sheet(m["notch"])
        pen.circle(cx, cy, 24, outline=ORANGE, width=4)
    if name == "neck_open":
        for key, label, dx, dy in (("tilt_servo", "tilt servo", 150, -40), ("pan_servo", "pan servo", 150, 30)):
            if key in m:
                px, py = to_sheet(m[key])
                pen.leader(px, py, px + dx, py + dy, label)
    if name == "inside_base" and "usb" in m:
        px, py = to_sheet(m["usb"])
        pen.leader(px, py, px - 120, py + 70, "USB to the UNO", right=False)
    if name == "print/plates":
        for i in range(6):
            key = f"plate_{i + 1}"
            if key in m:
                px, py = to_sheet(m[key])
                pen.balloon(px, py, i + 1, r=17, font="small")
    if name == "head_over_the_top":
        ray(pen, to_sheet, m, (x + 30, y + 30, x + w - 30, y + h - 30))
    if name == "exploded" and "axis_lo" in m:
        # the axis of the turret as a chain line, like on the drawings
        chain(pen, to_sheet(m["axis_lo"]), to_sheet(m["axis_hi"]))


def sheet(cols, number, total, fonts, marks):
    inner_w = WIDTH - 2 * MARGIN
    col_w = inner_w / len(cols)
    rows = max(len(c) for c in cols)
    pic_h = PICTURE_H if rows == 2 else PICTURE_H * 0.78
    cell_h = HEAD + pic_h + PAD
    body = rows * cell_h
    height = round(2 * MARGIN + body + TITLE_H)
    img = Image.new("RGB", (s(WIDTH), s(height)), PAPER)
    pen = Pen(img, fonts)
    x0, y0, x1 = MARGIN, MARGIN, WIDTH - MARGIN
    y1 = height - MARGIN

    def step(n, x, y, w, h):
        pen.balloon(x + 40, y + 44, n)
        pen.text(x + 76, y + 55, STEPS[n - 1][1])
        picture(pen, n, x + PAD, y + HEAD, w - 2 * PAD, h - HEAD - PAD, marks)

    for c, col in enumerate(cols):
        x = x0 + c * col_w
        if len(col) == rows:
            for r, n in enumerate(col):
                step(n, x, y0 + r * cell_h, col_w, cell_h)
        else:
            step(col[0], x, y0, col_w, body)
    # thin lines between the steps, drawn last so no picture covers them
    for c in range(1, len(cols)):
        pen.line([(x0 + c * col_w, y0), (x0 + c * col_w, y0 + body)], fill=HAIR, width=THIN_W)
    for c, col in enumerate(cols):
        if len(col) == rows:
            for r in range(1, rows):
                yy = y0 + r * cell_h
                pen.line([(x0 + c * col_w, yy), (x0 + (c + 1) * col_w, yy)], fill=HAIR, width=THIN_W)
    # the title strip at the foot like on the drawings and the wiring page
    ty = y0 + body
    pen.line([(x0, ty), (x1, ty)], width=FRAME_W - 1)
    pen.text(x0 + 22, ty + 43, "brainSOL", "title")
    steps = [n for c in cols for n in c]
    mid = f"steps {min(steps)} to {max(steps)}"
    pen.line([(x0 + 260, ty), (x0 + 260, y1)], width=FRAME_W - 1)
    pen.text(x0 + 282, ty + 41, mid, "text")
    pen.line([(x1 - 230, ty), (x1 - 230, y1)], width=FRAME_W - 1)
    pen.text(x1 - 208, ty + 41, f"sheet {number} of {total}", "text")
    pen.rect(x0, y0, x1, y1, width=FRAME_W)
    return img.resize((WIDTH, height), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--font", type=Path, default=FONT, help="osifont.ttf, the lettering of the drawings")
    args = ap.parse_args()
    if not args.font.exists():
        raise SystemExit(f"missing font {args.font}, get osifont.ttf from github.com/hikikomori82/osifont")

    def f(size):
        return ImageFont.truetype(str(args.font), s(size))

    fonts = {"text": f(33), "num": f(27), "pic": f(29), "small": f(25), "title": f(38)}
    marks = load_marks()
    for i, cols in enumerate(SHEETS, 1):
        out = DOCS / f"steps-{i}.png"
        sheet(cols, i, len(SHEETS), fonts, marks).save(out, optimize=True)
        print(f"wrote {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
