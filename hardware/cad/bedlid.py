"""the plant bed lid, a deep lid with soil in it that takes the place of the lid

the tub sits on the tray like the lid and keeps all of its underside: skirt, columns, the posts the
uno hangs from, the fingers on the pi and both ribs, its floor is the lid plate
in the middle a hollow island lifts the neck by BED_LIFT, its top is the top of the lid round the pan
axis moved up: horn pocket, hub hole and pad are the same, the cable slot is a wider C so the cables
move freely when the neck turns, the printed neck and head go on as they are
in each corner a hollow post carries a table for a small light sensor board, the cable leaves the
board on any side, runs over the table to an opening beside the board and down the post into the base
the rim and the island top lie in one plane, the part prints upside down on it, the tub floor and the
four tables need supports from the plate, nothing else does
the checks move the base down by BED_LIFT instead of the neck and the head up, it is the same for
every pair and the joints of assembly.py stay as they are
"""

import math

import manifold3d as m3d
import numpy as np
from build123d import Plane, Polygon, extrude, loft

from . import assembly as A
from . import base, cables, checks, kit
from . import params as P
from .helpers import arc_slot_points, box, cone, cyl, rrect_points, rrect_prism, union_all
from .mesh import to_trimesh, transformed

LIFT = P.BED_LIFT
CORNERS = {"front_right": (1, 1), "back_right": (1, -1), "front_left": (-1, 1), "back_left": (-1, -1)}


def top():
    """rim and island top above the table"""
    return P.BASE_TOP + LIFT


def floor_top():
    """the tub floor stands on the underside of the lid plate, thinner than the plate"""
    return P.LID_BOTTOM + P.BED_FLOOR_T


def soil_z():
    return top() - P.BED_SOIL_BELOW_RIM


def seat_z():
    """where a board rests, on the spine of its table"""
    return top() - P.BED_SEAT_DROP


def table_z():
    """top and underside of the table plate"""
    z1 = seat_z() - P.BED_RELIEF
    return z1, z1 - P.BED_TABLE_T


def lift(dz=LIFT):
    m = np.eye(4)
    m[2, 3] = dz
    return m


def inner_size():
    return P.BASE_W - 2 * P.BED_WALL, P.BASE_D - 2 * P.BED_WALL, P.R_BIG - P.BED_WALL


# the C shaped cable slot, in the frame of the lid, the turret moves it up


def c_points(d=0.0, n=40, nf=8):
    """outline of the slot grown by d, counterclockwise, the same number of points for every d
    an annulus round plus x whose ends run parallel to the horn arm, the four end corners round"""
    r_in, r_out = P.BED_SLOT_R
    yc, rf = P.BED_SLOT_END, P.BED_SLOT_FILLET
    ri, ro, rfd = r_in - d, r_out + d, rf + d
    # the fillet centres stay where they are when the outline grows
    co = (-math.sqrt((r_out - rf) ** 2 - (yc + rf) ** 2), yc + rf)
    ci = (-math.sqrt((r_in + rf) ** 2 - (yc + rf) ** 2), yc + rf)
    ao, ai = math.atan2(co[1], co[0]), math.atan2(ci[1], ci[0])
    upper = []
    for k in range(nf + 1):
        a = ao + (1.5 * math.pi - ao) * k / nf
        upper.append((co[0] + rfd * math.cos(a), co[1] + rfd * math.sin(a)))
    for k in range(nf + 1):
        a = 1.5 * math.pi + (ai + math.pi - 1.5 * math.pi) * k / nf
        upper.append((ci[0] + rfd * math.cos(a), ci[1] + rfd * math.sin(a)))
    lower = [(x, -y) for x, y in upper][::-1]
    pts = [(ro * math.cos(-ao + 2 * ao * k / n), ro * math.sin(-ao + 2 * ao * k / n)) for k in range(n + 1)]
    pts += upper[1:]
    pts += [(ri * math.cos(ai - 2 * ai * k / n), ri * math.sin(ai - 2 * ai * k / n)) for k in range(1, n)]
    pts += lower[:-1]
    return [(P.TURRET_X + x, P.TURRET_Y + y) for x, y in pts]


def c_face(d, z):
    return Plane.XY.offset(z) * Polygon(*c_points(d), align=None)


def c_prism(d, z0, z1):
    return extrude(c_face(d, z0), z1 - z0)


def slot_cut(z_rim):
    """the slot through the plate and its rim, 45 degree edges on the top face and under the rim"""
    ct, cb = P.BED_SLOT_CHAMFER
    zt = P.BASE_TOP
    body = c_prism(0.0, z_rim - 1.0, zt + 1.0)
    upper = loft([c_face(0.0, zt - ct), c_face(ct + 0.01, zt + 0.01)], ruled=True)
    under = loft([c_face(cb + 0.01, z_rim - 0.01), c_face(0.0, z_rim + cb)], ruled=True)
    return body + upper + under


def c_section(d=0.0):
    return m3d.CrossSection([c_points(d)])


def old_slot_section(width=P.SLOT_W):
    return m3d.CrossSection([arc_slot_points(P.TURRET_X, P.TURRET_Y, P.SLOT_R, width, -P.SLOT_HALF_ANGLE,
                                             P.SLOT_HALF_ANGLE)])


# the part


def underside():
    """everything of the lid under its plate, made like in base.lid, the pad round the horn goes up
    with the turret, solids and holes"""
    iw, idp, ir = base.inner_size()
    sk_w, sk_d, sk_r = iw - 2 * P.FIT_SLIDE, idp - 2 * P.FIT_SLIDE, ir - P.FIT_SLIDE
    skirt = rrect_prism(sk_w, sk_d, sk_r, P.LID_BOTTOM - P.LID_SKIRT_H, P.LID_BOTTOM + 0.01, cb=0.6)
    skirt = skirt - rrect_prism(sk_w - 2 * P.LID_SKIRT_T, sk_d - 2 * P.LID_SKIRT_T, sk_r - P.LID_SKIRT_T,
                                P.LID_BOTTOM - P.LID_SKIRT_H - 1, P.LID_BOTTOM + 0.1)
    add = [skirt]
    for x, y in base.COLUMN_XY:
        add.append(cyl("z", P.COLUMN_D / 2, P.FLOOR_TOP, P.LID_BOTTOM + 0.01, (x, y)))
        add.append(cyl("z", base.SPIGOT_D / 2, P.TRAY_Z0 + base.SPIGOT_RECESS, P.FLOOR_TOP + 0.01, (x, y)))
    uno_top = kit.uno_origin()[2] + P.UNO_T
    for x, y in base.uno_hole_xy():
        add.append(cyl("z", P.UNO_POST_D / 2, uno_top, P.LID_BOTTOM + 0.01, (x, y)))
    pi_top = kit.pi_z0() + P.PI_T
    for x, y in base.pi_hole_xy():
        add.append(cyl("z", P.PI_FINGER_D / 2, pi_top + 0.3, P.LID_BOTTOM + 0.01, (x, y)))
    add.append(box(-60.0, 66.0, 44.2, 45.8, P.LID_BOTTOM - 5.0, P.LID_BOTTOM + 0.01))
    add.append(box(-47.0, -45.4, -64.0, 64.0, P.LID_BOTTOM - 5.0, P.LID_BOTTOM + 0.01))
    cuts = []
    for x, y in base.COLUMN_XY:
        cuts.append(cyl("z", P.M3_TAP / 2, P.TRAY_Z0 - 1, P.TRAY_Z0 + 10.0, (x, y)))
        cuts.append(cone("z", 1.7, P.M3_TAP / 2, P.TRAY_Z0 + base.SPIGOT_RECESS - 0.01,
                         P.TRAY_Z0 + base.SPIGOT_RECESS + 0.6, (x, y)))
    for x, y in base.uno_hole_xy():
        cuts.append(cyl("z", P.M3_TAP / 2, uno_top - 1, uno_top + 9.0, (x, y)))
        cuts.append(cone("z", 1.7, P.M3_TAP / 2, uno_top - 0.01, uno_top + 0.6, (x, y)))
    for x, y in base.pi_hole_xy():
        cuts.append(cyl("z", (P.PI_PIN_D + 0.5) / 2, pi_top - 1, pi_top + 4.0, (x, y)))
    return add, cuts


def pad_z0():
    """underside of the pad round the horn, in the frame of the lid"""
    return kit.pan_horn_frame()[0][2] - P.HORN_ARM_T - 0.4


def turret():
    """pad and cuts round the pan axis made like base.lid_turret_cuts, moved up to the island top,
    the C slot in place of the slot of the lid and a rim under the plate that follows it"""
    tx, ty = P.TURRET_X, P.TURRET_Y
    arm_top = kit.pan_horn_frame()[0][2]
    arm_bottom = arm_top - P.HORN_ARM_T
    ceiling = arm_top + P.PAN_HORN_PLAY
    z0 = pad_z0()
    cuts = [base.place_arm_left(P.HORN_SINGLE_LEN, arm_bottom - 3.0, ceiling),
            cyl("z", P.HORN_HUB_D / 2 + P.FIT_SNUG, arm_bottom - 3.0, ceiling, (tx, ty)),
            cyl("z", P.HORN_HUB_D / 2 + 0.3, ceiling - 0.01, P.BASE_TOP + 1, (tx, ty)),
            slot_cut(z0)]
    pad = [cyl("z", 9.0, z0, P.LID_BOTTOM + 0.01, (tx, ty)),
           box(tx - P.HORN_SINGLE_LEN - 3.0, tx, ty - 6.0, ty + 6.0, z0, P.LID_BOTTOM + 0.01),
           c_prism(P.BED_SLOT_RIM, z0, P.LID_BOTTOM + 0.01)]
    up = (0, 0, LIFT)
    return [s.translate(up) for s in pad], [s.translate(up) for s in cuts]


def island():
    """hollow stem out of the floor, a 45 degree flare and the top plate the foot rides on"""
    tx, ty = P.TURRET_X, P.TURRET_Y
    zt = top()
    zp = zt - P.LID_T
    big, stem, c = P.BED_ISLAND_R, P.BED_ISLAND_STEM_R, P.BED_CHAMFER
    zf = zp - (big - stem)
    return union_all([
        cyl("z", stem, P.LID_BOTTOM, zf + 0.01, (tx, ty)),
        cone("z", stem, big, zf, zp, (tx, ty)),
        cyl("z", big, zp, zt - P.EDGE, (tx, ty)),
        cone("z", big, big - P.EDGE, zt - P.EDGE, zt, (tx, ty)),
        # chamfer into the floor so the corner takes a liner or sealant, a little steeper than 45 degrees
        # so the facets of the mesh stay inside the overhang rule
        cone("z", stem + c, stem, floor_top() - 0.01, floor_top() + 1.1 * c, (tx, ty)),
    ])


def table_layout(sx, sy):
    """post with its opening, the middle of the board zone and the radius of the collar"""
    w, ln = P.BED_BOARD
    rc = P.BED_STEM_BORE_R + P.BED_COLLAR[0]
    near = P.BED_POST_XY[1] - rc - P.BED_OPENING_GAP - P.BED_STOP[1]
    return {"post": (sx * P.BED_POST_XY[0], sy * P.BED_POST_XY[1]), "board": (sx * P.BED_BOARD_X, sy * (near - ln / 2)),
            "r_collar": rc, "r_end": rc + 1.9}


def table_box(sx, sy, grow=0.0):
    """x0, x1, y0, y1 round the table plate"""
    t = table_layout(sx, sy)
    (px, py), (bx, by), re = t["post"], t["board"], t["r_end"]
    hw, hl = P.BED_BOARD[0] / 2 + P.BED_STOP[1], P.BED_BOARD[1] / 2 + P.BED_STOP[1]
    xs = [bx - hw, bx + hw, px - re, px + re]
    ys = [by - hl, by + hl, py - re, py + re]
    return min(xs) - grow, max(xs) + grow, min(ys) - grow, max(ys) + grow


def table(sx, sy):
    """hollow post with its table in one corner, the solid and its cuts"""
    t = table_layout(sx, sy)
    (px, py), (bx, by), rc, re = t["post"], t["board"], t["r_collar"], t["r_end"]
    w, ln = P.BED_BOARD
    leg, wall, stop_h = P.BED_STOP
    sw, sl = P.BED_SPINE
    zs = seat_z()
    zp1, zp0 = table_z()
    zc = zp1 + P.BED_COLLAR[1]
    r, c = P.BED_STEM_R, P.BED_POST_CHAMFER
    near = by + sy * (ln / 2 + wall)
    solid = [
        rrect_prism(w + 2 * wall, ln + 2 * wall, 2.0, zp0, zp1, cx=bx, cy=by),
        cyl("z", re, zp0, zp1, (px, py)),
        box(px - re, px + re, near - sy * 2.0, py, zp0, zp1),
        cyl("z", r, floor_top() - 0.01, zp0 + 0.01, (px, py)),
        cone("z", r + c, r, floor_top() - 0.01, floor_top() + 1.1 * c, (px, py)),
        cone("z", r, r + 2.0, zp0 - 2.0, zp0 + 0.01, (px, py)),
        # the board rests on the spine, pins pointing down under its edges have the relief beside it
        box(bx - sw / 2, bx + sw / 2, by - sl / 2, by + sl / 2, zp1 - 0.01, zs),
        # a collar round the opening keeps water on the table out of the post
        cyl("z", rc, zp1 - 0.01, zc, (px, py)),
    ]
    # stops at the corners only, a cable leaves the board on any side through the gaps between them
    for cx in (1, -1):
        for cy in (1, -1):
            x0, y0 = bx + cx * w / 2, by + cy * ln / 2
            solid.append(box(x0 - cx * leg, x0 + cx * wall, y0, y0 + cy * wall, zp1 - 0.01, zs + stop_h))
            solid.append(box(x0, x0 + cx * wall, y0 - cy * leg, y0 + cy * wall, zp1 - 0.01, zs + stop_h))
    cuts = [cyl("z", P.BED_STEM_BORE_R, P.LID_BOTTOM - 1.0, zc + 1.0, (px, py)),
            cone("z", P.BED_STEM_BORE_R + 0.6, P.BED_STEM_BORE_R, zc + 0.01, zc - 0.6, (px, py))]
    # notches in both long edges, a tie or a band goes over the board where the spine is, down a notch,
    # under the table and up the other one, it stays off the middle of the board
    tw, td, toff = P.BED_TIE
    for yt in (by - toff, by + toff):
        for side in (1, -1):
            xe = bx + side * (w / 2 + wall)
            cuts.append(box(xe - side * td, xe + side * 2.0, yt - tw / 2, yt + tw / 2, zp0 - 2.0, zp1 + 0.01))
    return union_all(solid), cuts


def tub():
    """outer wall, floor and cavity, a bead inside the rim gives it a wider face on the plate"""
    iw, idp, ir = inner_size()
    bw, bh, bc = P.BED_RIM_BEAD
    zt = top()
    outer = rrect_prism(P.BASE_W, P.BASE_D, P.R_BIG, P.LID_BOTTOM, zt, cb=0.4, ct=bc)
    # the cavity narrows at 45 degrees into the bead, so the bead needs no support
    cavity = rrect_prism(iw, idp, ir, floor_top(), zt - bh, cb=P.BED_CHAMFER, ct=bw)
    cavity = cavity + rrect_prism(iw - 2 * bw, idp - 2 * bw, ir - bw, zt - bh - 0.01, zt + 1.0)
    lead = rrect_prism(iw - 2 * bw + 2 * bc, idp - 2 * bw + 2 * bc, ir - bw + bc, zt - bc, zt + 1.0, cb=bc)
    return outer - cavity - lead


def bedlid():
    """the whole part in the device frame"""
    under_add, under_cuts = underside()
    tables = [table(sx, sy) for sx, sy in CORNERS.values()]
    body = union_all([tub(), island()] + under_add + [s for s, _ in tables])
    cuts = [cyl("z", P.BED_ISLAND_BORE_R, P.LID_BOTTOM - 1.0, top() - P.LID_T, (P.TURRET_X, P.TURRET_Y))]
    for _, tc in tables:
        cuts += tc
    body = body - union_all(cuts)
    pad, turret_cuts = turret()
    body = body + union_all(pad)
    body = body - union_all(turret_cuts + under_cuts)
    # posts next to the dc jack and the digital header get the notch of the lid
    return body - base.uno_clearance()


def part():
    return A.Part("bedlid", bedlid(), "base", "body", print_rot=((1, 0, 0), 180.0),
                  note="rim and island top on the bed, supports from the plate under the tub floor and the tables")


def build_parts():
    """the parts of the tracker with the bed lid in place of the lid, neck and head as printed"""
    return A.build_parts(lid=part())


def boards():
    """keep outs on every table for the sweep: the largest board with its parts, and a plug sticking
    out sideways on the side toward x = 0 and on the end toward y = 0, it lies on the top of the board,
    over the corner stops"""
    w, ln = P.BED_BOARD
    zs, h, f = seat_z(), P.BED_BOARD_STACK, P.FIT_SLIDE
    zb = zs + 1.6
    free, island_side = P.BED_PLUG_OUT
    out = {}
    for name, (sx, sy) in CORNERS.items():
        bx, by = table_layout(sx, sy)["board"]
        x0, x1, y0, y1 = bx - w / 2 + f, bx + w / 2 - f, by - ln / 2 + f, by + ln / 2 - f
        out["board_" + name] = box(x0, x1, y0, y1, zs, zs + h)
        xe, ye = bx - sx * w / 2, by - sy * ln / 2
        out["plug_" + name + "_side"] = box(xe, xe - sx * (island_side if sy < 0 else free), y0, y1, zb, zs + h)
        out["plug_" + name + "_end"] = box(x0, x1, ye, ye - sy * free, zb, zs + h)
    return out


def electronics():
    """kit keep outs per group as meshes, the pan horn goes up with the island"""
    out = A.electronics()
    out["base"]["pan_horn"] = transformed(out["base"]["pan_horn"], lift())
    for k, s in boards().items():
        out["base"][k] = to_trimesh(s)
    return out


def pose_matrix(group, pan, tilt):
    """placement in the device frame, neck and head ride the island"""
    m = A.group_matrix(group, pan, tilt)
    return m if group == "base" else lift() @ m


# the checks run in a frame where the base is moved down by the lift


def check_parts(parts):
    out = []
    for p in parts:
        if p.group != "base":
            out.append(p)
            continue
        q = A.Part(p.name, p.shape, p.group, p.role, p.count, p.print_rot, p.note, p.instances)
        q._mesh = transformed(p.mesh(), lift(-LIFT))
        out.append(q)
    return out


def check_elec(elec):
    out = {g: dict(d) for g, d in elec.items()}
    out["base"] = {k: transformed(m, lift(-LIFT)) for k, m in elec["base"].items()}
    return out


# room under the floor, measured on the kit


def room_report(elec):
    pi = elec["base"]["pi"]
    uno = elec["base"]["uno"]
    plugs = kit.plug_top_z()
    need = plugs + P.UNO_PLUG_TOP_GAP
    return {"pi_top": float(pi.bounds[1][2]), "uno_top": float(uno.bounds[1][2]), "plug_top": float(plugs),
            "bend": P.UNO_PLUG_TOP_GAP, "need": float(need), "floor_under": P.LID_BOTTOM,
            "floor_top": floor_top(), "margin": float(P.LID_BOTTOM - need),
            "tray_floor": P.FLOOR_TOP, "room": P.LID_BOTTOM - P.FLOOR_TOP}


# cable budget with the neck on the island


def uno_way(top_pt, below, pans):
    """from a plug on the uno into the island to the bundle under the top plate, longest pose
    a plug under the bore goes straight up, one further out runs under the floor to the bore first"""
    r_in = P.BED_ISLAND_BORE_R - 3.0
    dx, dy = top_pt[0] - P.TURRET_X, top_pt[1] - P.TURRET_Y
    d = math.hypot(dx, dy)
    fixed = 0.0
    start = top_pt
    if d > r_in:
        k = r_in / d
        z = P.LID_BOTTOM - 2.0
        pts = [top_pt, (top_pt[0], top_pt[1], z), (P.TURRET_X + dx * k, P.TURRET_Y + dy * k, z)]
        fixed = cables.poly_len(pts)
        start = pts[-1]
    free, pose = cables.free_max(start, below, "neck", pans, [0.0])
    return fixed + free, pose


def cable_budget(lift_z=LIFT, photo=P.BED_PHOTO_CABLE):
    """the budget of cables.py with the neck lift_z higher, the way through the plate under the foot
    counts for every cable here, the build counts it for the servo leads only"""
    pans = np.arange(P.PAN_RANGE[0], P.PAN_RANGE[1] + 1e-6, 5.0)
    tilts = np.arange(P.TILT_RANGE[0], P.TILT_RANGE[1] + 1e-6, 5.0)
    b, _ = cables.exit_points()
    below = (b[0], b[1], b[2] + lift_z)
    neck_len = cables.poly_len(cables.neck_path()) + cables.ALLOW["neck"]
    loop_d, loop_pose = cables.loop_max(tilts)
    loop_len = loop_d + cables.ALLOW["loop"]
    through = cables.through_lid()
    plug_cut = 2 * P.DUPONT_LEN if P.CABLE_LEN_INCLUDES_PLUGS else 0.0
    rows = []
    gvs = sum(P.UNO_GVS_W) / 3
    heads = [(f"photoresistor {n} to A{i}", cables.uno_pin_top(P.UNO_A0_U + i * P.PITCH, gvs), n, photo)
             for i, n in enumerate(("L", "R", "U", "D"))]
    heads.append(("bh1750 to SDA SCL", cables.uno_pin_top(P.UNO_I2C_U, sum(P.UNO_I2C_W) / 4), "lux", P.BH_CABLE))
    for label, top_pt, name, length in heads:
        uno_d, uno_pose = uno_way(top_pt, below, pans)
        uno_len = uno_d + cables.ALLOW["uno"]
        head_len = cables.poly_len(cables.head_path(name)) + cables.ALLOW["head"]
        total = uno_len + through + neck_len + loop_len + head_len
        avail = length - plug_cut
        rows.append({"cable": label, "uno": uno_len, "through": through, "neck": neck_len, "loop": loop_len,
                     "head": head_len, "total": total, "length": length, "available": avail, "slack": avail - total,
                     "shortest": total + P.CABLE_SLACK_MIN + plug_cut,
                     "worst": f"pan {uno_pose[0]:.0f}, tilt {loop_pose:.0f}"})
    dg = sum(P.UNO_DGVS_W) / 3
    for label, which, u in (("tilt servo to D10", "tilt", P.UNO_D10_U), ("pan servo to D9", "pan", P.UNO_D9_U)):
        uno_d, uno_pose = uno_way(cables.uno_pin_top(u, dg), below, pans)
        uno_len = uno_d + cables.ALLOW["uno"]
        inner = cables.poly_len(cables.servo_lead_path(which)) + cables.ALLOW["servo"]
        total = uno_len + through + inner
        avail = P.SERVO_LEAD - P.DUPONT_LEN
        rows.append({"cable": label, "uno": uno_len, "through": through, "neck": inner, "loop": 0.0, "head": 0.0,
                     "total": total, "length": P.SERVO_LEAD, "available": avail, "slack": avail - total,
                     "shortest": total + P.CABLE_SLACK_MIN + P.DUPONT_LEN, "worst": f"pan {uno_pose[0]:.0f}"})
    return rows


# measured on the mesh


def tub_region():
    iw, idp, ir = inner_size()
    return m3d.CrossSection([rrect_points(iw, idp, ir, n=24)])


def soil_area(man, z):
    """open area of the tub at height z, the bores of the island and the posts are not soil"""
    pieces = (tub_region() - man.slice(z)).decompose()
    return max((p.area() for p in pieces), default=0.0)


def soil_report(mesh, dz=0.5):
    """litres of soil from the floor to the soil surface and up to the rim, sliced every dz"""
    man = checks.to_manifold(mesh)
    out = {}
    for key, z1 in (("soil", soil_z()), ("rim", top())):
        zs = np.arange(floor_top() + dz / 2, z1, dz)
        out[key] = float(sum(soil_area(man, z) for z in zs) * dz / 1e6)
    out["depth"] = soil_z() - floor_top()
    out["area_mid"] = float(soil_area(man, (floor_top() + soil_z()) / 2))
    return out


def device_lid_mesh(stl_path):
    """the printed lid from its stl back in the device frame, it lies turned about x with its top on z = 0"""
    import trimesh
    m = trimesh.load(stl_path)
    rot = np.diag([1.0, -1.0, -1.0, 1.0])
    rot[2, 3] = P.BASE_TOP
    return transformed(m, rot)


def ring(r_out, r_in=0.0):
    c = m3d.CrossSection.circle(r_out, 96).translate((P.TURRET_X, P.TURRET_Y))
    if r_in > 0:
        c = c - m3d.CrossSection.circle(r_in, 96).translate((P.TURRET_X, P.TURRET_Y))
    return c


def grown(cs, d):
    return cs.offset(d, m3d.JoinType.Round, 2.0, 96)


def slot_zone():
    """where the bed lid may differ from the lid round the axis: the old slot with its rim and the new
    one with its rim, a little grown"""
    return grown(old_slot_section(P.SLOT_W + 3.2) + c_section(P.BED_SLOT_RIM), 0.3)


def same_as_lid(bed_mesh, lid_mesh):
    """xor area of slices through the bed lid and the printed lid, under the plate and round the axis"""
    a, b = checks.to_manifold(bed_mesh), checks.to_manifold(lid_mesh)
    keep_out = ring(P.BED_ISLAND_BORE_R + 0.5)
    under = []
    for z in (3.4, 4.5, 6.0, 10.0, 12.0, 20.0, 23.0, 30.0, 38.0, 40.5, 42.0, 43.0, 44.0, 44.6, 44.95):
        sa, sb = a.slice(z), b.slice(z)
        x = (sa - sb) + (sb - sa)
        under.append((z, float((x - keep_out).area()), float((x ^ keep_out).area())))
    # the interface for the neck, the lid round the axis against the island top one lift higher, under
    # the plate only inside the bore, the island itself stands round it, the slot zone may differ
    zone = slot_zone()
    top_rows = []
    for z in (44.0, 44.6, 45.2, 45.6, 46.2, 46.6, 47.2, 47.8):
        disc = ring(P.BED_ISLAND_BORE_R - 0.4 if z < P.LID_BOTTOM else P.BED_ISLAND_R - 1.5)
        sa = a.slice(z + LIFT) ^ disc
        sb = b.slice(z) ^ disc
        x = (sa - sb) + (sb - sa)
        top_rows.append((z, z + LIFT, float((x - zone).area()), float((x ^ zone).area()), float(sb.area())))
    return under, top_rows, float((zone ^ ring(P.BED_ISLAND_R)).area())


def foot_outline(c=P.EDGE):
    """the outline of the foot of the neck at pan 0, inset c, with the edge chamfer the face it stands on"""
    pts = rrect_points(P.FOOT_W - 2 * c, P.NECK_D - 2 * c, P.R_SMALL - c, 0.0, P.TURRET_Y, n=10, tear_y=True)
    return m3d.CrossSection([pts])


def turned(cs, pan):
    m = A.group_matrix("neck", pan, 0.0)
    return cs.transform(m[:2, [0, 1, 3]])


def angle_reach(cs, r):
    """how far round the axis an outline reaches at radius r, degrees from plus x, the larger end"""
    from matplotlib.path import Path
    best = 0.0
    for poly in cs.to_polygons():
        path = Path(np.asarray(poly))
        a = np.radians(np.arange(0.0, 180.01, 0.25))
        pts = np.column_stack([P.TURRET_X + r * np.cos(a), P.TURRET_Y + r * np.sin(a)])
        inside = path.contains_points(pts)
        # walk from plus x while inside
        k = 0
        while k < len(a) and inside[k]:
            k += 1
        best = max(best, float(np.degrees(a[k - 1])) if k else 0.0)
    return best


def slot_report(neck_front_mesh, lid_mesh, bed_mesh, pan_step=2.0):
    """the C against the slot of the lid: width, reach, open area, bearing of the foot, cover, length"""
    old, new = old_slot_section(), c_section()
    pans = np.arange(P.PAN_RANGE[0], P.PAN_RANGE[1] + 1e-6, pan_step)
    foot = checks.to_manifold(neck_front_mesh).slice(P.BASE_TOP + 0.05)
    lid_top = checks.to_manifold(lid_mesh).slice(P.BASE_TOP - 0.05) ^ ring(40.0)
    bed_top = checks.to_manifold(bed_mesh).slice(top() - 0.05)
    bearing = {}
    for key, cs in (("lid", lid_top), ("bed", bed_top)):
        areas = [(turned(foot, p) ^ cs).area() for p in pans]
        k = int(np.argmin(areas))
        bearing[key] = (float(min(areas)), float(pans[k]), float(np.mean(areas)))
    # the slot with its top chamfer against the outline of the foot, and against the face it stands on,
    # which is smaller by the edge chamfer of the foot
    opening = c_section(P.BED_SLOT_CHAMFER[0])
    cover = max((opening - turned(foot_outline(0.0), p)).area() for p in pans)
    under_chamfer = max((opening - turned(foot_outline(), p)).area() for p in pans)
    # the seven cables lie side by side in the 5 mm wide exit, half of that bundle beyond the exit
    # centre at the end of the pan range, plus 2 mm
    bundle = sum(checks.cable_section(n, r) for _, n, r, _ in checks.cable_set()) / P.EXIT_W
    need = 90.0 + math.degrees((bundle / 2 + 2.0) / P.SLOT_R)
    rep = {
        "old_width": P.SLOT_W, "new_width": P.BED_SLOT_R[1] - P.BED_SLOT_R[0],
        "old_r": (P.SLOT_R - P.SLOT_W / 2, P.SLOT_R + P.SLOT_W / 2), "new_r": P.BED_SLOT_R,
        "old_area": float(old.area()), "new_area": float(new.area()),
        "old_reach": {r: angle_reach(old, r) for r in (8.0, P.SLOT_R, 13.0)},
        "new_reach": {r: angle_reach(new, r) for r in (8.0, P.SLOT_R, 13.0)},
        "bearing": bearing, "uncovered": float(cover), "under_chamfer": float(under_chamfer),
        "bundle": float(bundle), "need": float(need),
        "free_depth": float(pad_z0() + LIFT - kit.plug_top_z()), "free_depth_old": float(pad_z0() - kit.plug_top_z()),
        "free_r": P.BED_ISLAND_BORE_R,
        "wall_hub": P.BED_SLOT_R[0] - (P.HORN_HUB_D / 2 + 0.3),
        "wall_arm": P.BED_SLOT_END - (P.HORN_ARM_W0 / 2 + P.FIT_SNUG),
        "foot_reach": P.NECK_D / 2 - P.EDGE,
    }
    return rep


def zone_manifolds(bed_man, z_shift=-LIFT):
    """the bed lid above the floor split into island, the four tables and the rim, in the check frame"""
    big = 400.0
    z0, z1 = floor_top() + 1.0 + z_shift, top() + 1.0 + z_shift
    h = z1 - z0
    above = bed_man ^ m3d.Manifold.cube((big, big, h), True).translate((0, 0, (z0 + z1) / 2))
    isl = m3d.Manifold.cylinder(h, P.BED_ISLAND_R + 2.0, -1.0, 96).translate((P.TURRET_X, P.TURRET_Y, z0))
    out = {"island": above ^ isl}
    rest = above - isl
    # the tables stop short of the bead inside the rim, its round corners come close to them
    inside = grown(tub_region(), -(P.BED_RIM_BEAD[0] + 0.3)).extrude(h).translate((0, 0, z0))
    for name, (sx, sy) in CORNERS.items():
        x0, x1, y0, y1 = table_box(sx, sy, 2.0)
        b = m3d.Manifold.cube((x1 - x0, y1 - y0, h), True).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
        b = b ^ inside
        out["table " + name.replace("_", " ")] = above ^ b
        rest = rest - b
    out["rim and wall"] = rest
    return out


def soil_slab(bed_man, z_shift=-LIFT):
    cs = max((tub_region() - bed_man.slice(soil_z())).decompose(), key=lambda p: p.area())
    return cs.extrude(0.2).translate((0, 0, soil_z() - 0.2 + z_shift))


def clearances(scene, bed_mesh_check, pan_step=10.0, tilt_step=10.0):
    """smallest gap of the head to each zone of the bed lid, to every board and plug and to the soil"""
    pans = np.arange(P.PAN_RANGE[0], P.PAN_RANGE[1] + 1e-6, pan_step)
    tilts = np.arange(P.TILT_RANGE[0], P.TILT_RANGE[1] + 1e-6, tilt_step)
    bed_man = checks.to_manifold(bed_mesh_check)
    zones = zone_manifolds(bed_man)
    for k, m in scene.items.items():
        if k.startswith(("board_", "plug_")):
            zones[k.replace("_", " ")] = m[2]
    zones["soil surface"] = soil_slab(bed_man)
    head = checks.union([m for _, m in scene.group("head")])
    best = {k: (1e9, None) for k in zones}
    for pan in pans:
        for tilt in tilts:
            h = head.transform(checks.mtx(A.group_matrix("head", pan, tilt)))
            for k, z in zones.items():
                g = z.min_gap(h, 40.0)
                if g < best[k][0]:
                    best[k] = (float(g), (float(pan), float(tilt)))
    return best


def in_tables(x, y, grow=1.0):
    hit = np.zeros(len(x), bool)
    for sx, sy in CORNERS.values():
        x0, x1, y0, y1 = table_box(sx, sy, grow)
        hit |= (x > x0) & (x < x1) & (y > y0) & (y < y1)
    return hit


def print_report(prt, samples=4000, seed=2):
    """the checks of checks.part_report, the bridge and overhang rule only for faces that print without
    support, the faces of the tub floor and the tables count as supported and are measured apart:
    their area, whether a straight line down reaches the plate, the open volume under them, and the
    faces that lie on the plate"""
    rep = checks.part_report(prt)
    pm = prt.print_mesh()
    n = pm.face_normals
    tri = pm.triangles
    zmin, zmax = tri[:, :, 2].min(axis=1), tri[:, :, 2].max(axis=1)
    cen = tri.mean(axis=1)
    dx, dy, dz = cen[:, 0], -cen[:, 1], top() - cen[:, 2]  # back in the device frame
    down = n[:, 2] <= -0.996
    floor = down & (np.abs(zmin - (top() - floor_top())) < 0.05) & (np.abs(zmax - zmin) < 0.05)
    tables = down & (zmin > 0.3) & in_tables(dx, dy) & (dz > floor_top() + 1.0)
    on_support = floor | tables
    a = pm.area_faces
    rep["supported"] = {"tub floor": (float(top() - floor_top()), float(a[floor].sum())),
                        "tables": (float(zmin[tables].min()) if tables.any() else 0.0, float(a[tables].sum()))}
    free = pm.submesh([np.where(~on_support)[0]], append=True)
    rep["free"] = checks.overhang_stats(free)
    # a line straight down from points on the supported faces: to the plate, or onto the part
    man = checks.to_manifold(pm)
    rng = np.random.default_rng(seed)
    idx = np.where(on_support)[0]
    pick = rng.choice(idx, size=samples, p=a[idx] / a[idx].sum())
    u, v = rng.random(samples), rng.random(samples)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    t = tri[pick]
    pts = t[:, 0] + (t[:, 1] - t[:, 0]) * u[:, None] + (t[:, 2] - t[:, 0]) * v[:, None]
    heights, onto = [], []
    for p in pts:
        o = (float(p[0]), float(p[1]), float(p[2]) - 0.02)
        hits = man.ray_cast(o, (o[0], o[1], -1.0))
        if hits:
            hz = max(float(h.position[2]) for h in hits)
            heights.append(o[2] - hz)
            onto.append(True)
        else:
            heights.append(o[2])
            onto.append(False)
    heights, onto = np.array(heights), np.array(onto)
    area = float(a[on_support].sum())
    is_floor = floor[pick]
    rep["support"] = {
        "area": area,
        "onto_part_share": float(onto.mean()),
        "onto_part_area_floor": float(area * (onto & is_floor).mean()),
        "onto_part_area_tables": float(area * (onto & ~is_floor).mean()),
        "volume": float(area * heights.mean()),
        "volume_floor": float(area * (heights * is_floor).mean()),
        "volume_tables": float(area * (heights * ~is_floor).mean()),
        # the wall side of a table is only 2 mm from the wall, a branch comes in over the inner side, at
        # most the width of the table
        "lean": float(P.BED_BOARD[0] + 2 * P.BED_STOP[1]),
    }
    # faces on the plate
    bed = (n[:, 2] <= -0.99) & (zmax < 0.01)
    r_ax = np.hypot(dx - P.TURRET_X, dy - P.TURRET_Y)
    isl = bed & (r_ax < P.BED_ISLAND_R + 1.0)
    rep["contact"] = {"island": float(a[isl].sum()), "rim": float(a[bed & ~isl].sum()),
                      "rim_width": P.BED_WALL + P.BED_RIM_BEAD[0] - 2 * P.BED_RIM_BEAD[2]}
    return rep


def mass_zones(mesh, floor=None, chamfer=None, wall=None):
    """solid volume in cm3 of each zone of a bed lid mesh in the device frame: underside, floor, the
    chamfers round the tub floor, walls with the bead, island, posts with their tables, the arguments
    give the sizes of an older version"""
    floor = floor_top() if floor is None else floor
    chamfer = P.BED_CHAMFER if chamfer is None else chamfer
    wall = P.BED_WALL if wall is None else wall
    man = checks.to_manifold(mesh)
    big, zt = 400.0, top() + 1.0

    def slab(z0, z1):
        return m3d.Manifold.cube((big, big, z1 - z0), True).translate((0, 0, (z0 + z1) / 2))

    isl = m3d.Manifold.cylinder(zt - P.LID_BOTTOM, P.BED_ISLAND_R + 1.5, -1.0, 96).translate(
        (P.TURRET_X, P.TURRET_Y, P.LID_BOTTOM))
    tables = []
    for sx, sy in CORNERS.values():
        x0, x1, y0, y1 = table_box(sx, sy, 1.0)
        tables.append(m3d.Manifold.cube((x1 - x0, y1 - y0, zt - floor), True).translate(
            ((x0 + x1) / 2, (y0 + y1) / 2, (zt + floor) / 2)))
        px, py = table_layout(sx, sy)["post"]
        tables.append(m3d.Manifold.cylinder(zt - floor, P.BED_STEM_R + P.BED_POST_CHAMFER + 6.5, -1.0, 64).translate(
            (px, py, floor)))
    tab = checks.union(tables)
    iw, idp, ir = P.BASE_W - 2 * wall, P.BASE_D - 2 * wall, P.R_BIG - wall
    inner = m3d.CrossSection([rrect_points(iw, idp, ir, n=24)]).extrude(chamfer + 0.01).translate((0, 0, floor))
    zones = {"underside": man ^ slab(-1.0, P.LID_BOTTOM)}
    rest = man - slab(-1.0, P.LID_BOTTOM)
    zones["island"] = rest ^ isl
    rest = rest - isl
    zones["posts and tables"] = rest ^ tab
    rest = rest - tab
    zones["floor"] = rest ^ slab(P.LID_BOTTOM, floor)
    rest = rest - slab(P.LID_BOTTOM, floor)
    zones["chamfers"] = rest ^ inner
    zones["walls and bead"] = rest - inner
    return {k: float(v.volume() / 1000.0) for k, v in zones.items()}


def floor_sag(load_kg=1.5, e_mod=2500.0, nu=0.35):
    """sag of the tub floor in mm under wet soil, rough: a square plate the size of the tub, simply
    supported on the walls, which hang on the four columns and bend far less, no credit for the ribs
    under the floor, the island or the posts, printed PLA taken at 2500 MPa"""
    iw, _, _ = inner_size()
    q = load_kg * 9.81 / (iw * iw)
    d = e_mod * P.BED_FLOOR_T ** 3 / (12 * (1 - nu ** 2))
    return 0.00406 * q * iw ** 4 / d


def estimate_at(mesh, layer):
    """estimate.py for another layer height: the model keeps its flow, and a second figure where the
    printer moves at the same speed with thicker lines, so the flow grows with the layer"""
    from . import estimate as E
    _, infill, _ = E.SETTINGS["bedlid"]
    vol = float(mesh.volume)
    shell = min(vol, float(mesh.area) * 1.4)
    material = shell + (vol - shell) * infill / 100.0
    layers = max(1, int(round(float(mesh.extents[2]) / layer)))
    grams = material / 1000.0 * E.DENSITY
    flow_bound = (material / E.FLOW + layers * E.LAYER_S) / 60.0
    speed_bound = (material / (E.FLOW * layer / 0.2) + layers * E.LAYER_S) / 60.0
    return {"layer": layer, "grams": grams, "minutes": flow_bound, "minutes_speed": speed_bound}


def support_estimate(rep):
    """filament and time of the supports, rough: a share of the open volume under the supported faces
    plus interface layers on them, at the flow of estimate.py, slower for the many short moves"""
    from . import estimate as E
    s = rep["support"]
    out = {}
    for key, share, iface in (("sparse", 0.04, 0.4), ("normal", 0.12, 0.6)):
        vol = s["volume"] * share + s["area"] * iface * 0.7
        grams = vol / 1000.0 * E.DENSITY
        minutes = vol / E.FLOW / 60.0 * 1.6
        out[key] = {"share": share, "volume": vol, "grams": grams, "minutes": minutes}
    return out
