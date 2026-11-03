"""the signature engraved into the lid top: the name line, the fhv mark, a thin rule and the class tag

the layout lives in a flat frame in millimetres, u to the right and v up as a person in front of
the tracker reads it. that person looks toward minus y, so on the lid u runs along minus x and v
along minus y, a turn by 180 degrees and no mirror

the letters come from the ttf outlines in assets. where a bowl or an arch meets a stem, Inter and
JetBrains Mono leave a narrow notch of lid between the strokes, and between the strokes of M and N
JetBrains Mono leaves long thin slivers. the printer cannot make lid material narrower than the
island limit, so every sign is closed with half that limit before it is cut: notches and slivers
narrower than the limit are cut away with the letter, counters and the gaps between letters stay
as drawn. checks.py proves this on the lid mesh
"""

import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import manifold3d as m3d
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from . import params as P

ASSETS = Path(__file__).resolve().parent / "assets"
FLAT_TOL = 0.01  # chord error of curves in mm, far below what the nozzle can show
ROUND = m3d.JoinType.Round
ARC_SEGMENTS = 96  # per full circle for every offset, the default of manifold is far too coarse at 0.4 mm


def offset(cs, d):
    return cs.offset(d, ROUND, 2.0, ARC_SEGMENTS)


def topology(cs):
    """number of pieces and the holes of each, what an offset must not change"""
    pieces = cs.decompose()
    return len(pieces), sorted(p.num_contour() - 1 for p in pieces)


def union(parts):
    parts = [p for p in parts if p is not None and not p.is_empty()]
    return m3d.CrossSection.batch_boolean(parts, m3d.OpType.Add) if parts else m3d.CrossSection()


# fonts


class _LoopPen(BasePen):
    """the contours of a glyph as closed point loops, curves cut into short lines"""

    def __init__(self, glyphs, tol):
        super().__init__(glyphs)
        self.tol = tol
        self.loops = []
        self.cur = []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _qCurveToOne(self, c, p):
        p0, c, p1 = (np.asarray(v, float) for v in (self.cur[-1], c, p))
        # a quadratic leaves its chord by at most a quarter of the control point offset
        dev = np.linalg.norm(p0 - 2 * c + p1) / 4
        n = max(int(math.ceil(math.sqrt(dev / self.tol))), 1)
        for i in range(1, n + 1):
            t = i / n
            q = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * c + t * t * p1
            self.cur.append((float(q[0]), float(q[1])))

    def _curveToOne(self, c1, c2, p):
        raise ValueError("a ttf outline has no cubic curves")

    def _closePath(self):
        if len(self.cur) >= 3:
            self.loops.append(np.asarray(self.cur, float))
        self.cur = []

    _endPath = _closePath


class Font:
    """outlines and advance widths of one ttf file"""

    def __init__(self, path):
        self.tt = TTFont(str(path))
        self.upm = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.glyphs = self.tt.getGlyphSet()
        self.hmtx = self.tt["hmtx"]
        self.x_height = self.tt["OS/2"].sxHeight
        self.cap_height = self.tt["OS/2"].sCapHeight

    def advance(self, ch):
        return self.hmtx[self.cmap[ord(ch)]][0]

    def loops(self, ch, k):
        """closed loops of one sign in millimetres for a scale k from font units"""
        pen = _LoopPen(self.glyphs, FLAT_TOL / k)
        self.glyphs[self.cmap[ord(ch)]].draw(pen)
        return [lp * k for lp in pen.loops]


@lru_cache(maxsize=None)
def font(name):
    return Font(ASSETS / name)


# signs


def fill(cs):
    """close a sign with half the island limit, the slivers between strokes go with the letter"""
    r = P.ENGRAVE_ISLAND_MIN / 2
    return offset(offset(cs, r), -r)


@lru_cache(maxsize=None)
def logo_points():
    """the square fhv mark in svg units with y down, the first polygon of the official logo

    the file holds the mark, the word mark FHV and the subtitle Vorarlberg University of Applied
    Sciences. the subtitle strokes would need the logo about 160 mm wide to reach the stroke limit,
    so the lid carries the mark alone, the compact form fhv.at uses itself as favicon and footer logo
    """
    root = ET.parse(ASSETS / P.SIG_LOGO_FILE).getroot()
    poly = next(el for el in root.iter() if el.tag.endswith("polygon"))
    nums = [float(v) for v in re.split(r"[\s,]+", poly.get("points").strip())]
    return np.asarray(list(zip(nums[0::2], nums[1::2])), float)


def logo(height, u0, v0):
    """the mark at a height, lower left corner at u0 v0, svg y turned to point up, no other change"""
    pts = logo_points()
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    k = height / (hi[1] - lo[1])
    q = np.column_stack([(pts[:, 0] - lo[0]) * k + u0, (hi[1] - pts[:, 1]) * k + v0])
    return m3d.CrossSection([q], m3d.FillRule.NonZero)


def logo_width(height):
    pts = logo_points()
    ext = pts.max(axis=0) - pts.min(axis=0)
    return height * ext[0] / ext[1]


def rect(u0, v0, u1, v1):
    return m3d.CrossSection([np.array([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], float)])


def text(line, fnt, size, track=0.0, u0=0.0, v0=0.0, by="x", filled=True):
    """one line of signs on the baseline v0 from u0, size is the x height or with by="cap" the cap height

    returns the signs as (character, section) and the ink extent along u
    """
    k = size / (fnt.x_height if by == "x" else fnt.cap_height)
    u = u0
    signs = []
    for i, ch in enumerate(line):
        if ch != " ":
            cs = m3d.CrossSection([lp + (u, v0) for lp in fnt.loops(ch, k)], m3d.FillRule.NonZero)
            signs.append((ch, fill(cs) if filled else cs))
        u += fnt.advance(ch) * k
        if i < len(line) - 1:
            u += track
    b = union([cs for _, cs in signs]).bounds()
    return signs, (b[0], b[2])


def placed(line, fnt, size, track, v0, by="x", u_mid=None, u_left=None, filled=True):
    """a line moved so its ink is centred on u_mid or starts at u_left"""
    _, (a, b) = text(line, fnt, size, track, by=by, filled=filled)
    du = u_mid - (a + b) / 2 if u_mid is not None else u_left - a
    signs, ext = text(line, fnt, size, track, u0=du, v0=v0, by=by, filled=filled)
    return signs, ext


# layout


def layout(filled=True):
    """the parts of the signature in the flat frame, the block centred on u = 0 with its lowest point on v = 0

    the name line centred, below it a row with the fhv mark, a thin rule and the class tag. the mark
    is four tag cap heights over three tall, so the top of its upper bar lines up with the caps of
    the tag. returns a list of (kind, character, section), the kinds are url, logo, rule and tag
    """
    f_url, f_tag = font(P.SIG_URL_FONT), font(P.SIG_TAG_FONT)
    desc = 0.208 * f_url.upm * P.SIG_X_HEIGHT / f_url.x_height  # the tail of g in Inter, 426 of 2048
    signs, _ = placed(P.SIG_URL, f_url, P.SIG_X_HEIGHT, P.SIG_URL_TRACK, 0.0, u_mid=0.0, filled=filled)
    parts = [("url", ch, cs) for ch, cs in signs]
    # the row of mark, rule and tag
    tag_cap = P.SIG_TAG_CAP
    mark_h = tag_cap * 4 / 3
    v_tag = -desc - P.SIG_ROW_GAP - mark_h
    _, (a, b) = text(P.SIG_TAG, f_tag, tag_cap, P.SIG_TAG_TRACK, by="cap")
    gap = P.SIG_RULE_GAP
    row_w = logo_width(mark_h) + gap + P.SIG_RULE_W + gap + (b - a)
    u = -row_w / 2
    parts.append(("logo", "", logo(mark_h, u, v_tag)))
    u += logo_width(mark_h) + gap
    parts.append(("rule", "", rect(u, v_tag, u + P.SIG_RULE_W, v_tag + mark_h)))
    u += P.SIG_RULE_W + gap
    signs, _ = placed(P.SIG_TAG, f_tag, tag_cap, P.SIG_TAG_TRACK, v_tag, by="cap", u_left=u, filled=filled)
    parts += [("tag", ch, cs) for ch, cs in signs]
    lo = union([cs for _, _, cs in parts]).bounds()[1]
    return [(kind, ch, cs.translate((0.0, -lo))) for kind, ch, cs in parts]


def to_lid(cs):
    """flat frame to the lid top: a turn by 180 degrees, the block centre on SIG_X, its front on SIG_Y"""
    return cs.rotate(180.0).translate((P.SIG_X, P.SIG_Y))


@lru_cache(maxsize=None)
def _profiles():
    parts = layout()
    raw = layout(filled=False)
    return parts, raw


def profile(kind=None, raw=False):
    """the engraved region on the lid top in device x y, one kind of part or all of them"""
    parts = _profiles()[1 if raw else 0]
    return to_lid(union([cs for k, _, cs in parts if kind is None or k == kind]))


def sizes():
    """the numbers for the report"""
    f_url = font(P.SIG_URL_FONT)
    k = P.SIG_X_HEIGHT / f_url.x_height
    b = profile().bounds()
    return {"x_height": P.SIG_X_HEIGHT, "url_cap": f_url.cap_height * k, "tag_cap": P.SIG_TAG_CAP,
            "logo_height": P.SIG_TAG_CAP * 4 / 3, "depth": P.SIG_DEPTH,
            "box": (b[0], b[1], b[2], b[3]), "width": b[2] - b[0], "height": b[3] - b[1],
            "fill": P.ENGRAVE_ISLAND_MIN / 2, "url_font": P.SIG_URL_FONT, "tag_font": P.SIG_TAG_FONT}


def sample():
    """a piece of the name line over a piece of the class tag at the lid sizes, for the fit test

    flat frame, the ink centred on the origin
    """
    f_url, f_tag = font(P.SIG_URL_FONT), font(P.SIG_TAG_FONT)
    row1, _ = placed(P.SIG_SAMPLE[0], f_url, P.SIG_X_HEIGHT, P.SIG_URL_TRACK, P.SIG_TAG_CAP + P.SIG_ROW_GAP,
                     u_mid=0.0)
    row2, _ = placed(P.SIG_SAMPLE[1], f_tag, P.SIG_TAG_CAP, P.SIG_TAG_TRACK, 0.0, by="cap", u_mid=0.0)
    cs = union([cs for _, cs in row1 + row2])
    b = cs.bounds()
    return cs.translate((-(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2))


def sample_cut(cx, cy):
    """the sample cut into a face that lies on the plate at z = 0, read from below, so u runs along minus x"""
    if not P.SIG_ON:
        return None
    cs = sample().mirror((1.0, 0.0)).translate((cx, cy))
    return prism(cs.simplify(0.004), -1.0, P.SIG_DEPTH)


# solids


def prism(cs, z0, z1):
    """a build123d solid from a cross section, one face per piece with its holes"""
    from build123d import Face, Plane, Wire, extrude

    solids = []
    for piece in cs.decompose():
        loops = piece.to_polygons()
        areas = [0.5 * float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(np.roll(p[:, 0], -1), p[:, 1])) for p in loops]
        outer = int(np.argmax(np.abs(areas)))
        wires = [Wire.make_polygon([(float(x), float(y), z0) for x, y in lp], close=True) for lp in loops]
        face = Face(wires[outer], [w for i, w in enumerate(wires) if i != outer])
        solids.append(extrude(face, z1 - z0, dir=Plane.XY.z_dir))
    if not solids:
        return None
    out = solids[0]
    return out.fuse(*solids[1:]) if len(solids) > 1 else out


def cut(tol=0.004):
    """the solid that is taken out of the lid, from the floor of the recess to above the top

    tol drops outline points closer than this to the line of their neighbours, the web model of
    the twin uses a coarser outline so the letters do not blow up the download
    """
    if not P.SIG_ON:
        return None
    return prism(profile().simplify(tol), P.BASE_TOP - P.SIG_DEPTH, P.BASE_TOP + 1.0)
