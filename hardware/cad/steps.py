"""the renders of the build steps in the readme, from the wiring on the table to the closed base

each picture shows one thing: where a board goes, where a cable is plugged in and how it runs,
or which part goes on next with which screws, the boards and cables come from kit_detail.py
and wires.py, the printed parts from assembly.py, the thing a step is about is orange
the screw letters are the ones of docs/drawings.pdf
"""

import numpy as np
import trimesh

from . import assembly as A
from . import base as B
from . import kit
from . import kit_detail as KD
from . import params as P
from . import wires as W
from .mesh import to_trimesh, transformed
from .render import ORANGE, camera
from .views import ROLE, shot

STEP_SIZE = (1000, 750)
GREY = "#7d7f84"  # cables that are already in place and not the subject of a step


def printed(parts, names, pan=0.0, tilt=0.0, colour=None, opacity=1.0, move=None):
    """render items of printed parts by name at a pose, colour paints them the orange of a step"""
    by = {p.name: p for p in parts}
    out = []
    for n in names:
        p = by[n]
        m = A.group_matrix(p.group, pan, tilt)
        if move is not None:
            m = move @ m
        for pm in p.placed_meshes():
            out.append((transformed(pm, m), colour or ROLE[p.role], opacity, "accent" if colour else p.role))
    return out


def shift(v):
    m = np.eye(4)
    m[:3, 3] = v
    return m


def cut(items, origin, normal):
    """items cut by a plane, the side the normal points to stays, the cut faces closed"""
    import manifold3d as mf
    n = np.asarray(normal, float) / np.linalg.norm(normal)
    out = []
    for it in items:
        m = it[0]
        mesh = mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32))
        solid = mf.Manifold(mesh)
        kept = solid.trim_by_plane(tuple(n), float(n @ np.asarray(origin, float))).to_mesh()
        if len(kept.tri_verts):
            back = trimesh.Trimesh(np.asarray(kept.vert_properties)[:, :3], np.asarray(kept.tri_verts))
            out.append((back,) + tuple(it[1:]))
    return out


def servo_matrix(which, pan=0.0, tilt=0.0):
    o, x, z = kit.pan_servo_frame() if which == "pan" else kit.tilt_servo_frame()
    return A.group_matrix("neck", pan, tilt) @ KD.frame_matrix(o, x, z)


def servo_items(which, pan=0.0, tilt=0.0, move=None, colour=None):
    m = servo_matrix(which, pan, tilt)
    return KD.items(KD.servo_meshes(), m if move is None else move @ m, colour)


def module_matrix(name, pan=0.0, tilt=0.0):
    s, i = kit.sensor_layout()[name]
    o, x, z = kit.module_placement(s, i, "bh" if name == "lux" else "ldr")
    return A.group_matrix("head", pan, tilt) @ KD.frame_matrix(o, x, z)


def screws(letter, out, colour=ORANGE, move=None, only=None):
    """the screws of one letter of docs/drawings.pdf pulled out of their holes by out mm"""
    from .drawings import screw_groups
    g = next(s for s in screw_groups() if s.letter == letter)
    items = []
    for s in g.solids(out, only=only):
        m = to_trimesh(s)
        if move is not None:
            m.apply_transform(move)
        items.append((m, colour, 1.0, "accent", "screw"))
    return items, g


# on the table, before anything is built


def table_layout():
    """the pi and the uno lying side by side on the table, the ports toward the front"""
    m_pi = KD.frame_matrix((0.0, 0.0, 1.45), (0, 1, 0), (0, 0, 1))
    m_uno = KD.frame_matrix((34.0, 80.0, 1.65), (0, -1, 0), (0, 0, 1))
    return m_pi, m_uno


def usb_ends(m_pi, m_uno):
    """the usb a plug in the lower port next to the ethernet jack and the b plug in the uno"""
    a = W.End(KD.apply(m_pi, KD.pi_usb_port(upper=False, pair=0)), KD.vec(m_pi, (0, 1, 0)),
              KD.vec(m_pi, (1, 0, 0)), "usb_a")
    b = W.End(KD.apply(m_uno, KD.uno_usb_port()), KD.vec(m_uno, (0, 1, 0)), KD.vec(m_uno, (-1, 0, 0)), "usb_b")
    return a, b


def power_end(m_pi):
    return W.End(KD.apply(m_pi, KD.pi_power_port()), KD.vec(m_pi, (1, 0, 0)), KD.vec(m_pi, (0, -1, 0)), "micro_usb")


def table_usb(out):
    """step: the usb cable from the lower port of the pi, next to the ethernet jack, to the uno"""
    m_pi, m_uno = table_layout()
    items = KD.items(KD.pi_meshes(), m_pi) + KD.items(KD.uno_meshes(), m_uno)
    a, b = usb_ends(m_pi, m_uno)
    r = W.USB_R
    cable, _ = W.usb_cable(a, [(-27, 140, r + 1.5), (-10, 162, r), (30, 170, r), (66, 152, r + 1.0)], b, accent=ORANGE)
    items += cable
    pw = power_end(m_pi)
    rp = W.POWER_R
    power, _ = W.power_cable(pw, [(36, 4, rp + 0.5), (32, -14, rp), (14, -60, rp), (0, -200, rp), (-20, -420, rp)])
    items += power
    marks = {"port": KD.apply(m_pi, (P.PI_L + 6.0, P.PI_USB_Y[0], 8.0)),
             "switch": KD.apply(m_uno, (13.4, 30.7, P.UNO_T + 3.0))}
    return [shot("steps/usb", out, items, camera((22.0, 78.0, 0.0), 28, 40, 330), size=STEP_SIZE, marks=marks)]


def uno_on_table():
    return KD.frame_matrix((0.0, 0.0, 1.65), (1, 0, 0), (0, 0, 1))


def gvs_end(m, u, rows, x_sign, kind="dupont", n=3):
    """a plug standing on a g v s column, x runs from the g pin toward the s pin"""
    t = P.UNO_T
    w_mid = sum(rows) / len(rows)
    x = KD.vec(m, (0, x_sign, 0))
    return W.End(KD.apply(m, (u, w_mid, t + 2.5)), x, KD.vec(m, (0, 0, 1)), kind, n)


def nested_arcs(us, w_mid, top, toward, r_inner, edge_u, fan, r_wire, far=60.0):
    """mid points of flat cables that leave plugs side by side along u, rise and bend over toward
    plus u (toward 1) or minus u (toward -1) on one common centre, so they nest without touching,
    then drop past the board edge at edge_u and fan out on the table, one list per cable"""
    order = sorted(range(len(us)), key=lambda i: us[i] * toward)
    inner = us[order[-1]]
    c = inner + toward * r_inner
    out = [None] * len(us)
    for rank, i in enumerate(order[::-1]):
        r = abs(c - us[i])
        pts = []
        for a in np.radians([25, 50, 70, 90]):
            pts.append((c - toward * r * np.cos(a), w_mid, top + 3.0 + r * np.sin(a)))
        h = top + 3.0 + r
        e = edge_u + toward * (4.0 + 2.5 * rank)
        pts += [(e, w_mid + fan[i] * 0.4, h - 2.0), (e + toward * 9.0, w_mid + fan[i] * 0.8, r_wire + 3.0),
                (e + toward * 22.0, w_mid + fan[i], r_wire), (e + toward * far, w_mid + fan[i] * 2.0, r_wire)]
        out[i] = pts
    return out


def table_sensors(out):
    """step: the four light sensor cables on A0 to A3, the black wire on G"""
    m = uno_on_table()
    items = KD.items(KD.uno_meshes(), m)
    marks = {}
    top = P.UNO_T + 2.5 + W.DUPONT_L
    us = [KD.uno_a_u(i) for i in range(4)]
    w_mid = P.UNO_GVS_W[1]
    routes = nested_arcs(us, w_mid, top, 1, 7.0, P.UNO_L, [-9.0, -3.0, 3.0, 9.0], W.JUMPER_R)
    for i, u in enumerate(us):
        a = gvs_end(m, u, P.UNO_GVS_W, -1)
        cable, _ = W.jumper(a, [KD.apply(m, p) for p in routes[i]], None, plug_accent=ORANGE)
        items += cable
        marks[f"A{i}"] = KD.apply(m, (u, w_mid, top))
    # the rows where the three wires of the A0 plug leave it
    for row, w in zip("GVS", P.UNO_GVS_W):
        marks[row] = KD.apply(m, (us[0], w, top + 1.0))
    cam = camera(KD.apply(m, (58.0, 6.0, 14.0)), 212, 44, 115)
    return [shot("steps/analog", out, items, cam, size=STEP_SIZE, marks=marks)]


def table_servos(out):
    """step: the pan servo on 9 and the tilt servo on 10, brown on G"""
    m = uno_on_table()
    items = KD.items(KD.uno_meshes(), m)
    top = P.UNO_T + 2.5 + 14.5
    us = [KD.uno_d_u(9), KD.uno_d_u(10)]
    w_mid = P.UNO_DGVS_W[1]
    routes = nested_arcs(us, w_mid, top, -1, 7.0, 0.0, [5.0, -5.0], W.SERVO_R, far=50.0)
    marks = {}
    for k, (n, u) in enumerate(zip((9, 10), us)):
        b = gvs_end(m, u, P.UNO_DGVS_W, 1, "servo")
        pts = [KD.apply(m, p) for p in routes[k]]
        # the lead comes from its servo, here it starts out of the picture on the table
        start = W.End(pts[-1], KD.vec(m, (0, 1, 0)), KD.vec(m, (1, 0, 0)), "free")
        cable, _ = W.servo_lead(start, pts[-2::-1], b, plug_accent=ORANGE)
        items += cable
        marks[str(n)] = KD.apply(m, (u, w_mid, top))
    marks["brown"] = KD.apply(m, (us[0], P.UNO_DGVS_W[0], top + 2.5))
    cam = camera(KD.apply(m, (24.0, 44.0, 16.0)), 38, 42, 110)
    return [shot("steps/digital", out, items, cam, size=STEP_SIZE, marks=marks)]


def table_lux(out):
    """step: the bh1750 on the i2c header at the far end, GND VCC SDA SCL as printed on the board"""
    m = uno_on_table()
    items = KD.items(KD.uno_meshes(), m)
    top = P.UNO_T + 2.5 + W.DUPONT_L
    w_mid = sum(P.UNO_I2C_W) / 4
    a = W.End(KD.apply(m, (P.UNO_I2C_U, w_mid, P.UNO_T + 2.5)), KD.vec(m, (0, -1, 0)), KD.vec(m, (0, 0, 1)),
              "dupont", 4)
    route = nested_arcs([P.UNO_I2C_U], w_mid, top, 1, 6.0, P.UNO_L, [-4.0], W.JUMPER_R)[0]
    cable, _ = W.jumper(a, [KD.apply(m, p) for p in route], None, ("black", "red", "blue", "green"), plug_accent=ORANGE)
    items += cable
    # each name on the wire that leaves the plug above its pin
    marks = {name: KD.apply(m, (P.UNO_I2C_U, KD.uno_i2c_w(name), top + 1.0)) for name in KD.UNO_I2C_NAMES}
    marks["plug"] = KD.apply(m, (P.UNO_I2C_U, w_mid, top))
    cam = camera(KD.apply(m, (64.0, 10.0, 14.0)), 232, 38, 105)
    return [shot("steps/i2c", out, items, cam, size=STEP_SIZE, marks=marks)]


# the tray, the pi on its pins with its two cables


def tray_power_cable(accent=None):
    """the power cable from the micro usb plug along the floor and out through the notch"""
    pw = power_end(KD.pi_matrix())
    rp = W.POWER_R
    z = P.FLOOR_TOP + rp
    zt = P.TRAY_Z0 + rp
    nx = B.power_notch_x()
    back = -P.BASE_D / 2
    # outside it turns along the back wall and leaves past the corner of the tray
    mid = [(15.0, -54.0, 9.5), (12.0, -62.0, z), (nx + 1.0, -70.0, z), (nx, back + 2.0, z), (nx, back - 3.0, z),
           (nx - 3.0, back - 8.0, zt + 1.0), (nx - 14.0, back - 11.0, zt), (-60.0, back - 13.0, zt),
           (-110.0, back - 18.0, zt), (-300.0, back - 30.0, zt)]
    return W.power_cable(pw, mid, accent=accent)


def coil_points():
    """two turns of the usb cable round the posts in the front bay, clockwise seen from above"""
    (x0, y0), (x1, y1) = B.coil_posts()
    rc = 6.0 + W.USB_R + 0.4
    z0, pitch = P.FLOOR_TOP + W.USB_R + 0.3, 4.4
    pts = []
    for turn in range(2):
        for k in range(9):
            a = np.radians(90 - 180 * k / 8)
            pts.append((x1 + rc * np.cos(a), y1 + rc * np.sin(a), 0))
        for k in range(9):
            a = np.radians(-90 - 180 * k / 8)
            pts.append((x0 + rc * np.cos(a), y0 + rc * np.sin(a), 0))
    pts = np.asarray(pts, float)
    pts[:, 2] = z0 + pitch * np.linspace(0.12, 2.0, len(pts))
    return [tuple(p) for p in pts]


def tray_usb_cable(b_end=None, accent=None, after=None):
    """the usb cable from the lower port next to the ethernet jack, two turns round the posts,
    then either to b_end or loose on the floor of the front bay"""
    m = KD.pi_matrix()
    a = W.End(KD.apply(m, KD.pi_usb_port(upper=False, pair=0)), KD.vec(m, (0, 1, 0)), KD.vec(m, (1, 0, 0)), "usb_a")
    (x0, y0), _ = B.coil_posts()
    ax = a.o[0]
    lead = [(ax + 1.0, 71.5, 13.5), (ax + 7.0, 72.5, 11.0), (x0 - 10.0, 67.0, 8.5)]
    coil = coil_points()
    loose = [(-10.0, 61.5, 20.0), (14.0, 64.5, 18.5), (32.0, 66.0, 13.0), (46.0, 63.0, 8.5), (54.0, 50.0, 7.6)]
    tail = after if after is not None else loose
    if b_end is None:
        b_end = W.End((55.0, -10.0, P.FLOOR_TOP + 5.5), (1, 0, 0), (0, 1, 0), "usb_b")
    return W.usb_cable(a, lead + coil + tail, b_end, accent=accent)


def tray_power(parts, out):
    """step: the pi onto its four pins, the power cable along the floor and out through the notch"""
    items = printed(parts, ["tray"]) + KD.items(KD.pi_meshes(), KD.pi_matrix())
    cable, _ = tray_power_cable(ORANGE)
    items += cable
    nx = B.power_notch_x()
    marks = {"notch": (nx, -P.BASE_D / 2 + P.WALL, P.TRAY_Z0 + 7.0),
             "plug": KD.apply(KD.pi_matrix(), (14.0, -14.0, 6.0))}
    cam = camera((-2.0, -22.0, 8.0), 24, 56, 370)
    return [shot("steps/tray_power", out, items, cam, size=STEP_SIZE, marks=marks)]


def tray_usb(parts, out):
    """step: the usb cable into the lower port next to the ethernet jack, two turns round the posts"""
    items = printed(parts, ["tray"]) + KD.items(KD.pi_meshes(), KD.pi_matrix())
    items += tray_power_cable()[0]
    cable, _ = tray_usb_cable(accent=ORANGE)
    items += cable
    marks = {"port": KD.apply(KD.pi_matrix(), (P.PI_L + 8.0, P.PI_USB_Y[0], 9.0))}
    cam = camera((-8.0, 16.0, 8.0), 16, 62, 350)
    return [shot("steps/tray_usb", out, items, cam, size=STEP_SIZE, marks=marks)]


# the neck, every cable runs up the column on the right of both servos

# where each cable runs: through the exit in the foot floor, up the column against the back wall,
# out through the slot in the top, the flat side of each cable in brackets
EXIT = {"L": (8.9, -34.6), "R": (10.05, -34.6), "U": (11.2, -34.6), "D": (12.35, -34.6),
        "lux": (9.0, -29.3), "pan": (10.35, -29.3), "tilt": (11.6, -29.3)}
COLUMN = {"L": (10.4, -43.6), "R": (14.6, -43.6), "U": (10.4, -42.25), "D": (14.6, -42.25), "lux": (13.6, -40.9),
          "pan": (10.6, -38.6), "tilt": (13.0, -28.6)}
TOP = {"L": (8.6, -34.9), "R": (12.6, -34.9), "U": (8.6, -33.6), "D": (12.6, -33.6), "lux": (11.0, -32.6)}
SENSORS = ("L", "R", "U", "D", "lux")


def neck_up(name):
    """control points of a sensor cable from the foot floor to above the top, pan 0, and the
    points where its flat side is held"""
    ex, ey = EXIT[name]
    cx, cy = COLUMN[name]
    tx, ty = TOP[name]
    z0 = P.BASE_TOP + P.FOOT_FLOOR_T
    # out of the exit the cables turn to the back wall at once, under the tab of the pan servo
    pts = [(ex, ey, z0 + 0.5), (ex, ey, z0 + 2.4), (ex * 0.5 + cx * 0.5, cy + 2.2, z0 + 5.4), (cx, cy + 0.4, z0 + 8.5)]
    pts += [(cx, cy, z) for z in (66.0, 74.0, 82.0, 92.0, 101.0)]
    pts += [(tx * 0.5 + cx * 0.5, ty * 0.3 + cy * 0.7, 108.5), (tx, ty - 3.0, 114.5), (tx, ty, 119.5),
            (tx, ty, P.NECK_TOP + 3.0)]
    pins = [((ex, ey, z0), (0, 1, 0)), ((cx, cy, 80.0), (1, 0, 0)), ((tx, ty, P.NECK_TOP), (1, 0, 0))]
    return pts, pins


def lead_down(which):
    """control points of a servo lead from where it leaves its servo down to the foot floor"""
    cx, cy = COLUMN[which]
    ex, ey = EXIT[which]
    z0 = P.BASE_TOP + P.FOOT_FLOOR_T
    # both leads leave their servo at the spline end on the case bottom side, the pan lead goes
    # straight through the wall into the column, the tilt lead comes out of the top of its servo,
    # runs over to the column under the top wall and down its front side, both stay flat
    a = lead_start(which)
    x0, y0, z1 = a.o
    if which == "pan":
        pts = [(x0 + 1.8, y0, z1), (cx - 0.4, y0 - 1.0, z1 - 1.2), (cx, cy + 0.6, z1 - 4.0), (cx, cy, 66.0)]
    else:
        pts = [(x0, y0, z1 + 2.1), (x0 + 2.5, y0, z1 + 3.3), (x0 + 7.0, y0, z1 + 3.1), (cx, cy, z1 + 0.3),
               (cx, cy, 100.0), (cx, cy, 80.0), (cx, cy, 66.0)]
    pts += [(cx, cy + 0.4, z0 + 8.5), (ex * 0.5 + cx * 0.5, cy + 2.2, z0 + 5.4), (ex, ey, z0 + 2.4), (ex, ey, z0 + 0.5)]
    pins = [((cx, cy, 66.0), (0, 1, 0)), ((ex, ey, z0), (0, 1, 0))]
    return pts, pins


def lead_start(which, pan=0.0, tilt=0.0):
    """the end of a servo lead at the case, as a free end, the side across the three wires"""
    m = servo_matrix(which, pan, tilt)
    o, d = KD.servo_lead_exit()
    return W.End(KD.apply(m, o), KD.vec(m, (0, 1, 0)), KD.vec(m, d), "free")


def apply_all(m, pts):
    return [KD.apply(m, p) for p in pts]


def neck_cables(parts, out):
    """step: both servos in the back half, every cable up the column, 20 mm hang out below"""
    items = printed(parts, ["neck_back"])
    items += servo_items("pan") + servo_items("tilt")
    z0 = P.BASE_TOP + P.FOOT_FLOOR_T
    side = P.TURRET_Y - 4.0
    # out of the top the cables fall over the right side, the plugs hang beside the neck
    hang = {"L": (34.0, 74.0), "R": (40.0, 66.0), "U": (46.0, 80.0), "D": (52.0, 70.0), "lux": (59.0, 62.0)}
    for name in SENSORS:
        pts, pins = neck_up(name)
        n = 4 if name == "lux" else 3
        ex, ey = EXIT[name]
        tx, ty = TOP[name]
        hx, hz = hang[name]
        a = hanging(name, 20.0 - P.FOOT_FLOOR_T)
        pts = [(ex, ey, P.BASE_TOP - 6.0)] + pts
        b = W.End((hx, side, hz), (0, 1, 0), (0, 0, 1), "dupont", n)
        up = [(tx + 3.0, ty - 1.5, P.NECK_TOP + 7.0), (hx * 0.45 + tx * 0.55, side - 2.0, P.NECK_TOP + 11.0),
              (hx - 1.0, side - 1.0, P.NECK_TOP - 2.0), (hx, side, hz + W.DUPONT_L + 22.0)]
        colours = ("black", "red", "blue", "green") if n == 4 else ("black", "red", "yellow")
        cable, _ = W.jumper(a, pts + up, b, colours, accent=ORANGE, pins=pins)
        items += cable
    for which, px in (("pan", -6.0), ("tilt", 6.0)):
        pts, pins = lead_down(which)
        b = W.End((px, P.TURRET_Y - 1.0, z0 - 50.0), (1, 0, 0), (0, 0, 1), "servo")
        tail = [(px + 4.0, P.TURRET_Y - 1.0, z0 - 22.0)]
        cable, _ = W.servo_lead(lead_start(which), pts + tail, b, accent=ORANGE, pins=pins, lead=(1.0, 6.0))
        items += cable
    marks = {"below": (12.0, P.TURRET_Y, z0 - 9.0), "column": (14.0, -42.0, 90.0)}
    cam = camera((12.0, P.TURRET_Y, 64.0), 16, 6, 280)
    return [shot("steps/neck_cables", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


# the loose plugs below the neck hang a little apart
HANG_DX = {"L": -7.0, "R": -2.5, "U": 2.0, "D": 6.5, "lux": 11.5}


def hanging(name, n_drop=20.0):
    """a loose plug hanging below the foot of the standing neck"""
    ex, ey = EXIT[name]
    n = 4 if name == "lux" else 3
    return W.End((ex + HANG_DX[name], ey, P.BASE_TOP - n_drop - W.DUPONT_L), (0, 1, 0), (0, 0, 1), "dupont", n)


def neck_close(parts, out):
    """step: the front half on, both halves held by two screws B from below the foot"""
    items = printed(parts, ["neck_front", "neck_back"])
    items += servo_items("pan") + servo_items("tilt")
    for name in SENSORS:
        pts, pins = neck_up(name)
        ex, ey = EXIT[name]
        tx, ty = TOP[name]
        a = hanging(name, 20.0 + {"L": 0.0, "R": 6.0, "U": 2.0, "D": 9.0, "lux": 4.0}[name])
        pts = [(ex, ey, P.BASE_TOP - 6.0)] + pts
        # out of the top the cables fall over to the back of the neck
        back = P.TURRET_Y - P.NECK_D / 2
        up = [(tx, ty - 6.0, P.NECK_TOP + 9.0), (tx, ty - 16.0, P.NECK_TOP + 12.0), (tx, back - 6.0, P.NECK_TOP - 6.0),
              (tx, back - 7.0, P.NECK_TOP - 40.0)]
        colours = ("black", "red", "blue", "green") if name == "lux" else ("black", "red", "yellow")
        cable, _ = W.jumper(a, pts + up, None, colours, pins=pins)
        items += W.tint(cable, GREY)
    for which in ("pan", "tilt"):
        pts, pins = lead_down(which)
        ex, ey = EXIT[which]
        end = W.End((ex, ey, P.BASE_TOP - 70.0), (0, 1, 0), (0, 0, 1), "free")
        cable, _ = W.servo_lead(lead_start(which), pts + [(ex, ey, P.BASE_TOP - 20.0)], end, pins=pins, lead=(1.0, 6.0))
        items += W.tint(cable, GREY)
    sc, g = screws("B", 14.0)
    items += sc
    marks = {"B": tuple(np.asarray(g.places[1][0]) - (0, 0, 14.0 + 3.0))}
    for i, (h, d) in enumerate(g.places):
        marks[f"hole_{i}"] = tuple(h)
        marks[f"tip_{i}"] = tuple(np.asarray(h) - np.asarray(d) * (14.0 + 9.0))
    cam = camera((4.0, P.TURRET_Y, 64.0), 32, 12, 225)
    return [shot("steps/neck_close", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


# the cables in the built tracker, from the uno under the lid up the neck into the head

A_PINS = {"L": 0, "R": 1, "U": 2, "D": 3}
SERVO_PIN = {"pan": 9, "tilt": 10}


def uno_end(name):
    """the plug of a cable on the uno hanging under the lid"""
    m = KD.uno_matrix()
    if name in A_PINS:
        return gvs_end(m, KD.uno_a_u(A_PINS[name]), P.UNO_GVS_W, -1)
    if name == "lux":
        w = sum(P.UNO_I2C_W) / 4
        return W.End(KD.apply(m, (P.UNO_I2C_U, w, P.UNO_T + 2.5)), KD.vec(m, (0, -1, 0)), KD.vec(m, (0, 0, 1)),
                     "dupont", 4)
    return gvs_end(m, KD.uno_d_u(SERVO_PIN[name]), P.UNO_DGVS_W, 1, "servo")


def under_lid(name):
    """from the top of the plug on the uno, below the lid and the horn, to the slot and the exit"""
    e = uno_end(name)
    top = e.exit()
    ex, ey = EXIT[name]
    z = P.LID_BOTTOM
    if name in SERVO_PIN:
        pts = [(top[0] - 4.0, top[1] - 4.0, z - 2.8), (top[0] * 0.45 + ex * 0.55, top[1] * 0.45 + ey * 0.55, z - 2.6),
               (ex + 1.0, ey + 0.5, z - 2.2)]
    else:
        pts = [(top[0] + 2.5, top[1] * 0.7 + ey * 0.3, z - 3.4), (ex - 2.0, ey, z - 1.8)]
    return pts + [(ex, ey, z + 0.5), (ex, ey, P.BASE_TOP + 0.5)]


def head_point(u, v, n, tilt):
    return KD.apply(A.group_matrix("head", 0.0, tilt), kit.head_xyz(u, v, n))


# where each cable passes the slot in the back of the head, and its way on the floor to its module
HEAD_SLOT = {"L": (-4.5, 1.6), "R": (4.5, 1.6), "U": (-1.2, 1.0), "D": (1.2, -1.0), "lux": (5.5, -1.4)}


def module_end(name, tilt):
    m = module_matrix(name, 0.0, tilt)
    return W.End(KD.apply(m, KD.module_plug_origin()), KD.vec(m, (0, 1, 0)), KD.vec(m, (1, 0, 0)), "dupont",
                 4 if name == "lux" else 3)


def into_head(name, tilt):
    """from above the neck top into the slot in the back of the head and along its floor, and
    where the cable lies flat on that floor"""
    tx, ty = TOP[name]
    su, sv = HEAD_SLOT[name]
    n = P.BACK_T + W.JUMPER_R + 0.3
    floor = [(su, sv)]
    if name == "L":
        floor += [(-12.0, 1.0), (-20.0, 0.5)]
    elif name == "R":
        floor += [(12.0, 1.0), (20.0, 0.5)]
    elif name == "lux":
        floor += [(16.0, 0.5), (24.0, 12.0), (25.5, 24.0)]
    pts = [(tx, ty, P.NECK_TOP + 4.5), head_point(su, sv, -3.0, tilt), head_point(su, sv, 1.0, tilt)]
    # the cable rises again where it nears the plug, which sits on the module above the floor
    lift = [0.8] + [0.4] * (len(floor) - 2) + [2.0] if len(floor) > 1 else [1.6]
    pts += [head_point(u, v, n + h, tilt) for (u, v), h in zip(floor, lift)]
    if name in ("U", "D"):
        pts.append(head_point(0.0, 4.6 if name == "U" else -4.6, n + 3.0, tilt))
    # flat on the floor, the side of the cable across its way in the plane of the floor
    m = A.group_matrix("head", 0.0, tilt)
    normal = np.asarray(KD.vec(m, (0, 1, 0)))
    pins = []
    for (u0, v0), (u1, v1) in zip(floor, floor[1:]):
        d = np.asarray(KD.vec(m, (u1 - u0, 0, v1 - v0)))
        pins.append((head_point(u0, v0, n, tilt), tuple(np.cross(normal, d))))
    if len(floor) == 1:
        pins.append((head_point(su, sv, n, tilt), KD.vec(m, (1, 0, 0))))
    return pts, pins


def sensor_route(name, tilt=None, accent=None, colours=None):
    """a light sensor cable or the bh1750 cable from the uno to its module, or with tilt None loose
    out of the top of the neck, falling over the back"""
    pts, pins = neck_up(name)
    a = uno_end(name)
    mid = under_lid(name) + pts
    if tilt is None:
        tx, ty = TOP[name]
        back = P.TURRET_Y - P.NECK_D / 2
        mid += [(tx, ty - 6.0, P.NECK_TOP + 9.0), (tx, ty - 16.0, P.NECK_TOP + 12.0),
                (tx, back - 6.0, P.NECK_TOP - 6.0), (tx, back - 7.0, P.NECK_TOP - 40.0)]
        b = None
    else:
        more, floor_pins = into_head(name, tilt)
        mid += more
        b = module_end(name, tilt)
        pins = pins + floor_pins
    pins = [((a.o[0], a.o[1], P.LID_BOTTOM), (0, 1, 0))] + pins
    colours = colours or (("black", "red", "blue", "green") if name == "lux" else ("black", "red", "yellow"))
    return W.jumper(a, mid, b, colours, accent=accent, pins=pins, lead=(2.0, 3.0))


def servo_route(which, accent=None):
    """a servo lead from its servo down the neck, through the slot to its pin on the uno"""
    pts, pins = lead_down(which)
    b = uno_end(which)
    mid = pts + under_lid(which)[::-1]
    pins = pins + [((b.o[0], b.o[1], P.LID_BOTTOM), (1, 0, 0))]
    return W.servo_lead(lead_start(which), mid, b, accent=accent, pins=pins, lead=(1.0, 2.0))


def usb_tail(lift=0.0):
    """the usb cable from the last turn round the posts up to the uno, lift raises the lid"""
    return [(-14.0, 60.5, 20.5), (4.0, 63.0, 23.0 + lift * 0.3), (20.0, 68.0, 25.0 + lift * 0.7),
            (27.0, 72.0, 27.0 + lift)]


def uno_b_end(lift=0.0):
    m = shift((0, 0, lift)) @ KD.uno_matrix()
    return W.End(KD.apply(m, KD.uno_usb_port()), KD.vec(m, (0, 1, 0)), KD.vec(m, (-1, 0, 0)), "usb_b")


def horn_mesh(frame):
    o, x, z = frame
    return to_trimesh(kit.frame_map(kit.horn_local(screw=False), o, x, z))


def lid_neck(parts, out):
    """step: the horn into its pocket under the lid, the neck on top, the horn screw G from below,
    cut through the turret axis"""
    keep = ((0.0, P.TURRET_Y, 0.0), (0.0, -1.0, 0.0))
    items = cut(printed(parts, ["lid"]), *keep)
    items += printed(parts, ["neck_back"]) + servo_items("pan") + servo_items("tilt")
    items.append((horn_mesh(kit.pan_horn_frame()), ORANGE, 1.0, "accent"))
    out_g = 12.0
    sc, g = screws("G", out_g, only=[0])
    items += sc
    for name in SENSORS:
        pts, pins = neck_up(name)
        ex, ey = EXIT[name]
        tx, ty = TOP[name]
        drop = 14.0 + (3.0 if name in ("R", "D") else 0.0)
        a = W.End((ex + HANG_DX[name] + 4.0, ey, P.LID_BOTTOM - drop - W.DUPONT_L),
                  (0, 1, 0), (0, 0, 1), "dupont", 4 if name == "lux" else 3)
        mid = [(ex, ey, P.LID_BOTTOM - 5.0), (ex, ey, P.LID_BOTTOM + 0.5), (ex, ey, P.BASE_TOP + 0.5)] + pts
        mid += [(tx, ty - 6.0, P.NECK_TOP + 9.0), (tx, ty - 16.0, P.NECK_TOP + 12.0),
                (tx, P.TURRET_Y - P.NECK_D / 2 - 6.0, P.NECK_TOP - 6.0)]
        cable, _ = W.jumper(a, mid, None, pins=pins)
        items += W.tint(cable, GREY)
    for which in ("pan", "tilt"):
        pts, pins = lead_down(which)
        ex, ey = EXIT[which]
        end = W.End((ex + 9.0, ey, P.LID_BOTTOM - 34.0), (0, 1, 0), (0, 0, 1), "free")
        mid = pts + [(ex, ey, P.BASE_TOP + 0.5), (ex, ey, P.LID_BOTTOM + 0.5), (ex + 1.0, ey, P.LID_BOTTOM - 12.0)]
        cable, _ = W.servo_lead(lead_start(which), mid, end, pins=pins, lead=(1.0, 6.0))
        items += W.tint(cable, GREY)
    h, d = g.places[0]
    marks = {"G": tuple(np.asarray(h) - np.asarray(d) * (out_g + 1.5)),
             "horn": (-9.0, P.TURRET_Y + 2.0, kit.pan_horn_frame()[0][2] - 0.8)}
    cam = camera((0.0, P.TURRET_Y, 46.0), 18, 10, 125)
    return [shot("steps/lid_neck", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


def uno_cables(parts, out):
    """step: every cable onto the uno under the lid, the lid and the neck seen through"""
    ghost = 0.16
    # the engraving on the lid would only show as noise through the ghost, the top of the plate goes
    lid = cut(printed(parts, ["lid"], opacity=ghost), (0.0, 0.0, P.BASE_TOP - 1.2), (0.0, 0.0, -1.0))
    items = lid + printed(parts, ["neck_front", "neck_back"], opacity=ghost)
    items += servo_items("pan") + servo_items("tilt")
    items += KD.items(KD.uno_meshes(), KD.uno_matrix())
    items.append((horn_mesh(kit.pan_horn_frame()), "#e4e1da", ghost, "kit"))
    for name in SENSORS:
        items += sensor_route(name, None, accent=ORANGE)[0]
    for which in ("pan", "tilt"):
        items += servo_route(which, accent=ORANGE)[0]
    # the usb cable comes up from its turns round the posts in the tray, out of the picture here
    b = uno_b_end()
    free = W.End((b.o[0] - 6.0, 70.0, -40.0), (1, 0, 0), (0, 0, 1), "free")
    items += W.usb_cable(free, [(b.o[0] - 4.0, 72.0, 6.0), (b.o[0] - 1.0, 73.0, 22.0)], b, accent=ORANGE)[0]
    m = KD.uno_matrix()
    top = P.UNO_T + 2.5 + W.DUPONT_L
    marks = {"A0 to A3": KD.apply(m, (KD.uno_a_u(1.5), P.UNO_GVS_W[1], top)),
             "SDA SCL": KD.apply(m, (P.UNO_I2C_U, sum(P.UNO_I2C_W) / 4, top)),
             "9 10": KD.apply(m, (KD.uno_d_u(9.5), P.UNO_DGVS_W[1], top + 0.5)),
             "USB": KD.apply(m, (-P.UNO_USB_OVERHANG - 20.0, sum(P.UNO_USB_W) / 2, P.UNO_T + 5.5))}
    for i, (u, w) in enumerate(P.UNO_HOLES):
        if i in P.UNO_USED_HOLES:
            marks[f"E{i}"] = KD.apply(m, (u, w, 0.0))
    cam = camera((14.0, -14.0, 36.0), 36, 52, 235)
    return [shot("steps/uno_cables", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


def turret(parts, tilt=90.0, ears=True):
    """the lid with the neck on it and the two ears, as built so far"""
    items = printed(parts, ["lid", "neck_front", "neck_back"], tilt=tilt)
    if ears:
        items += printed(parts, ["ear_horn", "ear_pivot"], tilt=tilt)
    return items


def loose_tops():
    """the cable ends out of the top of the neck before the head goes on, fallen over its back"""
    items = []
    back = P.TURRET_Y - P.NECK_D / 2
    for name in SENSORS:
        tx, ty = TOP[name]
        a = W.End((tx, ty, P.NECK_TOP - 10.0), (1, 0, 0), (0, 0, 1), "free")
        n = 4 if name == "lux" else 3
        lean = {"L": -7.0, "R": -2.0, "U": 3.0, "D": 8.0, "lux": 13.0}[name]
        drop = {"L": 30.0, "R": 22.0, "U": 34.0, "D": 26.0, "lux": 18.0}[name]
        b = W.End((tx + lean, back - 5.0, P.NECK_TOP - drop - W.DUPONT_L), (1, 0, 0), (0, 0, 1), "dupont", n)
        mid = [(tx, ty, P.NECK_TOP + 2.0), (tx + 0.3 * lean, ty - 7.0, P.NECK_TOP + 8.0),
               (tx + 0.7 * lean, back - 3.0, P.NECK_TOP + 3.0)]
        colours = ("black", "red", "blue", "green") if n == 4 else ("black", "red", "yellow")
        cable, _ = W.jumper(a, mid, b, colours, lead=(1.0, 4.0))
        items += W.tint(cable, GREY)
    return items


def ears_on(parts, out):
    """step: the left ear with the horn over the spline, screw G, the right ear with the pivot
    screw F, both standing straight up"""
    tilt = 90.0
    items = turret(parts, tilt, ears=False)
    sl, sr = -24.0, 24.0
    items += printed(parts, ["ear_horn"], tilt=tilt, colour=ORANGE, move=shift((sl, 0, 0)))
    items += printed(parts, ["ear_pivot"], tilt=tilt, colour=ORANGE, move=shift((sr, 0, 0)))
    horn = horn_mesh(kit.tilt_horn_frame())
    horn.apply_transform(shift((sl, 0, 0)) @ A.group_matrix("head", 0.0, tilt))
    items.append((horn, "#e4e1da", 1.0, "kit"))
    out_g, out_f = 14.0, 16.0
    sg, g = screws("G", out_g, only=[1], move=shift((sl, 0, 0)))
    sf, f = screws("F", out_f, move=shift((sr, 0, 0)))
    items += sg + sf + loose_tops()
    hg, dg = g.places[1]
    hf, df = f.places[0]
    marks = {"G": tuple(np.asarray(hg) - np.asarray(dg) * (out_g + 1.0) + (sl, 0, 0)),
             "F": tuple(np.asarray(hf) - np.asarray(df) * (out_f + 1.0) + (sr, 0, 0))}
    cam = camera((0.0, P.TURRET_Y, 104.0), 12, 16, 250)
    return [shot("steps/ears", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


def head_back_on(parts, out):
    """step: the cables through the slot of the back shell, the shell on the ear ends, four C"""
    tilt = 90.0
    lift = 34.0
    items = turret(parts, tilt)
    items += printed(parts, ["head_back"], tilt=tilt, move=shift((0, 0, lift)))
    out_c = 12.0
    sc, c = screws("C", out_c, move=shift((0, 0, lift)) @ A.group_matrix("head", 0.0, tilt))
    items += sc
    for name in SENSORS:
        tx, ty = TOP[name]
        su, sv = HEAD_SLOT[name]
        a = W.End((tx, ty, P.NECK_TOP - 10.0), (1, 0, 0), (0, 0, 1), "free")
        n = 4 if name == "lux" else 3
        s0 = np.asarray(head_point(su, sv, -3.0, tilt)) + (0, 0, lift)
        s1 = np.asarray(head_point(su, sv, 6.0, tilt)) + (0, 0, lift)
        lean = {"L": -1.0, "R": 1.0, "U": -0.4, "D": 0.4, "lux": 1.4}[name]
        b = W.End(s1 + (lean * 9.0, -2.0, 34.0), (1, 0, 0), (-lean * 0.25, 0.05, -1.0), "dupont", n)
        mid = [(tx, ty, P.NECK_TOP + 2.0), tuple(s0 - (0, 0, 8.0)), tuple(s0), tuple(s1)]
        colours = ("black", "red", "blue", "green") if n == 4 else ("black", "red", "yellow")
        cable, _ = W.jumper(a, mid, b, colours, lead=(1.0, 3.0))
        items += W.tint(cable, GREY)
    marks = {}
    m = shift((0, 0, lift)) @ A.group_matrix("head", 0.0, tilt)
    for i, (h, d) in enumerate(c.places):
        marks[f"C{i}"] = KD.apply(m, tuple(np.asarray(h) - np.asarray(d) * (out_c + 1.0)))
    cam = camera((0.0, P.TURRET_Y, 128.0), 24, 26, 360)
    return [shot("steps/head_back", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


def head_items(parts, tilt, modules=True, cables_colour=None):
    """the back shell on the ears with the modules on their pegs and the cables plugged in"""
    items = turret(parts, tilt) + printed(parts, ["head_back"], tilt=tilt)
    if modules:
        for name in SENSORS:
            kind = "bh" if name == "lux" else "ldr"
            items += KD.items(KD.module_meshes(kind), module_matrix(name, 0.0, tilt))
    return items


def modules_on(parts, out):
    """step: each light sensor on its two pegs, its cable plugged on G to G, the bh1750 in the corner"""
    tilt = 90.0
    items = head_items(parts, tilt)
    marks = {}
    for name in SENSORS:
        items += sensor_route(name, tilt, accent=ORANGE)[0]
        s, _ = kit.sensor_layout()[name]
        marks[name] = head_point(s[0], s[1], P.PCB_TOP_N, tilt)
    cam = camera((0.0, P.TURRET_Y, 132.0), 180, 62, 330)
    return [shot("steps/modules", out, items, cam, size=STEP_SIZE, floor=False, marks=marks)]


def panel_mesh(tilt, move=None):
    m = to_trimesh(kit.panel())
    m.apply_transform(A.group_matrix("head", 0.0, tilt) if move is None else move @ A.group_matrix("head", 0.0, tilt))
    return m


def bezel_on(parts, out):
    """step: the panel into the bezel, eight screws D from behind"""
    tilt = 90.0
    items = head_items(parts, tilt)
    for name in SENSORS:
        items += W.tint(sensor_route(name, tilt)[0], GREY)
    up_p, up_b = 22.0, 44.0
    items.append((panel_mesh(tilt, shift((0, 0, up_p))), "#141a2a", 1.0, "panel"))
    corners = [tuple(np.asarray(c) + (0, 0, up_p)) for c in A.panel_corners(0.0, tilt)]
    items += printed(parts, ["head_bezel"], tilt=tilt, colour=ORANGE, move=shift((0, 0, up_b)))
    out_d = 12.0
    sd, d = screws("D", out_d, move=A.group_matrix("head", 0.0, tilt))
    items += sd
    m = A.group_matrix("head", 0.0, tilt)
    h, dd = d.places[2]
    marks = {"D": KD.apply(m, tuple(np.asarray(h) - np.asarray(dd) * (out_d + 1.0)))}
    cam = camera((0.0, P.TURRET_Y, 132.0), 34, 16, 420)
    return [shot("steps/bezel", out, items, cam, size=STEP_SIZE, floor=False, panels=[corners], marks=marks)]


def base_close(parts, out):
    """step: the lid with everything on it onto the tray, the four feet with screws A from below and
    the two caps into the ear hubs"""
    tilt = 90.0
    lift = 36.0
    up = shift((0, 0, lift))
    items = printed(parts, ["tray"]) + KD.items(KD.pi_meshes(), KD.pi_matrix())
    items += W.tint(tray_power_cable()[0], GREY)
    items += W.tint(tray_usb_cable(uno_b_end(lift), after=usb_tail(lift))[0], GREY)
    top = printed(parts, ["lid", "neck_front", "neck_back", "ear_horn", "ear_pivot", "head_back", "head_bezel"],
                  tilt=tilt, move=up)
    # the two caps just before they are pressed into the ear hubs
    caps = printed(parts, ["cap"], tilt=tilt)
    for it, side in zip(caps, (-1, 1)):
        it[0].apply_transform(up @ shift((side * 9.0, 0, 0)))
    top += caps
    top += KD.items(KD.uno_meshes(), up @ KD.uno_matrix())
    for name in SENSORS:
        top += [(transformed(it[0], up),) + tuple(it[1:]) for it in W.tint(sensor_route(name, tilt)[0], GREY)]
    for which in ("pan", "tilt"):
        top += [(transformed(it[0], up),) + tuple(it[1:]) for it in W.tint(servo_route(which)[0], GREY)]
    items += top
    items.append((panel_mesh(tilt, up), "#141a2a", 1.0, "panel"))
    corners = [tuple(np.asarray(c) + (0, 0, lift)) for c in A.panel_corners(0.0, tilt)]
    down = -14.0
    items += printed(parts, ["foot"], colour=ORANGE, move=shift((0, 0, down)))
    out_a = 12.0
    sa, a = screws("A", out_a, move=shift((0, 0, down)))
    items += sa
    h, d = a.places[2]
    marks = {"A": tuple(np.asarray(h) - np.asarray(d) * (out_a + 1.0) + (0, 0, down)),
             "cap": tuple(np.mean(caps[1][0].bounds, axis=0))}
    cam = camera((0.0, -8.0, 62.0), 34, 8, 560)
    return [shot("steps/base", out, items, cam, size=STEP_SIZE, floor=False, panels=[corners], marks=marks)]


RENDERS = {
    "steps/usb": lambda parts, elec, out: table_usb(out),
    "steps/tray_power": lambda parts, elec, out: tray_power(parts, out),
    "steps/tray_usb": lambda parts, elec, out: tray_usb(parts, out),
    "steps/neck_cables": lambda parts, elec, out: neck_cables(parts, out),
    "steps/neck_close": lambda parts, elec, out: neck_close(parts, out),
    "steps/lid_neck": lambda parts, elec, out: lid_neck(parts, out),
    "steps/uno_cables": lambda parts, elec, out: uno_cables(parts, out),
    "steps/ears": lambda parts, elec, out: ears_on(parts, out),
    "steps/head_back": lambda parts, elec, out: head_back_on(parts, out),
    "steps/modules": lambda parts, elec, out: modules_on(parts, out),
    "steps/bezel": lambda parts, elec, out: bezel_on(parts, out),
    "steps/base": lambda parts, elec, out: base_close(parts, out),
    "steps/analog": lambda parts, elec, out: table_sensors(out),
    "steps/digital": lambda parts, elec, out: table_servos(out),
    "steps/i2c": lambda parts, elec, out: table_lux(out),
}


def all_steps(parts, elec, out, only=None):
    written = []
    for name, f in RENDERS.items():
        if only is None or name in only:
            written += f(parts, elec, out)
    return written

