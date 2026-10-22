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


def product_views(parts, out):
    shots = [
        ("front_three_quarter", 15, 35, camera(TARGET, 38, 20, 470)),
        ("rear_three_quarter", -20, 55, camera(TARGET, 215, 24, 470)),
        ("side", 0, 45, camera(TARGET, 90, 2, 520)),
        ("top", 25, 30, camera((0, -5, 60), 0, 89.5, 520, up=(0, 1, 0))),
        ("head_flat", 0, 90, camera(TARGET, 32, 22, 470)),
        ("head_over_the_top", 30, 155, camera(TARGET, 40, 20, 480)),
    ]
    written = []
    for name, pan, tilt, cam in shots:
        path = Path(out) / f"{name}.png"
        par = name in ("side", "top")
        render(scene_items(parts, pan, tilt), path, cam, panels=[A.panel_corners(pan, tilt)], parallel=par,
               zoom=1.0 if not par else 1.15)
        written.append(path)
    return written


def exploded(parts, elec, out):
    offs = {
        "foot": (0, 0, -28), "tray": (0, 0, 0), "lid": (0, 0, 70),
        "neck_front": (0, 34, 130), "neck_back": (0, -34, 130),
        "head_back": (0, 30, 205), "head_bezel": (0, 95, 205),
        "ear_horn": (-40, 0, 205), "ear_pivot": (40, 0, 205), "cap": (-62, 0, 205),
        "pi": (0, 0, 0), "uno": (0, 0, 70), "pan_horn": (0, 0, 50), "pan_servo": (0, 0, 130),
        "tilt_servo": (0, 0, 130), "tilt_horn": (-40, 0, 205), "panel": (0, 62, 205),
    }
    items = []
    for name, group, role, mesh in A.posed(parts, 0, 0, elec):
        base = name.split("_")[0] if name.startswith("foot") else name
        key = base
        if name.startswith("cap_"):
            key = "cap_r"
        if name.startswith("module"):
            key = "module"
        o = offs.get(key)
        if key == "cap_r":
            o = (62, 0, 205)
        if key == "module":
            o = (0, 46, 205)
        if name.startswith("foot_"):
            o = offs["foot"]
        if o is None:
            o = (0, 0, 0)
        m = mesh.copy()
        m.apply_translation(o)
        color = ROLE[role] if role != "kit" else kit_color(name)
        items.append((m, color, 1.0, role if role != "kit" else "kit"))
    path = Path(out) / "exploded.png"
    render(items, path, camera((0, 10, 150), 42, 16, 900), size=(1600, 1800), floor=False,
           center=(0, 10, 150))
    return [path]


def inside_views(parts, elec, out):
    written = []
    ghost = {"lid": 0.12, "neck_front": 0.25, "neck_back": 0.25}
    items = scene_items(parts, 0, 90, elec, ghost=ghost,
                        skip=("head_back", "head_bezel", "ear_horn", "ear_pivot", "cap", "cap_2",
                              "tilt_horn") + tuple(n for n in elec["head"]))
    path = Path(out) / "inside_base.png"
    render(items, path, camera((0, -5, 25), 25, 52, 420), center=(0, 0, 30))
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
        items = [(bed, "#1c1c20", 1.0, "kit"), (mesh, ROLE[p.role], 1.0, p.role)]
        path = Path(out) / "print" / f"{p.name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        render(items, path, camera(tgt, 30, 38, dist), size=(1200, 900), floor=False, center=tgt)
        written.append(path)
    return written


def all_views(parts, elec, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    w = []
    w += product_views(parts, out)
    w += exploded(parts, elec, out)
    w += inside_views(parts, elec, out)
    w += cable_view(parts, elec, out)
    w += print_views(parts, out)
    return w


_ = (np, transformed)
