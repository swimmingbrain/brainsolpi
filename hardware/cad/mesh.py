"""turn build123d solids into triangle meshes and move them around"""

import math

import numpy as np
import trimesh


def to_trimesh(shape, tol=0.04, ang=0.15):
    verts, tris = shape.tessellate(tol, ang)
    v = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=float)
    f = np.array(tris, dtype=np.int64)
    m = trimesh.Trimesh(v, f, process=True)
    m.merge_vertices(digits_vertex=5)
    m.fix_normals()
    return m


def rot_matrix(axis, angle_deg, origin):
    """4x4 right handed rotation about an axis through origin"""
    return trimesh.transformations.rotation_matrix(math.radians(angle_deg), np.asarray(axis, float), np.asarray(origin, float))


def pose_matrices(pan, tilt, pan_origin, tilt_origin):
    """matrices for the neck group and the head group, blueprint section 3 and 9

    the head first turns about the tilt axis at its pan 0 position, then everything that
    pans turns about the pan axis, axis (0, 0, -1) so positive pan turns clockwise from above
    """
    m_pan = rot_matrix((0, 0, -1), pan, pan_origin)
    m_tilt = rot_matrix((1, 0, 0), tilt, tilt_origin)
    return m_pan, m_pan @ m_tilt


def transformed(mesh, matrix):
    m = mesh.copy()
    m.apply_transform(matrix)
    return m


def apply_point(matrix, p):
    v = np.array([p[0], p[1], p[2], 1.0])
    return (matrix @ v)[:3]
