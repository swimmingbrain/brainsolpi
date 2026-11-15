"""the head: back shell, front bezel, two hinge ears and two copper caps

head frame at pan 0 and tilt 0: u = x to the right, v = z minus the tilt axis height,
n = y minus the back face of the head, n grows toward the front
the back shell prints on its back face and the bezel on its front face, both visible faces
come off the bed, the ears stand on the end face that meets the head, so every recess in them
opens sideways and needs no support
"""

import math

from build123d import GeomType, Plane, Polygon, chamfer, extrude, loft

from . import kit
from . import params as P
from .helpers import box, cone, cyl, poly_prism, roof, stadium_points, union_all

N_ARC = 10
CABLE_U = P.HEAD_CABLE_U
EXIT_L = 18.0  # cable exit slot in the back of the head
EXIT_W = 8.0
BEZEL_SCREWS = ((-73.5, -18.0), (-73.5, 18.0), (73.5, -18.0), (73.5, 18.0),
                (-28.0, -49.0), (-28.0, 49.0), (28.0, -49.0), (28.0, 49.0))
EAR_SCREWS_V = (-7.0, 7.0)


def yb():
    return P.HEAD_BACK_Y


def hx(u, v, n):
    return kit.head_xyz(u, v, n)


def hbox(u0, u1, v0, v1, n0, n1):
    return box(u0, u1, yb() + n0, yb() + n1, P.Z_TILT + v0, P.Z_TILT + v1)


def hcyl_n(r, n0, n1, u, v):
    """cylinder along n at a point of the head face"""
    return cyl("y", r, yb() + n0, yb() + n1, (u, P.Z_TILT + v))


def hcone_n(r0, r1, n0, n1, u, v):
    return cone("y", r0, r1, yb() + n0, yb() + n1, (u, P.Z_TILT + v))


def uv_face(pts, n):
    """polygon in the u v plane at height n, built so its normal points to plus n"""
    pl = Plane(origin=(0, yb() + n, P.Z_TILT), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    return pl * Polygon(*[(u, -v) for u, v in pts][::-1], align=None)


def rr_uv(w, h, r, cu=0.0, cv=0.0, n=N_ARC):
    pts = []
    for (su, sv), a0 in zip([(1, 1), (-1, 1), (-1, -1), (1, -1)], [0, 90, 180, 270]):
        ccu, ccv = cu + su * (w / 2 - r), cv + sv * (h / 2 - r)
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((ccu + r * math.cos(a), ccv + r * math.sin(a)))
    return pts


def slab(n0, n1, inset=0.0, c0=0.0, c1=0.0, w=None, h=None, r=None):
    """rounded rectangle slab between n0 and n1 with 45 degree chamfers c0 and c1"""
    w = (P.HEAD_W if w is None else w) - 2 * inset
    h = (P.HEAD_H if h is None else h) - 2 * inset
    r = max((P.R_MID if r is None else r) - inset, 0.5)
    secs = []
    secs.append((n0, c0))
    if c0 > 0:
        secs.append((n0 + c0, 0.0))
    if c1 > 0:
        secs.append((n1 - c1, 0.0))
    secs.append((n1, c1))
    if len(secs) == 2:
        return extrude(uv_face(rr_uv(w, h, r), n0), n1 - n0)
    faces = [uv_face(rr_uv(w - 2 * c, h - 2 * c, max(r - c, 0.3)), nn) for nn, c in secs]
    return loft(faces, ruled=True)


def uv_prism(pts, n0, n1):
    return extrude(uv_face(pts, n0), n1 - n0)


# back shell


def panel_rib_spots():
    """posts under the panel, clear of every module and the cable paths"""
    return [(-30.0, 26.0), (30.0, -26.0), (-30.0, -26.0), (45.0, 18.0), (-45.0, -18.0)]


def module_clearance(grow=1.0):
    """grown boxes around each module footprint, used to keep ribs away"""
    out = []
    for name, ((su, sv), (iu, iv)) in kit.sensor_layout().items():
        off = P.LDR_FROM_END if name != "lux" else P.BH_CHIP_FROM_END
        eu, ev = su - off * iu, sv - off * iv
        tu, tv = eu + (P.MOD_L + P.PLUG_REACH) * iu, ev + (P.MOD_L + P.PLUG_REACH) * iv
        hw = P.MOD_W / 2 + grow
        u0, u1 = sorted((eu, tu))
        v0, v1 = sorted((ev, tv))
        if iu != 0:
            out.append(hbox(u0 - grow, u1 + grow, sv - hw, sv + hw, P.BACK_T - 0.1, P.PANEL_BACK_N + 0.1))
        else:
            out.append(hbox(su - hw, su + hw, v0 - grow, v1 + grow, P.BACK_T - 0.1, P.PANEL_BACK_N + 0.1))
    return union_all(out)


def back_shell():
    J = P.HEAD_JOINT
    outer = slab(0.0, J, c0=P.EDGE, c1=P.GAP / 2)
    inner = slab(P.BACK_T, J + 1.0, inset=P.HEAD_WALL_T)
    shell = outer - inner
    add = [shell]
    # module pegs, a shoulder sets the stand off, the pin goes through the board hole
    for name, (s, i) in kit.sensor_layout().items():
        kind = "bh" if name == "lux" else "ldr"
        o, xd, _ = kit.module_placement(s, i, kind)
        for side in (-1, 1):
            # hole centre in the device frame
            hu = o[0] + xd[0] * P.MOD_HOLE_FROM_SENSOR_END + side * (-xd[2]) * P.MOD_HOLE_SPACING / 2
            hv = o[2] - P.Z_TILT + xd[2] * P.MOD_HOLE_FROM_SENSOR_END + side * xd[0] * P.MOD_HOLE_SPACING / 2
            add.append(hcyl_n(3.4, P.BACK_T - 0.01, P.PCB_BOTTOM_N, hu, hv))
            pin_r = P.MOD_HOLE_D / 2 - P.FIT_SNUG
            add.append(hcyl_n(pin_r, P.PCB_BOTTOM_N - 0.01, P.PCB_TOP_N + 2.4, hu, hv))
            add.append(hcone_n(pin_r, pin_r - 0.6, P.PCB_TOP_N + 2.4, P.PCB_TOP_N + 3.0, hu, hv))
    # panel rest, a rib just inside the panel edge plus a few posts, cut where modules pass
    rw = 1.6
    pw, ph = P.PANEL_W / 2 - 2.5, P.PANEL_H / 2 - 2.5
    ribs = [hbox(-pw - rw / 2, pw + rw / 2, ph - rw / 2, ph + rw / 2, P.BACK_T - 0.01, P.PANEL_BACK_N),
            hbox(-pw - rw / 2, pw + rw / 2, -ph - rw / 2, -ph + rw / 2, P.BACK_T - 0.01, P.PANEL_BACK_N),
            hbox(-pw - rw / 2, -pw + rw / 2, -ph, ph, P.BACK_T - 0.01, P.PANEL_BACK_N),
            hbox(pw - rw / 2, pw + rw / 2, -ph, ph, P.BACK_T - 0.01, P.PANEL_BACK_N)]
    for u, v in panel_rib_spots():
        ribs.append(hcyl_n(2.5, P.BACK_T - 0.01, P.PANEL_BACK_N, u, v))
    rib = union_all(ribs) - module_clearance(1.2) - cable_lane()
    add.append(rib)
    # sockets that take the ends of the bezel bosses and line the two parts up
    for u, v in BEZEL_SCREWS:
        add.append(hcyl_n(boss_r() + 0.2 + 1.6, P.BACK_T - 0.01, P.BACK_T + 1.6, u, v))
    body = union_all(add)
    cuts = []
    for u, v in BEZEL_SCREWS:
        cuts.append(hcyl_n(boss_r() + 0.2, P.BACK_T, P.BACK_T + 2.0, u, v))
        # flat head from behind, countersunk flush in the back face
        cuts.append(back_csk(u, v))
    # ear screws come from inside, the head stays a little proud of the floor
    for side in (-1, 1):
        for v in EAR_SCREWS_V:
            u = side * ear_screw_u()
            cuts.append(hcyl_n(P.M3_CLEAR / 2, -1.0, P.BACK_T + 1.0, u, v))
            cuts.append(hcone_n(P.M3_CLEAR / 2, P.M3_CSK_D / 2, P.BACK_T - 0.8, P.BACK_T + 0.01, u, v))
    # one to four dots next to each module, the same count as A0 to A3 plus one
    cuts.append(sensor_dots())
    # cable exit with soft edges
    cuts.append(uv_prism(stadium_points(CABLE_U, 0.0, EXIT_L, EXIT_W), -1.0, P.BACK_T + 1.0))
    cuts.append(stadium_chamfer(CABLE_U, 0.0, EXIT_L, EXIT_W, 0.0, 0.8))
    return body - union_all(cuts)


def sensor_dots():
    """small dimples in the floor, L one, R two, U three, D four, so every cable finds its pin"""
    out = []
    for count, name in enumerate(("L", "R", "U", "D"), start=1):
        (su, sv), (iu, iv) = kit.sensor_layout()[name]
        lu, lv = -iv, iu
        for k in range(count):
            u = su + iu * (9.0 + 3.0 * k) + lu * 15.0
            v = sv + iv * (9.0 + 3.0 * k) + lv * 15.0
            out.append(hcyl_n(0.9, P.BACK_T - 0.4, P.BACK_T + 0.5, u, v))
    return union_all(out)


def cable_lane():
    """keep the floor clear on the way from the modules to the cable exit"""
    return union_all([
        hbox(-60.0, 60.0, -4.5, 4.5, P.BACK_T - 0.1, P.PANEL_BACK_N + 0.1),
        hbox(CABLE_U - 5.0, CABLE_U + 5.0, -40.0, 40.0, P.BACK_T - 0.1, P.PANEL_BACK_N + 0.1),
    ])


def stadium_chamfer(cu, cv, length, width, n_face, c):
    """45 degree chamfer around a slot that opens in a face at n_face, going toward minus n"""
    big = uv_face(stadium_points(cu, cv, length + 2 * c, width + 2 * c), n_face - 0.01)
    small = uv_face(stadium_points(cu, cv, length, width), n_face + c)
    return loft([big, small], ruled=True)


def back_csk(u, v):
    h = (P.M3_CSK_D - P.M3_CLEAR) / 2
    return hcyl_n(P.M3_CLEAR / 2, -1.0, P.BACK_T + 1.0, u, v) + hcone_n(P.M3_CSK_D / 2 + 0.01, P.M3_CLEAR / 2, -0.01, h, u, v)


def boss_r():
    return 3.4


def ear_screw_u():
    return P.NECK_W / 2 + P.EAR_GAP + P.EAR_T / 2


# bezel


def bezel():
    J = P.HEAD_JOINT
    T = P.HEAD_T
    outer = slab(J, T, c0=P.GAP / 2, c1=P.EDGE)
    cavity = slab(J - 1.0, P.PANEL_BACK_N, inset=P.HEAD_WALL_T)
    body = outer - cavity
    adds = []
    # bosses for the screws from behind, they end short of the floor so the walls meet first
    for u, v in BEZEL_SCREWS:
        adds.append(hcyl_n(boss_r(), P.BACK_T + 0.2, P.PANEL_BACK_N + 0.01, u, v))
    # small pads that keep the sensor end of every module down on its pegs
    for name, (s, i) in kit.sensor_layout().items():
        kind = "bh" if name == "lux" else "ldr"
        o, xd, _ = kit.module_placement(s, i, kind)
        for side in (-1, 1):
            pu = o[0] + xd[0] * 2.5 + side * (-xd[2]) * 9.5
            pv = o[2] - P.Z_TILT + xd[2] * 2.5 + side * xd[0] * 9.5
            adds.append(hbox(pu - 1.5, pu + 1.5, pv - 1.5, pv + 1.5, P.PCB_TOP_N + 0.3, P.PANEL_BACK_N + 0.01))
    body = body + union_all(adds)
    cuts = []
    # pocket for the panel and the window in front of it
    f = P.PANEL_FIT
    cuts.append(uv_prism(rr_uv(P.PANEL_W + 2 * f, P.PANEL_H + 2 * f, 0.6), P.PANEL_BACK_N - 1.0, P.PANEL_FRONT_N))
    ww, wh = P.PANEL_W - 2 * P.BEZEL_LIP, P.PANEL_H - 2 * P.BEZEL_LIP
    cuts.append(uv_prism(rr_uv(ww, wh, 2.0), P.PANEL_FRONT_N - 0.01, T + 1.0))
    c = 0.8
    cuts.append(loft([uv_face(rr_uv(ww, wh, 2.0), T - c), uv_face(rr_uv(ww + 2 * c, wh + 2 * c, 2.0 + c), T + 0.01)], ruled=True))
    # eyes and the lux window
    for name, (s, i) in kit.sensor_layout().items():
        if name == "lux":
            cuts.append(lux_window(s, i))
        else:
            cuts.append(eye_cut(s, i))
    # tap holes in the bosses
    for u, v in BEZEL_SCREWS:
        cuts.append(hcyl_n(P.M3_TAP / 2, P.BACK_T, P.BACK_T + 7.5, u, v))
    return body - union_all(cuts)


def lux_window(s, i):
    """slot in front of the bh1750 chip with a 45 degree flare at the front

    the chip sits beside the board centre line, the slot runs across the board so the chip looks
    straight out anywhere in BH_WINDOW_SIDE, s is the sensor point on the centre line
    """
    yu, yv = kit.board_side(i)
    near, far = P.BH_WINDOW_SIDE
    a = (s[0] - near * yu, s[1] - near * yv)
    b = (s[0] - far * yu, s[1] - far * yv)
    cu, cv = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    span = math.hypot(b[0] - a[0], b[1] - a[1])
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    w = P.BH_WINDOW_D
    T = P.HEAD_T
    fl = 2.3

    def face(n, grow):
        return uv_face(stadium_points(cu, cv, span + w + 2 * grow, w + 2 * grow, ang, n=24), n)

    straight = extrude(face(P.PANEL_BACK_N - 1.0, 0.0), T + 1.0 - (P.PANEL_BACK_N - 1.0))
    flare = loft([face(T - fl, 0.0), face(T + 0.01, fl + 0.01)], ruled=True)
    return straight + flare


def eye_cut(s, i):
    """well with a vertical shade wall on the panel side, 45 degree flares on the other sides"""
    su, sv = s
    iu, iv = i
    r0 = P.LDR_D / 2 + 0.3
    T = P.HEAD_T
    nb = P.PANEL_BACK_N
    rt = r0 + (T - nb) * math.tan(math.radians(P.EYE_FLARE))
    c = hcone_n(r0, rt, nb, T + 0.01, su, sv) + hcyl_n(r0, P.PCB_TOP_N, nb + 0.01, su, sv)
    # keep only the side away from the panel, the cut face is the shade wall
    wall = r0
    big = 40.0
    if iu != 0:
        wu = su + iu * wall
        u0, u1 = (wu - big, wu) if iu > 0 else (wu, wu + big)
        keep = hbox(u0, u1, sv - big, sv + big, P.PCB_TOP_N - 1, T + 2)
    else:
        wv = sv + iv * wall
        v0, v1 = (wv - big, wv) if iv > 0 else (wv, wv + big)
        keep = hbox(su - big, su + big, v0, v1, P.PCB_TOP_N - 1, T + 2)
    return c & keep


# ears


def hull2d(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


EAR_CORNER_R = 2.0  # corners of the ear where it meets the head


def ear_end_t():
    """half width of the flat end face, where the 45 degree tangents of the corners meet it"""
    return P.EAR_W / 2 - EAR_CORNER_R + EAR_CORNER_R * (math.sqrt(2) - 1)


def ear_outline():
    """ear shape in (s, t), s from the tilt axis toward the head, t up at tilt 0

    the corners at the head end are round down to 45 degrees and then run straight into the end
    face, so the ear standing on that face has no overhang steeper than 45 degrees
    """
    pts = []
    for k in range(48):
        a = 2 * math.pi * k / 48
        pts.append((P.EAR_HUB_R * math.cos(a), P.EAR_HUB_R * math.sin(a)))
    s1 = P.HEAD_OFFSET
    hw = P.EAR_W / 2
    rc = EAR_CORNER_R
    for sc, tc in ((s1 - rc, hw - rc), (s1 - rc, -hw + rc)):
        for k in range(24):
            a = 2 * math.pi * k / 24
            pts.append((sc + rc * math.cos(a), tc + rc * math.sin(a)))
    pts += [(s1, -ear_end_t()), (s1, ear_end_t())]
    pts = [(min(x, s1), y) for x, y in pts]
    return hull2d(pts)


def ear_plane(x):
    """plane at x whose local x is s (device +y) and local y is t (device +z)"""
    return Plane(origin=(x, P.TURRET_Y, P.Z_TILT), x_dir=(0, 1, 0), z_dir=(1, 0, 0))


def ear_prism(side, pts, z0, z1):
    """prism of a polygon in (s, t) from z0 to z1, z from the inner face outward"""
    xi = side * (P.NECK_W / 2 + P.EAR_GAP)
    xa, xb = sorted((xi + side * z0, xi + side * z1))
    return extrude(ear_plane(xa) * Polygon(*pts, align=None), xb - xa)


def ear_side_prism(side, pts, half):
    """prism of a polygon in (s, z) across t from minus half to half, z from the inner face outward"""
    xi = side * (P.NECK_W / 2 + P.EAR_GAP)
    pl = Plane(origin=(xi, P.TURRET_Y, P.Z_TILT + side * half), x_dir=(0, 1, 0), z_dir=(0, 0, -side))
    return extrude(pl * Polygon(*pts, align=None), 2 * half)


def ear_rib(side):
    """rib that carries the hub down to the end face, the ear prints standing on that face

    seen from outside its sides leave the hub on tangents and end EAR_RIB_W apart on the end face,
    its top is level with the foot of the hub chamfer and falls in a plane from the lowest point of
    the hub to EAR_RIB_H above the plate at the end face, so the hub has plastic under it all the
    way down and no face of the rib leans out more than 20 degrees
    """
    R = P.EAR_HUB_R
    s1 = P.HEAD_OFFSET
    w = P.EAR_RIB_W / 2
    a = math.atan2(w, s1) + math.acos(R / math.hypot(s1, w))
    ts, tt = R * math.cos(a), R * math.sin(a)
    z_top = P.EAR_T + P.EAR_HUB_H - P.EDGE
    rib = ear_prism(side, [(ts, -tt), (s1, -w), (s1, w), (ts, tt)], P.EAR_T - 1.0, z_top)
    z_end = P.EAR_T + P.EAR_RIB_H
    k = (z_top - z_end) / (s1 - R)
    slope = [(R, z_top), (s1 + 1.0, z_end - k), (s1 + 1.0, z_top + 2.0), (R, z_top + 2.0)]
    return rib - ear_side_prism(side, slope, P.EAR_W)


def end_face_chamfer(body):
    """small chamfer round the end face against elephant foot, the corner flares need none"""
    y_end = P.TURRET_Y + P.HEAD_OFFSET
    edges = []
    for e in body.edges():
        vs = e.vertices()
        if e.geom_type != GeomType.LINE or any(abs(v.Y - y_end) > 1e-4 for v in vs):
            continue
        a, b = vs[0], vs[1]
        # skip the short ends of the plate at the corner flares
        if abs(a.Z - b.Z) < 1e-4 and abs(abs(a.Z - P.Z_TILT) - ear_end_t()) < 1e-3:
            continue
        edges.append(e)
    return chamfer(edges, P.EAR_FOOT_C)


def ear(side):
    """side -1 is the left ear with the horn, side +1 the right ear with the pivot screw

    the ears print standing on the end face that meets the head, tilt axis level, so the horn
    pocket, the holes and the cap recess all open sideways, their round tops get a 45 degree roof
    and the hub stands on a rib that runs down to the end face
    """
    xi = side * (P.NECK_W / 2 + P.EAR_GAP)
    xo = side * (P.NECK_W / 2 + P.EAR_GAP + P.EAR_T)
    xh = side * (P.NECK_W / 2 + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H)
    lo = min(xi, xo)
    c = (P.TURRET_Y, P.Z_TILT)
    up = (0, -1, 0)  # up on the bed, away from the head
    plate = extrude(ear_plane(lo) * Polygon(*ear_outline(), align=None), P.EAR_T)
    hub = cyl("x", P.EAR_HUB_R, min(xi, xh), max(xi, xh), c)
    # 0.8 chamfer on the hub rim
    hub_ch = cone("x", P.EAR_HUB_R, P.EAR_HUB_R - P.EDGE, xh - side * P.EDGE, xh, c)
    hub = (hub - cyl("x", P.EAR_HUB_R + 1, xh - side * P.EDGE, xh + side * 1, c)) + hub_ch
    s1 = P.HEAD_OFFSET
    body = plate + hub + ear_rib(side)
    cuts = []
    if side < 0:
        # horn pocket, hub and arm snug from the inner face to just past the arm, the arm points to
        # the head and down on the bed, the horn seat stays where the tilt servo expects it
        pd = P.HORN_POCKET_DEPTH
        arm = kit.arm_solid(1, P.HORN_SINGLE_LEN, 0.0, pd + 0.01, grow=P.FIT_SNUG)
        cuts.append(kit.frame_map(arm, (xi + 0.01, P.TURRET_Y, P.Z_TILT), (0, 1, 0), (side, 0, 0)))
        rp = P.HORN_HUB_D / 2 + P.FIT_SNUG
        cuts.append(cyl("x", rp, xi - side * 0.01, xi + side * pd, c))
        cuts.append(roof("x", rp, xi - side * 0.01, xi + side * pd, c, up))
        # screw hole from the pocket floor to the cap recess
        rh = P.HORN_SCREW_HEAD_D / 2 + 0.3
        cuts.append(cyl("x", rh, xh + side * 1, xi + side * (pd - 0.01), c))
        cuts.append(roof("x", rh, xh + side * 1, xi + side * (pd - 0.01), c, up))
    else:
        # pivot screw threads through the whole ear from the countersink to the inner face and turns
        # in the bearing of the neck, the roof of the hole stays inside the thread of the screw
        csk_top = xh - side * P.CAP_T
        h = (P.M3_CSK_D - P.M3_TAP) / 2
        cuts.append(cyl("x", P.M3_TAP / 2, xi - side * 0.01, csk_top, c))
        cuts.append(roof("x", P.M3_TAP / 2, xi - side * 0.01, csk_top, c, up, flat=P.M3_TAP / 2 + 0.15))
        cuts.append(cone("x", P.M3_TAP / 2, P.M3_CSK_D / 2 + 0.01, csk_top - side * h, csk_top + side * 0.01, c))
    # cap recess with a small pry notch on the underside, its roof is flat 0.1 above the round
    cuts.append(cyl("x", P.CAP_D / 2, xh - side * P.CAP_T, xh + side, c))
    cuts.append(roof("x", P.CAP_D / 2, xh - side * P.CAP_T, xh + side, c, up, flat=P.CAP_D / 2 + 0.1))
    cuts.append(box(min(xh, xh - side * P.CAP_T), max(xh, xh - side * P.CAP_T) + 0.0 + 1.0 * (side > 0),
                    P.TURRET_Y - 0.8, P.TURRET_Y + 0.8, P.Z_TILT - P.CAP_D / 2 - 1.0, P.Z_TILT - P.CAP_D / 2 + 0.5))
    # tap holes in the end of the plate for the screws from inside the head, they stand upright on
    # the bed, a 45 degree mouth against elephant foot and a pointed end that needs no bridge
    xu = side * ear_screw_u()
    y_end = P.TURRET_Y + s1
    r = P.M3_TAP / 2
    for v in EAR_SCREWS_V:
        cv = (xu, P.Z_TILT + v)
        cuts.append(cyl("y", r, y_end - P.EAR_SCREW_DEPTH, y_end + 0.1, cv))
        cuts.append(cone("y", r, 0.05, y_end - P.EAR_SCREW_DEPTH, y_end - P.EAR_SCREW_DEPTH - r + 0.05, cv))
        cuts.append(cone("y", r + P.EAR_FOOT_C + 0.01, r, y_end + 0.01, y_end - P.EAR_FOOT_C, cv))
    return end_face_chamfer(body - union_all(cuts))


def cap():
    """copper cap over the horn screw and the pivot screw, three crush ribs hold it"""
    r = P.CAP_D / 2 - 0.1
    c = cyl("z", r, 0.0, P.CAP_T)
    c = c - (cyl("z", r + 1, P.CAP_T - 0.5, P.CAP_T + 1) - cone("z", r, r - 0.5, P.CAP_T - 0.5, P.CAP_T))
    ribs = []
    for k in range(3):
        a = 2 * math.pi * k / 3
        ribs.append(cyl("z", 0.35, 0.3, P.CAP_T - 0.5, (r * math.cos(a), r * math.sin(a))))
    return c + union_all(ribs)


def cap_places():
    """where the caps sit, outer face centre and outward direction"""
    out = []
    for side in (-1, 1):
        xh = side * (P.NECK_W / 2 + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H)
        out.append(((xh - side * P.CAP_T, P.TURRET_Y, P.Z_TILT), (side, 0, 0)))
    return out


def caps_placed():
    out = []
    for origin, d in cap_places():
        out.append(kit.frame_map(cap(), origin, (0, 1, 0), d))
    return out


_ = (poly_prism, hx)
