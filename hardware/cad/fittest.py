"""a small plate that checks every fit in about twenty minutes of printing

servo frame, horn pocket, module peg pair, three tap holes, a pi pin, a cap recess and a
corner of the panel pocket with its lip, all with the same numbers as the real parts, and a
strip of the lid signature under the plate to judge the engraving before the long lid print
print one cap next to it

the servo test is a slice of the back half of the neck around the tilt servo, the pocket with
its crush ribs, the half keyhole for both bosses and the way out for the lead, about ten minutes
"""

import math

from build123d import Plane, Polygon, loft

from . import kit, neck, signature
from . import params as P
from .helpers import box, cone, cyl, poly_prism, rrect_points, union_all

PLATE_T = 1.6


def upright_rib(x, y, nx, ny, h, z0, z1, taper=1.2):
    """crush rib with a 90 degree point standing on a frame wall, lower toward its top end z1
    so the case finds its way in, x y is the middle of its foot, nx ny points into the opening"""
    ex, ey = -ny, nx

    def section(z, hh):
        foot = hh + 0.05
        pts = [(x - 0.05 * nx - foot * ex, y - 0.05 * ny - foot * ey), (x + hh * nx, y + hh * ny),
               (x - 0.05 * nx + foot * ex, y - 0.05 * ny + foot * ey)]
        return Plane.XY.offset(z) * Polygon(*pts, align=None)

    return loft([section(z0, h), section(z1 - taper, h)], ruled=True) + \
        loft([section(z1 - taper, h), section(z1, 0.05)], ruled=True)


def fit_plate():
    plate = poly_prism(rrect_points(104.0, 56.0, 4.0, cx=-4.0, cy=-2.0), 0.0, PLATE_T)
    add, cut = [], []
    # servo frame with the air and the crush ribs of the neck, the servo goes in spline down, so
    # the lead stays above the frame, its tabs rest in the notches and both bosses pass the hole
    a = neck.side_air()
    g = P.SERVO_PLAY + P.FIT_SLIDE
    sx, sy = -35.0, 12.0
    cw, cl = P.SERVO_W + 2 * a, P.SERVO_L + 2 * a
    add.append(box(sx - cl / 2 - 6.5, sx + cl / 2 + 6.5, sy - cw / 2 - 2.4, sy + cw / 2 + 2.4, 0, 9.0))
    cut.append(box(sx - cl / 2, sx + cl / 2, sy - cw / 2, sy + cw / 2, -1, 10))
    tl = P.SERVO_L + 2 * P.SERVO_TAB_LEN + 2 * g
    z1 = 9.0 - P.SERVO_TAB_T - P.FIT_SLIDE
    cut.append(box(sx - tl / 2, sx + tl / 2, sy - cw / 2, sy + cw / 2, z1, 10))
    h = a + P.SERVO_RIB_BITE
    ribs = [upright_rib(sx - cl / 2, sy, 1, 0, h, 0.0, z1), upright_rib(sx + cl / 2, sy, -1, 0, h, 0.0, z1)]
    for dx in (-P.SERVO_L / 2 + neck.BUMP_IN, P.SERVO_L / 2 - neck.BUMP_IN):
        ribs += [upright_rib(sx + dx, sy - cw / 2, 0, 1, h, 0.0, z1),
                 upright_rib(sx + dx, sy + cw / 2, 0, -1, h, 0.0, z1)]
    # the pan horn pocket exactly as in the lid, printed the same way up: the thin plate on the bed,
    # the horn lies in the pocket with its hub down through the hole, the servo spline comes from below
    hx, hy = -44.0, -16.0
    o, _, _ = kit.pan_horn_frame()
    thin = P.BASE_TOP - (o[2] + P.PAN_HORN_PLAY)
    top = thin + P.HORN_ARM_T + P.PAN_HORN_PLAY + 0.6
    add.append(box(hx - 10, hx + 20, hy - 6.5, hy + 6.5, 0, top))
    arm = kit.arm_solid(1, P.HORN_SINGLE_LEN, thin, top + 0.1, grow=P.FIT_SNUG)
    cut.append(arm.translate((hx, hy, 0)))
    cut.append(cyl("z", P.HORN_HUB_D / 2 + P.FIT_SNUG, thin, top + 0.1, (hx, hy)))
    cut.append(cyl("z", P.HORN_HUB_D / 2 + 0.3, -1, top + 0.1, (hx, hy)))
    # module peg pair, 16 apart, same shoulder and pin as in the head
    for dy in (-P.MOD_HOLE_SPACING / 2, P.MOD_HOLE_SPACING / 2):
        px, py = -8.0, 12.0 + dy
        pin_r = P.MOD_HOLE_D / 2 - P.FIT_SNUG
        add.append(cyl("z", 3.4, PLATE_T - 0.01, PLATE_T + P.MOD_STANDOFF, (px, py)))
        add.append(cyl("z", pin_r, PLATE_T, PLATE_T + P.MOD_STANDOFF + P.MOD_T + 2.4, (px, py)))
        add.append(cone("z", pin_r, pin_r - 0.6, PLATE_T + P.MOD_STANDOFF + P.MOD_T + 2.4,
                        PLATE_T + P.MOD_STANDOFF + P.MOD_T + 3.0, (px, py)))
    # three tap holes, 2.6, 2.65 and 2.7 from the front, a notch count marks each one
    tx, ty_ = -8.0, -16.0
    add.append(box(tx - 6, tx + 6, ty_ - 13, ty_ + 13, 0, 10.0))
    for k, d in enumerate((2.6, 2.65, 2.7)):
        y = ty_ - 8.0 + 8.0 * k
        cut.append(cyl("z", d / 2, 2.0, 10.1, (tx, y)))
        for j in range(k + 1):
            cut.append(box(tx + 5.2, tx + 6.1, y - 2.0 + j * 1.6, y - 1.2 + j * 1.6, 7.0, 10.1))
    # pi pin on a stand off, the board must slide on and sit flat
    add.append(cyl("z", 3.0, PLATE_T - 0.01, PLATE_T + P.PI_STANDOFF, (14.0, 18.0)))
    add.append(cyl("z", P.PI_PIN_D / 2, PLATE_T, PLATE_T + P.PI_STANDOFF + P.PI_T + 1.5, (14.0, 18.0)))
    add.append(cone("z", P.PI_PIN_D / 2, 0.8, PLATE_T + P.PI_STANDOFF + P.PI_T + 1.5,
                    PLATE_T + P.PI_STANDOFF + P.PI_T + 2.3, (14.0, 18.0)))
    # cap recess, press the printed cap in and pull it out with a screwdriver tip
    add.append(cyl("z", 9.0, 0, 4.0, (32.0, 14.0)))
    cut.append(cyl("z", P.CAP_D / 2, 4.0 - P.CAP_T, 4.1, (32.0, 14.0)))
    cut.append(box(32.0 - 0.8, 32.0 + 0.8, 14.0 - P.CAP_D / 2 - 1.0, 14.0 - P.CAP_D / 2 + 0.5, 4.0 - P.CAP_T, 4.1))
    # corner of the panel pocket printed face down like the bezel, the panel corner drops in
    cx, cy = 20.0, -28.0
    f = P.PANEL_FIT
    lip = P.BEZEL_LIP
    depth = P.PANEL_T + P.BEZEL_FRONT_T
    corner = box(cx, cx + 24, cy, cy + 24, 0, depth + 1.0)
    pocket = box(cx + 6 - f, cx + 30, cy + 6 - f, cy + 30, P.BEZEL_FRONT_T, depth + 2)
    window = box(cx + 6 + lip, cx + 30, cy + 6 + lip, cy + 30, -1, P.BEZEL_FRONT_T + 0.1)
    add.append(corner - pocket - window)
    # a strip of the lid signature in the face on the plate, it prints like the lid top, turn the
    # plate over to read it
    cut.append(signature.sample_cut(0.0, -16.0))
    body = union_all([plate] + add)
    return (body - union_all(cut)) + union_all(ribs)


def servo_slice(depth=8.5):
    """the back half of the neck around the tilt servo, cut off depth behind the parting plane,
    it prints on the cut face like the back half prints on its back"""
    t = P.TURRET_Y
    _, back = neck.halves()
    zb = neck.tilt_holder().bounding_box().min.Z - 1.0
    return back & box(-P.NECK_W / 2 - 1.0, neck.column_x0() + 1.0, t - depth, t, zb, P.NECK_TOP + 1.0)


_ = math
