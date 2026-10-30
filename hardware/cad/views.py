"""all renders that go into hardware/renders"""

from pathlib import Path

import numpy as np
import trimesh

from . import assembly as A
from . import cables
from . import params as P
from .mesh import transformed
from .render import KIT_COLORS, MODULE_COLOR, camera, render

ROLE = {"body": P.COLORS["body"], "dark": P.COLORS["dark"], "accent": P.COLORS["accent"]}
TARGET = (0.0, -12.0, 78.0)


def kit_color(name):
    if name.startswith("face_"):
        return "#c8a46e" if name != "face_lux" else "#8a7a5a"
    return MODULE_COLOR if name.startswith("module") else KIT_COLORS.get(name, "#555560")


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


def product_views(parts, elec, out):
    shots = [
        ("front_three_quarter", 15, 35, camera(TARGET, 38, 20, 470)),
        ("rear_three_quarter", -20, 55, camera(TARGET, 215, 24, 470)),
        ("side", 0, 45, camera(TARGET, 90, 2, 520)),
        ("top", 0, 10, camera((0, -5, 60), 0, 89.5, 520, up=(0, 1, 0))),
        ("head_flat", 0, 90, camera(TARGET, 32, 22, 470)),
        ("head_over_the_top", 30, 155, camera(TARGET, 150, 22, 480)),
    ]
    written = []
    kit_vis = visible_kit(elec)
    for name, pan, tilt, cam in shots:
        path = Path(out) / f"{name}.png"
        par = name in ("side", "top")
        loop = [(cables.loop_points(pan, tilt), "#1e1e22", 2.6)]
        render(scene_items(parts, pan, tilt, kit_vis), path, cam, panels=[A.panel_corners(pan, tilt)], parallel=par,
               zoom=1.0 if not par else 1.15, lines=loop)
        written.append(path)
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
    path = Path(out) / "exploded.png"
    c = (0, -10, 205)
    render(items, path, camera(c, 36, 14, 1120), size=(1400, 2000), floor=False, center=c)
    return [path]


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
    ghost = {"lid": 0.14}
    skip = ("head_back", "head_bezel", "ear_horn", "ear_pivot", "cap", "cap_2", "neck_front", "neck_back",
            "pan_servo", "tilt_servo") + tuple(n for n in elec["head"])
    items = scene_items(parts, 0, 90, elec, ghost=ghost, skip=skip)
    lines = [(usb_coil_points(), "#3a3a40", 2.0)]
    lines += [(cables.route_points(n, 0, 90)[:4], c, 0.9) for n, c in
              (("L", "#e0b030"), ("R", "#e07a40"), ("U", "#7cc060"), ("D", "#5b9be0"), ("lux", "#b080e0"))]
    path = Path(out) / "inside_base.png"
    render(items, path, camera((0, -5, 25), 25, 55, 420), center=(0, 0, 30), lines=lines)
    written.append(path)
    # the back shell with its modules, seen from the front with the bezel off
    by = {p.name: p for p in parts}
    items = [(by["head_back"].mesh(), ROLE["dark"], 1.0, "dark")]
    for k, m in elec["head"].items():
        if k.startswith("module"):
            items.append((m, MODULE_COLOR if k != "module_lux" else "#3a3550", 1.0, "kit"))
    lines = [(cables.route_points(n, 0, 0)[-3:], c, 1.1) for n, c in
             (("L", "#c9a227"), ("R", "#c46a3a"), ("U", "#6aa84f"), ("D", "#5b8bd0"), ("lux", "#a070c0"))]
    path = Path(out) / "head_inside.png"
    hc = (0.0, P.HEAD_BACK_Y, P.Z_TILT)
    render(items, path, camera(hc, 0, 8, 300), floor=False, lines=lines, center=hc)
    written.append(path)
    # the open neck, back half with both servos laid in
    items = [(by["neck_back"].mesh(), ROLE["dark"], 1.0, "dark")]
    for k in ("pan_servo", "tilt_servo"):
        items.append((elec["neck"][k], kit_color(k), 1.0, "kit"))
    nc = (0.0, P.TURRET_Y, 85.0)
    path = Path(out) / "neck_open.png"
    render(items, path, camera(nc, 0, 10, 230), floor=False, center=nc)
    written.append(path)
    return written


def cable_view(parts, elec, out):
    pan, tilt = 40, 25
    ghost = {p.name: 0.18 for p in parts}
    for p in parts:
        for i in range(len(p.instances)):
            ghost[f"{p.name}_{i + 2}"] = 0.18
    items = scene_items(parts, pan, tilt, elec, ghost=ghost)
    colors = {"L": "#e0b030", "R": "#e07a40", "U": "#7cc060", "D": "#5b9be0", "lux": "#b080e0"}
    lines = [(cables.route_points(n, pan, tilt), c, 1.0) for n, c in colors.items()]
    path = Path(out) / "cables.png"
    render(items, path, camera(TARGET, 60, 18, 430), lines=lines)
    return [path]


def print_views(parts, out):
    written = []
    for p in parts:
        mesh = p.print_mesh()
        bed = trimesh.creation.box(extents=(180, 180, 1.0))
        bed.apply_translation((0, 0, -0.5))
        ext = mesh.extents
        dist = max(160.0, 2.4 * float(max(ext)))
        tgt = (0.0, 0.0, float(ext[2]) / 2)
        # a lighter plate under the charcoal parts so their shape reads
        bed_color = "#55555c" if p.role == "dark" else "#1c1c20"
        items = [(bed, bed_color, 1.0, "kit"), (mesh, ROLE[p.role], 1.0, p.role)]
        path = Path(out) / "print" / f"{p.name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        render(items, path, camera(tgt, 30, 38, dist), size=(1200, 900), floor=False, center=tgt)
        written.append(path)
    return written


def all_views(parts, elec, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    w = []
    w += product_views(parts, elec, out)
    w += exploded(parts, elec, out)
    w += inside_views(parts, elec, out)
    w += cable_view(parts, elec, out)
    w += print_views(parts, out)
    return w


_ = (np, transformed)
