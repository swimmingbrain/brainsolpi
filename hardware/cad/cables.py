"""cable length budget, every cable traced from its UNO header to its part for the worst pose

a route is a chain of segments, fixed segments ride inside one rigid group, free segments
cross a joint and must be long enough for the worst pan or tilt
lengths are measured between the backs of the plug housings, where the wire leaves them
"""

import math

import numpy as np

from . import head as H
from . import kit
from . import neck as N
from . import params as P
from .assembly import group_matrix
from .mesh import apply_point

# extra wire for bends and a little sag, measured on paper sketches of each segment
ALLOW = {"uno": 6.0, "neck": 6.0, "loop": 8.0, "head": 5.0, "servo": 6.0}


def poly_len(pts):
    pts = np.asarray(pts, float)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def turret(x, y, z):
    """point in the turret frame (pan 0) given relative to the pan axis"""
    return (P.TURRET_X + x, P.TURRET_Y + y, z)


def exit_points():
    """where the bundle crosses the lid slot and the foot floor, pan 0"""
    # the bundle hugs the inner edge of the slot on its way down to the uno
    below = turret(P.SLOT_R - P.SLOT_W / 2 + 1.5, 0.0, P.LID_BOTTOM - 1.0)
    above = turret(P.SLOT_R, 0.0, P.BASE_TOP + P.FOOT_FLOOR_T)
    return below, above


def neck_path():
    """from the foot floor up the cable column, around the pivot boss, to the top entry"""
    _, above = exit_points()
    # the column runs straight up beside the pivot boss, the bundle leans from the exit to the entry
    pts = [above,
           turret(P.SLOT_R, 0.0, P.BASE_TOP + 8.0),
           turret(N.CABLE_X, 0.0, P.NECK_TOP - P.NECK_WALL),
           turret(N.CABLE_X, 0.0, P.NECK_TOP)]
    return pts


def head_exit():
    return kit.head_xyz(H.CABLE_U, 0.0, 0.0)


def module_plug_end(name):
    (su, sv), (iu, iv) = kit.sensor_layout()[name]
    off = P.LDR_FROM_END if name != "lux" else P.BH_CHIP_FROM_END
    eu, ev = su - off * iu, sv - off * iv
    reach = P.MOD_L + P.PLUG_REACH
    return (eu + reach * iu, ev + reach * iv)


def head_path(name):
    """inside the head along the floor from the plug to the cable exit"""
    pu, pv = module_plug_end(name)
    n_plug = P.PCB_TOP_N + 1.5
    # the wires run free behind the panel to the near end of the exit slot
    half = H.EXIT_L / 2 - H.EXIT_W / 2
    eu = min(max(pu, H.CABLE_U - half), H.CABLE_U + half)
    return [kit.head_xyz(pu, pv, n_plug), kit.head_xyz(eu, 0.0, P.BACK_T), kit.head_xyz(eu, 0.0, 0.0)]


def uno_pin_top(u, w):
    x, y = kit.uno_to_device(u, w)
    return (x, y, kit.plug_top_z())


def free_max(fixed_pt, moving_local, which, pans, tilts):
    """longest straight distance between a point and a point that moves with a group"""
    best, pose = 0.0, None
    for pan in pans:
        for tilt in tilts:
            m = group_matrix(which, pan, tilt)
            p = apply_point(m, moving_local)
            d = float(np.linalg.norm(np.asarray(fixed_pt) - p))
            if d > best:
                best, pose = d, (float(pan), float(tilt))
    return best, pose


def loop_max(tilts):
    """distance from the neck top entry to the head exit for every tilt, pan does not matter"""
    entry = neck_path()[-1]
    best, pose = 0.0, None
    for tilt in tilts:
        p = apply_point(group_matrix("head", 0.0, tilt), head_exit())
        d = float(np.linalg.norm(np.asarray(entry) - p))
        if d > best:
            best, pose = d, float(tilt)
    return best, pose


def route_points(name, pan, tilt):
    """polyline of one photoresistor or the bh1750 cable at a pose, for the renders"""
    idx = {"L": 0, "R": 1, "U": 2, "D": 3}
    if name == "lux":
        top = uno_pin_top(P.UNO_I2C_U, sum(P.UNO_I2C_W) / 4)
    else:
        top = uno_pin_top(P.UNO_A0_U + idx[name] * P.PITCH, sum(P.UNO_GVS_W) / 3)
    m_neck = group_matrix("neck", pan, tilt)
    m_head = group_matrix("head", pan, tilt)
    below, _ = exit_points()
    pts = [top, (top[0], top[1], top[2] + 3.0)]
    pts.append(tuple(apply_point(m_neck, below)))
    pts += [tuple(apply_point(m_neck, p)) for p in neck_path()]
    entry = np.asarray(pts[-1])
    hx = apply_point(m_head, head_exit())
    # a soft arc for the service loop, lifted a little above the straight line
    mid = (entry + hx) / 2 + np.array([0.0, 0.0, 6.0])
    pts.append(tuple(mid))
    pts += [tuple(apply_point(m_head, p)) for p in head_path(name)[::-1]]
    return pts


def budget():
    pans = np.arange(P.PAN_RANGE[0], P.PAN_RANGE[1] + 1e-6, 5.0)
    tilts = np.arange(P.TILT_RANGE[0], P.TILT_RANGE[1] + 1e-6, 5.0)
    below, _ = exit_points()
    neck_len = poly_len(neck_path())
    loop_d, loop_pose = loop_max(tilts)
    loop_len = loop_d + ALLOW["loop"]
    rows = []
    sensors = {"L": 0, "R": 1, "U": 2, "D": 3}
    plug_cut = 2 * P.DUPONT_LEN if P.CABLE_LEN_INCLUDES_PLUGS else 0.0
    gvs_mid = sum(P.UNO_GVS_W) / 3
    for name, idx in sensors.items():
        top = uno_pin_top(P.UNO_A0_U + idx * P.PITCH, gvs_mid)
        uno_d, uno_pose = free_max(top, below, "neck", pans, [0.0])
        uno_len = uno_d + ALLOW["uno"]
        head_len = poly_len(head_path(name)) + ALLOW["head"]
        total = uno_len + neck_len + ALLOW["neck"] + loop_len + head_len
        avail = P.PHOTO_CABLE - plug_cut
        rows.append({"cable": f"photoresistor {name} to A{idx}", "uno": uno_len, "neck": neck_len + ALLOW["neck"],
                     "loop": loop_len, "head": head_len, "total": total, "available": avail,
                     "slack": avail - total, "worst": f"pan {uno_pose[0]:.0f}, tilt {loop_pose:.0f}"})
    # bh1750 on the i2c header
    i2c = uno_pin_top(P.UNO_I2C_U, sum(P.UNO_I2C_W) / 4)
    uno_d, uno_pose = free_max(i2c, below, "neck", pans, [0.0])
    head_len = poly_len(head_path("lux")) + ALLOW["head"]
    total = uno_d + ALLOW["uno"] + neck_len + ALLOW["neck"] + loop_len + head_len
    avail = P.BH_CABLE - plug_cut
    rows.append({"cable": "bh1750 to SDA SCL", "uno": uno_d + ALLOW["uno"], "neck": neck_len + ALLOW["neck"],
                 "loop": loop_len, "head": head_len, "total": total, "available": avail, "slack": avail - total,
                 "worst": f"pan {uno_pose[0]:.0f}, tilt {loop_pose:.0f}"})
    # servo leads, one plug at the uno end only
    dg = sum(P.UNO_DGVS_W) / 3
    to, _, _ = kit.tilt_servo_frame()
    tilt_lead = turret(to[0] - P.SERVO_LEAD_Z, 0.0, P.Z_TILT - (P.SERVO_L - P.SERVO_SHAFT_FROM_END) - 2.0)
    tilt_path = [tilt_lead, turret(to[0] - P.SERVO_LEAD_Z, 0.0, P.Z_TILT - 21.0), turret(13.0, 0.0, P.Z_TILT - 21.0),
                 turret(13.0, 0.0, P.BASE_TOP + 10.0), exit_points()[1]]
    po, _, _ = kit.pan_servo_frame()
    far = P.SERVO_SHAFT_FROM_END - P.SERVO_L
    pan_lead = turret(far - 2.0, 0.0, po[2] - P.SERVO_LEAD_Z)
    pan_path = [pan_lead, turret(far - 3.0, 0.0, po[2] + 3.0), turret(13.0, 0.0, po[2] + 3.0),
                turret(13.0, 0.0, P.BASE_TOP + 10.0), exit_points()[1]]
    for label, path, u in (("tilt servo to D10", tilt_path, P.UNO_D10_U), ("pan servo to D9", pan_path, P.UNO_D9_U)):
        top = uno_pin_top(u, dg)
        uno_d, uno_pose = free_max(top, below, "neck", pans, [0.0])
        inner = poly_len(path) + ALLOW["servo"] + (P.LID_BOTTOM - 1.0 - 0) * 0
        total = uno_d + ALLOW["uno"] + inner + (P.BASE_TOP + P.FOOT_FLOOR_T - (P.LID_BOTTOM - 1.0))
        avail = P.SERVO_LEAD - P.DUPONT_LEN
        rows.append({"cable": label, "uno": uno_d + ALLOW["uno"], "neck": inner, "loop": 0.0, "head": 0.0,
                     "total": total, "available": avail, "slack": avail - total, "worst": f"pan {uno_pose[0]:.0f}"})
    return rows


def through_lid():
    return P.BASE_TOP + P.FOOT_FLOOR_T - (P.LID_BOTTOM - 1.0)


_ = math
