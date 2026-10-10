"""off screen renders with pyvista, colour roles from blueprint section 9"""

import numpy as np
import pyvista as pv

from . import params as P

pv.OFF_SCREEN = True


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
    # thin busbar like lines inside every cell
    for j in range(cells[1]):
        for k in (0.33, 0.66):
            y = int((j + k) * ch)
            img[y:y + 1, :] = base + 14
    return pv.Texture(np.clip(img, 0, 255).astype(np.uint8))


def add_panel_face(pl, corners):
    """corners: lower left, lower right, upper right, upper left of the visible panel face"""
    quad = pv.Quadrilateral(np.asarray(corners, float))
    quad.texture_map_to_plane(origin=corners[0], point_u=corners[1], point_v=corners[3], inplace=True)
    pl.add_mesh(quad, texture=panel_texture(), ambient=0.25, diffuse=0.7, specular=0.35, specular_power=40)


def setup_lights(pl, key_dir=(-0.6, 1.0, 1.3)):
    pl.remove_all_lights()
    key = pv.Light(position=tuple(np.array(key_dir) * 1000), focal_point=(0, 0, 60), intensity=0.85, light_type="scene light")
    fill = pv.Light(position=(900, 300, 400), focal_point=(0, 0, 60), intensity=0.35, light_type="scene light")
    rim = pv.Light(position=(-200, -1000, 600), focal_point=(0, 0, 60), intensity=0.45, light_type="scene light")
    top = pv.Light(position=(0, 0, 1200), focal_point=(0, 0, 0), intensity=0.25, light_type="scene light")
    for lt in (key, fill, rim, top):
        pl.add_light(lt)


def shade_mesh(mesh, feature_angle=32):
    pd = to_pv(mesh)
    return pd.compute_normals(split_vertices=True, feature_angle=feature_angle, auto_orient_normals=False)


def render(items, path, camera, size=(1600, 1200), panels=(), parallel=False, zoom=1.0, key_dir=(-0.6, 1.0, 1.3)):
    """items: list of (trimesh, colour, opacity), camera: (position, focal point, up)"""
    pl = pv.Plotter(off_screen=True, window_size=size)
    pl.set_background(P.COLORS["background"])
    for mesh, color, opacity in items:
        pl.add_mesh(shade_mesh(mesh), color=color, opacity=opacity, smooth_shading=True,
                    ambient=0.18, diffuse=0.8, specular=0.12, specular_power=18)
    for corners in panels:
        add_panel_face(pl, corners)
    setup_lights(pl, key_dir)
    pl.camera_position = camera
    if parallel:
        pl.enable_parallel_projection()
    pl.camera.zoom(zoom)
    pl.enable_anti_aliasing("ssaa")
    pl.screenshot(str(path))
    pl.close()
