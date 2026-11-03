"""programmatic checks: interference sweep, closed solids, bed fit, overhangs, thin walls"""

import math

import manifold3d as m3d
import numpy as np

from . import assembly as A
from . import params as P
from . import signature as S

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


# the engraved signature, measured on the lid mesh


def _largest(test, hi, step=0.05):
    """largest radius up to hi for which test holds at every smaller radius too

    walks up in small steps and halves the last one. a recess grown far enough can lose a new hole
    again, so a plain halving over the whole range could jump over a failure
    """
    lo, r = 0.0, step
    while r < hi + 1e-9:
        if not test(r):
            break
        lo, r = r, r + step
    else:
        return hi if test(hi) else lo
    for _ in range(8):
        mid = (lo + r) / 2
        if test(mid):
            lo = mid
        else:
            r = mid
    return lo


def strokes_hold(cs, r):
    """after taking r off every side, each piece is still one piece with the same holes"""
    for piece in cs.decompose():
        rest = S.offset(piece, -r).decompose()
        if len(rest) != 1 or rest[0].num_contour() != piece.num_contour():
            return False
    return True


def islands_hold(cs, r):
    """after growing the recess by r, no two pieces meet and no counter closes"""
    return S.topology(S.offset(cs, r)) == S.topology(cs)


def engraving_report(lid_mesh):
    """slice the lid half way down the recess and measure what the printer has to make

    strokes: the recess shrunk by half the stroke limit keeps every piece and every hole
    islands: the recess grown by half the island limit keeps them as well, so no counter, gap or
    wall between recesses is narrower than the limit. both are also measured as numbers
    """
    man = to_manifold(lid_mesh)
    top = P.BASE_TOP
    design = S.profile()
    zone = S.offset(design, 0.5)
    measured = zone - man.slice(top - P.SIG_DEPTH / 2)
    rep = {"sizes": S.sizes()}
    rep["area_design"] = design.area()
    rep["area_measured"] = measured.area()
    rep["pieces"] = S.topology(measured)[0]
    rep["holes"] = sum(S.topology(measured)[1])
    # the font as drawn, no counter or gap may be lost by the fill or the mesh
    rep["same_topology"] = S.topology(measured) == S.topology(S.profile(raw=True))
    rep["stroke_min"] = 2 * _largest(lambda r: strokes_hold(measured, r), hi=1.2)
    rep["island_min"] = 2 * _largest(lambda r: islands_hold(measured, r), hi=1.2)
    rep["strokes_ok"] = rep["stroke_min"] >= P.ENGRAVE_STROKE_MIN and strokes_hold(measured, P.ENGRAVE_STROKE_MIN / 2)
    rep["islands_ok"] = rep["island_min"] >= P.ENGRAVE_ISLAND_MIN and islands_hold(measured, P.ENGRAVE_ISLAND_MIN / 2)
    # widest span across, the largest circle that fits, per kind of part
    spans = {}
    for kind in ("line", "tag", "heart", "logo", "rule"):
        part = measured ^ S.offset(S.profile(kind), 0.2)
        spans[kind] = 2 * _largest(lambda r: not S.offset(part, -r).is_empty(), hi=8.0, step=0.25)
    rep["spans"] = spans
    # depth: open just above the floor, closed just below it
    above = (zone - man.slice(top - P.SIG_DEPTH + 0.02)).area()
    below = (zone - man.slice(top - P.SIG_DEPTH - 0.02)).area()
    rep["depth_ok"] = abs(above - design.area()) < 0.02 * design.area() and below < 1e-3
    # solid plastic behind the floor, sliced every 0.1 mm down to the skin limit
    skin = 0.0
    z = top - P.SIG_DEPTH - 0.05
    while skin < P.ENGRAVE_SKIN_MIN + 0.5:
        if (S.offset(design, 0.3) - man.slice(z)).area() > 1e-3:
            break
        skin = top - P.SIG_DEPTH - z + 0.05
        z -= 0.1
    rep["skin"] = skin
    # clear distance to the edge of the flat top, holes and other recesses
    flat = man.slice(top - 0.05) + measured
    rep["clear"] = _largest(lambda r: (S.offset(measured, r) - flat).area() < 1e-3, hi=15.0, step=0.5)
    for k in ("area_design", "area_measured", "stroke_min", "island_min", "skin", "clear"):
        rep[k] = round(float(rep[k]), 3)
    rep["spans"] = {k: round(float(v), 3) for k, v in spans.items()}
    rep["sizes"] = {k: (round(float(v), 3) if isinstance(v, float) else v) for k, v in rep["sizes"].items()}
    rep["sizes"]["box"] = [round(float(v), 2) for v in rep["sizes"]["box"]]
    return rep


def engraving_failures(rep):
    out = []
    if abs(rep["area_measured"] - rep["area_design"]) > 0.01 * rep["area_design"]:
        out.append(f"the signature in the lid mesh covers {rep['area_measured']:.1f} mm2, the design {rep['area_design']:.1f}")
    if not rep["same_topology"]:
        out.append("the signature lost a counter or a letter against the font outlines")
    if not rep["strokes_ok"]:
        out.append(f"a stroke of the signature is {rep['stroke_min']:.2f} mm wide, the limit is {P.ENGRAVE_STROKE_MIN}")
    if not rep["islands_ok"]:
        out.append(f"an island of the signature is {rep['island_min']:.2f} mm wide, the limit is {P.ENGRAVE_ISLAND_MIN}")
    if not rep["depth_ok"]:
        out.append("the signature is not cut to its depth")
    if rep["skin"] < P.ENGRAVE_SKIN_MIN:
        out.append(f"only {rep['skin']:.1f} mm of solid lid behind the signature")
    if rep["clear"] < P.ENGRAVE_CLEAR_MIN:
        out.append(f"the signature comes within {rep['clear']:.1f} mm of an edge or a hole")
    return out


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
