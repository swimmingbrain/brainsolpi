"""STL, STEP, 3MF and the web files for the twin, assembly.json and one glb per group"""

import json
import struct
from pathlib import Path

import numpy as np
import pyvista as pv
from build123d import Compound, Location, Mesher, Plane, export_step

from . import base, kit
from . import params as P
from .assembly import PAN_ORIGIN, TILT_ORIGIN
from .mesh import to_trimesh, transformed

STEP_STAMP = "2026-01-01T00:00:00"  # fixed so a rebuild without changes gives the same files
GLB_LIMIT = 400_000  # one file
GLB_LIMIT_BASE = 600_000  # the base file, the letters on the lid take about 150 kB more
GLB_TOTAL_LIMIT = 1_500_000  # all four files, what a visitor of the page downloads
WEB_SIG_TOL = 0.05  # outline tolerance of the lid signature in the web model, mm
LF = chr(10)  # write unix line ends on windows too, the repo keeps lf


def located(shape, m4):
    """apply a rigid 4x4 matrix to a build123d shape"""
    m4 = np.asarray(m4, float)
    r, t = m4[:3, :3], m4[:3, 3]
    loc = Location(Plane(origin=tuple(t), x_dir=tuple(r[:, 0]), z_dir=tuple(r[:, 2])))
    return loc * shape


def export_parts(parts, out):
    stl_dir = Path(out) / "stl"
    step_dir = Path(out) / "step"
    stl_dir.mkdir(parents=True, exist_ok=True)
    step_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for p in parts:
        mesh = p.print_mesh()
        stl = stl_dir / f"{p.name}.stl"
        mesh.export(stl)
        shape = located(p.shape, p.print_matrix())
        shape.label = p.name
        step = step_dir / f"{p.name}.step"
        export_step(shape, step, timestamp=STEP_STAMP)
        written += [stl, step]
    return written


def export_assembly_step(parts, elec_shapes, path):
    children = []
    for p in parts:
        s = p.shape
        s.label = p.name
        children.append(s)
        for i, m in enumerate(p.instances):
            c = located(p.shape, m)
            c.label = f"{p.name} {i + 2}"
            children.append(c)
    for name, s in elec_shapes.items():
        s.label = f"keep out {name}"
        children.append(s)
    comp = Compound(children=children, label="brainsol")
    export_step(comp, path, timestamp=STEP_STAMP)
    return path


def plates():
    """print plates for the 180 mm bed, part names with their x y position on the plate"""
    return [
        ("plate_1_body_tray", "body", [("tray", (0, 0, 0))]),
        ("plate_2_body_lid", "body", [("lid", (0, 0, 0))]),
        ("plate_3_dark_neck_ears_feet", "dark", [("neck_front", (-30, 30, 0)), ("neck_back", (35, 30, 0)),
                                                  ("ear_horn", (-45, -45, 0)), ("ear_pivot", (-10, -45, 0)),
                                                  ("foot", (25, -40, 0)), ("foot", (45, -40, 0)),
                                                  ("foot", (25, -60, 0)), ("foot", (45, -60, 0))]),
        ("plate_4_dark_head_back", "dark", [("head_back", (0, 0, 0))]),
        ("plate_5_dark_bezel", "dark", [("head_bezel", (0, 0, 0))]),
        ("plate_6_accent_caps", "accent", [("cap", (-10, 0, 0)), ("cap", (10, 0, 0))]),
    ]


def plate_layout(parts):
    """placed print meshes per plate, used for the 3MF files and the plate renders"""
    by = {p.name: p for p in parts}
    out = []
    for name, role, items in plates():
        placed = []
        for pname, (x, y, _) in items:
            p = by[pname]
            m = np.eye(4)
            m[:3, 3] = [x, y, 0]
            placed.append((pname, p, m @ p.print_matrix()))
        out.append((name, role, placed))
    return out


def export_3mf(parts, out):
    d = Path(out) / "3mf"
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for name, _, placed in plate_layout(parts):
        mesher = Mesher()
        for pname, p, m in placed:
            mesher.add_shape(located(p.shape, m), linear_deflection=0.02, angular_deflection=0.1, part_number=pname)
        path = d / f"{name}.3mf"
        mesher.write(str(path))
        written.append(path)
    return written


# web


def _smooth(mesh, feature_angle=30.0):
    pd = pv.PolyData(np.asarray(mesh.vertices, float),
                     np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64).ravel())
    pd = pd.compute_normals(split_vertices=True, feature_angle=feature_angle, auto_orient_normals=False,
                            consistent_normals=False)
    faces = pd.faces.reshape(-1, 4)[:, 1:]
    return np.asarray(pd.points, np.float32), np.asarray(pd.point_data["Normals"], np.float32), faces


def _decimate(mesh, target):
    if len(mesh.faces) <= target:
        return mesh
    pd = pv.PolyData(np.asarray(mesh.vertices, float),
                     np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64).ravel())
    red = 1.0 - target / len(mesh.faces)
    pd = pd.decimate(red, volume_preservation=True)
    import trimesh
    return trimesh.Trimesh(np.asarray(pd.points), pd.faces.reshape(-1, 4)[:, 1:], process=True)


def glb_limit(group):
    return GLB_LIMIT_BASE if group == "base" else GLB_LIMIT


def write_glb(path, mesh, color_hex, name):
    """one mesh, one node without any transform, positions and normals in millimetres"""
    pos, nrm, faces = _smooth(mesh)
    idx_type, idx_ct = (np.uint16, 5123) if len(pos) < 65535 else (np.uint32, 5125)
    idx = faces.astype(idx_type).ravel()
    blobs = [pos.tobytes(), nrm.tobytes(), idx.tobytes()]
    offsets, buf = [], b""
    for b in blobs:
        while len(buf) % 4:
            buf += b"\0"
        offsets.append(len(buf))
        buf += b
    while len(buf) % 4:
        buf += b"\0"
    c = color_hex.lstrip("#")
    rgb = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [(v / 12.92) if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    gltf = {
        "asset": {"version": "2.0", "generator": "brainsol hardware build"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "materials": [{"name": name, "pbrMetallicRoughness": {"baseColorFactor": lin + [1.0], "metallicFactor": 0.0,
                                                             "roughnessFactor": 0.8}}],
        "buffers": [{"byteLength": len(buf)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offsets[0], "byteLength": len(blobs[0]), "target": 34962},
            {"buffer": 0, "byteOffset": offsets[1], "byteLength": len(blobs[1]), "target": 34962},
            {"buffer": 0, "byteOffset": offsets[2], "byteLength": len(blobs[2]), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": 2, "componentType": idx_ct, "count": len(idx), "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(js) % 4:
        js += b" "
    total = 12 + 8 + len(js) + 8 + len(buf)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack("<II", len(buf), 0x004E4942))
        f.write(buf)
    return Path(path).stat().st_size


def group_mesh(parts, group, tol=0.15, ang=0.35, swap=None):
    """one mesh of every part in a group, swap gives other shapes by part name"""
    import trimesh
    ms = []
    for p in parts:
        if p.group != group:
            continue
        m = to_trimesh((swap or {}).get(p.name, p.shape), tol=tol, ang=ang)
        ms.append(m)
        for inst in p.instances:
            ms.append(transformed(m, inst))
    return trimesh.util.concatenate(ms)


def panel_face_mesh():
    import trimesh
    x0, y0, z0 = kit.head_xyz(-P.PANEL_W / 2, -P.PANEL_H / 2, P.PANEL_FRONT_N - 0.4)
    x1, y1, z1 = kit.head_xyz(P.PANEL_W / 2, P.PANEL_H / 2, P.PANEL_FRONT_N)
    b = trimesh.creation.box(extents=(x1 - x0, y1 - y0, z1 - z0))
    b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b


def export_web(parts, out):
    d = Path(out) / "web"
    d.mkdir(parents=True, exist_ok=True)
    roles = {"base": "body", "neck": "dark", "head": "dark"}
    sizes, bounds = {}, []
    # the letters on the lid with a coarser outline, the print files keep the fine one
    swap = {"lid": base.lid(sig_tol=WEB_SIG_TOL)} if P.SIG_ON else {}
    for g in ("base", "neck", "head"):
        mesh = group_mesh(parts, g, swap=swap)
        target = len(mesh.faces)
        while True:
            m = _decimate(mesh, target)
            size = write_glb(d / f"{g}.glb", m, P.COLORS[roles[g]], g)
            if size <= glb_limit(g) * 0.95 or target < 2000:
                break
            target = int(target * 0.8)
        sizes[g] = (size, len(m.faces))
        bounds.append(m.bounds)
    pm = panel_face_mesh()
    sizes["panel"] = (write_glb(d / "panel.glb", pm, P.COLORS["panel"], "panel"), len(pm.faces))
    bounds.append(pm.bounds)
    lo = np.min([b[0] for b in bounds], axis=0)
    hi = np.max([b[1] for b in bounds], axis=0)
    data = assembly_json(lo, hi)
    (d / "assembly.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline=LF)
    return sizes, data


def r3(v):
    # adding 0.0 turns a negative zero into a plain zero
    return [round(float(x), 2) + 0.0 for x in v]


def sensor_points():
    out = {}
    for name, ((su, sv), _) in kit.sensor_layout().items():
        n = P.LDR_FACE_N if name != "lux" else P.PCB_TOP_N + P.BH_CHIP_TOP
        out[name] = r3(kit.head_xyz(su, sv, n))
    return out


def assembly_json(lo, hi):
    return {
        "units": "mm",
        "frame": "x right, y forward, z up",
        "parts": [
            {"id": "base", "file": "base.glb", "joint": None, "color": "body"},
            {"id": "neck", "file": "neck.glb", "joint": "pan", "color": "dark"},
            {"id": "head", "file": "head.glb", "joint": "tilt", "color": "dark"},
            {"id": "panel", "file": "panel.glb", "joint": "tilt", "color": "panel"},
        ],
        "joints": {
            "pan": {"origin": r3(PAN_ORIGIN), "axis": [0, 0, -1], "parent": None, "range": list(P.PAN_RANGE)},
            "tilt": {"origin": r3(TILT_ORIGIN), "axis": [1, 0, 0], "parent": "pan", "range": list(P.TILT_RANGE)},
        },
        "sensors": sensor_points(),
        "panel": {"center": r3(kit.head_xyz(0.0, 0.0, P.PANEL_FRONT_N)), "size": [P.PANEL_W, P.PANEL_H],
                  "normal": [0, 1, 0], "up": [0, 0, 1]},
        "bounds": {"min": r3(lo), "max": r3(hi)},
    }
