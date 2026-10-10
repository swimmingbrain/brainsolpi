"""simple keep out solids of the bought parts, placed in the device frame at pan 0 and tilt 0

they are not pretty, they are there so the checks can prove that nothing collides
"""

import math

from build123d import Location, Part, Plane, Vector

from . import params as P
from .helpers import box, cyl


def frame_map(shape, origin, x_dir, z_dir):
    """place a shape built in a local frame, local x and z map to the given directions"""
    pl = Plane(origin=Vector(*origin), x_dir=Vector(*x_dir), z_dir=Vector(*z_dir))
    return pl.location * shape


# servo


def servo_local():
    """case bottom at z = 0, spline axis on the z axis, the case runs toward minus x"""
    near = P.SERVO_SHAFT_FROM_END
    far = near - P.SERVO_L
    w = P.SERVO_W / 2
    s = box(far, near, -w, w, 0, P.SERVO_H)
    s += box(far - P.SERVO_TAB_LEN, near + P.SERVO_TAB_LEN, -w, w, P.SERVO_TAB_Z, P.SERVO_TAB_Z + P.SERVO_TAB_T)
    s += cyl("z", P.SERVO_BOSS_R, P.SERVO_H - 0.01, P.SERVO_BOSS_TOP)
    s += cyl("z", P.SERVO_SPLINE_D / 2, P.SERVO_BOSS_TOP - 0.01, P.SERVO_BOSS_TOP + P.SERVO_SPLINE_LEN)
    # where the lead leaves the far end, the first few millimetres are stiff
    s += box(far - 4.0, far + 0.01, -P.SERVO_LEAD_W / 2, P.SERVO_LEAD_W / 2,
             P.SERVO_LEAD_Z - P.SERVO_LEAD_T / 2 - 0.4, P.SERVO_LEAD_Z + P.SERVO_LEAD_T / 2 + 0.4)
    return s


def pan_servo_frame():
    """origin, local x and local z of the pan servo in the device frame"""
    boss_face = P.BASE_TOP + P.PAN_BOSS_GAP
    origin = (P.TURRET_X, P.TURRET_Y, boss_face + P.SERVO_BOSS_TOP)
    return origin, (1, 0, 0), (0, 0, -1)


def tilt_servo_frame():
    """the tilt servo lies at the top of the neck, spline out of the left side wall"""
    boss_face_x = tilt_boss_face_x()
    origin = (boss_face_x + P.SERVO_BOSS_TOP, P.TURRET_Y, P.Z_TILT)
    return origin, (0, 0, 1), (-1, 0, 0)


def tilt_boss_face_x():
    # the ear collar and horn pocket fix where the horn sits, the servo follows from that
    socket_floor = -(P.NECK_W / 2 + P.EAR_GAP) - socket_depth()
    hub_end = socket_floor + (P.HORN_TOTAL_H - P.HORN_ARM_T)
    return hub_end + P.HORN_HUB_PLAY


def socket_depth():
    return (P.RING_H - P.EAR_GAP) + P.COLLAR_PLAY / 2


def pan_servo():
    o, x, z = pan_servo_frame()
    return frame_map(servo_local(), o, x, z)


def tilt_servo():
    o, x, z = tilt_servo_frame()
    return frame_map(servo_local(), o, x, z)


# horns


def horn_local(arms=1, length=None, bore=True, screw=True):
    """arm underside at z = 0, hub toward plus z, arm along plus x (and minus x for two arms)"""
    length = length or P.HORN_SINGLE_LEN
    hub_r = P.HORN_HUB_D / 2
    ext = P.HORN_TOTAL_H - P.HORN_ARM_T
    s = cyl("z", hub_r, -P.HORN_ARM_T, ext)
    for sign in ([1, -1] if arms == 2 else [1]):
        s += arm_solid(sign, length, -P.HORN_ARM_T, 0.0)
    if bore:
        s -= cyl("z", P.SERVO_SPLINE_D / 2 + 0.05, -P.HORN_ARM_T + 0.6, ext + 0.1)
    if screw:
        s += cyl("z", P.HORN_SCREW_HEAD_D / 2, -P.HORN_ARM_T - P.HORN_SCREW_HEAD_H, -P.HORN_ARM_T + 0.01)
    return s


def arm_solid(sign, length, z0, z1, grow=0.0):
    """tapered horn arm with a round tip, grow widens it for pockets"""
    from build123d import Polygon, extrude

    w0 = P.HORN_ARM_W0 / 2 + grow
    w1 = P.HORN_ARM_W1 / 2 + grow
    tip_c = length - P.HORN_ARM_W1 / 2
    pts = [(0, -w0), (tip_c, -w1)]
    for i in range(1, 12):
        a = -math.pi / 2 + math.pi * i / 12
        pts.append((tip_c + w1 * math.cos(a), w1 * math.sin(a)))
    pts += [(tip_c, w1), (0, w0)]
    pts = [(sign * x, y) for x, y in pts]
    if sign < 0:
        pts = pts[::-1]
    return extrude(Plane.XY.offset(z0) * Polygon(*pts, align=None), z1 - z0)


def pan_horn_frame():
    """the pan horn hangs under the lid, its arm points to the left away from the cable slot"""
    boss_face = P.BASE_TOP + P.PAN_BOSS_GAP
    hub_end = boss_face - P.HORN_HUB_PLAY
    arm_top = hub_end - (P.HORN_TOTAL_H - P.HORN_ARM_T)
    return (P.TURRET_X, P.TURRET_Y, arm_top), (-1, 0, 0), (0, 0, 1)


def pan_horn():
    o, x, z = pan_horn_frame()
    return frame_map(horn_local(), o, x, z)


def tilt_horn_frame():
    """the tilt horn sits in the left ear, arm toward the head"""
    socket_floor = -(P.NECK_W / 2 + P.EAR_GAP) - socket_depth()
    return (socket_floor, P.TURRET_Y, P.Z_TILT), (0, 1, 0), (1, 0, 0)


def tilt_horn():
    o, x, z = tilt_horn_frame()
    return frame_map(horn_local(), o, x, z)


# head frame helpers, u to the right, v up, n toward the front at pan 0 and tilt 0


def head_xyz(u, v, n):
    return (u, P.HEAD_BACK_Y + n, P.Z_TILT + v)


def panel():
    x0, y0, z0 = head_xyz(-P.PANEL_W / 2, -P.PANEL_H / 2, P.PANEL_BACK_N)
    x1, y1, z1 = head_xyz(P.PANEL_W / 2, P.PANEL_H / 2, P.PANEL_FRONT_N)
    return box(x0, x1, y0, y1, z0, z1)


def module_local(kind="ldr"):
    """sensor end at x = 0, header end at x = MOD_L, board bottom at z = 0, parts on top"""
    s = box(0, P.MOD_L, -P.MOD_W / 2, P.MOD_W / 2, 0, P.MOD_T)
    for y in (-P.MOD_HOLE_SPACING / 2, P.MOD_HOLE_SPACING / 2):
        s -= cyl("z", P.MOD_HOLE_D / 2, -0.1, P.MOD_T + 0.1, (P.MOD_HOLE_FROM_SENSOR_END, y))
    pins = 3 if kind == "ldr" else 4
    hw = pins * P.PITCH / 2 + 0.1
    if kind == "ldr":
        s += cyl("z", P.LDR_D / 2, P.MOD_T - 0.01, P.MOD_T + P.LDR_TOP, (P.LDR_FROM_END, 0))
    else:
        s += box(P.BH_CHIP_FROM_END - 1.5, P.BH_CHIP_FROM_END + 1.5, -1.0, 1.0, P.MOD_T - 0.01, P.MOD_T + P.BH_CHIP_TOP)
        # small parts around the chip
        s += box(3.0, 10.0, -6.0, 6.0, P.MOD_T - 0.01, P.MOD_T + 1.0)
    # right angle header and the plug that sits on it, lying flat
    s += box(P.MOD_L - 2.5, P.MOD_L + 0.01, -hw, hw, P.MOD_T - 0.01, P.MOD_T + 2.6)
    s += box(P.MOD_L, P.MOD_L + P.PLUG_REACH, -hw, hw, P.MOD_T + 0.2, P.MOD_T + P.MOD_PARTS_H)
    # solder joints under the board at the header and at the sensor
    s += box(P.MOD_L - 4.0, P.MOD_L - 0.5, -hw, hw, -P.MOD_UNDER, 0.01)
    s += box(P.LDR_FROM_END - 2.0, P.LDR_FROM_END + 6.0, -3.0, 3.0, -P.MOD_UNDER, 0.01)
    return s


def module_placement(sensor_uv, inward_uv, kind="ldr"):
    """origin, x dir and z dir of a module in the device frame"""
    off = P.LDR_FROM_END if kind == "ldr" else P.BH_CHIP_FROM_END
    su, sv = sensor_uv
    iu, iv = inward_uv
    eu, ev = su - off * iu, sv - off * iv
    origin = head_xyz(eu, ev, P.PCB_BOTTOM_N)
    return origin, (iu, 0, iv), (0, 1, 0)


def module(sensor_uv, inward_uv, kind="ldr"):
    o, x, z = module_placement(sensor_uv, inward_uv, kind)
    return frame_map(module_local(kind), o, x, z)


def sensor_layout():
    """sensor centres on the head and the direction toward the board middle, in u and v

    the four photoresistors sit in the middle of each edge, the bh1750 next to the top right
    corner of the panel inside the wide side border
    """
    e = P.EYE_FROM_PANEL
    hw, hh = P.PANEL_W / 2, P.PANEL_H / 2
    lay = {
        "L": ((-hw - e, 0.0), (1, 0)),
        "R": ((hw + e, 0.0), (-1, 0)),
        "U": ((0.0, hh + e), (0, -1)),
        "D": ((0.0, -hh - e), (0, 1)),
    }
    inner_v = P.HEAD_H / 2 - P.HEAD_WALL_T - 0.4
    bh_v = inner_v - P.MOD_W / 2
    inner_u = P.HEAD_W / 2 - P.HEAD_WALL_T - 0.4
    bh_u = inner_u - P.BH_CHIP_FROM_END
    lay["lux"] = ((bh_u, bh_v), (-1, 0))
    return lay


def modules():
    out = {}
    for name, (s, i) in sensor_layout().items():
        out[name] = module(s, i, "bh" if name == "lux" else "ldr")
    return out


# raspberry pi 3b+


def pi_local():
    t = P.PI_T
    s = box(0, P.PI_L, 0, P.PI_W, 0, t)
    ov = P.PI_PORT_OVERHANG
    s += box(P.PI_L - 21 + ov, P.PI_L + ov, P.PI_ETH_Y - P.PI_ETH_W / 2, P.PI_ETH_Y + P.PI_ETH_W / 2, t, t + P.PI_ETH_H)
    for yc in P.PI_USB_Y:
        s += box(P.PI_L - 17.5 + ov, P.PI_L + ov, yc - P.PI_USB_W / 2, yc + P.PI_USB_W / 2, t, t + P.PI_USB_H)
    s += box(7.0, 58.0, 49.9, 55.0, t, t + P.PI_GPIO_H)
    s += box(P.PI_PWR_X - 4.0, P.PI_PWR_X + 4.0, -1.5, 4.0, t, t + 3.0)
    s += box(32.0 - 7.5, 32.0 + 7.5, -1.5, 10.0, t, t + 6.5)
    s += box(53.5 - 3.5, 53.5 + 3.5, -2.5, 12.0, t, t + 6.0)
    s += box(-P.PI_SD_OVERHANG, 15.0, 22.0, 34.0, -1.5, 0.01)
    under = box(6.0, 80.0, 7.0, 49.0, -P.PI_UNDER, 0.01)
    s += under
    # micro usb power plug, the plug stays inside the base
    pw, ph, pl = P.MICRO_USB_PLUG
    s += box(P.PI_PWR_X - pw / 2, P.PI_PWR_X + pw / 2, -1.5 - pl, -1.5, t - 1.5, t - 1.5 + ph)
    # usb a plug of the cable to the uno, lower port of the pair next to the ethernet jack
    aw, ah, al = P.USB_A_PLUG
    yc = P.PI_USB_Y[0]
    s += box(P.PI_L + ov, P.PI_L + ov + al, yc - aw / 2, yc + aw / 2, t + 0.5, t + 0.5 + ah)
    return s


def pi_z0():
    return P.FLOOR_TOP + P.PI_STANDOFF


def pi_to_device(X, Y):
    return (P.PI_X0 - Y, P.PI_Y0 + X)


def pi():
    origin = (P.PI_X0, P.PI_Y0, pi_z0())
    # local X maps to device +y, local Y maps to device -x
    return frame_map(pi_local(), origin, (0, 1, 0), (0, 0, 1))


# keyestudio uno


def uno_origin():
    x0 = P.TURRET_X + P.UNO_ABLOCK_DX - P.UNO_GVS_W[1]
    y0 = P.TURRET_Y + P.UNO_A0_U + 1.5 * P.PITCH
    z0 = P.LID_BOTTOM - P.UNO_PLUG_TOP_GAP - (P.UNO_T + P.HEADER_BASE_H + P.DUPONT_LEN)
    return x0, y0, z0


def uno_to_device(u, w):
    x0, y0, _ = uno_origin()
    return (x0 + w, y0 - u)


def plug_top_z():
    return uno_origin()[2] + P.UNO_T + P.HEADER_BASE_H + P.DUPONT_LEN


def uno_local():
    t = P.UNO_T
    s = box(0, P.UNO_L, 0, P.UNO_W, 0, t)
    for i, (u, w) in enumerate(P.UNO_HOLES):
        s -= cyl("z", P.UNO_HOLE_D / 2, -0.1, t + 0.1, (u, w))
    s += box(-P.UNO_USB_OVERHANG, 10.0, P.UNO_USB_W[0], P.UNO_USB_W[1], t, t + P.UNO_USB_H)
    s += box(-P.UNO_DC_OVERHANG, 12.0, P.UNO_DC_W[0], P.UNO_DC_W[1], t, t + P.UNO_DC_H)
    s += box(18.0, 65.0, 50.2, 52.7, t, t + 8.5)
    s += box(27.0, 64.0, 0.7, 3.2, t, t + 8.5)
    pin_top = t + P.UNO_PIN_H
    g0, s0 = min(P.UNO_GVS_W) - 1.27, max(P.UNO_GVS_W) + 1.27
    s += box(P.UNO_A0_U - 1.27, P.UNO_A0_U + 5 * P.PITCH + 1.27, g0, s0, t, pin_top)
    d0, d1 = min(P.UNO_DGVS_W) - 1.27, max(P.UNO_DGVS_W) + 1.27
    s += box(17.0, 64.0, d0, d1, t, pin_top)
    i0, i1 = min(P.UNO_I2C_W) - 1.27, max(P.UNO_I2C_W) + 1.27
    s += box(P.UNO_I2C_U - 1.27, P.UNO_I2C_U + 1.27, i0, i1, t, pin_top)
    plug_z0 = t + P.HEADER_BASE_H
    plug_z1 = plug_z0 + P.DUPONT_LEN
    for i in range(4):
        u = P.UNO_A0_U + i * P.PITCH
        s += box(u - 1.25, u + 1.25, g0 - 0.1, s0 + 0.1, plug_z0, plug_z1)
    for u in (P.UNO_D9_U, P.UNO_D10_U):
        s += box(u - 1.25, u + 1.25, d0 - 0.1, d1 + 0.1, plug_z0, plug_z1)
    s += box(P.UNO_I2C_U - 1.25, P.UNO_I2C_U + 1.25, i0 - 0.1, i1 + 0.1, plug_z0, plug_z1)
    s += box(4.0, 64.0, 4.0, 49.0, -P.UNO_UNDER, 0.01)
    # usb b plug of the cable from the pi
    bw, bh, bl = P.USB_B_PLUG
    wc = sum(P.UNO_USB_W) / 2
    s += box(-P.UNO_USB_OVERHANG - bl, -P.UNO_USB_OVERHANG, wc - bw / 2, wc + bw / 2, t + 0.0, t + bh)
    return s


def uno():
    x0, y0, z0 = uno_origin()
    # local u maps to device -y, local w to device +x
    return frame_map(uno_local(), (x0, y0, z0), (0, -1, 0), (0, 0, 1))


def a_pin_xy(i):
    """device x and y of the S pin of analog input i"""
    return uno_to_device(P.UNO_A0_U + i * P.PITCH, P.UNO_GVS_W[2])


def base_electronics():
    return {"pi": pi(), "uno": uno(), "pan_horn": pan_horn()}


def neck_electronics():
    return {"pan_servo": pan_servo(), "tilt_servo": tilt_servo()}


def head_electronics():
    out = {"panel": panel(), "tilt_horn": tilt_horn()}
    for k, m in modules().items():
        out["module_" + k] = m
    return out


def as_part(s):
    return s if isinstance(s, Part) else Part(s.wrapped)


_ = Location
