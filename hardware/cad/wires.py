"""cables of the step pictures, swept along smooth curves, with the plugs at their ends

a cable is a path through a few points, the path is a centripetal catmull rom curve through
them, every wire is a tube swept along it, flat cables put their wires side by side and spread
them to the 2.54 grid where they enter a plug
only for the renders, the cable budget of the build stays in cables.py
"""

import math

import numpy as np
import trimesh
from build123d import Plane, Polygon, chamfer, loft

from .helpers import box
from .mesh import to_trimesh

PITCH = 2.54

# wire colours, calm versions of the real ones
WIRE = {
    "black": "#2c2c2f", "red": "#a54b42", "yellow": "#c8a64c", "brown": "#5c4031", "amber": "#d29a45",
    "blue": "#55708f", "green": "#5d8659", "usb": "#58718b", "power": "#2f2f33",
}
HOUSING = "#2a2a2d"
OVERMOLD = "#303034"
METAL = "#b4b7bb"

# the kit cables
JUMPER_R = 0.62  # 26 awg with its insulation
SERVO_R = 0.52
USB_R = 2.1
POWER_R = 1.7
DUPONT_L = 14.0  # housing from the header base to where the wires leave it


def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


# the curve


def catmull_rom(points, step=0.4):
    """centripetal catmull rom through every point, resampled so the points lie step mm apart"""
    p = np.asarray(points, float)
    keep = [0]
    for i in range(1, len(p)):
        if np.linalg.norm(p[i] - p[keep[-1]]) > 1e-6:
            keep.append(i)
    p = p[keep]
    if len(p) < 2:
        return p
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    dense = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-6) ** 0.5
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-6) ** 0.5
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-6) ** 0.5
        n = max(4, int(np.linalg.norm(p2 - p1) / (step / 2)))
        for t in np.linspace(t1, t2, n, endpoint=False):
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            dense.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    dense.append(p[-1])
    dense = np.asarray(dense)
    seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(s[-1] / step) + 1)
    at = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(at, s, dense[:, k]) for k in range(3)])


def arclength(path):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])


def tangents(path):
    t = np.gradient(path, axis=0)
    return t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)


def side_vectors(path, first, last=None):
    """a side vector at every point that turns as little as it can along the path, double
    reflection, and if last is given the twist is spread so the side ends there"""
    tan = tangents(path)
    s = np.empty_like(path)
    v = unit(np.asarray(first, float) - np.dot(first, tan[0]) * tan[0])
    s[0] = v
    for i in range(len(path) - 1):
        v1 = path[i + 1] - path[i]
        c1 = v1 @ v1
        if c1 < 1e-12:
            s[i + 1] = s[i]
            continue
        rl = s[i] - (2 / c1) * (v1 @ s[i]) * v1
        tl = tan[i] - (2 / c1) * (v1 @ tan[i]) * v1
        v2 = tan[i + 1] - tl
        c2 = v2 @ v2
        s[i + 1] = unit(rl - (2 / c2) * (v2 @ rl) * v2 if c2 > 1e-12 else rl)
    if last is not None:
        want = unit(np.asarray(last, float) - np.dot(last, tan[-1]) * tan[-1])
        b = np.cross(tan[-1], s[-1])
        ang = math.atan2(float(want @ b), float(want @ s[-1]))
        frac = arclength(path) / max(arclength(path)[-1], 1e-9)
        for i in range(len(path)):
            a = ang * frac[i]
            bi = np.cross(tan[i], s[i])
            s[i] = math.cos(a) * s[i] + math.sin(a) * bi
    return s


def tube(path, r, sides=14, caps=True):
    """a round tube along a resampled path, a trimesh"""
    path = np.asarray(path, float)
    tan = tangents(path)
    side = side_vectors(path, np.cross(tan[0], [0.0, 0.0, 1.0]) if abs(tan[0][2]) < 0.9 else [1.0, 0, 0])
    up = np.cross(tan, side)
    a = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    ring = np.cos(a)[None, :, None] * side[:, None, :] + np.sin(a)[None, :, None] * up[:, None, :]
    verts = (path[:, None, :] + r * ring).reshape(-1, 3)
    n = len(path)
    faces = []
    for i in range(n - 1):
        for j in range(sides):
            a0, a1 = i * sides + j, i * sides + (j + 1) % sides
            b0, b1 = a0 + sides, a1 + sides
            faces += [(a0, a1, b0), (a1, b1, b0)]
    if caps:
        c0, c1 = len(verts), len(verts) + 1
        verts = np.vstack([verts, path[0], path[-1]])
        for j in range(sides):
            faces.append((c0, (j + 1) % sides, j))
            last = (n - 1) * sides
            faces.append((c1, last + j, last + (j + 1) % sides))
    # the faces wind outward by construction, no repair needed
    return trimesh.Trimesh(verts, np.asarray(faces), process=False)


# a cable with its plugs


class End:
    """where a cable ends: origin on the mating face of its plug, x across the wires, z the way
    the wires leave the plug, kind dupont, servo, usb_a, usb_b or micro_usb"""

    def __init__(self, origin, x_dir, z_dir, kind="dupont", n=3):
        self.o = np.asarray(origin, float)
        self.x = unit(x_dir)
        self.z = unit(z_dir)
        self.kind = kind
        self.n = n

    def exit(self):
        return self.o + self.z * PLUG_LEN[self.kind]


PLUG_LEN = {"dupont": DUPONT_L, "servo": 14.5, "usb_a": 40.0, "usb_b": 40.0, "micro_usb": 24.0, "free": 0.0}


def route(a, mid, b=None, lead=6.0):
    """the centre line from the plug a through the mid points to the plug b (or to a free end),
    lead is the straight run out of the plugs, one value or one for each end"""
    la, lb = (lead, lead) if np.isscalar(lead) else lead
    pts = [a.exit(), a.exit() + a.z * la]
    pts += [np.asarray(p, float) for p in mid]
    if b is not None:
        pts += [b.exit() + b.z * lb, b.exit()]
    return catmull_rom(pts)


def spread_offsets(path, n, pitch, ends_spread):
    """offset of each wire across the cable along the path, 2.54 at a plug, pitch elsewhere"""
    s = arclength(path)
    total = s[-1]
    w = np.full(len(path), pitch)
    for at_start, on in zip((True, False), ends_spread):
        if not on:
            continue
        d = s if at_start else total - s
        k = np.clip(1 - (d - 3.0) / 14.0, 0, 1)
        k = k * k * (3 - 2 * k)
        w = w + (PITCH - pitch) * k * (w < PITCH + 1e-9)
    return [(i - (n - 1) / 2) * w for i in range(n)]


def pinned_sides(path, first, last, pins):
    """side vectors that turn as little as they can between the pinned ones, pins are
    (point, side) pairs, each holds at the point of the path nearest to it"""
    marks = [(0, first)]
    for pt, v in pins or ():
        i = int(np.argmin(np.linalg.norm(path - np.asarray(pt, float), axis=1)))
        if 0 < i < len(path) - 1:
            marks.append((i, v))
    marks.sort(key=lambda m: m[0])
    if last is not None:
        marks.append((len(path) - 1, last))
    side = np.empty_like(path)
    for (i0, v0), (i1, v1) in zip(marks, marks[1:] + [(len(path) - 1, None)]):
        if i1 <= i0:
            continue
        side[i0:i1 + 1] = side_vectors(path[i0:i1 + 1], v0, v1)
    return side


def flat_cable(a, mid, b, colours, r=JUMPER_R, pitch=None, sides=12, pins=None, lead=6.0):
    """wires side by side from plug a to plug b, a list of (mesh, colour), pins hold the flat
    side of the cable across the given direction at a few points, lead is the straight run out
    of each plug"""
    pitch = pitch or 2 * r + 0.08
    path = route(a, mid, b, lead)
    side = pinned_sides(path, a.x, b.x if b is not None else None, pins)
    offs = spread_offsets(path, len(colours), pitch, (a.kind in ("dupont", "servo"),
                                                       b is not None and b.kind in ("dupont", "servo")))
    out = []
    for i, c in enumerate(colours):
        wire = path + side * offs[i][:, None]
        out.append((tube(catmull_rom(wire, 0.4), r, sides), c))
    return out, path


def round_cable(a, mid, b, colour, r):
    path = route(a, mid, b)
    return [(tube(path, r, 18), colour)], path


# plugs, built in a local frame with the mating face at z = 0, the wires leave toward plus z,
# the wide side along x


def dupont_housing(n):
    w, d = n * PITCH - 0.06, PITCH - 0.06
    h = cbox(-w / 2, w / 2, -d / 2, d / 2, 0.0, DUPONT_L, 0.25)
    # the small window of the latch on one side and a groove between the positions
    h -= box(-w / 2 + 0.5, w / 2 - 0.5, d / 2 - 0.25, d / 2 + 1, 3.0, 7.0)
    for i in range(1, n):
        x = -w / 2 + i * PITCH
        h -= box(x - 0.15, x + 0.15, -d / 2 - 1, -d / 2 + 0.2, 0.5, DUPONT_L - 0.5)
    return h


def servo_housing():
    w, d = 3 * PITCH + 0.1, 2.9
    h = cbox(-w / 2, w / 2, -d / 2, d / 2, 0.0, 14.5, 0.3)
    # the ridge on the signal side that keys the plug
    h += box(w / 2 - 2.0, w / 2 - 0.6, d / 2 - 0.1, d / 2 + 0.5, 1.0, 13.0)
    return h


def usb_a_plug():
    metal = box(-6.0, 6.0, -2.25, 2.25, -11.5, 0.5) - box(-5.6, 5.6, -1.85, 1.85, -12.0, -2.0)
    mold = cbox(-8.0, 8.0, -4.0, 4.0, 0.0, 24.0, 1.2)
    relief = loft([Plane.XY.offset(24.0) * Polygon(*_rr(10.0, 6.0, 1.5), align=None),
                   Plane.XY.offset(40.0) * Polygon(*_rr(5.0, 5.0, 2.45), align=None)], ruled=False)
    return {"metal": metal, "mold": mold + relief}


def usb_b_plug():
    metal = box(-4.1, 4.1, -3.6, 3.6, -9.0, 0.5)
    mold = cbox(-6.25, 6.25, -5.5, 5.5, 0.0, 26.0, 1.2)
    relief = loft([Plane.XY.offset(26.0) * Polygon(*_rr(9.0, 8.0, 2.0), align=None),
                   Plane.XY.offset(40.0) * Polygon(*_rr(5.0, 5.0, 2.45), align=None)], ruled=False)
    return {"metal": metal, "mold": mold + relief}


def micro_usb_plug():
    metal = box(-3.45, 3.45, -0.9, 0.9, -6.0, 0.5)
    mold = cbox(-5.5, 5.5, -3.75, 3.75, 0.0, 14.0, 1.0)
    relief = loft([Plane.XY.offset(14.0) * Polygon(*_rr(7.0, 5.0, 1.8), align=None),
                   Plane.XY.offset(24.0) * Polygon(*_rr(3.8, 3.8, 1.85), align=None)], ruled=False)
    return {"metal": metal, "mold": mold + relief}


def _rr(w, h, r, n=6):
    pts = []
    for (sx, sy), a0 in zip([(1, 1), (-1, 1), (-1, -1), (1, -1)], [0, 90, 180, 270]):
        cx, cy = sx * (w / 2 - r), sy * (h / 2 - r)
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def cbox(x0, x1, y0, y1, z0, z1, c):
    b = box(x0, x1, y0, y1, z0, z1)
    c = min(c, (x1 - x0) / 2 - 0.01, (y1 - y0) / 2 - 0.01, (z1 - z0) / 2 - 0.01)
    return chamfer(b.edges(), c) if c > 0.02 else b


_CACHE = {}


def plug_meshes(kind, n=3):
    """trimeshes of a plug in its local frame, per material, built once"""
    key = (kind, n)
    if key not in _CACHE:
        if kind == "dupont":
            parts = {"housing": dupont_housing(n)}
        elif kind == "servo":
            parts = {"housing": servo_housing()}
        elif kind == "usb_a":
            parts = usb_a_plug()
        elif kind == "usb_b":
            parts = usb_b_plug()
        elif kind == "micro_usb":
            parts = micro_usb_plug()
        else:
            parts = {}
        _CACHE[key] = {k: to_trimesh(s, tol=0.02, ang=0.2) for k, s in parts.items()}
    return _CACHE[key]


def plug_items(end, accent=None):
    """the plug of an end placed in the device frame, accent paints the plastic of it"""
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = end.x, np.cross(end.z, end.x), end.z, end.o
    out = []
    for k, mesh in plug_meshes(end.kind, end.n).items():
        mm = mesh.copy()
        mm.apply_transform(m)
        if k == "metal":
            out.append((mm, METAL, 1.0, "metal", "plug"))
        else:
            plastic = HOUSING if k == "housing" else OVERMOLD
            out.append((mm, accent or plastic, 1.0, "accent" if accent else "kit", "plug"))
    return out


def tint(items, colour):
    """the same cable in one quiet colour, the metal of its plugs stays metal"""
    return [it if it[3] == "metal" else (it[0], colour, it[2], "kit") + tuple(it[4:]) for it in items]


def wire_items(wires, accent=None):
    """the fifth field names the item a wire, so a check can find the cables of a picture"""
    return [(m, accent or c, 1.0, "accent" if accent else "kit", "wire") for m, c in wires]


# the kinds of cable of the kit


def jumper(a, mid, b, colours=("black", "red", "yellow"), accent=None, plug_accent=None, pins=None, lead=6.0):
    """a dupont cable with one housing at each end, plug_accent paints only the housings"""
    wires, path = flat_cable(a, mid, b, [WIRE[c] for c in colours], JUMPER_R, pins=pins, lead=lead)
    items = wire_items(wires, accent)
    for e in (a, b):
        if e is not None and e.kind != "free":
            items += plug_items(e, accent or plug_accent)
    return items, path


def servo_lead(a, mid, b=None, accent=None, plug_accent=None, pins=None, lead=6.0):
    """the lead of a servo, a is the servo end where the wires leave the case, b the plug"""
    wires, path = flat_cable(a, mid, b, [WIRE[c] for c in ("brown", "red", "amber")], SERVO_R, pitch=1.06, pins=pins,
                             lead=lead)
    items = wire_items(wires, accent)
    if b is not None:
        items += plug_items(b, accent or plug_accent)
    return items, path


def usb_cable(a, mid, b, accent=None):
    wires, path = round_cable(a, mid, b, WIRE["usb"], USB_R)
    items = wire_items(wires, accent)
    for e in (a, b):
        if e is not None and e.kind != "free":
            items += plug_items(e, accent)
    return items, path


def power_cable(a, mid, b=None, accent=None):
    wires, path = round_cable(a, mid, b, WIRE["power"], POWER_R)
    return wire_items(wires, accent) + plug_items(a, accent), path

