"""the neck, a clamshell split on the plane that holds both servo shafts

each half prints lying on its big outer face, so the visible front and back of the neck come
off the bed and every pocket opens upward, no supports
the front half carries the floor of the foot that rides on the lid, two screws from below go
through that floor into the back half, pins line the two halves up

assembly: the front half lies on its front face, the pan servo goes in a little higher than its
place and slides down until its tabs sit, so both bosses drop into the keyhole of the floor
the tilt servo drops in with its bosses in the half keyhole of the left wall, both leads leave
their servo at the spline end and run down the cable column to the exit in the floor
then the back half goes on, its crush ribs take the play out of both cases and two screws pull
it down
every plug goes down through the wide opening around the exit before the foot sits on the lid
"""

import math

from build123d import Plane, Polygon, extrude, loft

from . import kit
from . import params as P
from .helpers import box, cone, cyl, double_teardrop, poly_prism, rrect_points, stadium_points, teardrop, union_all

N_ARC = 10
CABLE_X = 11.0  # the cable column and the entry in the top sit on the right of the tilt servo
SCREW_XY = ((-21.0, -8.0), (21.5, -8.0))  # foot screws, local x and y, back half side
SCREW_DEPTH = 6.0  # tap hole above the floor, the M3x8 ends 5.6 above it, the hole stays under the tab slot
PIN_D = 3.0
LEAD_CLEAR = 1.0  # air above the lead in its relief
RIB_SPOTS = 8.0  # height of the crush ribs and bumps above the case bottom, between the lead and the tabs
BUMP_IN = 3.5  # bumps on the long sides this far in from each case end
OPENING_ROUND = 2.5  # corner radius of the wide cable opening at its front end
OPENING_CHAMFER = 1.0  # 45 degree corners under the flat bridge at its back end


def ty():
    return P.TURRET_Y


def z0():
    return P.BASE_TOP


def plan(w, d, r, z, y0=None):
    pts = rrect_points(w, d, r, 0.0, ty() if y0 is None else y0, n=N_ARC, tear_y=True)
    return Plane.XY.offset(z) * Polygon(*pts, align=None)


def column_plan(inset=0.0, z_bottom=None, z_top=None):
    """foot, 45 degree flare and neck as one plan lofted solid"""
    w_f, w_n, d = P.FOOT_W - 2 * inset, P.NECK_W - 2 * inset, P.NECK_D - 2 * inset
    r = max(P.R_SMALL - inset, 1.0)
    zb = z0() if z_bottom is None else z_bottom
    zt = P.NECK_TOP + 1 if z_top is None else z_top
    # an inset 45 degree flare moves down so the wall keeps its full thickness
    zf = z0() + P.FOOT_H - inset * (math.sqrt(2) - 1)
    zn = zf + P.FOOT_FLARE_H
    foot = extrude(plan(w_f, d, r, zb), zf - zb)
    flare = loft([plan(w_f, d, r, zf), plan(w_n, d, r, zn)], ruled=True)
    neck = extrude(plan(w_n, d, r, zn), zt - zn)
    return foot + flare + neck


def front_profile(inset=0.0):
    """outline seen from the front in the x z plane, rounded top corners"""
    hw_f, hw_n = P.FOOT_W / 2 - inset, P.NECK_W / 2 - inset
    zb = z0() + inset
    zf = z0() + P.FOOT_H
    zn = zf + P.FOOT_FLARE_H
    zt = P.NECK_TOP - inset
    r = max(P.R_SMALL - inset, 1.0)
    c = P.EDGE
    pts = [(-hw_f + c, zb), (hw_f - c, zb), (hw_f, zb + c), (hw_f, zf), (hw_n, zn)]
    for i in range(N_ARC + 1):
        a = math.radians(90 * i / N_ARC)
        pts.append((hw_n - r + r * math.cos(a), zt - r + r * math.sin(a)))
    for i in range(N_ARC + 1):
        a = math.radians(90 + 90 * i / N_ARC)
        pts.append((-hw_n + r + r * math.cos(a), zt - r + r * math.sin(a)))
    pts += [(-hw_n, zn), (-hw_f, zf), (-hw_f, zb + c)]
    return pts


def side_profile(inset=0.0):
    """outline seen from the side in the y z plane, 45 degree chamfers on the top edges"""
    hd = P.NECK_D / 2 - inset
    zb = z0() + inset
    zt = P.NECK_TOP - inset
    ch = max(P.NECK_TOP_CHAMFER - inset * 0.4, 1.0)
    c = P.EDGE
    t = ty()
    return [(t - hd + c, zb), (t + hd - c, zb), (t + hd, zb + c), (t + hd, zt - ch), (t + hd - ch, zt),
            (t - hd + ch, zt), (t - hd, zt - ch), (t - hd, zb + c)]


def xz_prism(pts, y0, y1):
    pl = Plane(origin=(0, y0, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    # plane local y is minus z here, flip the points
    face = Polygon(*[(x, -z) for x, z in pts][::-1], align=None)
    return extrude(pl * face, y1 - y0)


def yz_prism(pts, x0, x1):
    pl = Plane(origin=(x0, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
    face = Polygon(*pts, align=None)
    return extrude(pl * face, x1 - x0)


def outer():
    col = column_plan()
    col = col & xz_prism(front_profile(), ty() - 20, ty() + 20)
    col = col & yz_prism(side_profile(), -40, 40)
    return col


def cavity():
    w = P.NECK_WALL
    inner = column_plan(inset=w, z_bottom=z0() + P.FOOT_FLOOR_T)
    inner = inner & xz_prism(front_profile(inset=w), ty() - 20, ty() + 20)
    inner = inner & yz_prism(side_profile(inset=w), -40, 40)
    return inner & box(-40, 40, ty() - 20, ty() + 20, z0() + P.FOOT_FLOOR_T, P.NECK_TOP - w)


# the servo pockets, sizes in the local frame of kit.servo_local: case bottom at z = 0, spline on
# the z axis, the case toward minus x


def side_air():
    """air on each side and end of the case, room for a larger case and a snug fit on top"""
    return P.SERVO_PLAY + P.FIT_SNUG


def axial_air():
    """air at the case bottom past the screw heads and at the top cover, along the shaft"""
    return P.SERVO_PLAY + P.FIT_SLIDE


def pocket_bottom():
    """local z of the pocket wall behind the case bottom"""
    return -(P.SERVO_SCREW_PROUD + axial_air())


def pan_slide():
    """the pan servo goes into the front half this much higher and slides down, so the spline and
    both bosses pass over the foot floor and then drop into its keyhole"""
    return P.FOOT_FLOOR_T - P.PAN_BOSS_GAP + P.SERVO_SPLINE_LEN + 0.6


def column_x0():
    """left edge of the cable column, a full wall away from both servo pockets"""
    tilt_end = kit.tilt_servo_frame()[0][0] - pocket_bottom()
    pan_end = P.SERVO_SHAFT_FROM_END + side_air()
    return max(tilt_end, pan_end) + P.NECK_WALL


def pan_holder():
    """solid block around the pan servo, the servo shape is cut out later"""
    po, _, _ = kit.pan_servo_frame()
    hb = box(-P.FOOT_W / 2 + 1, column_x0(), ty() - 14, ty() + 14, z0() + P.FOOT_FLOOR_T - 0.01,
             po[2] - pocket_bottom() + 2.0)
    return hb


def tilt_holder():
    o, _, _ = kit.tilt_servo_frame()
    case_bottom_x = o[0]
    zb = P.Z_TILT - (P.SERVO_L - P.SERVO_SHAFT_FROM_END) - P.SERVO_TAB_LEN - axial_air() - 2.0
    return box(-P.NECK_W / 2 + 0.5, case_bottom_x - pocket_bottom() + 2.0, ty() - 14, ty() + 14, zb,
               P.NECK_TOP - 1.0)


def servo_pocket(frame, slide=0.0):
    """case and tabs of one servo with their air, in the device frame
    slide makes the pocket longer behind the case bottom, the servo goes in that much nearer its
    case bottom and slides toward its bosses into place, the face of each tab slot toward the
    bosses is the seat"""
    o, xd, zd = frame
    a = side_air()
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    w = P.SERVO_W / 2 + a
    zb = pocket_bottom() - slide
    s = box(far - a, near + a, -w, w, zb, P.SERVO_H + axial_air())
    ta = axial_air()
    s += box(far - P.SERVO_TAB_LEN - ta, near + P.SERVO_TAB_LEN + ta, -w, w,
             P.SERVO_TAB_Z - P.FIT_SLIDE - slide, P.SERVO_TAB_Z + P.SERVO_TAB_T)
    return kit.frame_map(s, o, xd, zd)


def lead_relief(frame, reach, slide=0.0):
    """room for the flat lead where it leaves the near end at the case bottom, across the whole
    width so it may sit on either long side, reach is how far it goes past the pocket end"""
    o, xd, zd = frame
    a = side_air()
    near = P.SERVO_SHAFT_FROM_END
    w = P.SERVO_W / 2 + a
    top = P.SERVO_LEAD_Z + P.SERVO_LEAD_T / 2 + LEAD_CLEAR
    s = box(near - 0.5, near + a + reach, -w, w, pocket_bottom() - slide, top)
    return kit.frame_map(s, o, xd, zd)


def convex_hull(pts):
    """convex hull of 2d points, counterclockwise, monotone chain"""
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))

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


def clip_below(pts, v_max):
    """the part of a convex polygon with y at most v_max"""
    out = []
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        pin, qin = p[1] <= v_max, q[1] <= v_max
        if pin:
            out.append(p)
        if pin != qin:
            k = (v_max - p[1]) / (q[1] - p[1])
            out.append((p[0] + k * (q[0] - p[0]), v_max))
    return out


def keyhole_points(roof=0, n=48):
    """outline of the gear boss and the small boss as one keyhole with straight sides, both grown
    by the boss air, local x and y of the servo
    roof 1 or -1 adds a 45 degree roof toward plus or minus local y for a hole that prints lying,
    cut flat as high as the gear boss circle"""
    r1 = P.SERVO_BOSS_R + P.SERVO_BOSS_AIR
    r2 = P.SERVO_BOSS2_R + P.SERVO_BOSS_AIR
    c2 = -P.SERVO_BOSS2_X
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((r1 * math.cos(a), r1 * math.sin(a)))
        pts.append((c2 + r2 * math.cos(a), r2 * math.sin(a)))
    if roof:
        # the 45 degree tangents of both circles meet over the keyhole
        k1 = r1 * math.sqrt(2)
        k2 = r2 * math.sqrt(2) - c2
        pts.append(((k1 - k2) / 2, (k1 + k2) / 2))
    out = convex_hull(pts)
    if roof:
        out = clip_below(out, r1)
        out = [(x, roof * y) for x, y in out]
        if roof < 0:
            out = out[::-1]
    return out


def boss_keyhole(frame, roof=0):
    """the keyhole for both bosses from the top cover out through the wall or the floor"""
    o, xd, zd = frame
    s = poly_prism(keyhole_points(roof), P.SERVO_H - 0.1, P.SERVO_BOSS_TOP + P.SERVO_SPLINE_LEN + 4)
    return kit.frame_map(s, o, xd, zd)


def rib_along_y(base, normal, across, h, y_end, y_wall, taper=1.2):
    """crush rib with a 90 degree point on a pocket wall, it runs along local y from the parting
    plane side y_end to the floor of the pocket y_wall and gets lower toward y_end so the case
    finds its way in, base is the middle of its foot on the wall, local frame"""
    bx, bz = base
    nx, nz = normal
    ex, ez = across
    s = 1.0 if y_wall > y_end else -1.0

    def section(y, hh):
        foot = hh + 0.05
        pts = [(bx - 0.05 * nx - foot * ex, bz - 0.05 * nz - foot * ez),
               (bx + hh * nx, bz + hh * nz),
               (bx - 0.05 * nx + foot * ex, bz - 0.05 * nz + foot * ez)]
        pl = Plane(origin=(0, y, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
        # plane local y is minus z here
        return pl * Polygon(*[(x, -z) for x, z in pts], align=None)

    taper_y = y_end + s * taper
    lead_in = loft([section(y_end, 0.05), section(taper_y, h)], ruled=True)
    body = loft([section(taper_y, h), section(y_wall + s * 0.05, h)], ruled=True)
    return lead_in + body


def crush_ribs(frame):
    """crush ribs of one pocket in the device frame
    bumps on both long sides hold the case across, they sit in both halves
    the ribs on the case ends and on the tab slots sit in the back half only, it goes on last,
    so they push the case to the middle and the tabs onto their seats"""
    o, xd, zd = frame
    a = side_air()
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    w = P.SERVO_W / 2 + a
    h = a + P.SERVO_RIB_BITE
    zc = RIB_SPOTS
    bumps, ribs = [], []
    for sy in (1, -1):
        for x in (far + BUMP_IN, near - BUMP_IN):
            bumps.append(cone("y", 0.6, 0.15, sy * (w + 0.05), sy * (w - h), (x, zc)))
        # case ends, from the parting plane to the long side
        ribs.append(rib_along_y((far - a, zc), (1, 0), (0, 1), h, sy * 0.2, sy * w))
        ribs.append(rib_along_y((near + a, zc), (-1, 0), (0, 1), h, sy * 0.2, sy * w))
        # tab slots, the rib presses the tab onto the seat, it stays clear of the hole in the tab
        ht = P.FIT_SLIDE + P.SERVO_RIB_BITE
        zs = P.SERVO_TAB_Z - P.FIT_SLIDE
        for x in (far - P.SERVO_TAB_LEN / 2, near + P.SERVO_TAB_LEN / 2):
            ribs.append(rib_along_y((x, zs), (0, 1), (1, 0), ht, sy * 2.0, sy * w))
    t = ty()
    back = box(-60, 60, t - 40, t - 0.01, 0, 200)
    out = kit.frame_map(union_all(bumps), o, xd, zd)
    return out + (kit.frame_map(union_all(ribs), o, xd, zd) & back)


def exit_outline():
    """cable exit in the foot floor, round toward the front, pointed toward the back"""
    r = P.EXIT_W / 2
    half = P.EXIT_L / 2 - r
    cx, cy = P.SLOT_R, ty()
    pts = []
    for i in range(13):
        a = math.radians(180 * i / 12)
        pts.append((cx + r * math.cos(a), cy + half + r * math.sin(a)))
    for i in range(7):
        a = math.radians(180 + 45 * i / 6)
        pts.append((cx + r * math.cos(a), cy - half + r * math.sin(a)))
    pts.append((cx, cy - half - r * math.sqrt(2)))
    for i in range(7):
        a = math.radians(315 + 45 * i / 6)
        pts.append((cx + r * math.cos(a), cy - half + r * math.sin(a)))
    return pts[:-1]


def opening_outline():
    """wide cable opening in the foot floor around the exit, all seven plugs pass it before the
    neck goes onto the lid
    it runs from the foot of the column wall out to the kept floor around the countersink of the
    right foot screw and along the outer edge, the pin block stands further out
    the back end is the top while the front half prints, a flat bridge with 45 degree corners"""
    t = ty()
    x0 = column_x0()
    x1 = SCREW_XY[1][0] - P.M3_CSK_D / 2 - P.EXIT_KEEP
    half = P.NECK_D / 2 - P.EDGE - P.EXIT_KEEP
    r, c = OPENING_ROUND, OPENING_CHAMFER
    pts = [(x0 + c, t - half), (x1 - c, t - half), (x1, t - half + c)]
    for i in range(N_ARC + 1):
        a = math.radians(90 * i / N_ARC)
        pts.append((x1 - r + r * math.cos(a), t + half - r + r * math.sin(a)))
    for i in range(N_ARC + 1):
        a = math.radians(90 + 90 * i / N_ARC)
        pts.append((x0 + r + r * math.cos(a), t + half - r + r * math.sin(a)))
    pts.append((x0, t - half + c))
    return pts


def build():
    """both halves at their place in the device frame, pan 0"""
    t = ty()
    shell = outer() - cavity()
    add = [shell, pan_holder(), tilt_holder()]
    # screw bosses for the foot screws, they belong to the back half
    for sx, sy in SCREW_XY:
        add.append(cyl("z", 3.6, z0() + P.FOOT_FLOOR_T - 0.01, z0() + P.FOOT_FLOOR_T + 9.0, (sx, t + sy)))
    body = union_all(add)
    # keep the outside clean, holders and bosses must not poke through
    body = body & outer()
    pan, tilt = kit.pan_servo_frame(), kit.tilt_servo_frame()
    po, to = pan[0], tilt[0]
    inside = cavity()
    front = box(-50, 50, t, t + 30, z0() - 1, P.NECK_TOP + 2)
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    a = side_air()
    w = P.SERVO_W / 2 + a
    col_x0 = column_x0()
    cuts = [servo_pocket(pan), servo_pocket(tilt)]
    # in the front half the pan servo goes in higher and slides down onto its seats
    cuts.append(servo_pocket(pan, pan_slide()) & front)
    # pan lead from the near end through the wall into the cable column
    cuts.append(lead_relief(pan, P.NECK_WALL + 1.0) & inside)
    cuts.append(lead_relief(pan, P.NECK_WALL + 1.0, pan_slide()) & front & inside)
    # tilt lead out of the top end, over to the column under the top wall
    cuts.append(lead_relief(tilt, 6.0) & inside)
    lead_x0 = to[0] - (P.SERVO_LEAD_Z + P.SERVO_LEAD_T / 2 + LEAD_CLEAR)
    cuts.append(box(lead_x0, col_x0 + 0.5, t - w, t + w, P.Z_TILT + near - 0.5, P.NECK_TOP) & inside)
    # cable column on the right of both servos, top to bottom, it follows the inside of the wall
    cuts.append(box(col_x0, P.FOOT_W / 2, t - 13.0, t + 13.0, z0() + P.FOOT_FLOOR_T, P.NECK_TOP) & inside)
    # over the tilt servo the cables come in from the top entry
    cuts.append(box(col_x0, P.FOOT_W / 2, t - 6.0, t + 6.0, P.Z_TILT, P.NECK_TOP) & inside)
    # the pan servo hangs on its tabs, no thin plate between its top cover and the foot floor
    case_top = po[2] - P.SERVO_H - axial_air()
    cuts.append(box(far - a, near + a, t - w, t + w, z0() + P.FOOT_FLOOR_T - 0.01, case_top + 0.01))
    # entry slot in the top face
    cuts.append(poly_prism(stadium_points(CABLE_X, t, 12.0, 8.0, 0.0), P.NECK_TOP - P.NECK_WALL - 1, P.NECK_TOP + 1))
    # keyhole for both pan bosses and the cable exit in the foot floor, roofed toward the back
    # because the floor prints standing up with the front half, plus y of the pan servo is the back
    fz0, fz1 = z0() - 1, z0() + P.FOOT_FLOOR_T + 1
    cuts.append(boss_keyhole(pan, roof=1))
    # the exit also goes up through the foot of the pocket wall so the cables come up straight
    cuts.append(poly_prism(exit_outline(), fz0, fz1 + 3.0))
    # keyhole for both tilt bosses through the left wall, it splits on the parting plane
    cuts.append(boss_keyhole(tilt))
    body = body - union_all(cuts)
    # crush ribs, added after the pockets are cut
    body = body + crush_ribs(pan) + crush_ribs(tilt)
    # pivot boss inside the right wall and a pin block, added after the cable column is cut
    # the pivot boss hangs off the split face while printing, so it gets a roof on both sides
    late = [double_teardrop("x", P.PIVOT_BOSS_R, P.PIVOT_BOSS_X0, P.NECK_W / 2 - 0.5, (t, P.Z_TILT), (0, 1, 0))]
    late.append(box(19.0, P.FOOT_W / 2 - 1.0, t - 4.0, t + 4.0, z0() + P.FOOT_FLOOR_T - 0.01, z0() + 9.0))
    body = (body + union_all(late)) & outer()
    # bearing for the pivot screw on the right
    body = body - cyl("x", P.M3_CLEAR / 2, P.PIVOT_BOSS_X0 - 1.0, P.NECK_W / 2 + 3.0, (t, P.Z_TILT))
    return body


def parting_groove():
    """0.8 wide groove along the parting line and around the plinth"""
    g = P.GAP / 2
    t = ty()
    ring = xz_prism(front_profile(), t - g, t + g) - xz_prism(front_profile(inset=g), t - g - 1, t + g + 1)
    ring = ring & box(-40, 40, t - 20, t + 20, z0() + P.FOOT_FLOOR_T - g, P.NECK_TOP + 1)
    plinth = box(-40, 40, t - 20, t + 20, z0() + P.FOOT_FLOOR_T - g, z0() + P.FOOT_FLOOR_T + g)
    plinth = plinth - column_plan(inset=g, z_bottom=z0(), z_top=z0() + 10)
    return ring + plinth


def halves():
    """front half with the floor, back half without it"""
    t = ty()
    body = build()
    groove = parting_groove()
    floor_top = z0() + P.FOOT_FLOOR_T
    front_keep = box(-50, 50, t, t + 30, z0() - 1, P.NECK_TOP + 2) + box(-50, 50, t - 30, t, z0() - 1, floor_top)
    back_keep = box(-50, 50, t - 30, t, floor_top, P.NECK_TOP + 2)
    front = (body & front_keep) - groove
    # the wide opening only cuts the floor, the column wall and the back half keep the exit as before
    front = front - poly_prism(opening_outline(), z0() - 1, floor_top + 1)
    back = (body & back_keep) - groove
    front, back = add_screws_and_pins(front, back)
    return front, back


def add_screws_and_pins(front, back):
    t = ty()
    zf = z0()
    cuts_f, cuts_b, add_b = [], [], []
    for sx, sy in SCREW_XY:
        x, y = sx, t + sy
        # countersunk clearance through the floor from below
        cuts_f.append(teardrop("z", P.M3_CLEAR / 2, zf - 1, zf + P.FOOT_FLOOR_T + 1, (x, y), (0, -1, 0)))
        h = (P.M3_CSK_D - P.M3_CLEAR) / 2
        cuts_f.append(cone("z", P.M3_CSK_D / 2 + 0.01, P.M3_CLEAR / 2, zf - 0.01, zf + h, (x, y)))
        # tap hole in the back half boss, horizontal while printing so it gets a roof
        cuts_b.append(teardrop("z", P.M3_TAP / 2, zf + P.FOOT_FLOOR_T - 0.5, zf + P.FOOT_FLOOR_T + SCREW_DEPTH, (x, y),
                               (0, 1, 0)))
    # alignment pins on the back half, holes in the front half
    pin_spots = [(-21.0, z0() + 5.7), (-6.0, P.Z_TILT - 20.0), (-2.0, P.Z_TILT + 9.0), (21.5, z0() + 6.0)]
    for x, z in pin_spots:
        add_b.append(cyl("y", PIN_D / 2, t - 0.01, t + 3.0, (x, z)))
        cuts_f.append(cyl("y", PIN_D / 2 + P.FIT_SNUG, t - 0.01, t + 3.6, (x, z)))
    front = front - union_all(cuts_f)
    back = (back + union_all(add_b)) - union_all(cuts_b)
    return front, back

