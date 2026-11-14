"""the neck, a clamshell split on the plane that holds both servo shafts

each half prints lying on its big outer face, so the visible front and back of the neck come
off the bed and every pocket opens upward, no supports
the front half carries the floor of the foot that rides on the lid, two screws from below go
through that floor into the back half, pins line the two halves up
"""

import math

from build123d import Plane, Polygon, extrude, loft

from . import kit
from . import params as P
from .helpers import box, cone, cyl, double_teardrop, poly_prism, rrect_points, stadium_points, teardrop, union_all

N_ARC = 10
CABLE_X = 11.0  # the cable column and the entry in the top sit on the right of the tilt servo
SCREW_XY = ((-21.0, -8.0), (21.5, -8.0))  # foot screws, local x and y, back half side
PIN_D = 3.0


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


def column_x0():
    """left edge of the cable column, a full wall away from both servo pockets"""
    tilt_end = kit.tilt_servo_frame()[0][0]
    pan_end = P.SERVO_SHAFT_FROM_END
    return max(tilt_end, pan_end) + P.FIT_SLIDE + P.NECK_WALL


def pan_holder():
    """solid block around the pan servo, the servo shape is cut out later"""
    hb = box(-P.FOOT_W / 2 + 1, column_x0(), ty() - 14, ty() + 14, z0() + P.FOOT_FLOOR_T - 0.01,
             z0() + P.PAN_BOSS_GAP + P.SERVO_BOSS_TOP + P.FIT_SLIDE + 2.0)
    return hb


def tilt_holder():
    o, _, _ = kit.tilt_servo_frame()
    case_bottom_x = o[0]
    zb = P.Z_TILT - (P.SERVO_L - P.SERVO_SHAFT_FROM_END) - P.SERVO_TAB_LEN - P.FIT_SLIDE - 2.0
    return box(-P.NECK_W / 2 + 0.5, case_bottom_x + P.FIT_SLIDE + 2.0, ty() - 14, ty() + 14, zb, P.NECK_TOP - 1.0)


def grown_servo(frame):
    """servo keep out grown by the sliding fit, made from boxes so it stays simple"""
    o, xd, zd = frame
    g = P.FIT_SLIDE
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    w = P.SERVO_W / 2
    s = box(far - g, near + g, -w - g, w + g, -g, P.SERVO_H + g)
    s += box(far - P.SERVO_TAB_LEN - g, near + P.SERVO_TAB_LEN + g, -w - g, w + g,
             P.SERVO_TAB_Z - g, P.SERVO_TAB_Z + P.SERVO_TAB_T + g)
    s += cyl("z", P.SERVO_BOSS_R + 0.4, P.SERVO_H - 0.1, P.SERVO_BOSS_TOP + P.SERVO_SPLINE_LEN + 4)
    return kit.frame_map(s, o, xd, zd)


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
    cuts = []
    cuts.append(grown_servo(kit.pan_servo_frame()))
    cuts.append(grown_servo(kit.tilt_servo_frame()))
    # lead channels, pan lead leaves the far end and climbs, tilt lead drops from its far end
    po, _, _ = kit.pan_servo_frame()
    pan_lead_z = po[2] - P.SERVO_LEAD_Z
    far_x = P.SERVO_SHAFT_FROM_END - P.SERVO_L
    inside = cavity()
    cuts.append(box(far_x - 6.0, far_x + 0.5, t - 3.0, t + 3.0, pan_lead_z - 3.0, po[2] + 6.0) & inside)
    cuts.append(box(far_x - 6.0, 10.0, t - 3.0, t + 3.0, po[2] + P.FIT_SLIDE + 2.0, po[2] + 8.0) & inside)
    to, _, _ = kit.tilt_servo_frame()
    tilt_lead_x = to[0] - P.SERVO_LEAD_Z
    tilt_far_z = P.Z_TILT - (P.SERVO_L - P.SERVO_SHAFT_FROM_END)
    cuts.append(box(tilt_lead_x - 3.0, tilt_lead_x + 3.0, t - 3.0, t + 3.0, tilt_far_z - 12.0, tilt_far_z + 0.5) & inside)
    cuts.append(box(tilt_lead_x - 3.0, 18.0, t - 3.0, t + 3.0, tilt_far_z - 12.0, tilt_far_z - 4.0) & inside)
    # cable column on the right of both servos, top to bottom, it follows the inside of the wall
    col_x0 = column_x0()
    cuts.append(box(col_x0, P.FOOT_W / 2, t - 13.0, t + 13.0, z0() + P.FOOT_FLOOR_T, P.NECK_TOP) & inside)
    # over the tilt servo the cables come in from the top entry
    cuts.append(box(col_x0, P.FOOT_W / 2, t - 6.0, t + 6.0, P.Z_TILT, P.NECK_TOP) & inside)
    # the pan servo case rests on the foot floor, no thin plate under it
    near, far = P.SERVO_SHAFT_FROM_END, P.SERVO_SHAFT_FROM_END - P.SERVO_L
    case_top = po[2] - P.SERVO_H + P.FIT_SLIDE
    cuts.append(box(far - P.FIT_SLIDE, near + P.FIT_SLIDE, t - P.SERVO_W / 2 - P.FIT_SLIDE, t + P.SERVO_W / 2 + P.FIT_SLIDE,
                    z0() + P.FOOT_FLOOR_T - 0.01, case_top))
    # entry slot in the top face
    cuts.append(poly_prism(stadium_points(CABLE_X, t, 12.0, 8.0, 0.0), P.NECK_TOP - P.NECK_WALL - 1, P.NECK_TOP + 1))
    # pan boss hole and cable exit in the foot floor, roofed toward the back because the
    # floor prints standing up with the front half
    up = (0, -1, 0)
    fz0, fz1 = z0() - 1, z0() + P.FOOT_FLOOR_T + 1
    cuts.append(teardrop("z", P.SERVO_BOSS_R + 0.55, fz0, fz1, (0.0, t), up))
    cuts.append(poly_prism(exit_outline(), fz0, fz1))
    # tilt servo boss through the left wall
    cuts.append(cyl("x", P.SERVO_BOSS_R + 0.4, -P.NECK_W / 2 - 3.0, -P.NECK_W / 2 + P.NECK_WALL + 1.5, (t, P.Z_TILT)))
    body = body - union_all(cuts)
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
        cuts_b.append(teardrop("z", P.M3_TAP / 2, zf + P.FOOT_FLOOR_T - 0.5, zf + P.FOOT_FLOOR_T + 8.0, (x, y), (0, 1, 0)))
    # alignment pins on the back half, holes in the front half
    pin_spots = [(-21.0, z0() + 5.7), (-6.0, P.Z_TILT - 20.0), (-2.0, P.Z_TILT + 9.0), (21.5, z0() + 6.0)]
    for x, z in pin_spots:
        add_b.append(cyl("y", PIN_D / 2, t - 0.01, t + 3.0, (x, z)))
        cuts_f.append(cyl("y", PIN_D / 2 + P.FIT_SNUG, t - 0.01, t + 3.6, (x, z)))
    front = front - union_all(cuts_f)
    back = (back + union_all(add_b)) - union_all(cuts_b)
    return front, back

