"""detailed models of the bought parts, only for the step pictures

kit.py keeps its simple keep outs for the checks, the cutouts and the drawings, the models here
are drawn beside them from the same values and sit in the same local frames
the raspberry pi 3b+ follows its official mechanical drawing, the uno is the black keyestudio
board of the kit as its photos show it, the positions marked measure in params.py are kept
each model is a set of shapes per material, so the renders can give every material its colour
"""

import functools
import math

import numpy as np
from build123d import Axis, Compound, Plane, Polygon, chamfer, extrude, fillet

from . import kit
from . import params as P
from .helpers import box, cyl
from .mesh import to_trimesh

# calm colours, so the orange of a step stays the one loud thing in a picture
COLOURS = {
    "pi_pcb": "#4f6b55",  # muted green solder mask of the pi
    "uno_pcb": "#28292c",  # the keyestudio board is black
    "metal": "#b4b7bb",
    "tin": "#cfcdc6",
    "gold": "#c4a45c",
    "black": "#2a2a2d",
    "chip": "#303033",
    "pkg": "#4a4a40",  # the substrate under the lid of the pi processor
    "white": "#e6e2d8",
    "cream": "#d9cfb8",
    "brown": "#5b4535",
    "cap": "#a8916b",  # small ceramic capacitors
    "coil": "#5c5d60",
    "yellow": "#c9ad57",  # the yellow headers of the keyestudio board, muted
    "g_row": "#557192",  # the g v s rows of the board, blue, red and yellow plastic
    "v_row": "#a0544b",
    "s_row": "#c9ad57",
    "tantal": "#c99b3f",
    "led_red": "#b65045",
    "led_green": "#5f9a5c",
    "led_amber": "#d0a14e",
    "card": "#3a4250",
    "ldr": "#b79b74",  # the face of a photoresistor
    "servo": "#53627a",  # the kit servos are blue, here a quiet slate blue
    "label": "#3c4658",
}

# the look of each material in render.py, the rest is plain kit plastic
ROLE = {"metal": "metal", "tin": "metal", "gold": "gold"}


class Model:
    """shapes per material in one local frame"""

    def __init__(self):
        self.by = {}

    def add(self, material, *shapes):
        self.by.setdefault(material, []).extend(s for s in shapes if s is not None)
        return self

    def merge(self, other, loc=None):
        for k, shapes in other.by.items():
            self.add(k, *[(loc * s if loc is not None else s) for s in shapes])
        return self

    def placed(self, origin, x_dir, z_dir):
        out = Model()
        for k, shapes in self.by.items():
            out.add(k, *[kit.frame_map(s, origin, x_dir, z_dir) for s in shapes])
        return out

    def meshes(self, tol=0.03):
        """one trimesh per material"""
        out = {}
        for k, shapes in self.by.items():
            if shapes:
                out[k] = to_trimesh(Compound(children=list(shapes)), tol=tol, ang=0.2)
        return out


def items(meshes, matrix=None, colour=None, opacity=1.0):
    """render items of a model, colour paints every material the same, for the orange of a step"""
    out = []
    for k, m in meshes.items():
        if matrix is not None:
            m = m.copy()
            m.apply_transform(matrix)
        role = ROLE.get(k, "kit") if colour is None else "accent"
        out.append((m, colour or COLOURS[k], opacity, role))
    return out


# small shapes


def rbox(x0, x1, y0, y1, z0, z1, r):
    """box with its upright edges rounded"""
    b = box(x0, x1, y0, y1, z0, z1)
    r = min(r, (x1 - x0) / 2 - 0.01, (y1 - y0) / 2 - 0.01)
    return fillet(b.edges().filter_by(Axis.Z), r) if r > 0.02 else b


def cbox(x0, x1, y0, y1, z0, z1, c):
    """box with every edge chamfered"""
    b = box(x0, x1, y0, y1, z0, z1)
    c = min(c, (x1 - x0) / 2 - 0.01, (y1 - y0) / 2 - 0.01, (z1 - z0) / 2 - 0.01)
    return chamfer(b.edges(), c) if c > 0.02 else b


def pin(x, y, z0, z1, s=0.64):
    """square header pin with a pointed tip"""
    h = s / 2
    k = h * 0.6
    return box(x - h, x + h, y - h, y + h, z0, z1 - 0.4) + box(x - k, x + k, y - k, y + k, z1 - 0.41, z1)


def ring(x, y, r_out, r_in, z0, z1):
    return cyl("z", r_out, z0, z1, (x, y)) - cyl("z", r_in, z0 - 0.1, z1 + 0.1, (x, y))


def outline_plate(pts, z0, z1):
    return extrude(Plane.XY.offset(z0) * Polygon(*pts, align=None), z1 - z0)


def rounded_outline(pts, r, n=6):
    """a polygon with each corner rounded by r"""
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2 = np.array(pts[i - 1]), np.array(pts[i]), np.array(pts[(i + 1) % k])
        a, b = p0 - p1, p2 - p1
        la, lb = np.linalg.norm(a), np.linalg.norm(b)
        a, b = a / la, b / lb
        half = math.acos(max(-1.0, min(1.0, float(a @ b)))) / 2
        d = min(r / math.tan(half), la / 2, lb / 2)
        rr = d * math.tan(half)
        c = p1 + (a + b) / np.linalg.norm(a + b) * (rr / math.sin(half))
        s, e = p1 + a * d, p1 + b * d
        a0, a1 = math.atan2(*(s - c)[::-1]), math.atan2(*(e - c)[::-1])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for j in range(n + 1):
            t = a0 + da * j / n
            out.append((float(c[0] + rr * math.cos(t)), float(c[1] + rr * math.sin(t))))
    return out


def gull_leads(cx, cy, body, pitch, n, z, lead_w=0.3, reach=1.0):
    """the gull wing leads of a square chip, n on each side"""
    out = []
    h = body / 2
    first = -(n - 1) / 2 * pitch
    for i in range(n):
        o = first + i * pitch
        for sx, sy, along in ((1, 0, "y"), (-1, 0, "y"), (0, 1, "x"), (0, -1, "x")):
            if along == "y":
                x0, x1 = (cx + h, cx + h + reach) if sx > 0 else (cx - h - reach, cx - h)
                out.append(box(x0, x1, cy + o - lead_w / 2, cy + o + lead_w / 2, z, z + 0.25))
            else:
                y0, y1 = (cy + h, cy + h + reach) if sy > 0 else (cy - h - reach, cy - h)
                out.append(box(cx + o - lead_w / 2, cx + o + lead_w / 2, y0, y1, z, z + 0.25))
    return out


# raspberry pi 3b+, x along the 85 side from the sd card end, y from the power edge, z up from
# the underside of the board, every position below is read from the official drawing

PI_GPIO_X1 = 8.37  # pin 1, the square pad, on the inner row next to the sd card end
PI_GPIO_Y = (51.23, 53.77)  # inner and outer row
PI_POE = ((60.23, 45.09), (62.77, 45.09), (60.23, 47.63), (62.77, 47.63))
PI_USB_TOP = 16.0
PI_USB_PORT_Z = (1.7, 9.3)  # bottom of the lower and of the upper opening above the board top
PI_USB_OPEN = (12.5, 5.2)
PI_ETH_X0 = 65.65
PI_USB_X0 = 69.3


@functools.cache
def pi_meshes():
    return pi_model().meshes()


@functools.cache
def uno_meshes():
    return uno_model().meshes()


@functools.cache
def servo_meshes():
    return servo_model().meshes()


@functools.cache
def module_meshes(kind="ldr"):
    return module_model(kind).meshes()


def pi_model():
    m = Model()
    t = P.PI_T
    board = outline_plate(rounded_outline([(0, 0), (P.PI_L, 0), (P.PI_L, P.PI_W), (0, P.PI_W)], 3.0), 0.0, t)
    for X, Y in P.PI_HOLES:
        board -= cyl("z", P.PI_HOLE_D / 2, -1, t + 1, (X, Y))
    m.add("pi_pcb", board)
    for X, Y in P.PI_HOLES:
        m.add("tin", ring(X, Y, 3.1, P.PI_HOLE_D / 2, t - 0.01, t + 0.04),
              ring(X, Y, 3.1, P.PI_HOLE_D / 2, -0.04, 0.01))

    # 40 pin header, pin 1 on the inner row next to the sd card end
    m.add("black", cbox(PI_GPIO_X1 - 1.27, PI_GPIO_X1 + 19 * 2.54 + 1.27, 50.0, 55.08, t, t + 2.5, 0.2))
    for k in range(20):
        for y in PI_GPIO_Y:
            m.add("gold", pin(PI_GPIO_X1 + k * 2.54, y, -1.4, t + P.PI_GPIO_H))
    # poe header, four pins beside the top right hole
    m.add("black", cbox(58.96, 64.04, 43.82, 48.9, t, t + 2.5, 0.2))
    for x, y in PI_POE:
        m.add("gold", pin(x, y, -1.4, t + P.PI_GPIO_H))
    # the run pads, not fitted
    for x in (60.23, 62.77):
        m.add("tin", ring(x, 40.01, 0.8, 0.45, t - 0.01, t + 0.04))

    # two double usb sockets and the ethernet jack, metal, they stick out past the board edge
    x1 = P.PI_L + P.PI_PORT_OVERHANG
    for yc in P.PI_USB_Y:
        shell = cbox(PI_USB_X0, x1, yc - 6.57, yc + 6.57, t, t + PI_USB_TOP, 0.25)
        ow, oh = PI_USB_OPEN
        for z0 in PI_USB_PORT_Z:
            shell -= box(x1 - 13.0, x1 + 1, yc - ow / 2, yc + ow / 2, t + z0, t + z0 + oh)
            # the plastic tongue sits in the upper part of each opening
            m.add("black", box(x1 - 13.0, x1 - 0.8, yc - 5.6, yc + 5.6, t + z0 + oh - 2.45, t + z0 + oh - 0.6))
        m.add("metal", shell)
        m.add("black", box(x1 - 13.2, x1 - 12.9, yc - ow / 2, yc + ow / 2, t + 0.5, t + PI_USB_TOP - 0.5))
    eth = cbox(PI_ETH_X0, x1, P.PI_ETH_Y - 7.75, P.PI_ETH_Y + 7.75, t, t + P.PI_ETH_H, 0.25)
    ey = P.PI_ETH_Y
    hole = box(x1 - 14.0, x1 + 1, ey - 5.85, ey + 5.85, t + 2.6, t + 10.6)
    notch = box(x1 - 14.0, x1 + 1, ey - 3.0, ey + 3.0, t + 1.3, t + 2.7)
    m.add("metal", eth - box(x1 - 14.0, x1 + 1, ey - 6.4, ey + 6.4, t + 0.8, t + 11.2))
    liner = box(x1 - 14.5, x1 - 0.05, ey - 6.4, ey + 6.4, t + 0.8, t + 11.2) - hole - notch
    m.add("black", liner)
    # the eight contacts at the top of the opening
    for i in range(8):
        y = ey - 3.55 + i * 1.02
        m.add("gold", box(x1 - 13.8, x1 - 4.0, y - 0.2, y + 0.2, t + 10.0, t + 10.6))
    m.add("led_green", box(x1 - 0.2, x1 + 0.05, ey + 4.2, ey + 6.2, t + 11.4, t + 12.6))
    m.add("led_amber", box(x1 - 0.2, x1 + 0.05, ey - 6.2, ey - 4.2, t + 11.4, t + 12.6))

    # hdmi, micro usb power and the audio jack on the power edge
    hd = cbox(24.75, 39.25, -1.5, 10.65, t, t + 6.2, 0.2)
    face = [(25.25, t + 5.6), (38.75, t + 5.6), (38.75, t + 2.6), (36.75, t + 0.9), (27.25, t + 0.9), (25.25, t + 2.6)]
    pocket = extrude(Plane.XZ.offset(1.6) * Polygon(*face, align=None), 9.0, dir=(0, 1, 0))
    m.add("metal", hd - pocket)
    m.add("black", box(26.5, 37.5, -1.0, 7.0, t + 2.6, t + 3.8), box(25.0, 39.0, 7.0, 7.4, t + 0.6, t + 5.8))
    mu = cbox(6.85, 14.35, -0.6, 4.71, t, t + 2.8, 0.15) + box(6.58, 14.62, -1.22, -0.6, t, t + 3.0)
    face = [(7.3, t + 2.5), (14.2, t + 2.5), (14.2, t + 1.5), (13.4, t + 0.6), (8.1, t + 0.6), (7.3, t + 1.5)]
    face = [(x, z) for x, z in face]
    pocket = extrude(Plane.XZ.offset(1.4) * Polygon(*face, align=None), 5.5, dir=(0, 1, 0))
    m.add("metal", mu - pocket)
    m.add("black", box(8.4, 13.1, -0.9, 4.0, t + 1.75, t + 2.2))
    jack = cbox(50.0, 57.0, 0.0, 12.5, t, t + 6.0, 0.3) + cyl("y", 3.0, -2.5, 0.2, (53.5, t + 3.0))
    m.add("black", jack - cyl("y", 1.75, -3.0, 9.0, (53.5, t + 3.0)))

    # camera and display connectors, a cream body with a dark latch on top
    for x0, x1c, y0, y1 in ((43.55, 47.5, 0.3, 22.7), (1.5, 5.45, 16.8, 39.2)):
        m.add("cream", box(x0, x1c, y0, y1, t, t + 4.4))
        m.add("brown", box(x0 + 0.2, x0 + 1.8, y0 + 0.6, y1 - 0.6, t + 4.4, t + 5.5))
        m.add("black", box(x0 + 2.1, x1c - 0.5, y0 + 1.2, y1 - 1.2, t + 4.35, t + 4.45))

    # processor with its metal lid, the radio under its can, usb and lan chip, power chip
    m.add("pkg", box(19.98, 33.98, 24.52, 38.52, t, t + 0.8))
    m.add("metal", rbox(20.5, 33.46, 25.04, 38.0, t + 0.8, t + 1.45, 0.8))
    can = rbox(6.6, 17.1, 36.16, 49.36, t, t + 1.9, 0.7)
    m.add("metal", chamfer(can.edges().group_by(Axis.Z)[-1], 0.25))
    m.add("chip", box(57.05, 66.05, 23.38, 32.38, t, t + 0.9))
    m.add("chip", box(10.76, 15.76, 12.64, 17.64, t, t + 0.9))
    m.add("coil", rbox(16.9, 20.5, 2.06, 6.46, t, t + 1.9, 0.4))
    for x0, x1c, y0, y1 in PI_SMALL:
        big = max(x1c - x0, y1 - y0)
        mat = "cap" if big >= 3.0 else "coil" if min(x1c - x0, y1 - y0) >= 1.9 else "chip" if big < 1.7 else "cap"
        m.add(mat, box(x0, x1c, y0, y1, t, t + (1.0 if big >= 2.4 else 0.55)))
    # power and activity lights
    m.add("led_red", box(0.75, 1.45, 7.1, 8.7, t, t + 0.6))
    m.add("led_green", box(0.75, 1.45, 10.7, 12.3, t, t + 0.6))

    # underneath: the memory chip, the sd card slot and the card in it
    m.add("chip", box(37.6, 49.6, 27.5, 39.5, -1.0, 0.01))
    m.add("metal", box(1.69, 13.13, 22.11, 34.1, -1.4, 0.01))
    m.add("card", rbox(-2.27, 11.0, 22.51, 33.51, -1.15, -0.4, 0.6))
    return m


# smaller parts on the top of the pi, from the drawing
PI_SMALL = [
    (14.93, 18.13, 8.05, 9.65), (65.55, 67.15, 45.32, 48.52), (58.21, 59.81, 9.86, 13.06), (19.45, 21.05, 17.85, 21.05),
    (5.24, 6.84, 9.26, 12.46), (14.92, 16.52, 2.35, 5.55), (48.85, 52.05, 35.15, 36.75), (58.65, 61.84, 7.04, 8.64),
    (21.70, 23.30, 17.85, 21.05), (67.29, 68.89, 20.28, 23.48), (64.97, 66.57, 36.72, 39.92),
    (7.56, 9.56, 17.25, 19.75), (16.76, 18.76, 17.25, 19.75), (16.76, 18.76, 10.54, 13.04), (7.76, 9.76, 10.54, 13.04),
    (49.00, 50.60, 44.05, 47.05), (24.63, 26.23, 10.93, 13.93), (48.10, 51.10, 14.00, 15.60),
    (9.20, 11.80, 32.00, 33.80), (54.00, 55.60, 44.20, 47.10), (55.80, 57.80, 16.80, 18.00),
    (25.46, 26.46, 16.08, 17.88), (25.46, 26.46, 13.98, 15.78), (19.41, 21.01, 15.37, 16.17),
    (19.40, 21.00, 14.12, 14.92), (6.06, 6.86, 18.15, 19.75), (10.17, 10.97, 18.23, 19.83), (5.47, 7.07, 14.38, 15.18),
    (5.48, 7.08, 15.60, 16.40), (47.92, 49.52, 39.58, 40.38), (43.08, 44.67, 31.12, 31.93),
    (19.56, 20.36, 10.55, 12.15),
]


def pi_usb_port(upper=False, pair=0):
    """centre of the opening of one usb port in the local frame of the pi, on the face of the socket"""
    z0 = PI_USB_PORT_Z[1 if upper else 0]
    return (P.PI_L + P.PI_PORT_OVERHANG, P.PI_USB_Y[pair], P.PI_T + z0 + PI_USB_OPEN[1] / 2)


def pi_power_port():
    """centre of the micro usb opening of the pi, local frame"""
    return (P.PI_PWR_X, -1.22, P.PI_T + 1.55)


# keyestudio uno of the kit, u along the 68.6 side from the usb end, w from the analog edge, z up
# from the underside of the board, the usb socket, the jack, the g v s blocks and the i2c header
# follow params.py, the rest is placed as the photos of the board show it

UNO_A_COLS = 6
UNO_D_COLS = 14  # D13 next to the usb end to D0
# the columns of D9 and D10 sit side by side on the 2.54 grid, the block is centred between the two values
# of params.py
UNO_D10_AT = (P.UNO_D9_U + P.UNO_D10_U) / 2 - P.PITCH / 2
UNO_SERIAL_U = 63.6
UNO_SERIAL_W = tuple(38.9 + i * P.PITCH for i in range(4))  # GND VCC TX RX from the bottom
# the four pins of the i2c header from the analog edge, as printed on the board from the top: GND VCC SDA SCL
UNO_I2C_NAMES = ("SCL", "SDA", "VCC", "GND")


def uno_d_u(n):
    """u of the digital column n, D13 is the nearest to the usb end"""
    return UNO_D10_AT - (n - 10) * P.PITCH


def uno_a_u(i):
    return P.UNO_A0_U + i * P.PITCH


def uno_i2c_w(name):
    return sorted(P.UNO_I2C_W)[UNO_I2C_NAMES.index(name)]


def uno_outline():
    L, W = P.UNO_L, P.UNO_W
    return [(0, 0), (L - 2.54, 0), (L, 2.54), (L, 37.85), (L - 2.54, 40.39), (L - 2.54, W - 1.52), (L - 4.06, W),
            (0, W)]


def gvs_block(m, cols_u, rows, t):
    """a block of male pins, one plastic strip per row in the colour of its row"""
    for name, w in rows:
        m.add(name, rbox(min(cols_u) - 1.2, max(cols_u) + 1.2, w - 1.17, w + 1.17, t, t + 2.5, 0.45))
        for u in cols_u:
            m.add("gold", pin(u, w, -1.6, t + P.UNO_PIN_H))


def female_header(m, us, w, t):
    m.add("yellow", cbox(min(us) - 1.27, max(us) + 1.27, w - 1.25, w + 1.25, t, t + 8.5, 0.2))
    for u in us:
        m.add("black", box(u - 0.45, u + 0.45, w - 0.45, w + 0.45, t + 8.49, t + 8.53))


def uno_model():
    m = Model()
    t = P.UNO_T
    board = outline_plate(rounded_outline(uno_outline(), 1.2), 0.0, t)
    for u, w in P.UNO_HOLES:
        board -= cyl("z", P.UNO_HOLE_D / 2, -1, t + 1, (u, w))
    m.add("uno_pcb", board)
    for u, w in P.UNO_HOLES:
        m.add("gold", ring(u, w, 2.9, P.UNO_HOLE_D / 2, t - 0.01, t + 0.04))

    # usb b socket and the power jack at the usb end
    w0, w1 = P.UNO_USB_W
    sock = cbox(-P.UNO_USB_OVERHANG, 10.0, w0, w1, t, t + P.UNO_USB_H, 0.25)
    wc = (w0 + w1) / 2
    zc = t + P.UNO_USB_H / 2
    face = [(wc - 4.2, zc - 3.9), (wc + 4.2, zc - 3.9), (wc + 4.2, zc + 2.6), (wc + 2.9, zc + 3.9),
            (wc - 2.9, zc + 3.9), (wc - 4.2, zc + 2.6)]
    pocket = extrude(Plane(origin=(-P.UNO_USB_OVERHANG - 0.5, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
                     * Polygon(*face, align=None), 10.0, dir=(1, 0, 0))
    m.add("metal", sock - pocket)
    m.add("black", box(-P.UNO_USB_OVERHANG + 0.8, 4.0, wc - 2.9, wc + 2.9, zc - 0.7, zc + 2.4),
          box(3.6, 4.0, wc - 4.2, wc + 4.2, zc - 3.9, zc + 3.9))
    d0, d1 = P.UNO_DC_W
    dc = cbox(-P.UNO_DC_OVERHANG, 12.0, d0, d1, t, t + P.UNO_DC_H, 0.35)
    dz = t + P.UNO_DC_H - (d1 - d0) / 2 - 0.4
    dc -= cyl("x", 3.15, -P.UNO_DC_OVERHANG - 1, 9.0, ((d0 + d1) / 2, dz))
    m.add("black", dc)
    m.add("metal", cyl("x", 1.0, -P.UNO_DC_OVERHANG + 1.5, 9.5, ((d0 + d1) / 2, dz)))

    # female headers along both long edges, yellow
    female_header(m, [18.8 + i * P.PITCH for i in range(10)], 51.45, t)
    female_header(m, [45.72 + i * P.PITCH for i in range(8)], 51.45, t)
    female_header(m, [31.3 + i * P.PITCH for i in range(6)], 1.95, t)
    female_header(m, [P.UNO_A0_U + 1.0 + i * P.PITCH for i in range(6)], 1.95, t)

    # the g v s blocks, analog A0 to A5 near the analog edge and D13 to D0 near the digital edge
    rows_a = list(zip(("g_row", "v_row", "s_row"), P.UNO_GVS_W))
    gvs_block(m, [uno_a_u(i) for i in range(UNO_A_COLS)], rows_a, t)
    rows_d = list(zip(("g_row", "v_row", "s_row"), P.UNO_DGVS_W))
    gvs_block(m, [uno_d_u(n) for n in range(UNO_D_COLS)], rows_d, t)
    # i2c header beside A5 and the serial header beside D0, single blue strips
    for u, ws in ((P.UNO_I2C_U, P.UNO_I2C_W), (UNO_SERIAL_U, UNO_SERIAL_W)):
        m.add("g_row", rbox(u - 1.17, u + 1.17, min(ws) - 1.2, max(ws) + 1.2, t, t + 2.5, 0.45))
        for w in ws:
            m.add("gold", pin(u, w, -1.6, t + P.UNO_PIN_H))
    # two icsp headers
    for us, ws in (((4.3, 6.84, 9.38), (47.5, 50.04)), ((61.2, 63.74), (23.0, 25.54, 28.08))):
        m.add("yellow", cbox(min(us) - 1.27, max(us) + 1.27, min(ws) - 1.27, max(ws) + 1.27, t, t + 2.5, 0.2))
        for u in us:
            for w in ws:
                m.add("gold", pin(u, w, -1.6, t + P.UNO_PIN_H))

    # the processor with its gull wing leads, the usb chip, the crystal
    m.add("chip", box(40.5, 47.5, 20.5, 27.5, t, t + 1.1))
    m.add("tin", *gull_leads(44.0, 24.0, 7.0, 0.8, 8, t, reach=1.0))
    m.add("chip", box(18.5, 23.5, 33.5, 38.5, t, t + 0.9))
    m.add("metal", rbox(54.6, 57.6, 23.0, 29.0, t, t + 1.2, 0.5))
    # the 3.3 and 5 v slide switch next to the usb socket, its knob on the 5 v side
    m.add("metal", box(11.5, 19.5, 29.2, 32.2, t, t + 1.6))
    m.add("white", box(12.4, 14.4, 30.0, 31.4, t + 1.6, t + 3.1))
    # regulator, the big coil of the power stage, two tantalum capacitors
    m.add("chip", box(4.3, 10.8, 14.2, 17.7, t, t + 1.6))
    m.add("tin", box(6.0, 9.0, 17.7, 19.3, t, t + 0.3))
    m.add("coil", rbox(12.4, 18.8, 17.6, 24.0, t, t + 3.0, 0.8))
    for w in (8.6, 13.3):
        m.add("tantal", rbox(19.4, 23.7, w, w + 4.0, t, t + 2.6, 0.2))
        m.add("brown", box(19.4, 20.4, w + 0.05, w + 3.95, t + 2.6, t + 2.65))
    # reset button near the far end
    m.add("metal", box(64.3, 67.8, 15.2, 21.2, t, t + 1.5))
    m.add("black", box(65.3, 66.8, 16.7, 19.7, t + 1.5, t + 2.4))
    # lights and a few small parts
    for w, col in ((46.2, "led_amber"), (44.4, "led_amber"), (42.6, "led_green")):
        m.add(col, box(23.8, 25.4, w - 0.4, w + 0.4, t, t + 0.6))
    m.add("led_amber", box(38.6, 40.2, 33.1, 33.9, t, t + 0.6))
    for u, w, a, b in UNO_SMALL:
        m.add("cap" if a > 1.7 else "chip", box(u - a / 2, u + a / 2, w - b / 2, w + b / 2, t, t + 0.6))
    return m


# small parts of the uno, centre and size, read off the photos
UNO_SMALL = [
    (5.0, 43.0, 1.6, 0.8), (5.0, 41.2, 1.6, 0.8), (5.0, 39.4, 1.6, 0.8), (13.0, 40.0, 0.8, 1.6), (15.0, 44.5, 1.6, 0.8),
    (26.5, 34.0, 1.6, 0.8), (26.5, 36.0, 1.6, 0.8), (33.0, 30.5, 2.0, 1.25), (36.0, 21.0, 0.8, 1.6),
    (37.6, 24.0, 0.8, 1.6), (50.0, 22.0, 1.6, 0.8), (50.0, 26.0, 1.6, 0.8), (52.6, 30.5, 2.0, 1.25),
    (59.0, 18.0, 1.6, 0.8), (27.0, 23.0, 2.0, 1.25), (27.0, 19.0, 2.0, 1.25), (9.0, 21.5, 2.0, 1.25),
    (9.0, 25.0, 2.0, 1.25), (3.0, 20.0, 0.8, 1.6), (34.0, 15.5, 1.6, 0.8),
]


def uno_pin(kind, index, row="S"):
    """top of a pin in the local frame of the uno: kind a (A0 to A5), d (D0 to D13), i2c (GND VCC SDA SCL)"""
    z = P.UNO_T + P.UNO_PIN_H
    if kind == "a":
        return (uno_a_u(index), P.UNO_GVS_W["GVS".index(row)], z)
    if kind == "d":
        return (uno_d_u(index), P.UNO_DGVS_W["GVS".index(row)], z)
    return (P.UNO_I2C_U, uno_i2c_w(index), z)


def uno_usb_port():
    """centre of the opening of the usb b socket, local frame of the uno"""
    return (-P.UNO_USB_OVERHANG, sum(P.UNO_USB_W) / 2, P.UNO_T + P.UNO_USB_H / 2)


# sg90 class servo in the frame of kit.servo_local: case bottom at z = 0, the spline on the z axis,
# the case runs toward minus x, the lead leaves the far end


def servo_model():
    m = Model()
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    w = P.SERVO_W / 2
    h = P.SERVO_H
    # the case in three shells with a fine groove between them
    case = rbox(far, near, -w, w, 0.0, h, 0.6)
    for z in (3.2, P.SERVO_TAB_Z):
        groove = box(far - 1, near + 1, -w - 1, w + 1, z - 0.15, z + 0.15)
        case -= groove - box(far + 0.3, near - 0.3, -w + 0.3, w - 0.3, z - 1, z + 1)
    # a shallow recess on both long sides that holds the label
    for s in (1, -1):
        case -= box(far + 2.0, near - 2.0, s * w - 0.2 if s > 0 else -w - 1, w + 1 if s > 0 else -w + 0.2, 5.0, 13.6)
        m.add("label", box(far + 2.0, near - 2.0, s * (w - 0.2) - 0.05, s * (w - 0.2) + 0.05, 5.0, 13.6))
    m.add("servo", case)
    # the mounting ears with their hole and slit
    for sgn, x0 in ((1, near), (-1, far)):
        x1 = x0 + sgn * P.SERVO_TAB_LEN
        tab = box(min(x0, x1) - (0.3 if sgn > 0 else 0), max(x0, x1) + (0.3 if sgn < 0 else 0), -w, w,
                  P.SERVO_TAB_Z, P.SERVO_TAB_Z + P.SERVO_TAB_T)
        hx = x0 + sgn * 2.3
        tab -= cyl("z", 1.0, P.SERVO_TAB_Z - 1, P.SERVO_TAB_Z + 3, (hx, 0.0))
        tab -= box(min(hx, x1) - (0 if sgn > 0 else 1), max(hx, x1) + (1 if sgn > 0 else 0), -0.5, 0.5,
                   P.SERVO_TAB_Z - 1, P.SERVO_TAB_Z + 3)
        m.add("servo", tab)
    # gear boss, the small bump beside it, the splined output with its screw hole
    m.add("servo", cyl("z", P.SERVO_BOSS_R, h - 0.01, P.SERVO_BOSS_TOP))
    m.add("servo", cyl("z", 2.8, h - 0.01, h + 1.6, (-7.6, 0.0)))
    teeth = 21
    r0, r1 = P.SERVO_SPLINE_D / 2 - 0.25, P.SERVO_SPLINE_D / 2
    pts = []
    for i in range(teeth * 2):
        a = math.pi * i / teeth
        r = r1 if i % 2 == 0 else r0
        pts.append((r * math.cos(a), r * math.sin(a)))
    spline = extrude(Plane.XY.offset(P.SERVO_BOSS_TOP - 0.01) * Polygon(*pts, align=None), P.SERVO_SPLINE_LEN)
    spline -= cyl("z", 0.9, P.SERVO_BOSS_TOP, P.SERVO_BOSS_TOP + P.SERVO_SPLINE_LEN + 1)
    m.add("white", spline)
    return m


def servo_lead_exit():
    """where the three wires leave the case, middle of the flat lead, and the way they leave"""
    return (P.SERVO_SHAFT_FROM_END - P.SERVO_L - 0.3, 0.0, P.SERVO_LEAD_Z), (-1.0, 0.0, 0.0)


# keyestudio light sensor module and the bh1750 module, frame of kit.module_local: sensor end at
# x = 0, header end at x = MOD_L, board underside at z = 0, parts on top


def module_model(kind="ldr"):
    m = Model()
    t = P.MOD_T
    board = rbox(0.0, P.MOD_L, -P.MOD_W / 2, P.MOD_W / 2, 0.0, t, 1.5)
    for y in (-P.MOD_HOLE_SPACING / 2, P.MOD_HOLE_SPACING / 2):
        board -= cyl("z", P.MOD_HOLE_D / 2, -1, t + 1, (P.MOD_HOLE_FROM_SENSOR_END, y))
        m.add("gold", ring(P.MOD_HOLE_FROM_SENSOR_END, y, 3.6, P.MOD_HOLE_D / 2, t - 0.01, t + 0.04))
    m.add("uno_pcb", board)
    pins = 3 if kind == "ldr" else 4
    ys = [(i - (pins - 1) / 2) * P.PITCH for i in range(pins)]
    # right angle header, the pins reach past the board edge where the plug goes on
    m.add("yellow", box(P.MOD_L - 2.5, P.MOD_L, min(ys) - 1.27, max(ys) + 1.27, t, t + 2.5))
    for y in ys:
        zc = t + 1.27
        m.add("gold", box(P.MOD_L - 1.6, P.MOD_L - 0.96, y - 0.32, y + 0.32, -1.4, zc + 0.32),
              box(P.MOD_L - 1.6, P.MOD_L + 6.0, y - 0.32, y + 0.32, zc - 0.32, zc + 0.32))
    if kind == "ldr":
        x = P.LDR_FROM_END
        m.add("tin", box(x - 1.6, x - 1.2, -0.2, 0.2, t, t + 0.6), box(x + 1.2, x + 1.6, -0.2, 0.2, t, t + 0.6))
        m.add("ldr", cyl("z", P.LDR_D / 2, t + 0.5, t + P.LDR_TOP))
        m.add("cap", box(13.0, 14.6, -2.6, -1.8, t, t + 0.5), box(15.6, 17.2, -2.6, -1.8, t, t + 0.5))
        m.add("chip", box(13.0, 14.6, 1.8, 2.6, t, t + 0.5))
    else:
        x, y = P.BH_CHIP_FROM_END, -P.BH_CHIP_SIDE
        m.add("chip", box(x - 1.5, x + 1.5, y - 0.8, y + 0.8, t, t + P.BH_CHIP_TOP))
        m.add("ldr", box(x - 0.6, x + 0.6, y - 0.5, y + 0.5, t + P.BH_CHIP_TOP - 0.02, t + P.BH_CHIP_TOP + 0.03))
        m.add("chip", box(4.0, 7.0, -5.0, -3.4, t, t + 1.1), box(4.0, 7.0, 3.4, 5.0, t, t + 1.1))
        m.add("cap", box(17.0, 18.6, -3.0, -2.2, t, t + 0.5), box(17.0, 18.6, 2.2, 3.0, t, t + 0.5))
    return m


def module_plug_origin():
    """mating face of the plug on the right angle pins, local frame of a module"""
    return (P.MOD_L + 0.1, 0.0, P.MOD_T + 1.27)


# placements in the device frame, the same as kit.py


def pi_placed():
    return pi_model().placed((P.PI_X0, P.PI_Y0, kit.pi_z0()), (0, 1, 0), (0, 0, 1))


def uno_placed():
    return uno_model().placed(kit.uno_origin(), (0, -1, 0), (0, 0, 1))


def frame_matrix(origin, x_dir, z_dir):
    """4x4 matrix of a local frame like kit.frame_map, for points and meshes"""
    x = np.asarray(x_dir, float) / np.linalg.norm(x_dir)
    z = np.asarray(z_dir, float) / np.linalg.norm(z_dir)
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, origin
    return m


def pi_matrix():
    return frame_matrix((P.PI_X0, P.PI_Y0, kit.pi_z0()), (0, 1, 0), (0, 0, 1))


def uno_matrix():
    return frame_matrix(kit.uno_origin(), (0, -1, 0), (0, 0, 1))


def apply(m, p):
    return tuple((np.asarray(m) @ np.array([p[0], p[1], p[2], 1.0]))[:3])


def vec(m, v):
    """a direction of a local frame in the frame m is placed in"""
    return tuple(np.asarray(m)[:3, :3] @ np.asarray(v, float))
