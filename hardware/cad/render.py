"""off screen renders with pyvista, lit like a small product photo on a sheet of paper

each picture is drawn at twice its size in a few passes that numpy adds up: the soft light
(fill, rim and the room) dimmed where the parts hide the sky, the key light with a soft
shadow, both worked out from depth maps of the parts seen from many directions, the floor
turned into the paper with only its shadow left, and a thin ink outline around the parts
"""

import math

import numpy as np
import pyvista as pv
from PIL import Image
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkFloatArray

pv.OFF_SCREEN = True

# the paper of the sheets, sheets.py uses the same one so a render sits on the page without a seam
PAPER = "#f2efe8"
INK = "#26241f"
ORANGE = "#ff8b4b"
# colours of the printed parts as the renderer takes them, the light grey is set lower than the
# filament because the room light adds on top, its lit top comes out about #e4e1da
FILAMENT = {"body": "#cdc9c3", "dark": "#3b3b3e", "accent": ORANGE}
# the bought parts stay neutral, so the orange keeps its meaning on the sheets
KIT_COLORS = {
    "pi": "#5f6862", "uno": "#5a616b", "pan_horn": "#e4e1da", "tilt_horn": "#e4e1da",
    "pan_servo": "#64666c", "tilt_servo": "#64666c", "panel": "#141a2a",
}
MODULE_COLOR = "#45484f"
SENSOR_COLOR = "#a39782"

# matte plastic that still shows its form: diffuse, specular and its power, extra room light and
# how much of the key lamp it takes, the light grey plastic scatters light inside and picks up the
# bounce from the paper so it gets more room light and less lamp, its shaded sides stay light,
# the panel is a little glossy and the orange a little brighter so it reads as the orange of the sheets
LOOK = {
    "body": (0.86, 0.07, 8, 0.5, 0.5),
    "dark": (0.86, 0.22, 8, 0.0, 1.0),
    "accent": (0.86, 0.12, 12, 0.22, 1.0),
    "kit": (0.86, 0.10, 10, 0.0, 1.0),
    "panel": (0.60, 0.22, 3, 0.0, 1.0),
}

# the lights in the frame of the camera: to the right, up and toward the camera, then the strength
# and a slightly warm key against a slightly cool fill, like a lamp by a window
KEY = ((-1.0, 1.1, 0.35), 0.70, "#fffaf2")
FILL = ((0.9, 0.25, 0.7), 0.30, "#f2f6ff")
RIM = ((0.45, 0.9, -0.9), 0.35, "#ffffff")
AMBIENT = 0.30
# tan of the half angle of the key light seen from the parts, a larger lamp gives a softer shadow
SOFT = 0.18
# how much the parts take away of the soft light around them, 1 would be a dark room with one window
SKY = 0.6
SS = 2  # drawn at twice the size and scaled down, for smooth edges


def to_pv(mesh):
    faces = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64).ravel()
    return pv.PolyData(np.asarray(mesh.vertices, float), faces)


def rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], float) / 255


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


def panel_face(corners):
    """corners: lower left, lower right, upper right, upper left of the visible panel face"""
    quad = pv.Quadrilateral(np.asarray(corners, float))
    return quad.texture_map_to_plane(origin=corners[0], point_u=corners[1], point_v=corners[3])


def shade_mesh(mesh, feature_angle=32):
    pd = to_pv(mesh)
    return pd.compute_normals(split_vertices=True, feature_angle=feature_angle, auto_orient_normals=False)


def camera(target, az, el, dist, up=(0, 0, 1)):
    """az in degrees from the device front (+y) toward +x, el above the horizon"""
    a, e = math.radians(az), math.radians(el)
    d = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])
    pos = np.asarray(target, float) + d * dist
    return [tuple(pos), tuple(target), up]


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def light_dirs(cam):
    """directions from the scene toward each light, they turn with the camera"""
    pos, tgt, up = (np.asarray(c, float) for c in cam)
    f = unit(tgt - pos)
    r = unit(np.cross(f, up))
    z = np.array([0, 0, 1.0])
    return [(unit(a * r + b * z - c * f), k, col) for (a, b, c), k, col in (KEY, FILL, RIM)]


def zbuffer(pl):
    w, h = pl.window_size
    pl.render_window.Render()
    arr = vtkFloatArray()
    pl.render_window.GetZbufferData(0, 0, w - 1, h - 1, arr)
    return vtk_to_numpy(arr).reshape(h, w)[::-1].astype(np.float32)


def matrix(pl):
    w, h = pl.window_size
    m = pl.camera.GetCompositeProjectionTransformMatrix(w / h, -1, 1)
    return np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)])


def unproject(z, m):
    """world points of every pixel from the depth buffer, a band of rows at a time to save memory"""
    h, w = z.shape
    inv = np.linalg.inv(m)
    x = (np.arange(w) + 0.5) / w * 2 - 1
    out = np.empty((h, w, 3), np.float32)
    for r0 in range(0, h, 256):
        r1 = min(h, r0 + 256)
        y = 1 - (np.arange(r0, r1) + 0.5) / h * 2
        X, Y = np.meshgrid(x, y)
        ndc = np.stack([X, Y, z[r0:r1].astype(np.float64) * 2 - 1, np.ones_like(X)], -1)
        p = ndc @ inv.T
        out[r0:r1] = p[..., :3] / p[..., 3:]
    return out


def screenshot(pl):
    pl.render()
    return np.asarray(pl.screenshot(return_img=True))[..., :3].astype(np.float32) / 255


def vogel(n):
    """n points on a disc of radius 1, radius and angle"""
    i = np.arange(n) + 0.5
    return np.sqrt(i / n), i * 2.39996323


def lamp_dirs(key, n):
    """n directions spread over the round key lamp"""
    side = np.cross(key, (0, 0, 1.0))
    side = unit(side if np.linalg.norm(side) > 1e-6 else (1.0, 0, 0))
    up = np.cross(side, key)
    rr, aa = vogel(n)
    return [unit(key + SOFT * r * (math.cos(a) * side + math.sin(a) * up)) for r, a in zip(rr, aa)]


def sky_dirs(n):
    """n directions over the half sphere above the table, more of them high up like a soft room light"""
    rr, aa = vogel(n)
    return [np.array([r * math.cos(a), r * math.sin(a), math.sqrt(1 - r * r)]) for r, a in zip(rr, aa)]


def visibility(pl, pts, normals, dirs, mid, radius, weigh=False, size=1024, jitter=3.0):
    """share of the directions in which a point sees past the parts

    the parts are seen from each direction as a depth map, a point is lit from there when nothing
    in the map lies in front of it, weigh counts each direction by how much the face turns to it
    """
    pl.window_size = (size, size)
    pl.enable_parallel_projection()
    p4 = np.concatenate([pts, np.ones((len(pts), 1), np.float32)], -1)
    texel = 2 * radius * 1.05 / size
    dist = radius * 4
    acc = np.zeros(len(pts), np.float32)
    wsum = np.zeros(len(pts), np.float32)
    # each point looks a few texels off at random, so the edges of the single shadows turn into
    # fine noise that the blur takes away instead of lines
    rng = np.random.default_rng(7)
    for d in dirs:
        ju, jv = (rng.random((2, len(pts)), np.float32) - 0.5) * 2 * jitter
        up = np.cross(np.cross(d, (0, 0, 1.0)), d)
        up = unit(up if np.linalg.norm(up) > 1e-6 else (0, 1.0, 0))
        pl.camera_position = [tuple(mid + d * dist), tuple(mid), tuple(up)]
        pl.camera.parallel_scale = radius * 1.05
        pl.camera.clipping_range = (dist - radius * 1.1, dist + radius * 1.1)
        lmap = zbuffer(pl)
        m = matrix(pl).astype(np.float32)
        near, far = pl.camera.clipping_range
        q = p4 @ m.T
        u = np.clip(np.rint((q[:, 0] + 1) / 2 * size - 0.5 + ju), 0, size - 1).astype(np.int32)
        v = np.clip(np.rint((1 - (q[:, 1] + 1) / 2) * size - 0.5 + jv), 0, size - 1).astype(np.int32)
        # a face turned away from the light needs a larger margin against shading itself, and
        # nothing shallower than the engraving on the lid casts a shadow
        c = normals @ d.astype(np.float32)
        ca = np.clip(np.abs(c), 0.1, 1.0)
        bias = np.maximum(texel * (1.0 + 1.5 * np.sqrt(1 - ca * ca) / ca), 0.8) / (far - near)
        z = lmap[v, u]
        # 1 is the empty background of the map, nothing there casts a shadow
        lit = (z >= (q[:, 2] + 1) / 2 - bias) | (z >= 1.0)
        wt = np.clip(c, 0, None) if weigh else 1.0
        acc += lit * wt
        wsum += wt
    return acc / np.maximum(wsum, 1e-6)


def light_and_shadow(pl, pts, valid, obj, cam_pos, key, mid, radius):
    """key light shadow and sky light of every pixel, worked out on every second pixel

    both get a blur that stays on its side of the edge between the parts and the floor
    """
    h, w = valid.shape
    sub = pts[::2, ::2]
    ok = valid[::2, ::2]
    part = obj[::2, ::2]
    p = sub[ok]
    # the floor is flat, its normal from the depth buffer would only add noise
    nrm = np.where(part[..., None], surface_normals(sub, cam_pos), np.float32([0, 0, 1]))[ok]
    out = []
    # the parts keep sharper detail than the wide soft shadows on the floor
    for dirs, weigh, jitter, blur in ((lamp_dirs(key, 96), False, 2.0, (3, 11)), (sky_dirs(96), True, 5.0, (11, 25))):
        v = np.ones(ok.shape, np.float32)
        v[ok] = visibility(pl, p, nrm, dirs, mid, radius, weigh, jitter=jitter)
        v = np.where(part, masked_blur(v, part, blur[0]), np.where(ok, masked_blur(v, ok & ~part, blur[1]), 1.0))
        out.append(box(np.repeat(np.repeat(v, 2, 0), 2, 1)[:h, :w], 3))
    return out


def masked_blur(v, mask, k):
    m = mask.astype(np.float32)
    return box(v * m, k) / np.maximum(box(m, k), 1e-6)


def box(img, k):
    """mean over k by k pixels around each pixel, edges repeat, one axis at a time in float64 so
    the running sums keep their precision on a large picture
    """
    out = np.asarray(img, np.float64)
    pad = k // 2
    for ax in (0, 1):
        widths = [(0, 0)] * out.ndim
        widths[ax] = (pad + 1, k - 1 - pad)
        c = np.pad(out, widths, mode="edge").cumsum(ax)
        n = out.shape[ax]
        out = (np.take(c, np.arange(k, k + n), ax) - np.take(c, np.arange(0, n), ax)) / k
    return out.astype(np.float32)


def shift(a, dy, dx, fill):
    """a moved by dy rows and dx columns, the uncovered border gets fill"""
    h, w = a.shape[:2]
    out = np.full_like(a, fill)
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = a[max(-dy, 0):h - max(dy, 0), max(-dx, 0):w - max(dx, 0)]
    return out


def dilate(mask, r):
    out = mask.copy()
    ri = int(math.ceil(r))
    for dy in range(-ri, ri + 1):
        for dx in range(-ri, ri + 1):
            if dx * dx + dy * dy <= r * r and (dx or dy):
                out |= shift(mask, dy, dx, False)
    return out


def outline(mask, pts, cam_pos, width):
    """ink around the silhouette and along steps in depth between parts"""
    ring = dilate(mask, width) & ~mask
    dist = np.where(mask, np.linalg.norm(pts - cam_pos, axis=-1), np.inf)
    # a jump in depth of a few percent between neighbours is an edge in front of something,
    # the far side gets the line so the near part keeps its clean edge
    jump = np.zeros_like(mask)
    for dy, dx in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        near = shift(dist, dy, dx, np.inf)
        both = mask & np.isfinite(near)
        rel = np.where(both, (dist - near) / np.where(both, near, 1.0), 0.0)
        jump |= both & (rel > 0.035)
    inner = dilate(jump, max(width - 1.0, 0.0)) & mask
    return ring | inner


def render(items, path, cam, size=(1600, 1200), panels=(), parallel=False, zoom=1.0, floor=True,
           lines=(), lines_role="dark", ink=0.8, marks=None, cast=True):
    """items: list of (trimesh, colour, opacity, role), cam: (position, focal point, up),
    lines: list of (points, colour, radius) with an optional role, else lines_role

    floor puts the parts on the paper with their shadow, ink is the outline width in pixels of
    the final picture, 0 leaves it out, marks are named points in mm, the pixel of each comes back,
    cast False leaves out the shadows and the occlusion
    """
    w, h = size[0] * SS, size[1] * SS
    # no multisampling, a pixel is either a surface or not so the passes add up exactly, the
    # drawing at twice the size already smooths the edges
    pl = pv.Plotter(off_screen=True, window_size=(w, h))
    pl.render_window.SetMultiSamples(0)
    dirs = light_dirs(cam)
    key, soft_lights = dirs[0], dirs[1:]

    parts = []  # actor and its look
    for it in items:
        mesh, color, opacity = it[0], it[1], it[2]
        role = it[3] if len(it) > 3 else "body"
        a = pl.add_mesh(shade_mesh(mesh), color=color, opacity=opacity, smooth_shading=True)
        parts.append((a, LOOK.get(role, LOOK["kit"])))
    for corners in panels:
        a = pl.add_mesh(panel_face(corners), texture=panel_texture())
        parts.append((a, LOOK["panel"]))
    for ln in lines:
        pts, color, r = ln[:3]
        spline = pv.Spline(np.asarray(pts, float), max(len(pts) * 8, 40))
        a = pl.add_mesh(spline.tube(radius=r, n_sides=16), color=color, smooth_shading=True)
        parts.append((a, LOOK[ln[3] if len(ln) > 3 else lines_role]))
    bounds = np.array(pl.bounds).reshape(3, 2)
    mid = bounds.mean(1)
    radius = np.linalg.norm(bounds[:, 1] - bounds[:, 0]) / 2

    floor_actor = None
    if floor:
        # any grey, the paper colour is put in later from how much light reaches the floor
        disc = pv.Disc(center=(mid[0], mid[1], bounds[2, 0] - 0.02), inner=0, outer=radius * 12, c_res=180, r_res=8)
        floor_actor = pl.add_mesh(disc, color="#c0c0c0")
        parts.append((floor_actor, (LOOK["body"][0], 0.0, 1, 0.0, 1.0)))

    pl.camera_position = cam
    if parallel:
        pl.enable_parallel_projection()
    pl.camera.zoom(zoom)

    def lights(which):
        pl.remove_all_lights()
        for d, k, col in which:
            pl.add_light(pv.Light(position=tuple(mid + d * radius * 20), focal_point=tuple(mid), intensity=k,
                                  color=col, light_type="scene light"))

    def material(ambient, key_pass):
        for a, (dif, spec, power, room, lamp) in parts:
            a.prop.SetAmbient(ambient + room if ambient else 0.0)
            a.prop.SetDiffuse(dif * lamp if key_pass else dif)
            # the soft lights give a weaker gloss, the key light the real highlight
            a.prop.SetSpecular(spec if key_pass else spec * 0.35)
            a.prop.SetSpecularPower(power)

    # soft light from the sides and the room, on the paper so a see through part shows it
    lights(soft_lights)
    material(AMBIENT, False)
    pl.set_background(PAPER)
    soft_img = screenshot(pl)

    # key light alone on black, it adds to the soft light, and the depth of every pixel
    lights([key])
    material(0.0, True)
    pl.set_background("black")
    key_img = screenshot(pl)
    zb = zbuffer(pl)
    m_cam = matrix(pl)
    pts = unproject(zb, m_cam)
    valid = zb < 1.0
    del zb
    cam_pos = np.array(pl.camera.position)
    # the parts alone, for the outline
    if floor_actor is not None:
        floor_actor.visibility = False
    obj = zbuffer(pl) < 1.0
    if cast:
        vis, sky = light_and_shadow(pl, pts, valid, obj, cam_pos, key[0], mid, radius)
    else:
        vis = sky = np.ones(valid.shape, np.float32)
    pl.close()

    full = (soft_img + key_img).mean(-1)
    img = soft_img * (1 - SKY * (1 - sky))[..., None]
    del soft_img, sky
    img += key_img * vis[..., None]
    del key_img, vis
    # the floor is the paper, darkened by the share of light it lost, and far from the parts it
    # runs out into the plain paper so the edge of the floor never shows
    share = np.clip(img.mean(-1) / np.maximum(full, 1e-3), 0, 1)
    ground = valid & ~obj
    far = np.hypot(pts[..., 0] - mid[0], pts[..., 1] - mid[1])
    share = 1 - (1 - share) * np.clip((6 * radius - far) / (4 * radius), 0, 1)
    # and every shadow fades to plain paper before the border of the picture, so a crop on the
    # sheets never cuts one in a straight line
    ex, ey = np.arange(w), np.arange(h)
    ex, ey = np.minimum(ex, w - 1 - ex), np.minimum(ey, h - 1 - ey)
    edge = np.clip(np.minimum(ey[:, None], ex[None, :]) / (0.14 * min(w, h)), 0, 1).astype(np.float32)
    share = 1 - (1 - share) * edge * edge * (3 - 2 * edge)
    del edge
    # a loss below half a percent is only noise, the plain paper stays plain
    share = 1 - np.clip((1 - share) - 0.005, 0, None) / 0.995
    img[ground] = rgb(PAPER) * share[ground, None]
    del full, share, ground, far
    if ink:
        line = outline(obj, pts, cam_pos, ink * SS)
        img[line] = rgb(INK)
    save(img, path, size)
    return pixels(marks, m_cam, size)


def save(img, path, size):
    out = Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).resize(size, Image.LANCZOS)
    out.save(str(path), optimize=True)


def pixels(marks, m, size):
    """where each named point lands in the final picture"""
    px = {}
    for name, xyz in (marks or {}).items():
        q = m @ np.append(np.asarray(xyz, float), 1.0)
        q = q[:3] / q[3]
        px[name] = [round((q[0] + 1) / 2 * size[0], 1), round((1 - q[1]) / 2 * size[1], 1)]
    return px


def surface_normals(pts, cam_pos):
    """normals from the world points of neighbouring pixels, turned toward the camera"""
    n = np.cross(np.gradient(pts, axis=1), np.gradient(pts, axis=0))
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    flip = np.sum(n * (cam_pos - pts), -1) < 0
    n[flip] *= -1
    return n.astype(np.float32)


def drawing(items, path, cam, size=(1200, 900), parallel=False, zoom=1.0, line=1.2, feature_angle=40.0, panels=(),
            marks=None):
    """the parts as a line drawing in ink on the paper, edges where faces meet at more than
    feature_angle and the outline, hidden lines are left out
    """
    w, h = size[0] * SS, size[1] * SS
    pl = pv.Plotter(off_screen=True, window_size=(w, h))
    pl.set_background(PAPER)
    for it in items:
        # the cad faces come as separate patches, merged so only real edges are found
        pd = to_pv(it[0]).clean(tolerance=1e-6)
        # the faces only hide what lies behind them, pushed back a little so the edges win
        a = pl.add_mesh(pd, color=PAPER, lighting=False)
        a.mapper.SetResolveCoincidentTopologyToPolygonOffset()
        a.mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(2, 2)
        edges = pd.extract_feature_edges(feature_angle, boundary_edges=True, non_manifold_edges=False,
                                         manifold_edges=False)
        if edges.n_points:
            pl.add_mesh(edges, color=INK, line_width=line * SS, lighting=False, render_lines_as_tubes=False)
    for corners in panels:
        quad = panel_face(corners)
        pl.add_mesh(quad, color=PAPER, lighting=False)
        pl.add_mesh(quad.extract_feature_edges(boundary_edges=True), color=INK, line_width=line * SS, lighting=False)
    pl.camera_position = cam
    if parallel:
        pl.enable_parallel_projection()
    pl.camera.zoom(zoom)
    img = screenshot(pl)
    obj = zbuffer(pl) < 1.0
    m_cam = matrix(pl)
    pl.close()
    # the silhouette, the feature edges do not find it on round faces
    ring = dilate(obj, line * SS / 2 + 0.5) & ~obj
    img[ring] = rgb(INK)
    save(img, path, size)
    return pixels(marks, m_cam, size)


def lamp_ray(path, lamp, panel, area=None, scale=1.0):
    """a small lamp drawn in ink and one orange ray from it to the panel, on a finished render

    lamp and panel are pixels from marks, the lamp is drawn where the line from the panel toward
    it leaves the area (x0, y0, x1, y1), so the ray is as long as the picture allows
    """
    from PIL import ImageDraw
    img = Image.open(path).convert("RGB")
    k = 4  # drawn larger and scaled down for smooth lines
    big = img.resize((img.width * k, img.height * k), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    x0, y0, x1, y1 = area or (70, 70, img.width - 70, img.height - 70)
    (lx, ly), (px, py) = lamp, panel
    t = math.inf
    for dv, p, lo, hi in ((lx - px, px, x0, x1), (ly - py, py, y0, y1)):
        if dv > 1e-9:
            t = min(t, (hi - p) / dv)
        if dv < -1e-9:
            t = min(t, (lo - p) / dv)
    lx, ly = px + (lx - px) * t, py + (ly - py) * t
    ink, orange = tuple(round(c * 255) for c in rgb(INK)), tuple(round(c * 255) for c in rgb(ORANGE))
    r, w = 16 * scale, 3 * scale
    L = math.hypot(px - lx, py - ly)
    sx, sy = lx + (px - lx) / L * (r + 18 * scale), ly + (py - ly) / L * (r + 18 * scale)
    d.line([(sx * k, sy * k), (px * k, py * k)], fill=orange, width=round(w * 1.3 * k))
    d.ellipse(((px - 6 * scale) * k, (py - 6 * scale) * k, (px + 6 * scale) * k, (py + 6 * scale) * k), fill=orange)
    d.ellipse(((lx - r) * k, (ly - r) * k, (lx + r) * k, (ly + r) * k), outline=ink, width=round(w * k))
    for i in range(8):
        a = i * math.pi / 4
        d.line([((lx + (r + 7 * scale) * math.cos(a)) * k, (ly + (r + 7 * scale) * math.sin(a)) * k),
                ((lx + (r + 16 * scale) * math.cos(a)) * k, (ly + (r + 16 * scale) * math.sin(a)) * k)],
               fill=ink, width=round(w * k))
    big.resize(img.size, Image.LANCZOS).save(str(path), optimize=True)
