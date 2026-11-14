"""technical drawings of the tracker in one pdf, in the look of a freecad techdraw page

every view is a hidden line projection of the same solids the exports come from, made with the
opencascade algorithm techdraw uses. every dimension is measured on the model or read from
params.py, so the sheets follow a changed parameter at the next build
first angle projection, A3 landscape, millimetres
"""

import math
import os
import re
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from build123d import Axis, Compound, Plane
from fontTools.ttLib import TTFont
from matplotlib import rc_context
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as FaceMap
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS

from . import base, fasteners, head, kit, neck
from . import params as P
from .helpers import box, cone, cyl

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_FILE = ASSETS / "osifont.ttf"

# the sheet, A3 landscape with the iso 5457 frame, 20 mm filing margin on the left
SHEET_W, SHEET_H = 420.0, 297.0
FRAME = (20.0, 10.0, 410.0, 287.0)
PT = 72.0 / 25.4  # points per millimetre

# iso 128 line group 0.35, thin lines half of it
LW = {"visible": 0.35, "thin": 0.18, "hidden": 0.18, "centre": 0.18, "frame": 0.7, "table": 0.35,
      "fine": 0.13}
DASH = {"hidden": (2.0, 1.0), "centre": (6.0, 1.0, 0.5, 1.0)}

TEXT = 3.0  # cap height of dimension text
ARROW_L, ARROW_W = 2.8, 0.95
SMOOTH_DEG = 30.0  # faces that meet flatter than this are facets of one rounded surface


# font


class _Font:
    def __init__(self):
        self.prop = FontProperties(fname=str(FONT_FILE))
        tt = TTFont(str(FONT_FILE))
        self.upm = tt["head"].unitsPerEm
        self.cap = tt["OS/2"].sCapHeight / self.upm
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]

    def em(self, cap_h):
        """em size in mm for a cap height in mm"""
        return cap_h / self.cap

    def width(self, s, cap_h):
        em = self.em(cap_h)
        w = 0.0
        for ch in s:
            g = self.cmap.get(ord(ch))
            w += (self.hmtx[g][0] if g else self.upm * 0.6) / self.upm * em
        return w


_FONT = None


def font():
    global _FONT
    if _FONT is None:
        _FONT = _Font()
    return _FONT


def num(v):
    """a value the way techdraw prints it, up to two decimals and no trailing zeros"""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# hidden line removal


def _pt(p):
    return np.array([p.X(), p.Y(), p.Z()])


def edge_points(edge, defl):
    """an edge as a polyline, defl is the chord error in model mm"""
    c = BRepAdaptor_Curve(edge)
    u0, u1 = c.FirstParameter(), c.LastParameter()
    if c.GetType() == GeomAbs_CurveType.GeomAbs_Line:
        return np.array([_pt(c.Value(u0)), _pt(c.Value(u1))])
    d = GCPnts_QuasiUniformDeflection(c, defl)
    if d.IsDone() and d.NbPoints() >= 2:
        return np.array([_pt(d.Value(i)) for i in range(1, d.NbPoints() + 1)])
    return np.array([_pt(c.Value(u0 + (u1 - u0) * k / 24)) for k in range(25)])


def _edges_of(compound):
    out = []
    if compound is None or compound.IsNull():
        return out
    ex = TopExp_Explorer(compound, TopAbs_EDGE)
    while ex.More():
        out.append(TopoDS.Edge(ex.Current()))
        ex.Next()
    return out


def face_normal(face, p):
    s = BRepAdaptor_Surface(face)
    if s.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
        d = s.Plane().Axis().Direction()
        n = np.array([d.X(), d.Y(), d.Z()])
    else:
        surf = BRep_Tool.Surface_s(face)
        uv = ShapeAnalysis_Surface(surf).ValueOfUV(gp_Pnt(*p), 1e-6)
        props = GeomLProp_SLProps(surf, uv.X(), uv.Y(), 1, 1e-6)
        if not props.IsNormalDefined():
            return None
        d = props.Normal()
        n = np.array([d.X(), d.Y(), d.Z()])
    return -n if face.Orientation() == TopAbs_REVERSED else n


def soft_edges(topo):
    """edges where two faces meet at a small angle, the facets of a rounded corner drawn as polygon

    techdraw hides smooth edges, these are smooth to the eye but sharp for the kernel, so they
    are found here and dropped in every view where they are not on the outline
    """
    m = EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(topo, TopAbs_EDGE, TopAbs_FACE, m)
    fmap = FaceMap()
    TopExp.MapShapes_s(topo, TopAbs_FACE, fmap)
    planes = {}  # face index: normal of a plane or None, most faces are planes and need no projection
    lim = math.cos(math.radians(SMOOTH_DEG))

    def normal(f, p):
        k = fmap.FindIndex(f)
        if k not in planes:
            face = TopoDS.Face(f)
            flat = BRepAdaptor_Surface(face).GetType() == GeomAbs_SurfaceType.GeomAbs_Plane
            planes[k] = face_normal(face, p) if flat else None
        return planes[k] if planes[k] is not None else face_normal(TopoDS.Face(f), p)

    out = []
    for i in range(1, m.Extent() + 1):
        faces = m.FindFromIndex(i)  # a list of the kernel, turning it into a python list is slow
        if faces.Extent() not in (1, 2):
            continue
        f1, f2 = faces.First(), faces.Last()
        e = TopoDS.Edge(m.FindKey(i))
        c = BRepAdaptor_Curve(e)
        mid = _pt(c.Value((c.FirstParameter() + c.LastParameter()) / 2))
        # a seam or a line left inside one face by a boolean has the same face on both sides
        n1 = normal(f1, mid)
        n2 = n1 if faces.Extent() == 1 or f1.IsSame(f2) else normal(f2, mid)
        if n1 is None or n2 is None:
            continue
        if float(n1 @ n2) > lim:
            out.append((edge_points(e, 0.02), n1, n2))
    return out


_SOFT = {}  # id of a shape: (the shape, its soft edges), the shape is kept so its id stays its own


def soft_edges_of(shapes):
    out = []
    for s in shapes:
        hit = _SOFT.get(id(s))
        if hit is None or hit[0] is not s:
            hit = (s, soft_edges(s.wrapped))
            _SOFT[id(s)] = hit
        out += hit[1]
    return out


class _SegIndex:
    """grid of 2d segments for the test whether a point lies on one of them"""

    def __init__(self, polylines, cell=1.0):
        self.cell = cell
        grid = defaultdict(list)
        for pl in polylines:
            for a, b in zip(pl[:-1], pl[1:]):
                # a little margin, a point on a cell border may land in the cell next to it
                lo, hi = np.minimum(a, b) - 0.01, np.maximum(a, b) + 0.01
                for gx in range(int(math.floor(lo[0] / cell)), int(math.floor(hi[0] / cell)) + 1):
                    for gy in range(int(math.floor(lo[1] / cell)), int(math.floor(hi[1] / cell)) + 1):
                        grid[(gx, gy)].append((a, b))
        self.grid = {k: (np.array([a for a, _ in v]), np.array([b for _, b in v])) for k, v in grid.items()}

    def near(self, p, tol):
        cell = self.grid.get((int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell))))
        if cell is None:
            return False
        a, b = cell
        ab = b - a
        ll = np.maximum((ab * ab).sum(axis=1), 1e-18)
        t = np.clip(((p - a) * ab).sum(axis=1) / ll, 0.0, 1.0)
        d = p - (a + t[:, None] * ab)
        return bool(((d * d).sum(axis=1) < tol * tol).any())


def _along(pts, n):
    """n points spread evenly along a polyline, the ends included"""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], n)
    return np.column_stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])])


def compound_of(shapes):
    shapes = [s for s in shapes if s is not None]
    return shapes[0] if len(shapes) == 1 else Compound(children=shapes)


class Projection:
    """visible and hidden edges of some solids seen along a direction, in view mm

    d points from the model toward the viewer, up is the paper up direction
    """

    def __init__(self, shapes, d, up, defl=0.01, hidden=True):
        self.d = np.asarray(d, float) / np.linalg.norm(d)
        shapes = [s for s in shapes if s is not None]
        comp = compound_of(shapes)
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*self.d))
        ax.SetYDirection(gp_Dir(*np.asarray(up, float)))
        self.x = _pt(ax.XDirection())
        self.y = _pt(ax.YDirection())
        algo = HLRBRep_Algo()
        algo.Add(comp.wrapped)
        algo.Projector(HLRAlgo_Projector(ax))
        algo.Update()
        algo.Hide()
        h = HLRBRep_HLRToShape(algo)
        vis = _edges_of(h.VCompound()) + _edges_of(h.OutLineVCompound())
        hid = _edges_of(h.HCompound()) + _edges_of(h.OutLineHCompound()) if hidden else []
        drop = []
        for pts, n1, n2 in soft_edges_of(shapes):
            s1, s2 = float(n1 @ self.d), float(n2 @ self.d)
            if abs(s1) < 1e-6 or abs(s2) < 1e-6 or s1 * s2 < 0:
                continue  # on the outline, keep it
            drop.append(self.flat(pts))
        index = _SegIndex(drop)
        self.visible = self._clean(vis, defl, index)
        self.hidden = self._clean(hid, defl, index)

    def flat(self, pts):
        pts = np.atleast_2d(pts)
        return np.column_stack([pts @ self.x, pts @ self.y])

    def _clean(self, edges, defl, index):
        out = []
        for e in edges:
            pts = edge_points(e, defl)[:, :2]
            if len(pts) < 2 or np.linalg.norm(pts[-1] - pts[0]) < 1e-6 and len(pts) == 2:
                continue
            if np.max(np.linalg.norm(np.diff(pts, axis=0), axis=1)) < 1e-6:
                continue
            if all(index.near(p, 2e-3) for p in _along(pts, 11)):
                continue
            out.append(pts)
        return out


# the sheet


def _rot(v, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]])


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.array([1.0, 0.0])


def chain_segments(a, b, pattern=DASH["centre"]):
    """a dash dot line from a to b that starts, ends and crosses its middle with a long dash"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    length = float(np.linalg.norm(b - a))
    if length < 1e-9:
        return []
    u = (b - a) / length
    m = (a + b) / 2
    long_, gap, dot = pattern[0], pattern[1], pattern[2]
    step = long_ + 2 * gap + dot
    if length <= long_ + step:
        return [(a, b)]
    k = int((length / 2 - long_ / 2) // step)
    # stretch the dashes a little so the pattern fills the line exactly
    s = (length / 2) / (long_ / 2 + k * step)
    lg, gp, dt = long_ * s, gap * s, dot * s
    out = [(-lg / 2, lg / 2)]
    t = lg / 2
    for _ in range(k):
        out.append((t + gp, t + gp + dt))
        t2 = t + 2 * gp + dt
        out.append((t2, min(t2 + lg, length / 2)))
        t = t2 + lg
    segs = []
    for t0, t1 in out:
        segs.append((m + u * t0, m + u * t1))
        if t0 > 0:
            segs.append((m - u * t1, m - u * t0))
    return segs


class Sheet:
    """one A3 page, everything in paper millimetres from the lower left corner"""

    def __init__(self, title, scale, colour):
        self.title, self.scale, self.colour = title, scale, colour
        self.lines = defaultdict(list)  # style: list of polylines
        self.fills = []  # filled polygons, arrow heads and dots
        self.words = []  # (x, y, string, height, angle, ha, va)
        self.texts = []  # (corners, group, string) for the overlap check
        self.segs = []  # (a, b, group) for the overlap check
        self.group = "sheet"
        self._n = 0
        self.letters = set()  # the screws this sheet shows
        self.table_at = None  # where the screw table goes, it needs the numbers of every sheet

    def new_group(self):
        self._n += 1
        self.group = f"a{self._n}"
        return self.group

    # primitives

    def poly(self, pts, style="thin", group=None):
        pts = np.asarray(pts, float)
        if len(pts) < 2:
            return
        self.lines[style].append(pts)
        g = group or self.group
        for a, b in zip(pts[:-1], pts[1:]):
            self.segs.append((a, b, g))

    def seg(self, a, b, style="thin", group=None):
        self.poly([a, b], style, group)

    def chain(self, a, b, group=None):
        for p, q in chain_segments(a, b):
            self.poly([p, q], "centre", group)

    def circle(self, c, r, style="thin", n=48, group=None):
        t = np.linspace(0, 2 * math.pi, n + 1)
        self.poly(np.column_stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)]), style, group)

    def fill(self, pts):
        self.fills.append(np.asarray(pts, float))

    def dot(self, c, r=0.5):
        t = np.linspace(0, 2 * math.pi, 17)
        self.fill(np.column_stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)]))

    def arrow(self, tip, frm):
        """filled arrow head with its tip at tip, coming from the side of frm"""
        tip = np.asarray(tip, float)
        u = _unit(tip - np.asarray(frm, float))
        n = np.array([-u[1], u[0]])
        base = tip - u * ARROW_L
        self.fill([tip, base + n * ARROW_W / 2, base - n * ARROW_W / 2])

    def text(self, x, y, s, h=TEXT, rot=0.0, ha="center", va="baseline", group=None, check=True):
        f = font()
        self.words.append((x, y, s, h, rot, ha, va))
        if check:
            w = f.width(s, h)
            x0 = {"left": 0.0, "center": -w / 2, "right": -w}[ha]
            y0 = {"baseline": 0.0, "center": -h / 2, "bottom": 0.0, "top": -h}[va]
            corners = [np.array([x0, y0 - 0.2 * h]), np.array([x0 + w, y0 - 0.2 * h]),
                       np.array([x0 + w, y0 + h]), np.array([x0, y0 + h])]
            self.texts.append(([np.array([x, y]) + _rot(c, rot) for c in corners], group or self.group, s))

    def table(self, x0, y0, widths, rows, h=6.0, th=2.5, up=False, aligns=None):
        """a table with its lower left corner at x0 y0, the first row is the header

        up puts the header at the bottom and the rows above it, the way a parts list sits on
        the title block
        """
        g = self.new_group()
        n = len(rows)
        w = sum(widths)
        y1 = y0 + n * h
        self.poly([(x0, y0), (x0 + w, y0), (x0 + w, y1), (x0, y1), (x0, y0)], "table", g)
        for i in range(1, n):
            self.seg((x0, y0 + i * h), (x0 + w, y0 + i * h), "table" if i == (1 if up else n - 1) else "thin", g)
        x = x0
        for wd in widths[:-1]:
            x += wd
            self.seg((x, y0), (x, y1), "thin", g)
        aligns = aligns or ["left"] * len(widths)
        for i, row in enumerate(rows):
            yb = (y0 + i * h if up else y1 - (i + 1) * h) + (h - th) / 2
            x = x0
            for wd, cell, al in zip(widths, row, aligns):
                tx = x + 1.6 if al == "left" else (x + wd / 2 if al == "center" else x + wd - 1.6)
                self.text(tx, yb, str(cell), th, ha=al, group=g)
                x += wd
        self.group = "sheet"
        return x0, y0, x0 + w, y1

    # the frame and the title block

    def frame(self, n, m):
        x0, y0, x1, y1 = FRAME
        self.group = "frame"
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], "frame")
        # zones of 50 mm from the centre lines, numbers along the length, letters along the height
        cx, cy = SHEET_W / 2, SHEET_H / 2
        xs = [x0] + [cx + 50 * k for k in range(-3, 4)] + [x1]
        ys = [y0] + [cy + 50 * k for k in range(-2, 3)] + [y1]
        for x in xs[1:-1]:
            self.seg((x, y1), (x, y1 + 5), "table")
            self.seg((x, y0), (x, y0 - 5), "table")
        for y in ys[1:-1]:
            self.seg((x0, y), (x0 - 5, y), "table")
            self.seg((x1, y), (x1 + 5, y), "table")
        for i in range(len(xs) - 1):
            xm = (xs[i] + xs[i + 1]) / 2
            self.text(xm, y1 + 2.5, str(i + 1), 2.5, va="center", check=False)
            self.text(xm, y0 - 2.5, str(i + 1), 2.5, va="center", check=False)
        for i in range(len(ys) - 1):
            ym = (ys[-1 - i] + ys[-2 - i]) / 2
            self.text(x0 - 2.5, ym, "ABCDEFGH"[i], 2.5, va="center", check=False)
            self.text(x1 + 2.5, ym, "ABCDEFGH"[i], 2.5, va="center", check=False)
        for a, b in (((cx, y1), (cx, y1 + 10)), ((cx, y0), (cx, y0 - 10)), ((x0, cy), (x0 - 10, cy)),
                     ((x1, cy), (x1 + 10, cy))):
            self.seg(a, b, "frame")
        self.title_block(n, m)

    def title_block(self, n, m):
        x1, y0 = FRAME[2], FRAME[1]
        w, h = TB_W, TB_H
        x0, y1 = x1 - w, y0 + h
        self.group = "title"
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], "frame")
        ym = y0 + 12.0
        self.seg((x0, ym), (x1, ym), "table")
        xa = x0 + 46.0
        self.seg((xa, ym), (xa, y1), "table")
        cols = [x0, x0 + 24.0, x0 + 82.0, x0 + 120.0, x1]
        for x in cols[1:-1]:
            self.seg((x, y0), (x, ym), "table")

        def label(x, y, s):
            self.text(x + 1.5, y - 2.6, s, 1.8, ha="left")

        label(x0, y1, "project")
        self.text(x0 + 4, ym + 5.0, "brainSOL", 6.0, ha="left")
        label(xa, y1, "title")
        th = 4.2
        while font().width(self.title, th) > x1 - xa - 6 and th > 2.6:
            th -= 0.2
        self.text(xa + 3, ym + 5.0, self.title, th, ha="left")
        label(cols[0], ym, "scale")
        self.text((cols[0] + cols[1]) / 2, y0 + 2.6, self.scale, 3.5)
        label(cols[1], ym, "material, colour")
        self.text((cols[1] + cols[2]) / 2, y0 + 2.6, self.colour, 2.8)
        label(cols[2], ym, "projection")
        first_angle_symbol(self, ((cols[2] + cols[3]) / 2 + 1.0, y0 + 4.6))
        label(cols[3], ym, "sheet")
        self.text((cols[3] + cols[4]) / 2, y0 + 2.6, f"{n} of {m}", 3.5)
        self.group = "sheet"

    # output

    def render(self):
        """the matplotlib figure of the sheet"""
        fig = Figure(figsize=(SHEET_W / 25.4, SHEET_H / 25.4))
        ax = fig.add_axes((0, 0, 1, 1))
        ax.set_xlim(0, SHEET_W)
        ax.set_ylim(0, SHEET_H)
        ax.set_axis_off()
        for style, pls in self.lines.items():
            if not pls:
                continue
            kw = {"linewidths": LW[style] * PT, "colors": "black", "capstyle": "round", "joinstyle": "round"}
            if style == "hidden":
                kw["linestyles"] = [(0, tuple(v * PT for v in DASH[style]))]
                kw["capstyle"] = "butt"
            ax.add_collection(LineCollection(pls, **kw))
        if self.fills:
            ax.add_collection(PolyCollection(self.fills, facecolors="black", edgecolors="none", linewidths=0))
        f = font()
        for x, y, s, h, rot, ha, va in self.words:
            ax.text(x, y, s, fontproperties=f.prop, fontsize=f.em(h) * PT, rotation=rot, ha=ha, va=va,
                    rotation_mode="anchor", color="black")
        return fig

    def collisions(self):
        """texts that touch a line of another group or another text, the check after a change"""
        from matplotlib.path import Path as MPath
        bad = []
        boxes = []
        for c, g, s in self.texts:
            c = np.array(c)
            boxes.append((MPath(np.vstack([c, c[:1]])), g, s, c.min(axis=0), c.max(axis=0)))
        segs = [(a, b, g) for a, b, g in self.segs if g != "frame"]
        for i, (path, g, s, lo, hi) in enumerate(boxes):
            for a, b, sg in segs:
                if sg == g:
                    continue
                if max(a[0], b[0]) < lo[0] or min(a[0], b[0]) > hi[0]:
                    continue
                if max(a[1], b[1]) < lo[1] or min(a[1], b[1]) > hi[1]:
                    continue
                ts = np.linspace(0, 1, 24)
                if path.contains_points(a[None, :] + (b - a)[None, :] * ts[:, None]).any():
                    bad.append((s, "line of " + sg))
                    break
            for p2, g2, s2, lo2, hi2 in boxes[i + 1:]:
                if g2 == g or hi[0] < lo2[0] or hi2[0] < lo[0] or hi[1] < lo2[1] or hi2[1] < lo[1]:
                    continue
                if path.intersects_path(p2, filled=True):
                    bad.append((s, "text " + s2))
        return bad


TB_W, TB_H = 160.0, 30.0


def first_angle_symbol(sh, c, k=1.0):
    """iso 5456 symbol of first angle projection, the cone points away from the circles"""
    cx, cy = c
    big, small, length = 3.4 * k, 1.7 * k, 6.0 * k
    xt0 = cx - 9.0 * k
    xt1 = xt0 + length
    sh.poly([(xt0, cy - small), (xt1, cy - big), (xt1, cy + big), (xt0, cy + small), (xt0, cy - small)], "table")
    xc = cx + 5.0 * k
    sh.circle((xc, cy), big, "table")
    sh.circle((xc, cy), small, "table")
    sh.seg((xt0 - 1.2, cy), (xc + big + 1.2, cy), "fine")
    sh.seg((xc, cy - big - 1.2), (xc, cy + big + 1.2), "fine")


# views and what is drawn on them


class View:
    """a projection placed on a sheet: the model point ref lands on the paper point at

    hidden takes capsules (p0, p1, r) in model mm, hidden edges inside one are drawn dashed
    fine takes polygons in model mm, visible edges inside one are drawn with the fine line
    """

    def __init__(self, sh, shapes, d, up, scale, at, ref, hidden=(), fine=(), hidden_all=False):
        self.sh, self.s = sh, scale
        self.pr = Projection(shapes, d, up, hidden=bool(hidden) or hidden_all)
        self.d = self.pr.d
        self.ref2 = self.pr.flat(np.asarray(ref, float))[0]
        self.at = np.asarray(at, float)
        from matplotlib.path import Path as MPath
        fine_paths = [MPath(self.p(np.asarray(poly, float))) for poly in fine]
        caps = [(self.p(a), self.p(b), r * scale) for a, b, r in hidden]
        pts_all = []
        for pl in self.pr.visible:
            q = self.paper(pl)
            pts_all.append(q)
            style = "visible"
            if fine_paths and any(fp.contains_points(q).all() for fp in fine_paths):
                style = "fine"
            sh.poly(q, style, "model")
        for pl in self.pr.hidden:
            q = self.paper(pl)
            if hidden_all or any(all(_seg_dist(p, a, b) <= r for p in q) for a, b, r in caps):
                sh.poly(q, "hidden", "model")
        allp = np.vstack(pts_all) if pts_all else np.zeros((1, 2))
        self.box = (*allp.min(axis=0), *allp.max(axis=0))

    @property
    def left(self):
        return self.box[0]

    @property
    def bottom(self):
        return self.box[1]

    @property
    def right(self):
        return self.box[2]

    @property
    def top(self):
        return self.box[3]

    def paper(self, pts2):
        return self.at + self.s * (np.atleast_2d(pts2) - self.ref2)

    def p(self, xyz):
        q = self.paper(self.pr.flat(np.atleast_2d(np.asarray(xyz, float))))
        return q[0] if np.ndim(xyz) == 1 else q

    def along(self, axis):
        """whether a model direction lies in the paper plane"""
        return abs(float(np.dot(_unit3(axis), self.d))) < 1e-6

    def facing(self, axis):
        return abs(abs(float(np.dot(_unit3(axis), self.d))) - 1.0) < 1e-6

    # dimensions

    def dim(self, p1, p2, axis, at, tpos="auto", prefix="", suffix="", value=None):
        """linear dimension between two model points, measured along the paper axis h or v

        at is the paper x (for v) or y (for h) of the dimension line
        """
        sh = self.sh
        g = sh.new_group()
        q1, q2 = self.p(p1), self.p(p2)
        i = 0 if axis == "h" else 1
        j = 1 - i
        if q1[i] > q2[i]:
            q1, q2 = q2, q1
        a, b = q1.copy(), q2.copy()
        a[j] = b[j] = at
        for q, e in ((q1, a), (q2, b)):
            sgn = 1.0 if at > q[j] else -1.0
            if abs(at - q[j]) > 1.2:
                s0, s1 = q.copy(), e.copy()
                s0[j] += sgn * 0.8
                s1[j] += sgn * 1.8
                sh.seg(s0, s1, "thin", g)
        val = abs(q2[i] - q1[i]) / self.s if value is None else value
        dim_line(sh, a, b, prefix + num(val) + suffix, tpos, 0.0 if axis == "h" else 90.0, g)
        sh.group = "sheet"
        return val

    def note(self, target, rel, text, r=0.0, arrow=True, under=None, th=TEXT, at=None):
        """leader from a model point (or the rim of a circle of radius r around it) to a text

        rel places the bend of the leader relative to the point, at places it on the paper
        """
        sh = self.sh
        g = sh.new_group()
        t = self.p(target)
        elbow = np.asarray(at, float) if at is not None else t + np.asarray(rel, float)
        tip = t + _unit(elbow - t) * r * self.s if r else t
        leader(sh, tip, elbow, text, arrow, under, th, g)
        sh.group = "sheet"

    def cmark(self, c3, r, ext=2.0):
        """centre mark of a circle seen along its axis"""
        c = self.p(c3)
        R = r * self.s + ext
        g = self.sh.new_group()
        self.sh.chain(c - (R, 0), c + (R, 0), g)
        self.sh.chain(c - (0, R), c + (0, R), g)
        self.sh.group = "sheet"

    def axis(self, p0, p1, ext=2.0):
        a, b = self.p(p0), self.p(p1)
        u = _unit(b - a)
        g = self.sh.new_group()
        self.sh.chain(a - u * ext, b + u * ext, g)
        self.sh.group = "sheet"

    def balloon(self, target, rel, label, count=None, arrow=False, at=None):
        """balloon with a number or a letter, the leader ends in a dot on the part

        rel places the balloon relative to the point, at places it on the paper
        """
        sh = self.sh
        g = sh.new_group()
        t = self.p(target) if len(target) == 3 else np.asarray(target, float)
        c = np.asarray(at, float) if at is not None else t + np.asarray(rel, float)
        rel = c - t
        R = BALLOON_R
        sh.circle(c, R, "thin", group=g)
        e = c + _unit(t - c) * R
        sh.seg(e, t, "thin", g)
        if arrow:
            sh.arrow(t, c)
        else:
            sh.dot(t)
        sh.text(c[0], c[1] - 1.75, label, 3.5, group=g)
        if count:
            side = 1.0 if rel[0] >= 0 else -1.0
            sh.text(c[0] + side * (R + 1.2), c[1] - 1.25, count, 2.5, ha="left" if side > 0 else "right", group=g)
        sh.group = "sheet"


BALLOON_R = 3.6


def _unit3(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _seg_dist(p, a, b):
    ab = b - a
    ll = float(ab @ ab)
    t = 0.0 if ll < 1e-12 else min(max(float((p - a) @ ab) / ll, 0.0), 1.0)
    return float(np.linalg.norm(p - (a + t * ab)))


def dim_line(sh, a, b, txt, tpos, rot, g):
    """dimension line from a to b with arrows and the value above it, the iso 129 way"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = float(np.linalg.norm(b - a))
    u = _unit(b - a)
    n = np.array([-u[1], u[0]])  # the side the text stands on
    f = font()
    tw = f.width(txt, TEXT)
    inside = L >= 2 * ARROW_L + 1.0
    fits = tw + 1.6 <= L
    if tpos == "auto":
        tpos = "center" if fits else "right"
    lo, hi = (a, b) if inside else (a - u * (ARROW_L + 2.5), b + u * (ARROW_L + 2.5))
    if tpos == "right":
        hi = b + u * (ARROW_L + 2.0 + tw + 1.0) if not inside else b + u * (tw + 2.5)
        tc = hi - u * (tw / 2 + 0.5)
    elif tpos == "left":
        lo = a - u * (ARROW_L + 2.0 + tw + 1.0) if not inside else a - u * (tw + 2.5)
        tc = lo + u * (tw / 2 + 0.5)
    else:
        tc = (a + b) / 2
    sh.seg(lo, hi, "thin", g)
    if inside:
        sh.arrow(a, b)
        sh.arrow(b, a)
    else:
        sh.arrow(a, a - u)
        sh.arrow(b, b + u)
    p = tc + n * 0.9
    sh.text(p[0], p[1], txt, TEXT, rot=rot, group=g)


def leader(sh, tip, elbow, text, arrow=True, under=None, th=TEXT, g=None):
    """leader line with an arrow (or a dot) at tip, a short shoulder and the text above it"""
    tip, elbow = np.asarray(tip, float), np.asarray(elbow, float)
    side = 1.0 if elbow[0] >= tip[0] else -1.0
    f = font()
    w = max(f.width(text, th), f.width(under, th) if under else 0.0) + 2.0
    end = elbow + (side * w, 0.0)
    sh.poly([tip, elbow, end], "thin", g)
    if arrow:
        sh.arrow(tip, elbow)
    else:
        sh.dot(tip)
    x = elbow[0] + side * 1.0
    sh.text(x, elbow[1] + 0.9, text, th, ha="left" if side > 0 else "right", group=g)
    if under:
        sh.text(x, elbow[1] - 0.9 - th, under, th, ha="left" if side > 0 else "right", group=g)


# the bought parts and the screws as simple solids, only drawn


LETTERS = "ABCDEFGHJK"
THREAD_ROOT = 2.46  # minor diameter of an M3 thread, the thin line of the simplified thread


def screw_length(kind):
    m = re.search(r"M3x(\d+)", kind)
    return float(m.group(1)) if m else None


def screw_solid(kind):
    """head face at z = 0, shank toward plus z"""
    length = screw_length(kind)
    if length:
        head = cone("z", P.M3_CSK_D / 2, 1.5, 0.0, P.M3_HEAD_H)
        shank = cyl("z", 1.5, P.M3_HEAD_H - 0.01, length - 0.3)
        return head + shank + cone("z", 1.5, 1.2, length - 0.3, length)
    # the small pan head screw of a servo horn, its shank is only sketched
    head = cyl("z", P.HORN_SCREW_HEAD_D / 2, 0.0, P.HORN_SCREW_HEAD_H)
    return head + cyl("z", 1.0, P.HORN_SCREW_HEAD_H - 0.01, P.HORN_SCREW_HEAD_H + 4.0)


def _perp(d):
    d = _unit3(d)
    a = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    return np.cross(a, d)


class Screws:
    """one row of fasteners.uses with its letter and where every screw of it sits"""

    def __init__(self, letter, kind, where, count, places):
        self.letter, self.kind, self.where, self.count, self.places = letter, kind, where, count, places
        self.length = screw_length(kind) or P.HORN_SCREW_HEAD_H + 4.0

    def short(self):
        return self.kind.replace(" flat head", "")

    def solids(self, out=0.0, only=None):
        """the screws pulled out of their holes by out mm along their axis"""
        res = []
        for i, (h, d) in enumerate(self.places):
            if only is not None and i not in only:
                continue
            o = np.asarray(h, float) - _unit3(d) * out
            res.append(kit.frame_map(screw_solid(self.kind), tuple(o), tuple(_perp(d)), tuple(_unit3(d))))
        return res


def screw_groups():
    """every screw of the build, the rows of fasteners.uses matched to the places in the model"""
    ty, zt = P.TURRET_Y, P.Z_TILT
    xh = P.NECK_W / 2 + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H
    pan_o = kit.pan_horn_frame()[0]
    tilt_o = kit.tilt_horn_frame()[0]
    horn_back = P.HORN_ARM_T + P.HORN_SCREW_HEAD_H
    # the most telling word of each row first, the pivot row also names the neck
    places = {
        "pivot": [((xh - P.CAP_T, ty, zt), (-1, 0, 0))],
        "horn": [((pan_o[0], pan_o[1], pan_o[2] - horn_back), (0, 0, 1)),
                 ((tilt_o[0] - horn_back, ty, zt), (1, 0, 0))],
        "lid column": [((x, y, 0.0), (0, 0, 1)) for x, y in base.COLUMN_XY],
        "ear plate": [((side * head.ear_screw_u(), P.HEAD_BACK_Y + P.BACK_T, zt + v), (0, -1, 0))
                      for side in (-1, 1) for v in head.EAR_SCREWS_V],
        "bezel": [((u, P.HEAD_BACK_Y, zt + v), (0, 1, 0)) for u, v in head.BEZEL_SCREWS],
        "uno": [((x, y, kit.uno_origin()[2]), (0, 0, 1)) for x, y in base.uno_hole_xy()],
        "neck": [((sx, ty + sy, P.BASE_TOP), (0, 0, 1)) for sx, sy in neck.SCREW_XY],
    }
    out = []
    used = set()
    for i, (kind, where, n) in enumerate(fasteners.uses()):
        key = next((k for k in places if k in where and k not in used), None)
        if key is None:
            raise ValueError(f"no place in the drawings for the screws {where}")
        used.add(key)
        if len(places[key]) != n:
            raise ValueError(f"fasteners.py counts {n} screws {where}, the model has {len(places[key])}")
        out.append(Screws(LETTERS[i], kind, where, n, places[key]))
    return out


def horn(frame):
    o, x, z = frame
    return kit.frame_map(kit.horn_local(screw=False), o, x, z)


def pi_board():
    """the pi as a board with its holes and the tall ports, enough to see where it goes"""
    t = P.PI_T
    s = box(0, P.PI_L, 0, P.PI_W, 0, t)
    for X, Y in P.PI_HOLES:
        s -= cyl("z", P.PI_HOLE_D / 2, -0.1, t + 0.1, (X, Y))
    ov = P.PI_PORT_OVERHANG
    s += box(P.PI_L - 21 + ov, P.PI_L + ov, P.PI_ETH_Y - P.PI_ETH_W / 2, P.PI_ETH_Y + P.PI_ETH_W / 2, t, t + P.PI_ETH_H)
    for yc in P.PI_USB_Y:
        s += box(P.PI_L - 17.5 + ov, P.PI_L + ov, yc - P.PI_USB_W / 2, yc + P.PI_USB_W / 2, t, t + P.PI_USB_H)
    s += box(7.0, 58.0, 49.9, 55.0, t, t + P.PI_GPIO_H)
    return kit.frame_map(s, (P.PI_X0, P.PI_Y0, kit.pi_z0()), (0, 1, 0), (0, 0, 1))


def uno_board():
    """the uno as a board with its holes, the usb socket, the power jack and the headers"""
    t = P.UNO_T
    s = box(0, P.UNO_L, 0, P.UNO_W, 0, t)
    for u, w in P.UNO_HOLES:
        s -= cyl("z", P.UNO_HOLE_D / 2, -0.1, t + 0.1, (u, w))
    s += box(-P.UNO_USB_OVERHANG, 10.0, P.UNO_USB_W[0], P.UNO_USB_W[1], t, t + P.UNO_USB_H)
    s += box(-P.UNO_DC_OVERHANG, 12.0, P.UNO_DC_W[0], P.UNO_DC_W[1], t, t + P.UNO_DC_H)
    s += box(18.0, 65.0, 50.2, 52.7, t, t + 8.5)
    s += box(27.0, 64.0, 0.7, 3.2, t, t + 8.5)
    return kit.frame_map(s, kit.uno_origin(), (0, -1, 0), (0, 0, 1))


def moved(shape, m):
    """a shape moved by a 4x4 matrix of assembly.py, a plain shift or the mirror of the cap"""
    m = np.asarray(m, float)
    r, t = m[:3, :3], m[:3, 3]
    if np.allclose(r, np.eye(3)):
        return shape.translate(tuple(t))
    if np.allclose(r, np.diag([-1.0, 1.0, 1.0])):
        return shape.mirror(Plane.YZ).translate(tuple(t))
    raise ValueError("only shifts and the mirror about x are drawn")


def shift(shapes, v):
    return [s.translate(tuple(v)) for s in shapes]


ROLE_COLOUR = {"body": "PLA, light grey", "dark": "PLA, charcoal", "accent": "PLA, copper"}
NAMES = {
    "tray": "tray", "lid": "lid", "foot": "foot", "neck_front": "neck, front half", "neck_back": "neck, back half",
    "head_back": "head back shell", "head_bezel": "bezel", "ear_horn": "ear with the horn",
    "ear_pivot": "ear with the pivot", "cap": "cap",
}


class Model:
    """the printed parts of assembly.py and the bought parts, everything at pan 0 and tilt 0"""

    def __init__(self, parts):
        self.parts = {p.name: p for p in parts}
        self.order = [p.name for p in parts]
        self.item = {name: i + 1 for i, name in enumerate(self.order)}
        self.screws = screw_groups()
        self.by_letter = {s.letter: s for s in self.screws}

    def shape(self, name):
        return self.parts[name].shape

    def placed(self, name):
        p = self.parts[name]
        return [p.shape] + [moved(p.shape, m) for m in p.instances]

    def printed(self):
        out = []
        for n in self.order:
            out += self.placed(n)
        return out

    def screw(self, where_key):
        return next(s for s in self.screws if where_key in s.where)


# helpers for the sheets

ISO = (1.0, 1.0, 1.0)
GAP_COL = 14.0  # balloons and kit names stand this far beside a view


def bbox(shapes):
    b = compound_of(shapes).bounding_box()
    return np.array([b.min.X, b.min.Y, b.min.Z]), np.array([b.max.X, b.max.Y, b.max.Z])


def _hits(shape, point, direction):
    c, d = np.asarray(point, float), _unit3(direction)
    pts = shape.find_intersection_points(Axis(tuple(c), tuple(d)))
    return [float((np.array([q.X, q.Y, q.Z]) - c) @ d) for q, _ in pts]


def across(shape, point, direction):
    """width of a hole, a slot or a post measured on the solid, along a line through its middle"""
    ts = _hits(shape, point, direction)
    pos, neg = [t for t in ts if t > 1e-6], [t for t in ts if t < -1e-6]
    if not pos or not neg:
        raise ValueError(f"nothing to measure across {point}")
    return min(pos) - max(neg)


def reach(shape, point, direction):
    """distance from a point to the next face of the solid along a direction"""
    ts = [t for t in _hits(shape, point, direction) if t > 1e-6]
    if not ts:
        raise ValueError(f"nothing to measure from {point}")
    return min(ts)


def cyl_r(shape, axis, point, tol=0.05):
    """radius of the cylinder face of a solid whose axis runs through a point"""
    a = _unit3(axis)
    p = np.asarray(point, float)
    for f in shape.faces():
        srf = BRepAdaptor_Surface(f.wrapped)
        if srf.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cy = srf.Cylinder()
        d, o = _pt(cy.Axis().Direction()), _pt(cy.Axis().Location())
        v = p - o
        if abs(abs(float(d @ a)) - 1.0) < 1e-6 and np.linalg.norm(v - (v @ a) * a) < tol:
            return cy.Radius()
    raise ValueError(f"no cylinder on the axis through {point}")


def thread_lines(v, screws, out=0.0, move=(0, 0, 0)):
    """the thin root lines of the simplified thread on screws seen from the side"""
    if not screws.kind.startswith("M3"):
        return
    for h, d in screws.places:
        d = _unit3(d)
        if not v.along(d):
            continue
        o = np.asarray(h, float) + np.asarray(move, float) - d * out
        side = _unit3(np.cross(d, v.d))
        a0, a1 = o + d * P.M3_HEAD_H, o + d * (screws.length - 0.3)
        for k in (-1, 1):
            off = side * k * THREAD_ROOT / 2
            v.sh.seg(v.p(a0 + off), v.p(a1 + off), "fine", "model")


def screw_axes(v, screws, out, end, move=(0, 0, 0), ext=3.0):
    """centre line of every screw from its pulled out head to the point where its hole ends

    end is the coordinate along the screw axis, in the device frame, where the line stops
    """
    for h, d in screws.places:
        d = _unit3(d)
        h = np.asarray(h, float) + np.asarray(move, float)
        if v.facing(d):
            continue
        k = int(np.argmax(np.abs(d)))
        reach = (end - h[k]) / d[k]
        v.axis(h - d * (out + ext), h + d * reach, ext=0.0)


def head_point(screws, i, out, move=(0, 0, 0)):
    """a point inside the head of a pulled out screw, where its balloon points"""
    h, d = screws.places[i]
    d = _unit3(d)
    return np.asarray(h, float) + np.asarray(move, float) - d * (out - 0.6)


def sig_region():
    """the signature on the lid top as a polygon, its edges are drawn with the fine line"""
    from . import signature
    if not P.SIG_ON:
        return []
    b = signature.profile().bounds()
    z, g = P.BASE_TOP, 1.5
    return [[(b[0] - g, b[1] - g, z), (b[2] + g, b[1] - g, z), (b[2] + g, b[3] + g, z), (b[0] - g, b[3] + g, z)]]


def view_label(sh, v, text, dy=7.0, beside=False):
    if beside:
        sh.text(v.right + 6, v.bottom + 2, text, 3.0, ha="left", group="sheet")
    else:
        sh.text((v.left + v.right) / 2, v.bottom - dy, text, 3.0, group="sheet")


def side_at(v, target, side, dy=0.0, gap=GAP_COL):
    """a paper point in the column beside a view at the height of a model point"""
    p = v.p(target)
    return (v.right + gap if side == "r" else v.left - gap, p[1] + dy)


def tag(v, target, label, side, dy=0.0, count=None, gap=GAP_COL):
    """balloon in the column beside a view"""
    v.balloon(target, None, label, count, at=side_at(v, target, side, dy, gap))


def tag_screw(v, screws, out, side, dy=0.0, move=(0, 0, 0), count=True, gap=GAP_COL):
    """balloon for a screw row, on the screw that sits furthest out on that side of the view"""
    pts = [head_point(screws, i, out, move) for i in range(len(screws.places))]
    xs = [v.p(q)[0] for q in pts]
    i = int(np.argmax(xs)) if side == "r" else int(np.argmin(xs))
    tag(v, pts[i], screws.letter, side, dy, f"{screws.count}x" if count and screws.count > 1 else None, gap)


def kit_name(v, target, text, side, dy=0.0, gap=GAP_COL - 4):
    """leader with a dot for a bought part, the name says it comes with the kit"""
    v.note(target, None, text, arrow=False, th=2.8, at=side_at(v, target, side, dy, gap))


def hole(v, c3, r, rel, text, letter=None, at=None):
    """hole callout, the arrow touches the rim, the screw letter sits at the end of the text"""
    v.note(c3, rel, text + (f"  {letter}" if letter else ""), r=r, at=at)


def csk(clear=None):
    return f"⌀{num(clear or P.M3_CLEAR)} ⌵⌀{num(P.M3_CSK_D)}"


def tap():
    return f"⌀{num(P.M3_TAP)}"


def cross_lines(v, c3, lo, hi, ext=4.0):
    """centre lines of a symmetric part through the model point c3, across the view"""
    c = v.p(c3)
    g = v.sh.new_group()
    v.sh.chain((v.left - ext, c[1]), (v.right + ext, c[1]), g)
    v.sh.chain((c[0], v.bottom - ext), (c[0], v.top + ext), g)
    v.sh.group = "sheet"


# the sheets


def sheet_assembly(m):
    sh = Sheet("Assembly", "1:2", "see parts list")
    k = 0.5
    shapes = m.printed() + [kit.panel()] + list(kit.modules().values())
    lo, hi = bbox(shapes)
    ref = (lo + hi) / 2
    fine = sig_region()
    front = View(sh, shapes, (0, 1, 0), (0, 0, 1), k, (105, 205), ref)
    top = View(sh, shapes, (0, 0, 1), (0, -1, 0), k, (105, 98), ref, fine=fine)
    left = View(sh, shapes, (1, 0, 0), (0, 0, 1), k, (215, 205), ref)
    iso = View(sh, shapes, ISO, (0, 0, 1), k, (325, 195), ref, fine=fine)
    zt = P.Z_TILT + P.HEAD_H / 2
    front.dim((lo[0], 0, zt), (hi[0], 0, zt), "h", front.top + 9)
    front.dim((P.HEAD_W / 2 - P.R_MID, 0, hi[2]), (base.COLUMN_XY[0][0] + P.FOOT_PAD_D / 2, 0, lo[2]), "v",
              front.left - 10)
    left.dim((0, lo[1], 0), (0, hi[1], 0), "h", left.bottom - 10)
    # balloons, every part once
    it = m.item
    panel_item = len(m.order) + 1
    yf = P.BASE_D / 2
    yb = P.HEAD_BACK_Y
    tag(iso, (-60, yb + P.HEAD_T, P.Z_TILT + P.HEAD_H / 2 - 5), str(it["head_bezel"]), "r", 6)
    tag(iso, (-25, yb + P.PANEL_FRONT_N, P.Z_TILT + 10), str(panel_item), "r", 0)
    tag(iso, (-62, 40, P.BASE_TOP), str(it["lid"]), "r", 0)
    tag(iso, (-40, yf, 22), str(it["tray"]), "r", -4)
    fx, fy = base.COLUMN_XY[2]
    tag(front, (fx, fy + P.FOOT_PAD_D / 2, 1.5), str(it["foot"]), "r", -6, gap=12)
    ty = P.TURRET_Y
    nx = P.NECK_W / 2
    ex = nx + P.EAR_GAP + P.EAR_T
    tag(left, (ex, ty + 14, P.Z_TILT + 9), str(it["ear_pivot"]), "l", 14)
    tag(left, (nx, ty + 9, P.BASE_TOP + 28), str(it["neck_front"]), "l", 2)
    tag(left, (nx, ty - 9, P.BASE_TOP + 20), str(it["neck_back"]), "l", -8)
    tag(left, (P.HEAD_W / 2, yb + 3, P.Z_TILT + 40), str(it["head_back"]), "r", 0, gap=10)
    tag(top, (-ex + 3, ty - 4, P.Z_TILT + 13), str(it["ear_horn"]), "r", 10)
    cx = -(nx + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H) + 0.4
    tag(top, (cx, ty - 3, P.Z_TILT), str(it["cap"]), "r", -6)
    # parts list on the title block, item 1 at the bottom
    rows = [["item", "part", "count", "colour"]]
    for name in m.order:
        part = m.parts[name]
        rows.append([str(m.item[name]), NAMES[name], str(part.count), ROLE_COLOUR[part.role].replace("PLA, ", "")])
    rows.append([str(panel_item), "solar panel", "1", "kit"])
    sh.table(FRAME[2] - TB_W, FRAME[1] + TB_H, [14, 86, 18, 42], rows, h=6.0, th=2.6, up=True,
             aligns=["center", "left", "center", "left"])
    return sh


def screw_table(sh, screws, sheet_of):
    """the one table of every screw, drawn when the sheet numbers are known"""
    x0, y0 = sh.table_at
    rows = [["screw", "type", "count", "joins", "sheet"]]
    for s in screws:
        rows.append([s.letter, s.kind, str(s.count), s.where, ", ".join(str(n) for n in sheet_of.get(s.letter, []))])
    for kind, used, have, _ in fasteners.totals():
        if used:
            rows.append(["", kind, str(used), f"of {have} in the kit", ""])
    sh.table(x0, y0, [13, 33, 13, 87, 14], rows, h=5.6, th=2.5, up=False,
             aligns=["center", "left", "center", "left", "center"])


def sheet_screws_base(m):
    sh = Sheet("Screws in the base", "1:1", "see parts list")
    a = m.screw("lid column")
    sh.letters = {a.letter}
    up_lid, down_foot, out = 60.0, -22.0, 20.0
    move = (0, 0, down_foot)
    lid = shift([m.shape("lid")], (0, 0, up_lid))
    feet = shift(m.placed("foot"), move)
    screws = shift(a.solids(out), move)
    shapes = lid + [m.shape("tray")] + feet + screws
    lo, hi = bbox(shapes)
    ref = (lo + hi) / 2
    front = View(sh, shapes, (0, 1, 0), (0, 0, 1), 1.0, (125, 165), ref)
    col_end = up_lid + P.TRAY_Z0 + 10.0
    screw_axes(front, a, out, col_end, move)
    thread_lines(front, a, out, move)
    iso = View(sh, shapes, (1, 1, -1), (0, 0, 1), 0.5, (332, 192), ref)
    screw_axes(iso, a, out, col_end, move)
    view_label(sh, iso, "scale 1:2")
    it = m.item
    yf = P.BASE_D / 2
    tag(front, (-60, yf, up_lid + P.BASE_TOP - 1), str(it["lid"]), "r", 6)
    tag(front, (-60, yf, 30), str(it["tray"]), "r")
    x, y = base.COLUMN_XY[2]
    tag(front, (x - P.FOOT_PAD_D / 2 + 1, y, down_foot + 1.5), str(it["foot"]), "r", 4)
    tag_screw(front, a, out, "r", -4, move)
    tag_screw(iso, a, out, "r", -4, move, gap=10)
    sh.table_at = (FRAME[2] - TB_W, FRAME[1] + TB_H + 4)
    return sh


def sheet_screws_boards(m):
    sh = Sheet("Screws of the boards", "1:1", "see parts list")
    e = m.screw("uno")
    sh.letters = {e.letter}
    up_lid, uno_drop, pi_lift, out = 110.0, 22.0, 45.0, 16.0
    move = (0, 0, up_lid - uno_drop)
    lid = shift([m.shape("lid")], (0, 0, up_lid))
    uno = shift([uno_board()], move)
    pi = shift([pi_board()], (0, 0, pi_lift))
    screws = shift(e.solids(out), move)
    shapes = lid + uno + screws + pi + [m.shape("tray")]
    lo, hi = bbox(shapes)
    ref = (lo + hi) / 2
    front = View(sh, shapes, (0, 1, 0), (0, 0, 1), 1.0, (125, 160), ref)
    post_end = kit.uno_origin()[2] + P.UNO_T + 9.0 + up_lid
    screw_axes(front, e, out, post_end, move)
    thread_lines(front, e, out, move)
    # the pi drops onto its four pins
    pin_top = P.FLOOR_TOP + P.PI_STANDOFF
    for x, y in base.pi_hole_xy():
        front.axis((x, y, pin_top - 2), (x, y, kit.pi_z0() + pi_lift + P.PI_T + 3), ext=0.0)
    sub = lid + uno + screws
    lo2, hi2 = bbox(sub)
    iso = View(sh, sub, (1, 1, -1), (0, 0, 1), 0.5, (330, 180), (lo2 + hi2) / 2)
    screw_axes(iso, e, out, post_end, move)
    view_label(sh, iso, "scale 1:2")
    it = m.item
    yf = P.BASE_D / 2
    tag(front, (-60, yf, up_lid + P.BASE_TOP - 1), str(it["lid"]), "r", 6)
    tag(front, (-60, yf, 25), str(it["tray"]), "r")
    tag_screw(front, e, out, "l", -6, move)
    ux, uy, uz = kit.uno_origin()
    kit_name(front, (ux + 3, uy - 30, uz + move[2] + P.UNO_T / 2), "UNO, kit", "r", -2)
    kit_name(front, (P.PI_X0 - 30, P.PI_Y0 + 60, kit.pi_z0() + pi_lift + P.PI_T / 2), "Raspberry Pi, kit", "r", 6)
    tag_screw(iso, e, out, "r", -6, move, gap=10)
    return sh


def sheet_screws_neck(m):
    sh = Sheet("Screws in the neck", "1:1", "see parts list")
    b, g = m.screw("neck"), m.screw("horn")
    sh.letters = {b.letter, g.letter}
    front_half, back_half = m.shape("neck_front"), m.shape("neck_back")
    # the open neck, the servos and the front half pulled forward
    sv, fh = 30.0, 72.0
    servos = shift([kit.pan_servo(), kit.tilt_servo()], (0, sv, 0))
    opened = [back_half] + servos + shift([front_half], (0, fh, 0))
    lo, hi = bbox(opened)
    iso = View(sh, opened, (1.25, 1.0, 0.8), (0, 0, 1), 1.0, (305, 185), (lo + hi) / 2)
    # the closed neck from the front with the screws from below and the pan horn
    out_b, horn_drop, out_g = 18.0, 16.0, 16.0
    hmove = (0, 0, -horn_drop)
    pan_horn = shift([horn(kit.pan_horn_frame())], hmove)
    gs = shift(g.solids(out_g, only=[0]), hmove)
    closed = [front_half, back_half] + b.solids(out_b) + pan_horn + gs
    lo2, hi2 = bbox(closed)
    front = View(sh, closed, (0, 1, 0), (0, 0, 1), 1.0, (110, 160), (lo2 + hi2) / 2)
    screw_axes(front, b, out_b, P.BASE_TOP + P.FOOT_FLOOR_T + 8.0)
    thread_lines(front, b, out_b)
    h, _ = g.places[0]
    front.axis((h[0], h[1], h[2] - horn_drop - out_g - 3), (h[0], h[1], kit.pan_servo_frame()[0][2] - 6), ext=0.0)
    it = m.item
    ty = P.TURRET_Y
    tag(front, (P.NECK_W / 2 - 2, ty + P.NECK_D / 2, P.Z_TILT), str(it["neck_front"]), "r")
    tag_screw(front, b, out_b, "l", -4)
    tag(front, head_point(g, 0, out_g, hmove), g.letter, "r", -4)
    kit_name(front, (-9, ty, kit.pan_horn_frame()[0][2] - horn_drop - 0.8), "pan horn, kit", "r", 12)
    tag(iso, (-P.NECK_W / 2 + 1, ty - 8, P.NECK_TOP - 12), str(it["neck_back"]), "l", 8)
    tag(iso, (P.FOOT_W / 2 - 4, ty + fh + 10, P.BASE_TOP + 4), str(it["neck_front"]), "r", -6)
    po = kit.pan_servo_frame()[0]
    kit_name(iso, (po[0] + 3, ty + sv + P.SERVO_W / 2, po[2] - 14), "pan servo, kit", "l", -14)
    to = kit.tilt_servo_frame()[0]
    kit_name(iso, (to[0] - 14, ty + sv + P.SERVO_W / 2, P.Z_TILT + 3), "tilt servo, kit", "r", 10)
    return sh


def sheet_screws_hinge(m):
    sh = Sheet("Screws in the hinge", "1:1", "see parts list")
    f, g = m.screw("pivot"), m.screw("horn")
    sh.letters = {f.letter, g.letter}
    neck_parts = [m.shape("neck_front"), m.shape("neck_back")]
    caps = m.placed("cap")  # the first sits on the left ear, the mirrored one on the right
    sl_ear, sl_horn, sl_cap, out_g = -26.0, -13.0, -54.0, 16.0
    sr_ear, sr_cap, out_f = 26.0, 54.0, 18.0
    items = (neck_parts + shift([m.shape("ear_horn")], (sl_ear, 0, 0))
             + shift([horn(kit.tilt_horn_frame())], (sl_horn, 0, 0))
             + shift(g.solids(out_g, only=[1]), (sl_ear, 0, 0)) + shift([caps[0]], (sl_cap, 0, 0))
             + shift([m.shape("ear_pivot")], (sr_ear, 0, 0)) + shift(f.solids(out_f), (sr_ear, 0, 0))
             + shift([caps[1]], (sr_cap, 0, 0)))
    lo, hi = bbox(items)
    ref = (lo + hi) / 2
    front = View(sh, items, (0, 1, 0), (0, 0, 1), 1.0, (140, 205), ref)
    ty, zt = P.TURRET_Y, P.Z_TILT
    front.axis((lo[0] - 2, ty, zt), (hi[0] + 2, ty, zt), ext=0.0)
    thread_lines(front, f, out_f, (sr_ear, 0, 0))
    View(sh, items, (1, 1, 1), (0, 0, 1), 1.0, (150, 85), ref)
    it = m.item
    xe = P.NECK_W / 2 + P.EAR_GAP + P.EAR_T
    top_y = front.top + 12
    front.balloon((-xe + sl_ear + 2, ty, zt + P.EAR_W / 2 - 2), None, str(it["ear_horn"]),
                  at=(front.p((-xe + sl_ear, ty, zt))[0] - 4, top_y))
    front.balloon((xe + sr_ear - 2, ty, zt + P.EAR_W / 2 - 2), None, str(it["ear_pivot"]),
                  at=(front.p((xe + sr_ear, ty, zt))[0] + 4, top_y))
    xc = P.NECK_W / 2 + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H
    front.balloon((xc + sr_cap - 0.6, ty, zt + 4), None, str(it["cap"]), "2x",
                  at=(front.p((xc + sr_cap, ty, zt))[0] + 2, top_y))
    bot_y = front.p((0, ty, zt))[1] - 22
    hf = head_point(f, 0, out_f, (sr_ear, 0, 0))
    front.balloon(hf + (-3, 0, -1.2), None, f.letter, at=(front.p(hf)[0] + 4, bot_y))
    hg = head_point(g, 1, out_g, (sl_ear, 0, 0))
    front.balloon(hg + (0, 0, -1.2), None, g.letter, at=(front.p(hg)[0] - 2, bot_y))
    th = kit.tilt_horn_frame()[0]
    front.note((th[0] + sl_horn - 1, ty, zt - 2.5), None, "tilt horn, kit", arrow=False, th=2.8,
               at=(front.p((th[0] + sl_horn, ty, zt))[0] + 14, bot_y - 10))
    tag(front, (-P.NECK_W / 2, ty + 10, P.BASE_TOP + 30), str(it["neck_front"]), "l", 0, gap=8)
    return sh


def sheet_screws_head(m):
    sh = Sheet("Screws in the head", "1:1", "see parts list")
    c, d = m.screw("ear plate"), m.screw("bezel")
    sh.letters = {c.letter, d.letter}
    ctx = [m.shape("neck_front"), m.shape("neck_back"), m.shape("ear_horn"), m.shape("ear_pivot")] + m.placed("cap")
    s_shell, out_c, s_mod, s_panel, s_bezel, out_d = 34.0, 14.0, 56.0, 72.0, 92.0, 18.0
    mv = (0, s_shell, 0)
    mods = shift(list(kit.modules().values()), (0, s_mod, 0))
    items = (ctx + shift([m.shape("head_back")], mv) + shift(c.solids(out_c), mv) + shift(d.solids(out_d), mv)
             + mods + shift([kit.panel()], (0, s_panel, 0)) + shift([m.shape("head_bezel")], (0, s_bezel, 0)))
    lo, hi = bbox(items)
    ref = (lo + hi) / 2
    # seen from the side and a little from above, so the screws that sit side by side part
    side = View(sh, items, (1, 0, 0.15), (0, 0, 1), 1.0, (125, 175), ref)
    screw_axes(side, c, out_c, P.HEAD_BACK_Y - P.EAR_SCREW_DEPTH, mv)
    screw_axes(side, d, out_d, P.HEAD_BACK_Y + P.BACK_T + 7.5 + s_bezel, mv)
    behind = [s for s in items]
    iso = View(sh, behind, (1.0, -0.9, 0.7), (0, 0, 1), 0.5, (330, 190), ref)
    view_label(sh, iso, "scale 1:2")
    it = m.item
    hw, hh = P.HEAD_W / 2, P.HEAD_H / 2
    yb, zt = P.HEAD_BACK_Y, P.Z_TILT
    top_y = side.top + 12
    side.balloon((hw, yb + s_shell + 3, zt + hh - 4), None, str(it["head_back"]),
                 at=(side.p((hw, yb + s_shell, zt + hh))[0], top_y))
    side.balloon((hw, yb + s_bezel + 8, zt + hh - 4), None, str(it["head_bezel"]),
                 at=(side.p((hw, yb + s_bezel + 7, zt + hh))[0] + 6, top_y))
    side.note((hw, yb + s_panel + 1.2, zt + 20), None, "solar panel, kit", arrow=False, th=2.8,
              at=(side.right + 8, side.p((hw, yb + s_panel, zt + 20))[1] + 10))
    side.note((-hw + 20, yb + s_mod + P.PCB_BOTTOM_N + 0.8, zt - 25), None, "sensor modules, kit", arrow=False,
              th=2.8, at=(side.right + 8, side.p((hw, yb + s_panel, zt - 30))[1] - 12))
    low = side.bottom - 12
    pc = [head_point(c, i, out_c, mv) for i in range(c.count)]
    ic = int(np.argmin([side.p(q)[1] for q in pc]))
    side.balloon(pc[ic], None, c.letter, f"{c.count}x", at=(side.p(pc[ic])[0], low))
    pd = [head_point(d, i, out_d, mv) for i in range(d.count)]
    i_d = int(np.argmin([side.p(q)[1] for q in pd]))
    side.balloon(pd[i_d], None, d.letter, f"{d.count}x", at=(side.p(pd[i_d])[0] - 12, low))
    tag_screw(iso, d, out_d, "r", 0, mv, gap=10)
    return sh


# part sheets


def part_views(sh, m, name, k, layout, d_main, up_main, hidden=None, fine=None):
    """first angle views of one part, layout maps a view name to its paper point

    main is the principal view, below is the view from above, above the view from below,
    right the view from the left, left the view from the right, far the view from behind
    """
    shapes = [m.shape(name)]
    lo, hi = bbox(shapes)
    ref = (lo + hi) / 2
    dm, um = _unit3(d_main), _unit3(up_main)
    r = np.cross(um, dm)
    dirs = {"main": (dm, um), "below": (um, -dm), "above": (-um, dm), "right": (-r, um), "left": (r, um),
            "far": (-dm, um)}
    views = {}
    for key, at in layout.items():
        dd, uu = dirs[key]
        views[key] = View(sh, shapes, dd, uu, k, at, ref, hidden=(hidden or {}).get(key, ()),
                          fine=(fine or {}).get(key, ()))
    return views


def iso_view(sh, m, name, d, k, at, label=None, fine=(), beside=False):
    shapes = [m.shape(name)]
    lo, hi = bbox(shapes)
    v = View(sh, shapes, d, (0, 0, 1), k, at, (lo + hi) / 2, fine=fine)
    if label:
        view_label(sh, v, label, beside=beside)
    return v


def corner(w2, d2, r):
    """the middle of a rounded corner at plus x and plus y"""
    c = r * (1 - math.sqrt(0.5))
    return w2 - c, d2 - c


def sheet_tray(m):
    sh = Sheet("Tray", "1:1", ROLE_COLOUR[m.parts["tray"].role])
    a = m.screw("lid column")
    z0, ft = P.TRAY_Z0, P.FLOOR_TOP
    vs = part_views(sh, m, "tray", 1.0, {"main": (125, 240), "below": (125, 118), "right": (305, 240)},
                    (0, -1, 0), (0, 0, 1), hidden={"right": [((0, -80, ft), (0, 80, ft), 0.3)]})
    back, plan, side = vs["main"], vs["below"], vs["right"]
    w2 = P.BASE_W / 2
    back.dim((-w2, -w2, P.TRAY_TOP), (w2, -w2, P.TRAY_TOP), "h", back.top + 8)
    back.dim((-w2, -w2, z0), (-w2, -w2, P.TRAY_TOP), "v", back.left - 8)
    tray = m.shape("tray")
    nx = base.power_notch_x()
    wall_mid = -w2 + P.WALL / 2
    nw = across(tray, (nx, wall_mid, z0 + 0.5), (1, 0, 0))
    nh = reach(tray, (nx, wall_mid, z0), (0, 0, 1))
    back.dim((nx - nw / 2, -w2, z0), (nx + nw / 2, -w2, z0), "h", back.bottom - 7, tpos="right")
    back.dim((nx + nw / 2, -w2, z0), (nx + nw / 2, -w2, z0 + nh), "v", back.p((nx, 0, 0))[0] + 12)
    plan.dim((w2, -w2, P.TRAY_TOP), (w2, w2, P.TRAY_TOP), "v", plan.right + 8)
    (cx0, cy0) = base.COLUMN_XY[3]
    (cx1, cy1) = base.COLUMN_XY[0]
    plan.dim((cx0, cy0, ft), (cx1, cy0, ft), "h", plan.bottom - 8)
    plan.dim((cx1, cy0, ft), (cx1, cy1, ft), "v", plan.right + 16)
    ch = across(tray, (cx1, cy1, z0 + P.FLOOR / 2), (1, 0, 0))
    for x, y in base.COLUMN_XY:
        plan.cmark((x, y, ft), ch / 2)
    hole(plan, (cx1, cy1, ft), ch / 2, (14, 18), f"4x ⌀{num(ch)}", a.letter)
    cx, cy = corner(w2, w2, P.R_BIG)
    plan.note((cx, -cy, P.TRAY_TOP), (12, -14), f"R{num(P.R_BIG)}")
    plan.dim((-w2, 30, P.TRAY_TOP), (-w2 + P.WALL, 30, P.TRAY_TOP), "h", plan.top + 8, tpos="left")
    pins = base.pi_hole_xy()
    xs = sorted({x for x, _ in pins})
    ys = sorted({y for _, y in pins})
    plan.dim((xs[0], ys[0], ft), (xs[1], ys[0], ft), "h", plan.bottom - 16)
    plan.dim((xs[0], ys[0], ft), (xs[0], ys[1], ft), "v", plan.left - 8)
    plan.dim((-w2, ys[0], ft), (xs[0], ys[0], ft), "h", plan.bottom - 24, tpos="left")
    plan.dim((xs[0], -w2, ft), (xs[0], ys[0], ft), "v", plan.left - 16, tpos="auto")
    for x, y in pins:
        plan.cmark((x, y, ft), 3.0)
    hole(plan, (xs[1], ys[1], ft), P.PI_PIN_D / 2, (26, 14), f"4x pin ⌀{num(P.PI_PIN_D)}")
    posts = base.coil_posts()
    plan.dim((posts[0][0], posts[0][1], ft), (posts[1][0], posts[1][1], ft), "h", plan.top + 8)
    plan.dim((posts[1][0], posts[1][1], ft), (posts[1][0], w2, ft), "v", plan.right - 30)
    pd = across(tray, (posts[1][0], posts[1][1], ft + 1.0), (1, 0, 0))
    hole(plan, (posts[1][0], posts[1][1], ft), pd / 2, (18, -16), f"2x ⌀{num(pd)}")
    side.dim((-w2, -w2, z0), (-w2, -w2, ft), "v", side.right + 8, tpos="right")
    iso_view(sh, m, "tray", (-1, 1, 1), 0.5, (330, 135), "scale 1:2")
    return sh


def sheet_lid(m):
    sh = Sheet("Lid", "1:2", ROLE_COLOUR[m.parts["lid"].role])
    a, e, g = m.screw("lid column"), m.screw("uno"), m.screw("horn")
    k = 0.5
    vs = part_views(sh, m, "lid", k, {"main": (115, 152), "above": (115, 206), "below": (115, 85)},
                    (0, 1, 0), (0, 0, 1), fine={"below": sig_region()})
    front, under, top = vs["main"], vs["above"], vs["below"]
    w2 = P.BASE_W / 2
    zt, lb = P.BASE_TOP, P.LID_BOTTOM
    # top
    top.dim((-w2, -w2, zt), (w2, -w2, zt), "h", top.bottom - 8)
    top.dim((w2, -w2, zt), (w2, w2, zt), "v", top.left - 8)
    tx, ty = P.TURRET_X, P.TURRET_Y
    hub_r = across(m.shape("lid"), (tx, ty, zt - 0.5), (1, 0, 0)) / 2
    top.cmark((tx, ty, zt), hub_r)
    top.dim((tx, -w2, zt), (tx, ty, zt), "v", top.right + 8, tpos="auto")
    hole(top, (tx, ty, zt), hub_r, None, f"⌀{num(2 * hub_r)}", g.letter,
         at=(top.right + 16, top.p((0, ty, 0))[1] - 10))
    top.note((tx - P.SLOT_R - P.SLOT_W / 2, ty, zt), None, f"slot R{num(P.SLOT_R)} x {num(P.SLOT_W)}",
             at=(top.right + 16, top.p((0, ty, 0))[1] - 22))
    # the side seen from the front
    front.dim((-w2, w2, lb), (-w2, w2, zt), "v", front.left - 8, tpos="left")
    front.dim((w2, w2, zt), (w2, w2, P.TRAY_Z0 + base.SPIGOT_RECESS), "v", front.right + 8)
    # from below, positions from the centre lines
    cross_lines(under, (0, 0, lb), None, None)
    (cx, cy) = base.COLUMN_XY[0]
    (cx2, cy2) = base.COLUMN_XY[3]
    under.dim((cx2, cy, lb), (cx, cy, lb), "h", under.top + 29)
    under.dim((cx2, cy2, lb), (cx2, cy, lb), "v", under.left - 8)
    for x, y in base.COLUMN_XY:
        under.cmark((x, y, P.TRAY_Z0), P.COLUMN_D / 2)
    hole(under, (cx, cy2, P.TRAY_Z0), P.M3_TAP / 2, None, f"4x {tap()}", a.letter,
         at=(under.left - 16, under.p((cx, cy2, 0))[1] + 6))
    hole(under, (cx, cy, P.TRAY_Z0), P.COLUMN_D / 2, None, f"4x ⌀{num(base.SPIGOT_D)} on ⌀{num(P.COLUMN_D)}",
         at=(under.left - 16, under.p((cx, cy, 0))[1] - 6))
    uno = base.uno_hole_xy()
    uz = kit.uno_origin()[2] + P.UNO_T
    for x, y in uno:
        under.cmark((x, y, uz), P.UNO_POST_D / 2)
    order = sorted(range(len(uno)), key=lambda i: abs(uno[i][0]))
    for lvl, i in enumerate(order):
        x, y = uno[i]
        under.dim((0, y, uz), (x, y, uz), "h", under.top + 8 + 7 * lvl, tpos="auto")
    order = sorted(range(len(uno)), key=lambda i: abs(uno[i][1]))
    for lvl, i in enumerate(order):
        x, y = uno[i]
        under.dim((x, 0, uz), (x, y, uz), "v", under.right + 8 + 7 * lvl, tpos="auto")
    far = max(range(len(uno)), key=lambda i: abs(uno[i][1]))
    hole(under, (uno[far][0], uno[far][1], uz), P.M3_TAP / 2, None, f"3x {tap()} on ⌀{num(P.UNO_POST_D)}", e.letter,
         at=(under.right + 34, under.p((0, uno[far][1], 0))[1] - 4))
    iso_view(sh, m, "lid", (1, 1, -1), k, (330, 185))
    return sh


def sheet_neck(m, name):
    front_half = name == "neck_front"
    sh = Sheet("Neck, front half" if front_half else "Neck, back half", "1:1", ROLE_COLOUR[m.parts[name].role])
    b, f = m.screw("neck"), m.screw("pivot")
    vs = part_views(sh, m, name, 1.0, {"main": (95, 150), "above": (95, 245), "right": (175, 150), "far": (255, 150)},
                    (0, 1, 0), (0, 0, 1))
    front, under, side, rear = vs["main"], vs["above"], vs["right"], vs["far"]
    ty, z0 = P.TURRET_Y, P.BASE_TOP
    fw, nw = P.FOOT_W / 2, P.NECK_W / 2
    yf = ty + (P.NECK_D / 2 if front_half else -P.NECK_D / 2)
    front.dim((-fw, yf, z0), (fw, yf, z0), "h", front.bottom - 8)
    front.dim((-nw, yf, P.NECK_TOP - 10), (nw, yf, P.NECK_TOP - 10), "h", front.top + 8)
    front.dim((-fw, yf, z0), (-nw, yf, P.NECK_TOP), "v", front.right + 8)
    front.dim((fw, yf, z0), (fw, yf, z0 + P.FOOT_H), "v", front.left - 8)
    front.dim((fw, yf, z0), (nw, yf, P.Z_TILT), "v", front.left - 16)
    front.axis((-nw, yf, P.Z_TILT), (nw, yf, P.Z_TILT), ext=4.0)
    zb = z0 if front_half else z0 + P.FOOT_FLOOR_T  # the back half starts on the floor of the front half
    front.axis((0, yf, zb - 2), (0, yf, P.NECK_TOP + 4), ext=0.0)
    side.dim((nw, ty - P.NECK_D / 2, z0), (nw, ty + P.NECK_D / 2, z0), "h", side.bottom - 8)
    side.cmark((nw, ty, P.Z_TILT), P.M3_CLEAR / 2)
    hole(side, (nw, ty, P.Z_TILT), P.M3_CLEAR / 2, (22, 26), f"⌀{num(P.M3_CLEAR)}", f.letter)
    xs = [x for x, _ in neck.SCREW_XY]
    sy = ty + neck.SCREW_XY[0][1]
    r_hole = P.M3_CLEAR / 2 if front_half else P.M3_TAP / 2
    for x, _ in neck.SCREW_XY:
        under.cmark((x, sy, z0), r_hole)
    under.cmark((0, ty, z0), P.SERVO_BOSS_R)
    under.dim((xs[0], sy, z0), (0, ty, z0), "h", under.top + 8)
    under.dim((0, ty, z0), (xs[1], sy, z0), "h", under.top + 8)
    under.dim((xs[1], sy, z0), (xs[1], ty, z0), "v", under.left - 8, tpos="auto")
    if front_half:
        hole(under, (xs[0], sy, z0), r_hole, None, "2x " + csk(), b.letter, at=(under.right + 10, under.bottom - 6))
        part = m.shape(name)
        boss = across(part, (0, ty, z0 + P.FOOT_FLOOR_T / 2), (1, 0, 0)) / 2
        hole(under, (0, ty, z0), boss, None, f"⌀{num(2 * boss)}", at=(under.left - 14, under.bottom - 8))
        pin = across(part, (-6, ty + 1.0, P.Z_TILT - 20), (1, 0, 0))
        rear.note((-6, ty, P.Z_TILT - 20), None, f"4x ⌀{num(pin)}", r=pin / 2,
                  at=(rear.right + 12, rear.p((0, 0, P.Z_TILT - 20))[1] - 10))
    else:
        hole(under, (xs[0], sy, z0), r_hole, None, f"2x {tap()}", b.letter, at=(under.right + 10, under.bottom - 6))
        front.note((-21.0, ty, z0 + 5.7), None, f"4x pin ⌀{num(neck.PIN_D)}", r=neck.PIN_D / 2,
                   at=(front.right + 4, front.bottom - 16))
        po = kit.pan_servo_frame()[0]
        front.note((po[0] - 8, ty, po[2] - 8), None,
                   f"2x servo pocket {num(P.SERVO_L + 2 * P.FIT_SLIDE)} x {num(P.SERVO_W + 2 * P.FIT_SLIDE)}",
                   at=(front.right - 4, front.bottom - 28))
    iso_view(sh, m, name, (1, -1, 1) if front_half else (1, 1, 1), 1.0, (345, 205))
    return sh


def sheet_head_back(m):
    sh = Sheet("Head back shell", "1:1", ROLE_COLOUR[m.parts["head_back"].role])
    c, d = m.screw("ear plate"), m.screw("bezel")
    yb, zt = P.HEAD_BACK_Y, P.Z_TILT
    hw, hh = P.HEAD_W / 2, P.HEAD_H / 2
    floor = [((-90, yb + P.BACK_T, zt + hh), (90, yb + P.BACK_T, zt + hh), 0.3)]
    vs = part_views(sh, m, "head_back", 1.0, {"main": (118, 192), "below": (118, 118), "far": (305, 192)},
                    (0, 1, 0), (0, 0, 1), hidden={"below": floor})
    front, top, rear = vs["main"], vs["below"], vs["far"]
    rear.dim((-hw, yb, zt + hh), (hw, yb, zt + hh), "h", rear.top + 8)
    rear.dim((hw, yb, zt - hh), (hw, yb, zt + hh), "v", rear.left - 8)
    bs = head.BEZEL_SCREWS
    for u, v in bs:
        rear.cmark((u, yb, zt + v), P.M3_CSK_D / 2)
    rear.dim((bs[0][0], yb, zt + bs[0][1]), (bs[2][0], yb, zt + bs[0][1]), "h", rear.bottom - 8)
    rear.dim((bs[4][0], yb, zt + bs[4][1]), (bs[6][0], yb, zt + bs[4][1]), "h", rear.bottom - 16)
    rear.dim((bs[0][0], yb, zt + bs[0][1]), (bs[0][0], yb, zt + bs[1][1]), "v", rear.right + 8)
    rear.dim((bs[4][0], yb, zt + bs[4][1]), (bs[4][0], yb, zt + bs[5][1]), "v", rear.right + 15)
    hole(rear, (bs[1][0], yb, zt + bs[1][1]), P.M3_CSK_D / 2, None, "8x " + csk(), d.letter,
         at=(rear.p((bs[1][0], 0, 0))[0] - 6, rear.top + 18))
    cx, cz = corner(hw, hh, P.R_MID)
    rear.note((cx, yb, zt - cz), None, f"R{num(P.R_MID)}", at=(rear.right + 3, rear.bottom - 5))
    rear.dim((head.CABLE_U - head.EXIT_L / 2, yb, zt), (head.CABLE_U + head.EXIT_L / 2, yb, zt), "h",
             rear.p((0, 0, zt))[1] - 10)
    eu = head.ear_screw_u()
    ev = head.EAR_SCREWS_V
    for s in (-1, 1):
        for v in ev:
            front.cmark((s * eu, yb + P.BACK_T, zt + v), P.M3_CSK_D / 2)
    front.dim((-eu, yb, zt + ev[0]), (eu, yb, zt + ev[0]), "h", front.bottom - 8)
    front.dim((eu, yb, zt + ev[0]), (eu, yb, zt + ev[1]), "v", front.right + 8)
    hole(front, (eu, yb + P.BACK_T, zt + ev[1]), P.M3_CSK_D / 2, None, "4x " + csk(), c.letter,
         at=(front.p((eu, 0, 0))[0] - 10, front.top + 10))
    top.dim((-hw + 20, yb, zt + hh), (-hw + 20, yb + P.HEAD_JOINT, zt + hh), "v", top.left - 8)
    top.dim((hw - 20, yb, zt + hh), (hw - 20, yb + P.BACK_T, zt + hh), "v", top.right + 8, tpos="right")
    view_label(sh, rear, "seen from behind", dy=26)
    iso_view(sh, m, "head_back", (1, 1, 1), 0.5, (150, 62), "scale 1:2", beside=True)
    return sh


def sheet_bezel(m):
    sh = Sheet("Bezel", "1:1", ROLE_COLOUR[m.parts["head_bezel"].role])
    d = m.screw("bezel")
    yb, zt = P.HEAD_BACK_Y, P.Z_TILT
    hw, hh = P.HEAD_W / 2, P.HEAD_H / 2
    yf = yb + P.HEAD_T
    vs = part_views(sh, m, "head_bezel", 1.0, {"main": (118, 188), "below": (118, 110), "far": (305, 188)},
                    (0, 1, 0), (0, 0, 1))
    front, top, rear = vs["main"], vs["below"], vs["far"]
    front.dim((-hw, yf, zt + hh), (hw, yf, zt + hh), "h", front.top + 8)
    front.dim((hw, yf, zt - hh), (hw, yf, zt + hh), "v", front.left - 8)
    ww, wh = P.PANEL_W - 2 * P.BEZEL_LIP, P.PANEL_H - 2 * P.BEZEL_LIP
    front.dim((-ww / 2, yf, zt - wh / 2), (ww / 2, yf, zt - wh / 2), "h", front.bottom - 8)
    front.dim((-ww / 2, yf, zt - wh / 2), (-ww / 2, yf, zt + wh / 2), "v", front.right + 8)
    eyes = kit.sensor_layout()
    for name, ((su, sv), _) in eyes.items():
        front.cmark((su, yf, zt + sv), P.LDR_D / 2 if name != "lux" else P.BH_WINDOW_D / 2)
    (su, sv), _ = eyes["D"]
    eye = across(m.shape("head_bezel"), (su, yb + P.PANEL_BACK_N + 0.001, zt + sv), (1, 0, 0))
    hole(front, (su, yf, zt + sv), eye / 2, (24, 14), f"4x ⌀{num(eye)}")
    (lu, lv), _ = eyes["lux"]
    lc = front.p((lu, yf, zt + lv))
    hole(front, (lu, yf, zt + lv), P.BH_WINDOW_D / 2, None, f"⌀{num(P.BH_WINDOW_D)}", at=(lc[0] + 16, lc[1] - 12))
    front.dim((eyes["R"][0][0], yf, zt), (eyes["L"][0][0], yf, zt), "h", front.top + 16)
    front.dim((0, yf, zt + eyes["D"][0][1]), (0, yf, zt + eyes["U"][0][1]), "v", front.right + 15)
    bs = head.BEZEL_SCREWS
    for u, v in bs:
        rear.cmark((u, yb, zt + v), head.boss_r())
    hole(rear, (bs[1][0], yb + P.BACK_T, zt + bs[1][1]), P.M3_TAP / 2, None, f"8x {tap()}", d.letter,
         at=(rear.p((bs[1][0], 0, 0))[0] - 6, rear.top + 10))
    pw, ph = P.PANEL_W + 2 * P.PANEL_FIT, P.PANEL_H + 2 * P.PANEL_FIT
    rear.dim((-pw / 2, yb, zt - ph / 2), (pw / 2, yb, zt - ph / 2), "h", rear.bottom - 8)
    rear.dim((pw / 2, yb, zt - ph / 2), (pw / 2, yb, zt + ph / 2), "v", rear.right + 8)
    top.dim((-hw + 20, yb + P.HEAD_JOINT, zt + hh), (-hw + 20, yf, zt + hh), "v", top.left - 8)
    view_label(sh, rear, "seen from behind", dy=18)
    iso_view(sh, m, "head_bezel", (1, 1, 1), 0.5, (150, 58), "scale 1:2", beside=True)
    return sh


def sheet_ears(m):
    sh = Sheet("Ears", "2:1", ROLE_COLOUR[m.parts["ear_horn"].role])
    c, f, g = m.screw("ear plate"), m.screw("pivot"), m.screw("horn")
    ty, zt = P.TURRET_Y, P.Z_TILT
    for name, side, yrow in (("ear_horn", -1, 205), ("ear_pivot", 1, 82)):
        xi = side * (P.NECK_W / 2 + P.EAR_GAP)
        xo = side * (P.NECK_W / 2 + P.EAR_GAP + P.EAR_T)
        xh = side * (P.NECK_W / 2 + P.EAR_GAP + P.EAR_T + P.EAR_HUB_H)
        # both rows are seen from minus x, the horn ear shows its outside, the pivot ear its inside
        vs = part_views(sh, m, name, 2.0, {"main": (82, yrow), "right": (165, yrow), "far": (245, yrow)},
                        (-1, 0, 0), (0, 0, 1))
        a, end, b = vs["main"], vs["right"], vs["far"]
        outer, inner = (a, b) if side < 0 else (b, a)
        sh.text(a.left, a.top + 22, f"{NAMES[name]}, {m.parts[name].count}x", 3.5, ha="left")
        a.dim((xh, ty - P.EAR_HUB_R, zt - P.EAR_W / 2), (xh, ty + P.HEAD_OFFSET, zt - P.EAR_W / 2), "h",
              a.bottom - 8)
        a.dim((xo, ty + P.HEAD_OFFSET, zt - P.EAR_W / 2), (xo, ty + P.HEAD_OFFSET, zt + P.EAR_W / 2), "v",
              a.left - 8)
        outer.cmark((xh, ty, zt), P.EAR_HUB_R)
        hc = outer.p((xh, ty, zt))
        hole(outer, (xh, ty, zt), P.EAR_HUB_R, None, f"⌀{num(2 * P.EAR_HUB_R)}", at=(hc[0] - 26, outer.top + 10))
        hole(outer, (xh, ty, zt), P.CAP_D / 2, None, f"⌀{num(P.CAP_D)} x {num(P.CAP_T)}",
             at=(hc[0] + 22, outer.top + 10))
        if side < 0:
            hs = across(m.shape(name), (xh - side * (P.CAP_T + 0.5), ty, zt), (0, 1, 0))
            hole(outer, (xh, ty, zt), hs / 2, None, f"⌀{num(hs)}", g.letter, at=(hc[0] + 22, outer.bottom - 6))
        else:
            hole(outer, (xh, ty, zt), P.M3_TAP / 2, None, csk(P.M3_TAP), f.letter, at=(hc[0] + 22, outer.bottom - 6))
        ye = ty + P.HEAD_OFFSET
        eu = side * head.ear_screw_u()
        for v in head.EAR_SCREWS_V:
            end.cmark((eu, ye, zt + v), P.M3_TAP / 2)
        end.dim((xo, ye, zt + head.EAR_SCREWS_V[0]), (xo, ye, zt + head.EAR_SCREWS_V[1]), "v",
                end.right + 8 if end.p((xo, ye, zt))[0] > end.p((xi, ye, zt))[0] else end.left - 8)
        end.dim((xi, ye, zt - P.EAR_W / 2), (xo, ye, zt - P.EAR_W / 2), "h", end.bottom - 8)
        end.dim((xi, ye, zt + P.EAR_W / 2), (xh, ye, zt + P.EAR_W / 2), "h", end.top + 8)
        hole(end, (eu, ye, zt + head.EAR_SCREWS_V[0]), P.M3_TAP / 2, None, f"2x {tap()}", c.letter,
             at=(end.right + 8, end.bottom - 14))
        iso_view(sh, m, name, (side, 1, 1), 2.0, (348, yrow))
    return sh


def sheet_cap_foot(m):
    sh = Sheet("Cap and foot", "5:1", "PLA, copper and charcoal")
    a = m.screw("lid column")
    k = 5.0
    # cap, the left one, its outside faces minus x
    cs = m.placed("cap")[0]
    c0 = np.array(head.cap_places()[0][0])
    lo, hi = bbox([cs])
    ref = (lo + hi) / 2
    face = View(sh, [cs], (-1, 0, 0), (0, 0, 1), k, (85, 218), ref)
    edge = View(sh, [cs], (0, 1, 0), (0, 0, 1), k, (150, 218), ref)
    out = np.array(head.cap_places()[0][1], float)
    r = across(cs, c0 + out * P.CAP_T / 2, (0, 0, 1)) / 2
    face.cmark(c0, r)
    face.dim(c0 + (0, -r, 0), c0 + (0, r, 0), "h", face.bottom - 8, prefix="⌀")
    edge.dim(c0 + (-P.CAP_T, 0, r), c0, "h", edge.top + 8, tpos="right")
    # the rib at 240 degrees of the cap frame, local x runs along plus y and local y along minus z
    rib = c0 + out * P.CAP_T / 2 + (0, r * math.cos(4 * math.pi / 3), -r * math.sin(4 * math.pi / 3))
    face.note(rib, (16, 14), f"3x rib ⌀{num(2 * cyl_r(cs, out, rib))}")
    v = View(sh, [cs], (-1, 1, 1), (0, 0, 1), k, (240, 218), ref)
    sh.text(face.left, face.top + 22, f"cap, {m.parts['cap'].count}x, {ROLE_COLOUR[m.parts['cap'].role]}", 3.5,
            ha="left")
    # foot
    fs = m.shape("foot")
    x, y = base.COLUMN_XY[0]
    lo, hi = bbox([fs])
    ref = (lo + hi) / 2
    front = View(sh, [fs], (0, 1, 0), (0, 0, 1), k, (85, 140), ref,
                 hidden=[((x, y, -1), (x, y, P.FOOT_PAD_H + 1), P.M3_CSK_D / 2 + 0.2)])
    topv = View(sh, [fs], (0, 0, 1), (0, -1, 0), k, (85, 72), ref)
    f2 = P.FOOT_PAD_D / 2
    front.dim((x - f2, y, 0), (x + f2, y, 0), "h", front.top + 8)
    front.dim((x + f2, y, 0), (x + f2, y, P.FOOT_PAD_H), "v", front.left - 8)
    topv.cmark((x, y, P.FOOT_PAD_H), P.M3_CLEAR / 2)
    hole(topv, (x, y, P.FOOT_PAD_H), P.M3_CLEAR / 2, (34, 30), csk() + " from below", a.letter)
    v2 = View(sh, [fs], (1, 1, -1), (0, 0, 1), k, (240, 100), ref)
    sh.text(front.left, front.top + 20, f"foot, {m.parts['foot'].count}x, {ROLE_COLOUR[m.parts['foot'].role]}", 3.5,
            ha="left")
    view_label(sh, v2, "seen from below", dy=8)
    _ = v
    return sh


SHEETS = [
    sheet_assembly,
    sheet_screws_base,
    sheet_screws_boards,
    sheet_screws_neck,
    sheet_screws_hinge,
    sheet_screws_head,
    sheet_tray,
    sheet_lid,
    lambda m: sheet_neck(m, "neck_front"),
    lambda m: sheet_neck(m, "neck_back"),
    sheet_head_back,
    sheet_bezel,
    sheet_ears,
    sheet_cap_foot,
]


# building the pdf, the sheets are made in parallel because the hidden line removal is slow


_MODEL = None


def _init_worker(blobs):
    global _MODEL
    from build123d import Part
    from build123d.persistence import deserialize_shape
    parts = [SimpleNamespace(name=n, shape=Part(deserialize_shape(b)), count=c, role=r, instances=i)
             for n, b, c, r, i in blobs]
    _MODEL = Model(parts)


def _sheet_job(i):
    return i, SHEETS[i - 1](_MODEL)


def make(parts, path, only=None, log=None, workers=None):
    """build every sheet and write the pdf, returns the texts that touch a line or another text"""
    from build123d.persistence import serialize_shape
    m = Model(parts)
    jobs = [i for i in range(1, len(SHEETS) + 1) if only is None or i in only]
    done = {}
    workers = min(len(jobs), max(1, (os.cpu_count() or 2) // 2)) if workers is None else workers
    if workers > 1:
        blobs = [(p.name, serialize_shape(p.shape.wrapped), p.count, p.role, list(p.instances)) for p in parts]
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(blobs,)) as pool:
                for i, sh in pool.map(_sheet_job, jobs):
                    done[i] = sh
                    if log:
                        log(f"sheet {i} {sh.title}")
        except (BrokenProcessPool, OSError) as err:
            if log:
                log(f"no parallel sheets ({err}), one after the other")
            done = {}
    for i in jobs:
        if i not in done:
            done[i] = SHEETS[i - 1](m)
            if log:
                log(f"sheet {i} {done[i].title}")
    sheet_of = {}
    for i in jobs:
        for letter in done[i].letters:
            sheet_of.setdefault(letter, []).append(i)
    findings = {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rc_context({"pdf.fonttype": 42, "pdf.compression": 9, "lines.scale_dashes": False}):
        with PdfPages(path, metadata={"Title": "brainSOL technical drawings", "Creator": "brainSOL hardware build",
                                      "CreationDate": None, "ModDate": None}) as pdf:
            for i in jobs:
                sh = done[i]
                if sh.table_at:
                    screw_table(sh, m.screws, sheet_of)
                sh.frame(i, len(SHEETS))
                findings[f"{i} {sh.title}"] = sh.collisions()
                pdf.savefig(sh.render())
    return findings
