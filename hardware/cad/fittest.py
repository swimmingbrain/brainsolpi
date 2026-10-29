"""a small plate that checks every fit in about twenty minutes of printing

servo frame, horn pocket, module peg pair, three tap holes, a pi pin, a cap recess and a
corner of the panel pocket with its lip, all with the same numbers as the real parts
print one cap next to it
"""

import math

from . import kit
from . import params as P
from .helpers import box, cone, cyl, poly_prism, rrect_points, union_all

PLATE_T = 1.6


def fit_plate():
    plate = poly_prism(rrect_points(104.0, 56.0, 4.0, cx=-4.0, cy=-2.0), 0.0, PLATE_T)
    add, cut = [], []
    # servo frame, the servo drops in spline up, its tabs rest in the notches
    g = P.FIT_SLIDE
    sx, sy = -35.0, 12.0
    cw, cl = P.SERVO_W + 2 * g, P.SERVO_L + 2 * g
    add.append(box(sx - cl / 2 - 6.5, sx + cl / 2 + 6.5, sy - cw / 2 - 2.4, sy + cw / 2 + 2.4, 0, 9.0))
    cut.append(box(sx - cl / 2, sx + cl / 2, sy - cw / 2, sy + cw / 2, -1, 10))
    tl = P.SERVO_L + 2 * P.SERVO_TAB_LEN + 2 * g
    cut.append(box(sx - tl / 2, sx + tl / 2, sy - cw / 2, sy + cw / 2, 9.0 - P.SERVO_TAB_T - g, 10))
    # the pan horn pocket exactly as in the lid, printed the same way up: the thin plate on the bed,
    # the horn lies in the pocket with its hub down through the hole, the servo spline comes from below
    hx, hy = -44.0, -16.0
    o, _, _ = kit.pan_horn_frame()
    plate = P.BASE_TOP - (o[2] + P.PAN_HORN_PLAY)
    top = plate + P.HORN_ARM_T + P.PAN_HORN_PLAY + 0.6
    add.append(box(hx - 10, hx + 20, hy - 6.5, hy + 6.5, 0, top))
    arm = kit.arm_solid(1, P.HORN_SINGLE_LEN, plate, top + 0.1, grow=P.FIT_SNUG)
    cut.append(arm.translate((hx, hy, 0)))
    cut.append(cyl("z", P.HORN_HUB_D / 2 + P.FIT_SNUG, plate, top + 0.1, (hx, hy)))
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
    body = union_all([plate] + add)
    return body - union_all(cut)


_ = math
