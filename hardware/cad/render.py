"""off screen renders with pyvista, in the colour roles of params.py"""

import math

import numpy as np
import pyvista as pv

from . import params as P

pv.OFF_SCREEN = True

KIT_COLORS = {
    "pi": "#3e6b52", "uno": "#2e4a74", "pan_horn": "#d8d6d0", "tilt_horn": "#d8d6d0",
    "pan_servo": "#33558a", "tilt_servo": "#33558a", "panel": "#141a2a",
}
MODULE_COLOR = "#20283a"
LOOK = {
    "body": dict(ambient=0.14, diffuse=0.78, specular=0.10, specular_power=12),
    "dark": dict(ambient=0.30, diffuse=0.85, specular=0.30, specular_power=22),
    "accent": dict(ambient=0.22, diffuse=0.80, specular=0.45, specular_power=30),
    "kit": dict(ambient=0.25, diffuse=0.80, specular=0.15, specular_power=15),
}


def to_pv(mesh):
    faces = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64).ravel()
    return pv.PolyData(np.asarray(mesh.vertices, float), faces)


def panel_texture(w_px=1024, h_px=700, cells=(6, 4)):
    """deep blue black with fine cell lines, like the kit panel"""
    base = np.array([20, 26, 42], float)
    img = np.ones((h_px, w_px, 3)) * base
    rng = np.random.default_rng(3)
    img += rng.normal(0, 1.5, img.shape)
    line = np.array([58, 66, 88], float)
    cw, ch = w_px / cells[0], h_px / cells[1]
    for i in range(1, cells[0]):
        x = int(i * cw)
        img[:, x - 1:x + 2] = line
    for j in range(1, cells[1]):
        y = int(j * ch)
        img[y - 1:y + 2, :] = line
    for j in range(cells[1]):
        for k in (0.33, 0.66):
            y = int((j + k) * ch)
            img[y:y + 1, :] = base + 14
    return pv.Texture(np.clip(img, 0, 255).astype(np.uint8))


def add_panel_face(pl, corners):
    """corners: lower left, lower right, upper right, upper left of the visible panel face"""
    quad = pv.Quadrilateral(np.asarray(corners, float))
    quad = quad.texture_map_to_plane(origin=corners[0], point_u=corners[1], point_v=corners[3])
    pl.add_mesh(quad, texture=panel_texture(), ambient=0.3, diffuse=0.7, specular=0.5, specular_power=50)


def setup_lights(pl, center):
    pl.remove_all_lights()
    c = np.asarray(center, float)
    lights = [
        ((-0.7, 1.0, 1.2), 0.75),   # key, front left and high
        ((1.0, 0.6, 0.5), 0.35),    # fill from the right
        ((-0.3, -1.0, 0.8), 0.55),  # rim from behind
        ((0.0, 0.0, 1.0), 0.20),    # soft top
    ]
    for d, k in lights:
        d = np.asarray(d, float)
        d /= np.linalg.norm(d)
        pl.add_light(pv.Light(position=tuple(c + d * 1500), focal_point=tuple(c), intensity=k,
                              light_type="scene light"))


def shade_mesh(mesh, feature_angle=32):
    pd = to_pv(mesh)
    return pd.compute_normals(split_vertices=True, feature_angle=feature_angle, auto_orient_normals=False)


def floor_disc(z=0.0, r=420.0):
    return pv.Disc(center=(0, 0, z - 0.05), inner=0.0, outer=r, normal=(0, 0, 1), c_res=96)


def camera(target, az, el, dist, up=(0, 0, 1)):
    """az in degrees from the device front (+y) toward +x, el above the horizon"""
    a, e = math.radians(az), math.radians(el)
    d = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])
    pos = np.asarray(target, float) + d * dist
    return [tuple(pos), tuple(target), up]


def render(items, path, cam, size=(1600, 1200), panels=(), parallel=False, zoom=1.0, floor=True,
           lines=(), center=(0, -10, 60), occlusion=False):
    """items: list of (trimesh, colour, opacity, role), cam: (position, focal point, up)

    occlusion shades the floor of shallow recesses like the engraving on the lid, close ups only
    """
    pl = pv.Plotter(off_screen=True, window_size=size)
    pl.set_background(P.COLORS["background"])
    if floor:
        pl.add_mesh(floor_disc(), color="#17171a", ambient=0.6, diffuse=0.3, specular=0.0)
    for it in items:
        mesh, color, opacity = it[0], it[1], it[2]
        role = it[3] if len(it) > 3 else "body"
        pl.add_mesh(shade_mesh(mesh), color=color, opacity=opacity, smooth_shading=True, **LOOK.get(role, LOOK["kit"]))
    for corners in panels:
        add_panel_face(pl, corners)
    for pts, color, radius in lines:
        spline = pv.Spline(np.asarray(pts, float), max(len(pts) * 8, 40))
        pl.add_mesh(spline.tube(radius=radius), color=color, ambient=0.3, diffuse=0.8)
    setup_lights(pl, center)
    pl.camera_position = cam
    if parallel:
        pl.enable_parallel_projection()
    pl.camera.zoom(zoom)
    if occlusion:
        pl.enable_ssao(radius=0.8, bias=0.1, kernel_size=256, blur=True)
    pl.enable_anti_aliasing("ssaa")
    pl.screenshot(str(path))
    pl.close()
