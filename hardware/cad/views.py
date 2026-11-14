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
from .render import FILAMENT, KIT_COLORS, MODULE_COLOR, SENSOR_COLOR, camera, drawing, lamp_ray, render

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


def lamp_point(pan, tilt, dist=260.0):
    """a point straight out in front of the panel, where the lamp it turned to would stand"""
    c = np.asarray(A.panel_corners(pan, tilt))
    n = np.cross(c[3] - c[0], c[1] - c[0])
    return tuple(c.mean(0) + n / np.linalg.norm(n) * dist)


def product_views(parts, elec, out):
    shots = [
        ("front_three_quarter", 75, 45, camera(TARGET, 36, 22, 600)),
        ("rear_three_quarter", -20, 55, camera(TARGET, 215, 24, 580)),
        ("side", 0, 45, camera(TARGET, 90, 2, 520)),
        ("top", 0, 10, camera((0, -5, 60), 0, 89.5, 520, up=(0, 1, 0))),
        ("head_flat", 0, 90, camera(TARGET, 32, 22, 470)),
        ("head_over_the_top", 30, 155, camera(TARGET, 150, 22, 580)),
    ]
    written = []
    kit_vis = visible_kit(elec)
    # the notch for the power cable at the foot of the back wall
    notch = (6.0, -P.BASE_D / 2, P.TRAY_Z0 + 4.0)
    for name, pan, tilt, cam in shots:
        par = name in ("side", "top")
        loop = [(cables.loop_points(pan, tilt), CABLE, 2.6)]
        marks = {"notch": notch, "panel": panel_centre(pan, tilt), "lamp": lamp_point(pan, tilt)}
        written.append(shot(name, out, scene_items(parts, pan, tilt, kit_vis), cam,
                            panels=[A.panel_corners(pan, tilt)], parallel=par, zoom=1.0 if not par else 1.15,
                            lines=loop, marks=marks))
        if name == "front_three_quarter":
            # the picture at the top of the readme says what the tracker does, it faces a lamp
            lamp_ray(written[-1], MARKS[name]["lamp"], MARKS[name]["panel"], scale=1.2)
    return written


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


# the six plates of hardware/export/3mf, in the order of the files, laid out in three colours
PLATES = [["tray"], ["lid"], ["neck_front", "neck_back", "ear_horn", "ear_pivot", "foot"], ["head_back"],
          ["head_bezel"], ["cap"]]


def plates_view(parts, out):
    """every printed part as it comes off the printer, one group per plate, on the paper"""
    by = {p.name: p for p in parts}
    items = []
    # two rows of three plates, plate 1 at the far left, each in a cell of this size in mm,
    # the camera looks from the front so x runs to the left and the far row has the lower y
    cell = 190.0
    marks = {}
    for i, names in enumerate(PLATES):
        cx, cy = (1 - i % 3) * cell, (i // 3 - 0.5) * cell
        group = [(by[n].print_mesh(), by[n].role) for n in names for _ in range(by[n].count)]
        # small parts of one plate in rows that fit the cell
        rows, row, width = [], [], 0.0
        for m, role in group:
            wd = float(m.extents[0])
            if row and width + wd > cell * 0.85:
                rows.append(row)
                row, width = [], 0.0
            row.append((m, role))
            width += wd + 8.0
        rows.append(row)
        depth = [max(float(m.extents[1]) for m, _ in r) for r in rows]
        y = cy - (sum(depth) + 10.0 * (len(rows) - 1)) / 2
        for r, dep in zip(rows, depth):
            total = sum(float(m.extents[0]) for m, _ in r) + 8.0 * (len(r) - 1)
            x = cx + total / 2
            for m, role in r:
                m = m.copy()
                lo, hi = m.bounds
                # placed from right to left, so the order reads left to right from the camera
                m.apply_translation((x - hi[0], y + dep / 2 - (lo[1] + hi[1]) / 2, -lo[2]))
                items.append((m, ROLE[role], 1.0, role))
                x -= float(m.extents[0]) + 8.0
            y += dep + 10.0
        # the balloon with the plate number sits just in front of the plate
        marks[f"plate_{i + 1}"] = (cx, y + 8.0, 0.0)
    return [shot("print/plates", out, items, camera((0.0, 10.0, 0.0), 0, 58, 860), size=(1600, 1100), marks=marks)]


def twin_view(parts, out):
    """the tracker as a line drawing, for the page of the pi on the sheets, turned to a lamp on the left"""
    pan, tilt = 70, 20
    path = Path(out) / "page_twin.png"
    # the engraving on the lid is too fine for the pen at this size, it stays a light texture
    quiet = None
    if P.SIG_ON:
        from . import signature
        x0, y0, x1, y1 = signature.profile().bounds()
        quiet = (x0 - 2, y0 - 2, x1 + 2, y1 + 2, P.BASE_TOP - P.SIG_DEPTH - 0.5)
    MARKS["page_twin"] = drawing(scene_items(parts, pan, tilt), path, camera(TARGET, 45, 15, 520), size=(1000, 750),
                                 panels=[A.panel_corners(pan, tilt)], quiet=quiet,
                                 marks={"panel": panel_centre(pan, tilt), "lamp": lamp_point(pan, tilt)})
    return [path]


def all_views(parts, elec, out, only=None):
    """every render into out, or with only just the named ones: a group below or a step picture
    like steps/usb, marks.json keeps the marks of the renders not made this time"""
    from . import steps
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    groups = {
        "product_views": lambda: product_views(parts, elec, out),
        "signature_view": lambda: signature_view(parts, elec, out),
        "print_views": lambda: print_views(parts, out),
        "plates_view": lambda: plates_view(parts, out),
        "twin_view": lambda: twin_view(parts, out),
        "first_layer_view": lambda: first_layer_view(parts, out),
        "steps": lambda: steps.all_steps(parts, elec, out),
    }
    w = []
    for name, make in groups.items():
        if only is None or name in only:
            w += make()
    if only is not None:
        w += steps.all_steps(parts, elec, out, [n for n in only if n in steps.RENDERS])
    f = out / "marks.json"
    marks = json.loads(f.read_text(encoding="utf-8")) if only is not None and f.exists() else {}
    marks.update(MARKS)
    f.write_text(json.dumps(marks, indent=1) + "\n", encoding="utf-8")
    return w
