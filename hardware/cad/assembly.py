"""all printed parts with their group, colour role, count and print orientation"""

import math
from dataclasses import dataclass, field

import numpy as np

from . import base, head, kit, neck
from . import params as P
from .mesh import pose_matrices, rot_matrix, to_trimesh, transformed

PAN_ORIGIN = (P.TURRET_X, P.TURRET_Y, P.BASE_TOP)
TILT_ORIGIN = (P.TURRET_X, P.TURRET_Y, P.Z_TILT)


@dataclass
class Part:
    name: str
    shape: object
    group: str  # base, neck or head, blueprint section 9
    role: str  # body, dark or accent
    count: int = 1
    print_rot: tuple = ((1, 0, 0), 0.0)  # axis and angle that put the part on the bed
    note: str = ""
    instances: list = field(default_factory=list)  # extra placements in the device frame
    _mesh: object = None

    def mesh(self):
        if self._mesh is None:
            self._mesh = to_trimesh(self.shape)
        return self._mesh

    def print_matrix(self):
        axis, ang = self.print_rot
        m = rot_matrix(axis, ang, (0, 0, 0))
        pts = transformed(self.mesh(), m).vertices
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        t = np.eye(4)
        t[:3, 3] = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
        return t @ m

    def print_mesh(self):
        return transformed(self.mesh(), self.print_matrix())

    def placed_meshes(self):
        """the part and its extra copies in the device frame"""
        out = [self.mesh()]
        for m in self.instances:
            out.append(transformed(self.mesh(), m))
        return out


def build_parts():
    parts = []
    parts.append(Part("tray", base.tray(), "base", "body", note="floor on the bed"))
    parts.append(Part("lid", base.lid(), "base", "body", print_rot=((1, 0, 0), 180.0), note="top face on the bed"))
    feet = base.feet()
    f0 = feet[0]
    x0, y0 = base.COLUMN_XY[0]
    inst = []
    for x, y in base.COLUMN_XY[1:]:
        t = np.eye(4)
        t[:3, 3] = [x - x0, y - y0, 0]
        inst.append(t)
    parts.append(Part("foot", f0, "base", "dark", count=4, print_rot=((1, 0, 0), 180.0),
                      note="tray side on the bed, countersink up", instances=inst))
    front, back = neck.halves()
    parts.append(Part("neck_front", front, "neck", "dark", print_rot=((1, 0, 0), -90.0), note="front face on the bed"))
    parts.append(Part("neck_back", back, "neck", "dark", print_rot=((1, 0, 0), 90.0), note="back face on the bed"))
    parts.append(Part("head_back", head.back_shell(), "head", "dark", print_rot=((1, 0, 0), 90.0), note="back face on the bed"))
    parts.append(Part("head_bezel", head.bezel(), "head", "dark", print_rot=((1, 0, 0), -90.0), note="front face on the bed"))
    parts.append(Part("ear_horn", head.ear(-1), "head", "dark", print_rot=((0, 1, 0), 90.0), note="inner face on the bed"))
    parts.append(Part("ear_pivot", head.ear(1), "head", "dark", print_rot=((0, 1, 0), -90.0), note="inner face on the bed"))
    caps = head.caps_placed()
    # the right cap is the left one mirrored in place, same print
    mirror = np.diag([-1.0, 1.0, 1.0, 1.0])
    parts.append(Part("cap", caps[0], "head", "accent", count=2, print_rot=((0, 1, 0), -90.0),
                      note="outer face on the bed", instances=[mirror]))
    return parts


def electronics():
    """keep out solids per group, as meshes"""
    out = {"base": {}, "neck": {}, "head": {}}
    for k, s in kit.base_electronics().items():
        out["base"][k] = to_trimesh(s)
    for k, s in kit.neck_electronics().items():
        out["neck"][k] = to_trimesh(s)
    for k, s in kit.head_electronics().items():
        out["head"][k] = to_trimesh(s)
    return out


def group_matrix(group, pan, tilt):
    m_neck, m_head = pose_matrices(pan, tilt, PAN_ORIGIN, TILT_ORIGIN)
    if group == "base":
        return np.eye(4)
    return m_neck if group == "neck" else m_head


def posed(parts, pan, tilt, elec=None):
    """list of (name, group, role, mesh) at a pose"""
    out = []
    for p in parts:
        m = group_matrix(p.group, pan, tilt)
        for i, pm in enumerate(p.placed_meshes()):
            out.append((p.name if i == 0 else f"{p.name}_{i + 1}", p.group, p.role, transformed(pm, m)))
    if elec:
        for g, d in elec.items():
            m = group_matrix(g, pan, tilt)
            for k, mesh in d.items():
                out.append((k, g, "kit", transformed(mesh, m)))
    return out


def panel_corners(pan, tilt):
    """visible panel face corners, lower left, lower right, upper right, upper left"""
    _, m_head = pose_matrices(pan, tilt, PAN_ORIGIN, TILT_ORIGIN)
    hw, hh = P.PANEL_W / 2 - P.BEZEL_LIP + 0.5, P.PANEL_H / 2 - P.BEZEL_LIP + 0.5
    pts = []
    for u, v in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        x, y, z = kit.head_xyz(u, v, P.PANEL_FRONT_N + 0.02)
        pts.append((m_head @ np.array([x, y, z, 1.0]))[:3])
    return pts


_ = math
