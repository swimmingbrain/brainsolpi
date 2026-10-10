"""the base: tray, lid and four small feet

the lid stands on four columns that reach down to the tray floor, a screw from below goes
through each foot and the floor into its column, so no screw shows from the side or the top
the columns also set the shadow gap between lid and tray
"""

import math

from build123d import Axis, Plane

from . import kit
from . import params as P
from .helpers import arc_slot_points, box, cone, cyl, poly_prism, rrect_prism, stadium_points, union_all

COLUMN_XY = [
    (sx * (P.BASE_W / 2 - P.COLUMN_INSET), sy * (P.BASE_D / 2 - P.COLUMN_INSET))
    for sx in (1, -1)
    for sy in (1, -1)
]
SPIGOT_D = 6.0
SPIGOT_RECESS = 0.2  # the spigot ends short of the floor underside so the foot clamps the floor


def inner_size():
    return P.BASE_W - 2 * P.WALL, P.BASE_D - 2 * P.WALL, P.R_BIG - P.WALL


def pi_hole_xy():
    return [kit.pi_to_device(X, Y) for X, Y in P.PI_HOLES]


def uno_hole_xy():
    return [kit.uno_to_device(u, w) for i, (u, w) in enumerate(P.UNO_HOLES) if i in P.UNO_USED_HOLES]


def coil_posts():
    return [(-24.0, 50.0), (16.0, 50.0)]


def power_notch_x():
    # the micro usb plug ends near x = 4, the cable turns back to the rear wall there
    return 6.0


def tray():
    iw, idp, ir = inner_size()
    outer = rrect_prism(P.BASE_W, P.BASE_D, P.R_BIG, P.TRAY_Z0, P.TRAY_TOP, cb=P.EDGE, ct=0.4)
    cavity = rrect_prism(iw, idp, ir, P.FLOOR_TOP, P.TRAY_TOP + 1.0)
    t = outer - cavity
    cut = []
    # chamfered lead in, made as a thin wedge ring
    cut.append(cone_ring_lead(iw, idp, ir))
    # column holes in the floor
    for x, y in COLUMN_XY:
        cut.append(cyl("z", SPIGOT_D / 2 + P.FIT_SLIDE, P.TRAY_Z0 - 1, P.FLOOR_TOP + 1, (x, y)))
    # intake vents under the pi
    px0 = P.PI_X0 - P.PI_W + 6.0
    px1 = P.PI_X0 - 4.0
    n = int((px1 - px0) / P.VENT_PITCH) + 1
    xs = [px0 + i * P.VENT_PITCH for i in range(n)]
    for x in xs:
        cut.append(poly_prism(stadium_points(x, -26.0, 44.0, P.VENT_W, 90.0), P.TRAY_Z0 - 1, P.FLOOR_TOP + 1))
    # exhaust vents in the back wall behind the pi
    for x in xs:
        pts = stadium_points(x, 31.5, 15.0, P.VENT_W, 90.0)
        pl = Plane(origin=(0, -P.BASE_D / 2 + P.WALL + 1, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))
        cut.append(poly_prism(pts, 0, P.WALL + 2, plane=pl))
    # notch for the pi power cable at the bottom of the back wall
    nx = power_notch_x()
    cut.append(box(nx - 2.25, nx + 2.25, -P.BASE_D / 2 - 1, -P.BASE_D / 2 + P.WALL + 0.5, P.TRAY_Z0 - 1, P.TRAY_Z0 + 6.0))
    cut.append(cyl("y", 2.25, -P.BASE_D / 2 - 1, -P.BASE_D / 2 + P.WALL + 0.5, (nx, P.TRAY_Z0 + 6.0)))
    t = t - union_all(cut)
    add = []
    # pi standoffs with pins, the lid fingers keep the board down
    for x, y in pi_hole_xy():
        add.append(cyl("z", 3.0, P.FLOOR_TOP - 0.01, P.FLOOR_TOP + P.PI_STANDOFF, (x, y)))
        add.append(cyl("z", P.PI_PIN_D / 2, P.FLOOR_TOP, P.FLOOR_TOP + P.PI_STANDOFF + P.PI_T + 1.5, (x, y)))
        add.append(cone("z", P.PI_PIN_D / 2, 0.8, P.FLOOR_TOP + P.PI_STANDOFF + P.PI_T + 1.5,
                        P.FLOOR_TOP + P.PI_STANDOFF + P.PI_T + 2.3, (x, y)))
    # two low posts in the front bay to wind the spare usb cable around
    for x, y in coil_posts():
        add.append(cyl("z", 6.0, P.FLOOR_TOP - 0.01, P.FLOOR_TOP + 12.0, (x, y)))
    t = t + union_all(add)
    return t


def cone_ring_lead(iw, idp, ir):
    """45 degree lead in on the inner top edge of the tray wall"""
    c = 0.6
    a = rrect_prism(iw + 2 * c, idp + 2 * c, ir + c, P.TRAY_TOP - 0.001, P.TRAY_TOP + 0.5)
    b = rrect_prism(iw + 2 * c, idp + 2 * c, ir + c, P.TRAY_TOP - c, P.TRAY_TOP + 0.001, cb=c)
    return a + b


def lid_turret_cuts():
    """horn pocket, hub hole and the cable slot around the pan axis"""
    tx, ty = P.TURRET_X, P.TURRET_Y
    o, xdir, zdir = kit.pan_horn_frame()
    arm_top = o[2]
    arm_bottom = arm_top - P.HORN_ARM_T
    ceiling = arm_top + P.PAN_HORN_PLAY
    cuts = []
    # arm pocket, the arm points to the left, snug so it does not rattle
    arm = place_arm_left(P.HORN_SINGLE_LEN, arm_bottom - 3.0, ceiling)
    cuts.append(arm)
    cuts.append(cyl("z", P.HORN_HUB_D / 2 + P.FIT_SNUG, arm_bottom - 3.0, ceiling, (tx, ty)))
    # hub hole through the thin plate that stays over the arm
    cuts.append(cyl("z", P.HORN_HUB_D / 2 + 0.3, ceiling - 0.01, P.BASE_TOP + 1, (tx, ty)))
    # arc slot for the cables, centred on the right side, swings with the pan angle
    pts = arc_slot_points(tx, ty, P.SLOT_R, P.SLOT_W, -P.SLOT_HALF_ANGLE, P.SLOT_HALF_ANGLE)
    cuts.append(poly_prism(pts, arm_bottom - 3.0, P.BASE_TOP + 1))
    return cuts, arm_bottom


def place_arm_left(length, z0, z1):
    s = kit.arm_solid(1, length, z0, z1, grow=P.FIT_SNUG)
    s = s.rotate(Axis.Z, 180)
    return s.translate((P.TURRET_X, P.TURRET_Y, 0))


def lid():
    iw, idp, ir = inner_size()
    plate = rrect_prism(P.BASE_W, P.BASE_D, P.R_BIG, P.LID_BOTTOM, P.BASE_TOP, cb=0.4, ct=P.EDGE)
    sk_w, sk_d, sk_r = iw - 2 * P.FIT_SLIDE, idp - 2 * P.FIT_SLIDE, ir - P.FIT_SLIDE
    skirt = rrect_prism(sk_w, sk_d, sk_r, P.LID_BOTTOM - P.LID_SKIRT_H, P.LID_BOTTOM + 0.01, cb=0.6)
    skirt = skirt - rrect_prism(sk_w - 2 * P.LID_SKIRT_T, sk_d - 2 * P.LID_SKIRT_T, sk_r - P.LID_SKIRT_T,
                                P.LID_BOTTOM - P.LID_SKIRT_H - 1, P.LID_BOTTOM + 0.1)
    add = [plate, skirt]
    cuts, arm_bottom = lid_turret_cuts()
    # pad under the lid around the horn so the pocket has full depth
    pad_z0 = arm_bottom - 0.4
    add.append(cyl("z", 9.0, pad_z0, P.LID_BOTTOM + 0.01, (P.TURRET_X, P.TURRET_Y)))
    add.append(box(P.TURRET_X - P.HORN_SINGLE_LEN - 3.0, P.TURRET_X, P.TURRET_Y - 6.0, P.TURRET_Y + 6.0,
                   pad_z0, P.LID_BOTTOM + 0.01))
    add.append(slot_rim(pad_z0))
    # columns down to the floor with a spigot through it
    for x, y in COLUMN_XY:
        add.append(cyl("z", P.COLUMN_D / 2, P.FLOOR_TOP, P.LID_BOTTOM + 0.01, (x, y)))
        add.append(cyl("z", SPIGOT_D / 2, P.TRAY_Z0 + SPIGOT_RECESS, P.FLOOR_TOP + 0.01, (x, y)))
    # posts the uno hangs from, the board top faces the lid
    uno_top = kit.uno_origin()[2] + P.UNO_T
    for x, y in uno_hole_xy():
        add.append(cyl("z", P.UNO_POST_D / 2, uno_top, P.LID_BOTTOM + 0.01, (x, y)))
    # fingers that keep the pi on its pins
    pi_top = kit.pi_z0() + P.PI_T
    for x, y in pi_hole_xy():
        add.append(cyl("z", P.PI_FINGER_D / 2, pi_top + 0.3, P.LID_BOTTOM + 0.01, (x, y)))
    # two stiffening ribs that stay clear of the electronics
    add.append(box(-60.0, 66.0, 44.2, 45.8, P.LID_BOTTOM - 5.0, P.LID_BOTTOM + 0.01))
    add.append(box(-47.0, -45.4, -64.0, 64.0, P.LID_BOTTOM - 5.0, P.LID_BOTTOM + 0.01))
    lid_s = union_all(add)
    # holes
    for x, y in COLUMN_XY:
        cuts.append(cyl("z", P.M3_TAP / 2, P.TRAY_Z0 - 1, P.TRAY_Z0 + 10.0, (x, y)))
        cuts.append(cone("z", 1.7, P.M3_TAP / 2, P.TRAY_Z0 + SPIGOT_RECESS - 0.01, P.TRAY_Z0 + SPIGOT_RECESS + 0.6, (x, y)))
    for x, y in uno_hole_xy():
        cuts.append(cyl("z", P.M3_TAP / 2, uno_top - 1, uno_top + 9.0, (x, y)))
        cuts.append(cone("z", 1.7, P.M3_TAP / 2, uno_top - 0.01, uno_top + 0.6, (x, y)))
    for x, y in pi_hole_xy():
        cuts.append(cyl("z", (P.PI_PIN_D + 0.5) / 2, pi_top - 1, pi_top + 4.0, (x, y)))
    cuts.append(mark_cut())
    lid_s = lid_s - union_all(cuts)
    # posts next to the dc jack and the digital header get a notch
    lid_s = lid_s - uno_clearance()
    return lid_s


def uno_clearance():
    """grown boxes of the uno parts that sit next to the posts"""
    t = P.UNO_T
    c = 0.4
    parts = [
        (-P.UNO_DC_OVERHANG, 12.0, P.UNO_DC_W[0], P.UNO_DC_W[1], t, t + P.UNO_DC_H),
        (18.0, 65.0, 50.2, 52.7, t, t + 8.5),
        (-P.UNO_USB_OVERHANG, 10.0, P.UNO_USB_W[0], P.UNO_USB_W[1], t, t + P.UNO_USB_H),
    ]
    x0, y0, z0 = kit.uno_origin()
    out = []
    for u0, u1, w0, w1, h0, h1 in parts:
        out.append(box(x0 + w0 - c, x0 + w1 + c, y0 - u1 - c, y0 - u0 + c, z0 + h0 - c, z0 + h1 + c))
    return union_all(out)


def slot_rim(z0):
    """thicker rim around the cable slot under the lid so the wires never see a sharp edge"""
    pts_o = arc_slot_points(P.TURRET_X, P.TURRET_Y, P.SLOT_R, P.SLOT_W + 3.2, -P.SLOT_HALF_ANGLE, P.SLOT_HALF_ANGLE)
    return poly_prism(pts_o, z0, P.LID_BOTTOM + 0.01)


def mark_cut():
    """small sun mark pressed into the lid in front of the turret"""
    cx, cy = 0.0, P.BASE_D / 2 - 16.0
    z0 = P.BASE_TOP - P.MARK_DEPTH
    ring = cyl("z", 5.0, z0, P.BASE_TOP + 1, (cx, cy)) - cyl("z", 3.8, z0 - 1, P.BASE_TOP + 2, (cx, cy))
    dot = cyl("z", 1.6, z0, P.BASE_TOP + 1, (cx, cy))
    return ring + dot


def foot():
    """small foot under each corner, the lid screw goes through it"""
    x, y = COLUMN_XY[0]
    z0, z1 = 0.0, P.FOOT_PAD_H
    f = rrect_prism(P.FOOT_PAD_D, P.FOOT_PAD_D, P.FOOT_PAD_D / 2 - 0.01, z0, z1, cx=x, cy=y, cb=0.6, ct=0.4)
    hole = cyl("z", P.M3_CLEAR / 2, z0 - 1, z1 + 1, (x, y))
    csk = cone("z", P.M3_CSK_D / 2 + 0.01, P.M3_CLEAR / 2, z0 - 0.01, z0 + (P.M3_CSK_D - P.M3_CLEAR) / 2, (x, y))
    return f - hole - csk


def feet():
    out = []
    f0 = foot()
    x0, y0 = COLUMN_XY[0]
    for x, y in COLUMN_XY:
        out.append(f0.translate((x - x0, y - y0, 0)))
    return out


_ = math
