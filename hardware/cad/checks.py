"""programmatic checks: interference sweep, closed solids, bed fit, overhangs, thin walls"""

import math

import manifold3d as m3d
import numpy as np

from . import assembly as A
from . import params as P

CONTACT_TOL = 1.0  # mm3, two faces that touch on purpose leave a sliver of this size at most


def to_manifold(mesh):
    man = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                                tri_verts=np.asarray(mesh.faces, np.uint32)))
    if man.status() != m3d.Error.NoError:
        raise ValueError(f"mesh is not a manifold: {man.status()}")
    return man


def mtx(m4):
    return np.asarray(m4, float)[:3, :]


def union(mans):
    mans = [m for m in mans if m is not None]
    if not mans:
        return None
    if len(mans) == 1:
        return mans[0]
    return m3d.Manifold.batch_boolean(mans, m3d.OpType.Add)


def overlap(a, b):
    if a is None or b is None:
        return 0.0
    return (a ^ b).volume()


class Scene:
    """manifolds of every printed part and kit part at pan 0 and tilt 0"""

    def __init__(self, parts, elec):
        self.items = {}  # name: (group, kind, manifold)
        for p in parts:
            for i, pm in enumerate(p.placed_meshes()):
                name = p.name if i == 0 else f"{p.name}_{i + 1}"
                self.items[name] = (p.group, "part", to_manifold(pm))
        for g, d in elec.items():
            for k, mesh in d.items():
                self.items[k] = (g, "kit", to_manifold(mesh))

    def group(self, g, kind=None):
        return [(n, m) for n, (gg, kk, m) in self.items.items() if gg == g and (kind is None or kk == kind)]


def static_checks(scene):
    """every pair inside one rigid group, printed parts against each other and the kit"""
    rows = []
    for g in ("base", "neck", "head"):
        items = scene.group(g)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (na, ma), (nb, mb) = items[i], items[j]
                ka, kb = scene.items[na][1], scene.items[nb][1]
                if ka == "kit" and kb == "kit" and g != "head":
                    continue
                v = overlap(ma, mb)
                rows.append((g, na, nb, v))
    return rows


def sweep(scene, pan_step=10.0, tilt_step=10.0):
    """interference and clearance between the three groups over the full ranges"""
    pans = np.arange(P.PAN_RANGE[0], P.PAN_RANGE[1] + 1e-6, pan_step)
    tilts = np.arange(P.TILT_RANGE[0], P.TILT_RANGE[1] + 1e-6, tilt_step)
    base_all = union([m for _, m in scene.group("base")])
    neck_all = union([m for _, m in scene.group("neck")])
    head_all = union([m for _, m in scene.group("head")])
    base_parts = union([m for _, m in scene.group("base", "part")])
    neck_parts = union([m for _, m in scene.group("neck", "part")])
    head_parts = union([m for _, m in scene.group("head", "part")])
    res = {"base_neck": 0.0, "neck_head": 0.0, "base_head": 0.0, "worst": [],
           "gap_head_base": 1e9, "gap_head_base_pose": None, "gap_neck_head": 1e9, "gap_neck_head_pose": None,
           "poses": 0}
    # neck against the base only depends on pan
    for pan in pans:
        m_neck = mtx(A.group_matrix("neck", pan, 0.0))
        v = overlap(base_all, neck_all.transform(m_neck))
        res["base_neck"] = max(res["base_neck"], v)
        if v > CONTACT_TOL:
            res["worst"].append(("base", "neck", float(pan), None, v))
    # head against the neck only depends on tilt, both turn with pan
    for tilt in tilts:
        m_head = mtx(A.group_matrix("head", 0.0, tilt))
        v = overlap(neck_all, head_all.transform(m_head))
        res["neck_head"] = max(res["neck_head"], v)
        if v > CONTACT_TOL:
            res["worst"].append(("neck", "head", 0.0, float(tilt), v))
        g = neck_parts.min_gap(head_parts.transform(m_head), 30.0)
        if g < res["gap_neck_head"]:
            res["gap_neck_head"], res["gap_neck_head_pose"] = g, float(tilt)
    # head against the base needs the full grid
    for pan in pans:
        for tilt in tilts:
            m_head = mtx(A.group_matrix("head", pan, tilt))
            h = head_all.transform(m_head)
            v = overlap(base_all, h)
            res["poses"] += 1
            res["base_head"] = max(res["base_head"], v)
            if v > CONTACT_TOL:
                res["worst"].append(("base", "head", float(pan), float(tilt), v))
            g = base_parts.min_gap(head_parts.transform(m_head), 30.0)
            if g < res["gap_head_base"]:
                res["gap_head_base"], res["gap_head_base_pose"] = g, (float(pan), float(tilt))
    res["pans"] = [float(pans[0]), float(pans[-1]), pan_step]
    res["tilts"] = [float(tilts[0]), float(tilts[-1]), tilt_step]
    return res


def drill_down(scene, pan, tilt, ga, gb):
    """which items collide at one pose"""
    out = []
    for na, ma in scene.group(ga):
        for nb, mb in scene.group(gb):
            mb2 = mb.transform(mtx(A.group_matrix(gb, pan, tilt)))
            ma2 = ma.transform(mtx(A.group_matrix(ga, pan, tilt)))
            v = overlap(ma2, mb2)
            if v > CONTACT_TOL:
                out.append((na, nb, v))
    return out


# per part checks in print orientation


def overhang_stats(mesh, bed_tol=0.3):
    """areas of downward faces steeper than the rule, and the widest flat bridge"""
    n = mesh.face_normals
    a = mesh.area_faces
    zmin = mesh.triangles[:, :, 2].min(axis=1)
    off_bed = zmin > bed_tol
    down = n[:, 2]
    lim = -math.sin(math.radians(P.OVERHANG_MAX + 1.0))
    steep = off_bed & (down < lim) & (down > -0.996)
    flat = off_bed & (down <= -0.996)
    res = {"steep_area": 0.0, "steep_small_area": 0.0, "flat_area": float(a[flat].sum()), "bridge_max": 0.0,
           "steep_worst": []}
    if steep.any():
        # arcs on top of small holes print fine, only patches wider than a few millimetres count
        sub = mesh.submesh([np.where(steep)[0]], append=True)
        worst = []
        for comp in sub.split(only_watertight=False):
            ext = comp.vertices.max(axis=0) - comp.vertices.min(axis=0)
            if max(ext[0], ext[1]) < 3.0:
                res["steep_small_area"] += float(comp.area)
            else:
                res["steep_area"] += float(comp.area)
                worst.append((float(comp.area), tuple(np.round(comp.centroid, 1))))
        worst.sort(reverse=True)
        res["steep_worst"] = [w[1] for w in worst[:3]]
    if flat.any():
        sub = mesh.submesh([np.where(flat)[0]], append=True)
        spans = []
        for comp in sub.split(only_watertight=False):
            pts = comp.vertices[:, :2]
            if len(pts) < 3:
                continue
            c = pts - pts.mean(axis=0)
            _, _, vt = np.linalg.svd(c, full_matrices=False)
            proj = c @ vt.T
            ext = proj.max(axis=0) - proj.min(axis=0)
            spans.append(float(min(ext)))
        res["bridge_max"] = max(spans) if spans else 0.0
    return res


def wall_stats(mesh, man, n_samples=1500, seed=1):
    """sample the surface and measure the solid thickness straight in, ignore points near edges"""
    rng = np.random.default_rng(seed)
    a = mesh.area_faces
    prob = a / a.sum()
    fi = rng.choice(len(a), size=n_samples, p=prob)
    tri = mesh.triangles[fi]
    u, v = rng.random(n_samples), rng.random(n_samples)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    pts = tri[:, 0] + (tri[:, 1] - tri[:, 0]) * u[:, None] + (tri[:, 2] - tri[:, 0]) * v[:, None]
    nrm = mesh.face_normals[fi]
    th = []
    for p, nn in zip(pts, nrm):
        o = p - nn * 0.01
        e = p - nn * 30.0
        hits = man.ray_cast(tuple(o), tuple(e))
        if hits:
            th.append(float(np.linalg.norm(np.asarray(hits[0].position) - o)) + 0.01)
    th = np.array(th) if th else np.array([99.0])
    return {"p02": float(np.percentile(th, 2)), "share_thin": float((th < P.WALL_MIN - 0.05).mean())}


def part_report(part):
    pm = part.print_mesh()
    lo, hi = pm.bounds
    size = hi - lo
    shape = part.shape
    man = to_manifold(pm)
    rep = {
        "name": part.name,
        "count": part.count,
        "valid": bool(shape.is_valid),
        "solids": len(shape.solids()),
        "watertight": bool(pm.is_watertight),
        "volume": float(pm.volume),
        "size": [float(s) for s in size],
        "fits": bool(all(size[i] <= P.BED[i] for i in range(3))),
        "note": part.note,
    }
    rep.update(overhang_stats(pm))
    rep.update(wall_stats(pm, man))
    return rep
