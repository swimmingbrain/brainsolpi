"""small geometry helpers on top of build123d, all in the device frame"""

import math

from build123d import (
    Axis,
    Box,
    Cone,
    Cylinder,
    Location,
    Part,
    Plane,
    Polygon,
    Pos,
    Vector,
    extrude,
    loft,
)

AXES = {"x": Vector(1, 0, 0), "y": Vector(0, 1, 0), "z": Vector(0, 0, 1)}


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def _axis_plane(axis, a0, c):
    """plane whose normal is the given axis, origin at coordinate a0 along it and c across"""
    if axis == "z":
        return Plane(origin=(c[0], c[1], a0), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
    if axis == "x":
        return Plane(origin=(a0, c[0], c[1]), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
    return Plane(origin=(c[0], a0, c[1]), x_dir=(1, 0, 0), z_dir=(0, 1, 0))


def cyl(axis, r, a0, a1, c=(0.0, 0.0)):
    """cylinder along an axis from a0 to a1, c are the other two coordinates in xyz order"""
    lo, hi = min(a0, a1), max(a0, a1)
    pl = _axis_plane(axis, lo, c)
    return pl.location * Pos(0, 0, (hi - lo) / 2) * Cylinder(r, hi - lo)


def cone(axis, r0, r1, a0, a1, c=(0.0, 0.0)):
    """cone along an axis, radius r0 at a0 and r1 at a1"""
    if a1 < a0:
        a0, a1, r0, r1 = a1, a0, r1, r0
    pl = _axis_plane(axis, a0, c)
    return pl.location * Pos(0, 0, (a1 - a0) / 2) * Cone(r0, r1, a1 - a0)


def poly_prism(points, z0, z1, plane=None):
    """extrude a 2D polygon from z0 to z1 on a plane, the plane defaults to XY"""
    pl = (plane or Plane.XY).offset(z0)
    return extrude(pl * Polygon(*points, align=None), z1 - z0)


def rrect_points(w, d, r, cx=0.0, cy=0.0, n=10, tear_y=False):
    """outline of a rounded rectangle, with tear_y the arcs next to the +y and -y faces
    turn into 45 degree lines so the part can be printed lying on those faces"""
    pts = []
    corners = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    start = [0, 90, 180, 270]
    for (sx, sy), a0 in zip(corners, start):
        ccx = cx + sx * (w / 2 - r)
        ccy = cy + sy * (d / 2 - r)
        arc = []
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            ca, sa = math.cos(a), math.sin(a)
            if tear_y and abs(sa) > math.sqrt(0.5) + 1e-9:
                continue
            arc.append((ccx + r * ca, ccy + r * sa))
        if not tear_y:
            pts.extend(arc)
            continue
        # the 45 degree tangent line meets the y face here
        face_pt = (cx + sx * (w / 2 - r * (2 - math.sqrt(2))), cy + sy * d / 2)
        if (sx, sy) in ((1, 1), (-1, -1)):
            pts.extend(arc)
            pts.append(face_pt)
        else:
            pts.append(face_pt)
            pts.extend(arc)
    return pts


def rrect_prism(w, d, r, z0, z1, cx=0.0, cy=0.0, cb=0.0, ct=0.0):
    """rounded rectangle prism along z, cb and ct are 45 degree chamfers at bottom and top"""
    sections = []
    if cb > 0:
        sections.append((z0, cb))
        sections.append((z0 + cb, 0.0))
    else:
        sections.append((z0, 0.0))
    if ct > 0:
        sections.append((z1 - ct, 0.0))
        sections.append((z1, ct))
    else:
        sections.append((z1, 0.0))
    if cb <= 0 and ct <= 0:
        pts = rrect_points(w, d, r, cx, cy)
        return poly_prism(pts, z0, z1)
    faces = []
    for z, inset in sections:
        pts = rrect_points(w - 2 * inset, d - 2 * inset, max(r - inset, 0.3), cx, cy)
        faces.append(Plane.XY.offset(z) * Polygon(*pts, align=None))
    return loft(faces, ruled=True)


def rot(shape, axis_point, axis_dir, angle_deg):
    """rotate a shape about an axis through a point, right handed"""
    ax = Axis(axis_point, axis_dir)
    return shape.rotate(ax, angle_deg)


def teardrop(axis, r, a0, a1, c, up, flat=None):
    """horizontal hole for printing, a cylinder with a 45 degree roof toward up
    up is a unit vector across the axis in device coords, flat cuts the tip at that height"""
    ax = AXES[axis]
    upv = Vector(*up).normalized()
    xdir = upv.cross(ax)
    lo, hi = min(a0, a1), max(a0, a1)
    if axis == "z":
        origin = Vector(c[0], c[1], lo)
    elif axis == "x":
        origin = Vector(lo, c[0], c[1])
    else:
        origin = Vector(c[0], lo, c[1])
    pl = Plane(origin=origin, x_dir=xdir, z_dir=ax)
    tip = r * math.sqrt(2)
    n = 24
    pts = []
    for i in range(n + 1):
        a = math.radians(135 + 270 * i / n)
        pts.append((r * math.cos(a), r * math.sin(a)))
    # the arc runs from 135 to 405 degrees, the roof closes it over the top
    top = tip if flat is None else min(tip, flat)
    if top < tip - 1e-6:
        w_top = tip - top
        pts.append((w_top, top))
        pts.append((-w_top, top))
    else:
        pts.append((0.0, tip))
    return extrude(pl * Polygon(*pts, align=None), hi - lo)


def roof(axis, r, a0, a1, c, up, flat=None):
    """45 degree roof over a round hole of radius r, the hole itself stays a true cylinder
    the roof starts on the tangents of the circle, flat cuts its tip at that height"""
    ax = AXES[axis]
    upv = Vector(*up).normalized()
    xdir = upv.cross(ax)
    lo, hi = min(a0, a1), max(a0, a1)
    if axis == "z":
        origin = Vector(c[0], c[1], lo)
    elif axis == "x":
        origin = Vector(lo, c[0], c[1])
    else:
        origin = Vector(c[0], lo, c[1])
    pl = Plane(origin=origin, x_dir=xdir, z_dir=ax)
    k = r * math.sqrt(0.5)
    tip = r * math.sqrt(2)
    top = tip if flat is None else min(tip, flat)
    pts = [(0.0, 0.0), (k, k)]
    if top < tip - 1e-6:
        pts += [(tip - top, top), (top - tip, top)]
    else:
        pts.append((0.0, tip))
    pts.append((-k, k))
    return extrude(pl * Polygon(*pts, align=None), hi - lo)


def double_teardrop(axis, r, a0, a1, c, up):
    """round bar with 45 degree points toward up and toward minus up, for parts that print
    on either side of a split face"""
    ax = AXES[axis]
    upv = Vector(*up).normalized()
    xdir = upv.cross(ax)
    lo, hi = min(a0, a1), max(a0, a1)
    if axis == "z":
        origin = Vector(c[0], c[1], lo)
    elif axis == "x":
        origin = Vector(lo, c[0], c[1])
    else:
        origin = Vector(c[0], lo, c[1])
    pl = Plane(origin=origin, x_dir=xdir, z_dir=ax)
    pts = [(0.0, r * math.sqrt(2))]
    for i in range(13):
        a = math.radians(135 + 90 * i / 12)
        pts.append((r * math.cos(a), r * math.sin(a)))
    pts.append((0.0, -r * math.sqrt(2)))
    for i in range(13):
        a = math.radians(315 + 90 * i / 12)
        pts.append((r * math.cos(a), r * math.sin(a)))
    return extrude(pl * Polygon(*pts, align=None), hi - lo)


def csk_hole(p, d, length, tap=False, csk=True):
    """screw hole at point p on a surface, d is the unit vector into the material
    clearance or tap hole of the given length plus a 90 degree countersink at p"""
    dv = Vector(*d).normalized()
    pv = Vector(*p)
    hole_r = (2.65 if tap else 3.4) / 2
    pl = Plane(origin=pv - dv * 0.01, z_dir=dv)
    body = pl.location * Pos(0, 0, (length + 0.01) / 2) * Cylinder(hole_r, length + 0.01)
    if csk:
        h = (6.4 - 3.4) / 2
        body = body + pl.location * Pos(0, 0, h / 2) * Cone(6.4 / 2 + 0.01, 3.4 / 2, h + 0.02)
        # short counterbore above the surface so the cone opens cleanly
        body = body + Plane(origin=pv - dv * 0.6, z_dir=dv).location * Pos(0, 0, 0.3) * Cylinder(6.4 / 2 + 0.01, 0.6)
    return body


def tap_hole(p, d, depth):
    """self threading hole for a kit M3 screw, p on the surface, d into the material"""
    dv = Vector(*d).normalized()
    pv = Vector(*p)
    pl = Plane(origin=pv - dv * 0.4, z_dir=dv)
    body = pl.location * Pos(0, 0, (depth + 0.4) / 2) * Cylinder(2.65 / 2, depth + 0.4)
    # small entry chamfer so the screw finds the hole
    body = body + pl.location * Pos(0, 0, 0.6) * Cone(3.3 / 2, 2.65 / 2, 0.8)
    return body


def stadium_points(cx, cy, length, width, angle=0.0, n=8):
    """slot outline with round ends, length is the overall length"""
    r = width / 2
    half = max(length / 2 - r, 0.0)
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    pts = []
    for end, a_start in ((half, -90), (-half, 90)):
        for i in range(n + 1):
            a = math.radians(a_start + 180 * i / n)
            lx, ly = end + r * math.cos(a), r * math.sin(a)
            pts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca))
    return pts


def arc_slot_points(cx, cy, r, w, a0, a1, n=48):
    """curved slot along a circle of radius r from angle a0 to a1, degrees counterclockwise"""
    ro, ri = r + w / 2, r - w / 2
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((cx + ro * math.cos(a), cy + ro * math.sin(a)))
    ea = math.radians(a1)
    ex, ey = cx + r * math.cos(ea), cy + r * math.sin(ea)
    for i in range(1, 8):
        t = ea + math.pi * i / 8
        pts.append((ex + w / 2 * math.cos(t), ey + w / 2 * math.sin(t)))
    for i in range(n + 1):
        a = math.radians(a1 - (a1 - a0) * i / n)
        pts.append((cx + ri * math.cos(a), cy + ri * math.sin(a)))
    sa = math.radians(a0)
    sx, sy = cx + r * math.cos(sa), cy + r * math.sin(sa)
    for i in range(1, 8):
        t = sa + math.pi + math.pi * i / 8
        pts.append((sx + w / 2 * math.cos(t), sy + w / 2 * math.sin(t)))
    return pts


def union_all(shapes):
    """fuse a list of solids in one go, faster than adding them one by one"""
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        return None
    out = shapes[0]
    if len(shapes) > 1:
        out = out.fuse(*shapes[1:])
    return out


def solid_of(shape):
    """make sure we hand a Part around"""
    if isinstance(shape, Part):
        return shape
    return Part(shape.wrapped) if hasattr(shape, "wrapped") else shape


def at(loc_xyz, shape):
    return Location(loc_xyz) * shape
