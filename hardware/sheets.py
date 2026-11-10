# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.1"]
# ///
"""the picture steps of the readme, docs/steps-1.png to docs/steps-3.png

    uv run build.py      first, it writes the renders this script crops
    uv run sheets.py     then this, it takes the font of the web app from the brainsol repo next to this one
    uv run sheets.py --font path/to/GeistSerif-Regular.woff2

step 9 shows docs/screenshot.png, the page as the pi serves it
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
RENDERS = HERE / "renders"
DOCS = HERE.parent / "docs"
FONT = HERE.parent.parent / "brainsol" / "src" / "lib" / "fonts" / "GeistSerif-Regular.woff2"

# everything is drawn at twice the size and scaled down at the end, so the shapes get smooth edges
K = 2
WIDTH = 1600
PAD = 48
GAP_X = 48
GAP_Y = 40
TILE_W = (WIDTH - 2 * PAD - GAP_X) // 2
TILE_H = TILE_W * 3 // 4
RADIUS = 18
NUM_SIZE = 64
TEXT_SIZE = 36

WHITE = (255, 255, 255)
ORANGE = (255, 139, 75)
INK = (29, 29, 31)
DARK = (17, 17, 19)
PANEL = (30, 30, 34)
LINE = (70, 70, 78)
LIGHT = (236, 234, 228)
GREY = (150, 150, 158)

# render file or drawn picture, crop box in its pixels (left, top, right, bottom), the text
STEPS = [
    ("print/fit_test", (150, 160, 1050, 835), "Print the fit test first"),
    ("print/tray", (100, 90, 1100, 840), "Then the six plates in three colours"),
    ("sd card", None, "Write Raspberry Pi OS Lite to the card"),
    ("terminal", None, "Run the install script, choose a pin"),
    ("cables", (100, 30, 1500, 1080), "Plug in the UNO, wire, run the doctor"),
    ("neck_open", (250, 200, 1350, 1025), "Centre the servos before the horns"),
    ("rear_three_quarter", (440, 510, 1360, 1200), "Only the cable fits through the notch"),
    ("exploded", (250, 200, 1150, 1960), "Build it with the drawings"),
    ("screenshot", (0, 0, 1260, 945), "Power on, open brainsol.local:8080"),
    ("lock", None, "Unlock the admin tools with your pin"),
    ("bars", None, "Calibrate it with a lamp"),
    ("head_over_the_top", (100, 80, 1500, 1130), "It follows the light"),
]

# each sheet as columns of step numbers, a column with one step gets a tall picture
SHEETS = [
    [[1, 3], [2, 4]],
    [[5, 6, 7], [8]],
    [[9, 11], [10, 12]],
]

# where the notch sits in rear_three_quarter.png, it gets an orange ring
NOTCH = (1010, 1018, 48)


def font(path, size):
    return ImageFont.truetype(str(path), size * K)


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def fit(img, box, w, h):
    # crop, then scale into the tile, a box of another shape gets the corner colour around it
    src = img.crop(box) if box else img
    bg = src.getpixel((2, 2))
    scale = min(w / src.width, h / src.height)
    sw, sh = round(src.width * scale), round(src.height * scale)
    tile = Image.new("RGB", (w, h), bg)
    tile.paste(src.resize((sw, sh), Image.LANCZOS), ((w - sw) // 2, (h - sh) // 2))
    return tile, scale, ((w - sw) // 2, (h - sh) // 2)


def render_tile(name, box, w, h, fonts):
    if name == "sd card":
        return sd_card(w, h, fonts)
    if name == "terminal":
        return terminal(w, h, fonts)
    if name == "lock":
        return lock(w, h, fonts)
    if name == "bars":
        return bars(w, h, fonts)
    if name == "screenshot":
        tile, _, _ = fit(Image.open(DOCS / "screenshot.png").convert("RGB"), box, w, h)
        return tile
    img = Image.open(RENDERS / f"{name}.png").convert("RGB")
    tile, scale, (ox, oy) = fit(img, box, w, h)
    if name == "rear_three_quarter":
        x, y, r = NOTCH
        cx, cy, cr = (x - box[0]) * scale + ox, (y - box[1]) * scale + oy, r * scale
        ImageDraw.Draw(tile).ellipse((cx - cr, cy - cr, cx + cr, cy + cr), outline=ORANGE, width=6 * K)
    return tile


def sd_card(w, h, fonts):
    tile = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(tile)
    cw, ch = 300 * K, 390 * K
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    cut = 70 * K
    d.polygon([(x0, y0), (x0 + cw - cut, y0), (x0 + cw, y0 + cut), (x0 + cw, y0 + ch), (x0, y0 + ch)], fill=LIGHT)
    # the grip ridges on the top edge
    for i in range(6):
        gx = x0 + 34 * K + i * 28 * K
        d.rounded_rectangle((gx, y0 + 26 * K, gx + 12 * K, y0 + 86 * K), 4 * K, fill=(205, 203, 197))
    # the label
    lx0, ly0, lx1, ly1 = x0 + 30 * K, y0 + 140 * K, x0 + cw - 30 * K, y0 + ch - 34 * K
    d.rounded_rectangle((lx0, ly0, lx1, ly1), 10 * K, fill=PANEL)
    d.rectangle((lx0, ly0 + 30 * K, lx1, ly0 + 38 * K), fill=ORANGE)
    f = fonts["pic"]
    for i, text in enumerate(("Pi OS Lite", "64 bit")):
        tw = d.textlength(text, font=f)
        d.text(((lx0 + lx1 - tw) / 2, ly0 + 70 * K + i * 56 * K), text, font=f, fill=LIGHT)
    return tile


def terminal(w, h, fonts):
    tile = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(tile)
    tw, th = w - 120 * K, h - 130 * K
    x0, y0 = (w - tw) // 2, (h - th) // 2
    d.rounded_rectangle((x0, y0, x0 + tw, y0 + th), 14 * K, fill=PANEL, outline=LINE, width=2 * K)
    for i, c in enumerate((ORANGE, GREY, GREY)):
        cx = x0 + 34 * K + i * 30 * K
        d.ellipse((cx - 8 * K, y0 + 26 * K, cx + 8 * K, y0 + 42 * K), fill=c)
    d.line((x0, y0 + 66 * K, x0 + tw, y0 + 66 * K), fill=LINE, width=2 * K)
    f = fonts["pic"]
    lines = [
        [("$ ", ORANGE), ("deploy/install.sh", LIGHT)],
        [("[sudo] password: ", GREY)],
        [("new admin pin: ", GREY)],
        [("done, open in a browser", GREY)],
        [("http://brainsol.local:8080", ORANGE)],
    ]
    y = y0 + 100 * K
    for parts in lines:
        x = x0 + 34 * K
        for text, col in parts:
            d.text((x, y), text, font=f, fill=col)
            x += d.textlength(text, font=f)
        y += 62 * K
    return tile


def lock(w, h, fonts):
    tile = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(tile)
    bw, bh = 220 * K, 170 * K
    x0, y0 = (w - bw) // 2, h // 2 - 70 * K
    sw = 22 * K
    # the shackle, an arc over two posts
    sr = 70 * K
    cx = w // 2
    d.arc((cx - sr, y0 - sr - 40 * K, cx + sr, y0 - 40 * K + sr), 180, 360, fill=LIGHT, width=sw)
    d.rectangle((cx - sr, y0 - 40 * K, cx - sr + sw, y0 + 10 * K), fill=LIGHT)
    d.rectangle((cx + sr - sw, y0 - 40 * K, cx + sr, y0 + 10 * K), fill=LIGHT)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), 22 * K, fill=ORANGE)
    d.ellipse((cx - 16 * K, y0 + 52 * K, cx + 16 * K, y0 + 84 * K), fill=DARK)
    d.rectangle((cx - 7 * K, y0 + 70 * K, cx + 7 * K, y0 + 118 * K), fill=DARK)
    # four dots for the pin
    dy = y0 + bh + 70 * K
    for i in range(4):
        dx = cx + (i - 1.5) * 56 * K
        d.ellipse((dx - 13 * K, dy - 13 * K, dx + 13 * K, dy + 13 * K), fill=LIGHT)
    return tile


def bars(w, h, fonts):
    # the light sensor bars of the calibrate tab, a grey mark for dark and a white one for bright
    tile = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(tile)
    f = fonts["pic"]
    x0, x1 = 170 * K, w - 120 * K
    step = 104 * K
    y0 = (h - 3 * step) // 2
    levels = [(0.74, 0.16, 0.86), (0.66, 0.13, 0.81), (0.83, 0.2, 0.93), (0.6, 0.11, 0.77)]
    for i, (name, (fill, dark, bright)) in enumerate(zip("LRUD", levels)):
        cy = y0 + i * step
        top, bottom = d.textbbox((0, 0), name, font=f)[1::2]
        d.text((x0 - 70 * K, cy - (top + bottom) / 2), name, font=f, fill=GREY)
        d.rectangle((x0, cy - 16 * K, x1, cy + 16 * K), fill=PANEL)
        d.rectangle((x0, cy - 16 * K, x0 + (x1 - x0) * fill, cy + 16 * K), fill=ORANGE)
        for at, col in ((dark, GREY), (bright, LIGHT)):
            mx = x0 + (x1 - x0) * at
            d.rectangle((mx - 3 * K, cy - 26 * K, mx + 3 * K, cy + 26 * K), fill=col)
    return tile


def wrap(d, text, f, width):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if line and d.textlength(test, font=f) > width:
            lines.append(line)
            line = word
        else:
            line = test
    lines.append(line)
    return lines


def sheet(cols, fonts):
    tw, th = TILE_W * K, TILE_H * K
    cap_gap, line_h = 22 * K, round(TEXT_SIZE * 1.3) * K
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    nums = [n for col in cols for n in col]
    text_x = max(probe.textlength(str(n), font=fonts["num"]) for n in nums) + 20 * K
    caps = {n: wrap(probe, STEPS[n - 1][2], fonts["text"], tw - text_x) for n in nums}

    def cap_h(n):
        return max(NUM_SIZE * K, len(caps[n]) * line_h)

    rows = max(len(col) for col in cols)
    row_h = [max(cap_h(col[r]) for col in cols if len(col) == rows) for r in range(rows)]
    body = sum(th + cap_gap + rh for rh in row_h) + GAP_Y * K * (rows - 1)
    img = Image.new("RGB", (WIDTH * K, body + 2 * PAD * K), WHITE)
    d = ImageDraw.Draw(img)
    asc_num, asc_text = fonts["num"].getmetrics()[0], fonts["text"].getmetrics()[0]

    def step(n, x, y, h):
        name, box, _ = STEPS[n - 1]
        img.paste(render_tile(name, box, tw, h, fonts), (x, y), rounded_mask(tw, h, RADIUS * K))
        top = y + h + cap_gap
        d.text((x, top), str(n), font=fonts["num"], fill=ORANGE)
        # the number and the first line of the text share one baseline
        for i, line in enumerate(caps[n]):
            d.text((x + text_x, top + asc_num - asc_text + i * line_h), line, font=fonts["text"], fill=INK)

    for c, col in enumerate(cols):
        x, y = PAD * K + c * (tw + GAP_X * K), PAD * K
        if len(col) == rows:
            for n, rh in zip(col, row_h):
                step(n, x, y, th)
                y += th + cap_gap + rh + GAP_Y * K
        else:
            step(col[0], x, y, body - cap_gap - cap_h(col[0]))
    return img.resize((WIDTH, img.height // K), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--font", type=Path, default=FONT, help="GeistSerif-Regular.woff2 of the web app")
    args = ap.parse_args()
    fonts = {"num": font(args.font, NUM_SIZE), "text": font(args.font, TEXT_SIZE), "pic": font(args.font, 30)}
    for i, cols in enumerate(SHEETS, 1):
        out = DOCS / f"steps-{i}.png"
        sheet(cols, fonts).save(out, optimize=True)
        print(f"wrote {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
