"""all renders that go into hardware/renders

the pictures use the filament colours of the printed tracker, the bought parts stay grey and the
orange marks what a step of the readme is about, marks.json keeps the pixel of a few points so
hardware/sheets.py can put a ring or a leader line on them
"""

import json
from pathlib import Path

import numpy as np

from . import assembly as A
from . import cables
from . import params as P
from .render import FILAMENT, KIT_COLORS, MODULE_COLOR, ORANGE, SENSOR_COLOR, camera, render

ROLE = FILAMENT
TARGET = (0.0, -12.0, 78.0)
CABLE = "#2e2e32"
# the pixel of each named point, per render, filled in while rendering
MARKS = {}


def kit_color(name):
    if name.startswith("face_"):
        return SENSOR_COLOR
    return MODULE_COLOR if name.startswith("module") else KIT_COLORS.get(name, "#5c5d62")


def scene_items(parts, pan, tilt, elec=None, ghost=None, skip=()):
    out = []
    for name, group, role, mesh in A.posed(parts, pan, tilt, elec):
        if name in skip:
            continue
        if role == "kit":
            if name == "panel":
                continue
            out.append((mesh, kit_color(name), 1.0, "kit"))
        else:
            op = ghost.get(name, 1.0) if ghost else 1.0
            out.append((mesh, ROLE[role], op, role))
    return out


def visible_kit(elec):
    """kit parts that show from outside, the sensors in their eyes"""
    from . import kit
    from .mesh import to_trimesh
    head = {k: m for k, m in elec["head"].items() if k.startswith("module")}
    for k, s in kit.sensor_faces().items():
        head[k] = to_trimesh(s)
    return {"base": {}, "neck": {}, "head": head}


def shot(name, out, items, cam, **kw):
    """render into out/name.png and keep the pixels of its marks"""
    path = Path(out) / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    px = render(items, path, cam, **kw)
    if px:
        MARKS[name] = px
    return path


def panel_centre(pan, tilt):
    return tuple(np.mean(A.panel_corners(pan, tilt), axis=0))


def product_views(parts, elec, out):
    shots = [
        ("front_three_quarter", 15, 35, camera(TARGET, 36, 22, 520)),
        ("rear_three_quarter", -20, 55, camera(TARGET, 215, 24, 470)),
        ("side", 0, 45, camera(TARGET, 90, 2, 520)),
        ("top", 0, 10, camera((0, -5, 60), 0, 89.5, 520, up=(0, 1, 0))),
        ("head_flat", 0, 90, camera(TARGET, 32, 22, 470)),
        ("head_over_the_top", 30, 155, camera(TARGET, 150, 22, 480)),
    ]
    written = []
    kit_vis = visible_kit(elec)
    # the notch for the power cable at the foot of the back wall
    notch = (6.0, -P.BASE_D / 2, P.TRAY_Z0 + 4.0)
    for name, pan, tilt, cam in shots:
        par = name in ("side", "top")
        loop = [(cables.loop_points(pan, tilt), CABLE, 2.6)]
        marks = {"notch": notch, "panel": panel_centre(pan, tilt)}
        written.append(shot(name, out, scene_items(parts, pan, tilt, kit_vis), cam,
                            panels=[A.panel_corners(pan, tilt)], parallel=par, zoom=1.0 if not par else 1.15,
                            lines=loop, marks=marks))
    return written


def exploded(parts, elec, out):
    """head laid flat on top, everything lifted along z in assembly order"""
    lift = {
        "foot": -34, "tray": 0, "pi": 0, "lid": 62, "uno": 62, "pan_horn": 48,
        "neck_front": 128, "neck_back": 128, "pan_servo": 128, "tilt_servo": 128,
        "ear_horn": 168, "ear_pivot": 168, "tilt_horn": 168, "cap": 168,
        "head_back": 196, "module": 222, "panel": 248, "head_bezel": 276,
    }
    side = {"neck_front": (0, 30, 0), "neck_back": (0, -30, 0), "ear_horn": (-26, 0, 0), "ear_pivot": (26, 0, 0),
            "tilt_horn": (-26, 0, 0), "cap": (-48, 0, 0), "cap_2": (48, 0, 0)}
    items = []
    for name, group, role, mesh in A.posed(parts, 0, 90, elec):
        key = name
        if name.startswith("foot"):
            key = "foot"
        if name.startswith("module"):
            key = "module"
        if name.startswith("cap"):
            key = "cap"
        dz = lift.get(key, 0)
        dx, dy, _ = side.get(name, (0, 0, 0))
        m = mesh.copy()
        m.apply_translation((dx, dy, dz))
        color = ROLE[role] if role != "kit" else kit_color(name)
        items.append((m, color, 1.0, role if role != "kit" else "kit"))
    c = (0, -10, 205)
    # the axis of the pan turret, the sheets draw it as a centre line through the stack
    lo = min(float(m.bounds[0][2]) for m, *_ in items)
    hi = max(float(m.bounds[1][2]) for m, *_ in items)
    marks = {"axis_lo": (P.TURRET_X, P.TURRET_Y, lo - 20), "axis_hi": (P.TURRET_X, P.TURRET_Y, hi + 20)}
    # the parts float apart here, a shadow of one on the next would only look like dirt
    return [shot("exploded", out, items, camera(c, 36, 14, 1120), size=(1000, 1430), floor=False, cast=False,
                 marks=marks)]


def usb_coil_points():
    """the spare usb cable wound around the two posts in the front bay, for the inside render"""
    from . import base, kit
    (x0, y0), (x1, y1) = base.coil_posts()
    z = P.FLOOR_TOP + 4.0
    pts = []
    r = 6.0 + 2.5
    for turn in range(3):
        zz = z + turn * 2.6
        for k in range(13):
            a = np.radians(90 + 180 * k / 12)
            pts.append((x0 + r * np.cos(a), y0 + r * np.sin(a), zz))
        for k in range(13):
            a = np.radians(-90 + 180 * k / 12)
            pts.append((x1 + r * np.cos(a), y1 + r * np.sin(a), zz + 1.3))
    ax, ay = kit.pi_to_device(P.PI_L + P.PI_PORT_OVERHANG + P.USB_A_PLUG[2], P.PI_USB_Y[0])
    bx, by = kit.uno_to_device(-P.UNO_USB_OVERHANG - P.USB_B_PLUG[2], sum(P.UNO_USB_W) / 2)
    bz = kit.uno_origin()[2] + P.UNO_T + P.USB_B_PLUG[1] / 2
    az = kit.pi_z0() + P.PI_T + 4.5
    return [(ax, ay, az), (ax + 6, ay + 4, az - 2)] + pts + [(bx - 4, by + 4, bz - 6), (bx, by, bz)]


def inside_views(parts, elec, out):
    written = []
    # the open base, the usb cable from the pi to the uno is the step, so it is orange
    skip = ("lid", "head_back", "head_bezel", "ear_horn", "ear_pivot", "cap", "cap_2", "neck_front", "neck_back",
            "pan_servo", "tilt_servo") + tuple(n for n in elec["head"])
    items = scene_items(parts, 0, 90, elec, skip=skip)
    coil = usb_coil_points()
    lines = [(coil, ORANGE, 2.0, "accent")]
    lines += [(cables.route_points(n, 0, 90)[:4], CABLE, 0.9) for n in ("L", "R", "U", "D", "lux")]
    written.append(shot("inside_base", out, items, camera((0, -5, 25), 25, 55, 420), lines=lines, lines_role="kit",
                        marks={"usb": tuple(coil[len(coil) // 2])}))
    # the back shell with its modules, seen from the front with the bezel off
    by = {p.name: p for p in parts}
    items = [(by["head_back"].mesh(), ROLE["dark"], 1.0, "dark")]
    for k, m in elec["head"].items():
        if k.startswith("module"):
            items.append((m, MODULE_COLOR, 1.0, "kit"))
    lines = [(cables.route_points(n, 0, 0)[-3:], CABLE, 1.1) for n in ("L", "R", "U", "D", "lux")]
    hc = (0.0, P.HEAD_BACK_Y, P.Z_TILT)
    written.append(shot("head_inside", out, items, camera(hc, 0, 8, 300), floor=False, lines=lines, lines_role="kit"))
    # the open neck, back half with both servos laid in, the servos are the step
    items = [(by["neck_back"].mesh(), ROLE["dark"], 1.0, "dark")]
    for k in ("pan_servo", "tilt_servo"):
        items.append((elec["neck"][k], ORANGE, 1.0, "accent"))
    nc = (0.0, P.TURRET_Y, 85.0)
    marks = {k: tuple(elec["neck"][k].bounds.mean(0)) for k in ("pan_servo", "tilt_servo")}
    written.append(shot("neck_open", out, items, camera(nc, 0, 10, 230), floor=False, marks=marks))
    return written


def cable_view(parts, elec, out):
    pan, tilt = 40, 25
    ghost = {p.name: 0.18 for p in parts}
    for p in parts:
        for i in range(len(p.instances)):
            ghost[f"{p.name}_{i + 2}"] = 0.18
    items = scene_items(parts, pan, tilt, elec, ghost=ghost)
    lines = [(cables.route_points(n, pan, tilt), ORANGE, 1.0, "accent") for n in ("L", "R", "U", "D", "lux")]
    # no floor, a see through part over the floor would lose to the paper put in for it
    return [shot("cables", out, items, camera(TARGET, 60, 18, 430), lines=lines, lines_role="kit", floor=False)]


def signature_view(parts, elec, out):
    """close up of the signature on the lid as a person in front of the tracker sees it"""
    from . import signature
    if not P.SIG_ON:
        return []
    b = signature.profile().bounds()
    tgt = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2 + 4.0, P.BASE_TOP)
    items = scene_items(parts, 0, 0, visible_kit(elec))
    return [shot("lid_signature", out, items, camera(tgt, 0, 50, 200), size=(1600, 1100), floor=False,
                 panels=[A.panel_corners(0, 0)])]


def first_layer_view(parts, out):
    """the lid on the plate seen from below, the face that prints first with the signature in it"""
    from .mesh import rot_matrix, transformed
    lid = next(p for p in parts if p.name == "lid")
    # turned over about y and seen from above, the same picture as from under the plate but lit
    mesh = transformed(lid.print_mesh(), rot_matrix((0, 1, 0), 180.0, (0, 0, 0)))
    cam = [(0.0, 0.0, 400.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    return [shot("print/lid_first_layer", out, [(mesh, ROLE[lid.role], 1.0, lid.role)], cam, size=(1200, 1200),
                 floor=False, parallel=True, zoom=1.0)]


def print_views(parts, out):
    """each part as it lies on the bed, here on the paper"""
    written = []
    for p in parts:
        mesh = p.print_mesh()
        ext = mesh.extents
        dist = max(160.0, 2.4 * float(max(ext)))
        tgt = (0.0, 0.0, float(ext[2]) / 2)
        written.append(shot(f"print/{p.name}", out, [(mesh, ROLE[p.role], 1.0, p.role)], camera(tgt, 30, 38, dist),
                            size=(1200, 900)))
    return written


def all_views(parts, elec, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    w = []
    w += product_views(parts, elec, out)
    w += exploded(parts, elec, out)
    w += inside_views(parts, elec, out)
    w += cable_view(parts, elec, out)
    w += signature_view(parts, elec, out)
    w += print_views(parts, out)
    w += first_layer_view(parts, out)
    (out / "marks.json").write_text(json.dumps(MARKS, indent=1) + "\n", encoding="utf-8")
    return w
