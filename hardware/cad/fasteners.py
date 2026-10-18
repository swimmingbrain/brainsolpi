"""every screw the build uses, counted from the same constants the parts are made from"""

from . import base, head, neck
from . import params as P


def uses():
    return [
        ("M3x8 flat head", "foot through the tray floor into a lid column", len(base.COLUMN_XY)),
        ("M3x8 flat head", "foot floor of the neck into the back half", len(neck.SCREW_XY)),
        ("M3x8 flat head", "back shell into the end of each ear plate", 2 * len(head.EAR_SCREWS_V)),
        ("M3x8 flat head", "back shell into the bezel bosses", len(head.BEZEL_SCREWS)),
        ("M3x8 flat head", "uno onto its posts under the lid", len(P.UNO_USED_HOLES)),
        ("M3x14 flat head", "pivot of the right ear, turns in the neck", 1),
        ("servo horn screw", "pan horn under the lid and tilt horn in the left ear", 2),
    ]


def totals():
    out = {}
    for kind, _, n in uses():
        out[kind] = out.get(kind, 0) + n
    rows = []
    for kind, have in P.KIT_FASTENERS.items():
        used = out.get(kind, 0)
        rows.append((kind, used, have, have - used))
    return rows


def ok():
    return all(spare >= 0 for _, _, _, spare in totals())
