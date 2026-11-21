"""checks, exports and the report of the plant bed lid, cad/bedlid.py, without touching the other parts

    uv run build_bedlid.py                  checks with a 10 degree sweep, exports and reports/bedlid.md
    uv run build_bedlid.py --quick          30 degree sweep and no exports, for trying a parameter
    uv run build_bedlid.py --renders DIR    also the pictures of the bed lid into DIR

the exports are export/3mf/plate_2_body_bedlid.3mf, export/stl/bedlid.stl and export/step/bedlid.step,
all lying as they print, every other file stays as build.py wrote it
the exit code is 1 when a check fails, then nothing is exported
"""

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build123d import Mesher  # noqa: E402

from cad import assembly as A  # noqa: E402
from cad import bedlid as B  # noqa: E402
from cad import checks, estimate, exporting  # noqa: E402
from cad import params as P  # noqa: E402
from cad.mesh import transformed  # noqa: E402

LF = chr(10)
PLATE = "plate_2_body_bedlid.3mf"


def log(msg, t0):
    print(f"[{time.time() - t0:6.1f} s] {msg}", flush=True)


def fmt(v, nd=1):
    return f"{v:.{nd}f}"


def export_3mf(prt, out):
    """the part alone on the plate, lying as it prints, read back to be sure"""
    d = Path(out) / "3mf"
    d.mkdir(parents=True, exist_ok=True)
    path = d / PLATE
    mesher = Mesher()
    mesher.add_shape(exporting.located(prt.shape, prt.print_matrix()), linear_deflection=0.02, angular_deflection=0.1,
                     part_number=prt.name)
    mesher.write(str(path))
    shapes = Mesher().read(str(path))
    boxes = [s.bounding_box() for s in shapes]
    lo = np.min([(b.min.X, b.min.Y, b.min.Z) for b in boxes], axis=0)
    hi = np.max([(b.max.X, b.max.Y, b.max.Z) for b in boxes], axis=0)
    return path, len(shapes), lo, hi


def run_checks(parts, elec, step, t0):
    bed = next(p for p in parts if p.name == "bedlid")
    cparts, celec = B.check_parts(parts), B.check_elec(elec)
    scene = checks.Scene(cparts, celec)
    static = checks.static_checks(scene)
    log("static pairs", t0)
    sweep = checks.sweep(scene, step, step)
    log(f"sweep over {sweep['poses']} poses", t0)
    bed_check = next(p for p in cparts if p.name == "bedlid").mesh()
    zones = B.clearances(scene, bed_check, step, step)
    log("clearance of the head to each zone", t0)
    exit_rep = checks.cable_exit_report([p.mesh() for p in parts if p.group == "neck"], bed_check)
    log("cable exit", t0)
    tray = next(p for p in parts if p.name == "tray")
    tray_man = checks.to_manifold(tray.mesh())
    fit = {"bedlid": checks.to_manifold(bed.mesh()).min_gap(tray_man, 5.0),
           "bedlid_overlap": checks.overlap(checks.to_manifold(bed.mesh()), tray_man)}
    lid_stl = HERE / "export" / "stl" / "lid.stl"
    lid_mesh = B.device_lid_mesh(lid_stl)
    fit["lid"] = checks.to_manifold(lid_mesh).min_gap(tray_man, 5.0)
    fit["lid_overlap"] = checks.overlap(checks.to_manifold(lid_mesh), tray_man)
    same = B.same_as_lid(bed.mesh(), lid_mesh)
    neck_front = next(p for p in parts if p.name == "neck_front")
    slot = B.slot_report(neck_front.mesh(), lid_mesh, bed.mesh())
    log("fit to the tray, the faces kept from the lid and the slot", t0)
    return {"static": static, "sweep": sweep, "zones": zones, "exit": exit_rep, "fit": fit, "same": same,
            "slot": slot}


def failures_of(res, prt_rep, budget):
    out = []
    if not (prt_rep["valid"] and prt_rep["solids"] == 1 and prt_rep["watertight"]):
        out.append("the bed lid is not one closed solid")
    if not prt_rep["fits"]:
        out.append("the bed lid does not fit the bed")
    if prt_rep["free"]["steep_area"] > 1.0:
        out.append(f"{prt_rep['free']['steep_area']:.1f} mm2 of overhang steeper than 45 degrees")
    if prt_rep["free"]["bridge_max"] > P.BRIDGE_MAX:
        out.append(f"a bridge of {prt_rep['free']['bridge_max']:.1f} mm outside the supported faces")
    if prt_rep["support"]["onto_part_area_tables"] > 1.0:
        out.append("a supported face of a table has the part under it")
    bad = [(g, a, b, round(v, 2)) for g, a, b, v in res["static"] if v > checks.CONTACT_TOL]
    if bad:
        out.append(f"static overlap {bad}")
    for k in ("base_neck", "neck_head", "base_head"):
        if res["sweep"][k] > checks.CONTACT_TOL:
            out.append(f"{k} overlap {res['sweep'][k]:.2f} mm3")
    for k, (g, pose) in res["zones"].items():
        if g < 1.0:
            out.append(f"the head comes within {g:.2f} mm of the {k}")
    for r in budget:
        if r["slack"] < P.CABLE_SLACK_MIN:
            out.append(f"{r['cable']} has only {r['slack']:.1f} mm of slack with a {r['length']:.0f} mm cable")
    out += checks.cable_exit_failures(res["exit"])
    if res["fit"]["bedlid_overlap"] > checks.CONTACT_TOL:
        out.append("the bed lid overlaps the tray")
    under, top_rows, _ = res["same"]
    if max(a for _, a, _ in under) > 1.0 or max(x for _, _, x, _, _ in top_rows) > 1.0:
        out.append("the bed lid differs from the lid outside the island and the slot")
    if res["slot"]["uncovered"] > 0.5:
        out.append(f"{res['slot']['uncovered']:.1f} mm2 of the slot lie open beside the foot")
    return out


def budget_table(rows):
    L = ["| cable | length | uno into the island | through the plate | neck or servo | service loop | inside the head | "
         "needed | available | slack | shortest that works | worst pose |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['cable']} | {r['length']:.0f} | {fmt(r['uno'])} | {fmt(r['through'])} | {fmt(r['neck'])} | "
                 f"{fmt(r['loop'])} | {fmt(r['head'])} | {fmt(r['total'])} | {fmt(r['available'])} | "
                 f"{fmt(r['slack'])} | {r['shortest']:.0f} | {r['worst']} |")
    return L


def upright_room(zones):
    """how high a board with a plug standing on it may reach above the seat before the head touches it"""
    g = min(v[0] for k, v in zones.items() if k.startswith("board"))
    return P.BED_BOARD_STACK + g


def slim_lines(mass, layers, sup):
    """thicknesses, sag, where the plastic sits and what coarser layers bring"""
    L = ["## Shell", "",
         f"Tub wall {fmt(P.BED_WALL)} with a bead of {fmt(P.BED_RIM_BEAD[0])} x {fmt(P.BED_RIM_BEAD[1])} inside the rim, "
         f"floor {fmt(P.BED_FLOOR_T)} on the underside of the lid at {fmt(P.LID_BOTTOM)}, chamfers {fmt(P.BED_CHAMFER)}, "
         f"island stem {fmt(P.BED_ISLAND_STEM_R - P.BED_ISLAND_BORE_R)}, posts {fmt(P.BED_STEM_R - P.BED_STEM_BORE_R)}, "
         f"table plate {fmt(P.BED_TABLE_T)}. The floor sags about {fmt(B.floor_sag(), 2)} under 1.5 kg of wet soil, taken "
         "as a square plate simply supported on the walls, printed PLA at 2500 MPa, no credit for the ribs, the island "
         "or the posts. The underside of the lid and the island top stay as they are.", "",
         "| zone | solid cm3 |", "|---|---|"]
    L += [f"| {k} | {fmt(v)} |" for k, v in mass.items()]
    L += [f"| together | {fmt(sum(mass.values()))} |", "",
          "| layer | grams | hours, flow of estimate.py | hours, same speed with thicker lines | sparse tree supports on top |",
          "|---|---|---|---|---|"]
    s = sup["sparse"]
    for e in layers:
        k = e["layer"] / 0.2
        L.append(f"| {e['layer']:.2f} mm | {fmt(e['grams'], 0)} | {e['minutes'] / 60:.1f} | {e['minutes_speed'] / 60:.1f} | "
                 f"{fmt(s['grams'], 0)} g, {s['minutes'] / 60:.1f} to {s['minutes'] / k / 60:.1f} h |")
    L += ["", "The model takes a fixed flow, so it sees almost no gain from coarser layers. A printer that runs at its "
          "speed limit lays thicker lines in the same time, the second column, the truth lies between them.", ""]
    return L


def write_report(path, prt_rep, est, sup, res, room, soil, budget, budget_kit, budget_now, failures, plate, slim=()):
    sw, zones, ex, fit, sl = res["sweep"], res["zones"], res["exit"], res["fit"], res["slot"]
    L = ["# Plant bed lid", "",
         "Written by `uv run build_bedlid.py`. The bed lid of `cad/bedlid.py` takes the place of the lid, the tray,",
         "the neck and the head stay as printed. Do not edit by hand.", "", "## Result", ""]
    L += ([f"- {f}" for f in failures] if failures else ["All checks passed."])
    L += ["", f"Print file: `export/3mf/{PLATE}`, one object lying rim down as it prints, "
          f"{' x '.join(fmt(v) for v in plate)} mm.", ""]
    L += ["## The part in numbers", "", "| value | mm |", "|---|---|"]
    L.append(f"| island top and rim above the table | {fmt(B.top())} |")
    L.append(f"| island top above the lid top | {fmt(B.LIFT)} |")
    L.append(f"| tub floor, top and underside, the underside is the lid | {fmt(B.floor_top())} and {fmt(P.LID_BOTTOM)} |")
    L.append(f"| soil surface, {fmt(P.BED_SOIL_BELOW_RIM)} under the rim | {fmt(B.soil_z())} |")
    L.append(f"| soil depth | {fmt(soil['depth'])} |")
    zp1, zp0 = B.table_z()
    L.append(f"| board seat on the spine, table plate top and underside | {fmt(B.seat_z())}, {fmt(zp1)}, {fmt(zp0)} |")
    L.append(f"| board zone, corner stops only, gaps between them | {fmt(P.BED_BOARD[0])} x {fmt(P.BED_BOARD[1])}, "
             f"{fmt(P.BED_BOARD[0] + 2 * P.BED_STOP[1] - 2 * P.BED_STOP[0])} and "
             f"{fmt(P.BED_BOARD[1] + 2 * P.BED_STOP[1] - 2 * P.BED_STOP[0])} |")
    L.append(f"| opening and bore down each post, collar | {fmt(2 * P.BED_STEM_BORE_R)} round, {fmt(P.BED_COLLAR[1])} high |")
    L.append(f"| cable way down the island | {fmt(2 * P.BED_ISLAND_BORE_R)} round |")
    L += ["", f"Soil {soil['soil']:.2f} l up to the soil surface, {soil['rim']:.2f} l up to the rim. "
          f"Printed plastic is not watertight, the tub needs a liner or a coat of sealant.", ""]
    L += list(slim)
    L += ["## Room under the floor", "",
          f"The uno plugs end at {fmt(room['plug_top'])}, the wires need {fmt(room['bend'])} above them to bend, so the room has "
          f"to reach {fmt(room['need'])}. The floor underside is at {fmt(room['floor_under'])}, right there, the same as the "
          f"lid, so the margin is the bend room itself. The pi with its usb jacks ends at {fmt(room['pi_top'])}, the uno keep "
          f"out with its plugs at {fmt(room['uno_top'])}, the tray floor is at {fmt(room['tray_floor'])}.", ""]
    L += ["## Cable slot in the island top", "", "| | lid | bed lid |", "|---|---|---|"]
    L.append(f"| width, radii | {fmt(sl['old_width'])}, {fmt(sl['old_r'][0])} to {fmt(sl['old_r'][1])} | "
             f"{fmt(sl['new_width'])}, {fmt(sl['new_r'][0])} to {fmt(sl['new_r'][1])} |")
    for r in sorted(sl["old_reach"]):
        L.append(f"| reach round the axis at r {fmt(r)} | {fmt(sl['old_reach'][r], 0)} | {fmt(sl['new_reach'][r], 0)} |")
    L.append(f"| open area | {fmt(sl['old_area'], 0)} mm2 | {fmt(sl['new_area'], 0)} mm2 |")
    L.append(f"| free drop under the slot to the uno plugs | {fmt(sl['free_depth_old'])} | {fmt(sl['free_depth'])}, "
             f"{fmt(sl['free_r'])} round the axis |")
    bl, bb = sl["bearing"]["lid"], sl["bearing"]["bed"]
    L.append(f"| foot on the top, smallest over the pan range | {fmt(bl[0], 0)} mm2 at pan {bl[1]:.0f} | "
             f"{fmt(bb[0], 0)} mm2 at pan {bb[1]:.0f} |")
    L.append(f"| foot on the top, mean | {fmt(bl[2], 0)} mm2 | {fmt(bb[2], 0)} mm2 |")
    L += ["", f"Inside, the hub hole keeps a wall of {fmt(sl['wall_hub'])} and the horn arm pocket {fmt(sl['wall_arm'])}. "
          f"Outside, the face of the foot reaches only {fmt(sl['foot_reach'])} from the axis on its narrow sides, so the slot "
          f"ends at {fmt(P.BED_SLOT_R[1])} and the foot covers it at every pan angle, {fmt(sl['uncovered'], 2)} mm2 lie outside "
          f"the foot at worst. Only the top chamfer of the slot reaches past the face the foot stands on, "
          f"{fmt(sl['under_chamfer'], 1)} mm2 at worst, under the edge chamfer of the foot, nothing of it shows from above. "
          f"The seven cables lie {fmt(sl['bundle'])} long in the 5 mm exit of the foot, half of that plus 2 mm "
          f"beyond the end of the pan range needs {fmt(sl['need'], 0)} degrees at r {fmt(P.SLOT_R)}. Edges "
          f"{fmt(P.BED_SLOT_CHAMFER[0])} at 45 degrees on top and {fmt(P.BED_SLOT_CHAMFER[1])} under the rim.", ""]
    L += ["## Sensor tables", "",
          f"The cable leaves the board on any side through the gaps between the corner stops, runs over the table to "
          f"the opening beside the board and down the {fmt(2 * P.BED_STEM_BORE_R)} bore of the post and through the floor. "
          f"The bore passes a 5 pin row of 12.7 x 2.5 turned any way, two 4 pin plugs side by side or single housings. "
          f"A plug sticking out sideways has {fmt(P.BED_PLUG_OUT[0])} on the side and the end toward the middle of the "
          f"tub, on the back tables {fmt(P.BED_PLUG_OUT[1])} on the side toward the island. The board rests on a spine "
          f"{fmt(P.BED_SPINE[0])} x {fmt(P.BED_SPINE[1])}, pins pointing down up to {fmt(P.BED_RELIEF - 0.2)} fit beside it. "
          f"A board with a plug standing upright may reach {fmt(upright_room(zones))} above the seat, "
          f"{fmt(upright_room(zones) - 1.6)} above a 1.6 board, before the head touches it in the worst pose.", "",
          "From a board to the UNO: the plug sits on the header of the board, its cable runs over the table through a "
          "gap between the corner stops, over the collar into the opening beside the board and down the hollow post "
          "through the tub floor. Under the floor it runs through the room of the base to the UNO, which hangs under the "
          "floor next to the island, and plugs onto the pins the team picks, the head already uses A0 to A3, SDA and "
          "SCL, D9 and D10. From the front corners that is about 210 mm, a 300 mm cable reaches.", ""]
    L += ["## Print", "", "| value | measured | limit |", "|---|---|---|"]
    size = " x ".join(fmt(s) for s in prt_rep["size"])
    L.append(f"| size on the bed | {size} mm | {' x '.join(fmt(b, 0) for b in P.BED)} |")
    L.append(f"| one closed solid, watertight | {'yes' if prt_rep['valid'] and prt_rep['solids'] == 1 else 'no'}, "
             f"{'yes' if prt_rep['watertight'] else 'no'} | yes |")
    L.append(f"| steep overhang without support | {fmt(prt_rep['free']['steep_area'])} mm2 | 1.0 |")
    L.append(f"| widest bridge without support | {fmt(prt_rep['free']['bridge_max'])} mm | {fmt(P.BRIDGE_MAX)} |")
    L.append(f"| thin wall share | {fmt(100 * prt_rep['share_thin'])} % | |")
    s = prt_rep["support"]
    for k, (zz, area) in prt_rep["supported"].items():
        L.append(f"| on support: {k}, from {fmt(zz)} above the plate | {fmt(area, 0)} mm2 | |")
    L.append(f"| supported area straight above a table, not above the plate | {fmt(s['onto_part_area_floor'], 0)} mm2 of "
             f"the floor, {fmt(s['onto_part_area_tables'], 0)} mm2 of the tables | |")
    L.append(f"| open volume under the supported faces | {fmt(s['volume'] / 1000, 0)} cm3, "
             f"{fmt(s['volume_floor'] / 1000, 0)} under the floor and {fmt(s['volume_tables'] / 1000, 1)} under the tables | |")
    c = prt_rep["contact"]
    L.append(f"| on the plate: rim ring, {fmt(c['rim_width'])} wide, and island top | {fmt(c['rim'], 0)} and "
             f"{fmt(c['island'], 0)} mm2 | |")
    L.append(f"| filament and time without supports, {est['layer']} mm, {est['infill']} % {est['pattern']} | "
             f"{fmt(est['grams'], 0)} g, {est['minutes'] / 60:.1f} h | |")
    for k, v in sup.items():
        L.append(f"| with {k} tree supports, about {100 * v['share']:.0f} % of that volume | "
                 f"{fmt(est['grams'] + v['grams'], 0)} g, {(est['minutes'] + v['minutes']) / 60:.1f} h | estimate |")
    L += ["", "Prints rim down as the 3mf lies, the rim ring and the island top on the plate. Supports: tree, on build "
          "plate only. They are needed under the tub floor and under the four tables and nowhere else, the island, its "
          "pockets and every bore stay free. Every supported face of the tables sees the plate straight below it. The "
          f"floor sees it too except {fmt(s['onto_part_area_floor'], 0)} mm2 straight above the tables, there the branches "
          f"lean in from beside the table, at most {fmt(s['lean'])} mm over {fmt(B.table_z()[1] - B.floor_top())} mm of "
          f"height, about {math.degrees(math.atan2(s['lean'], B.table_z()[1] - B.floor_top())):.0f} degrees. Normal "
          "supports that only grow "
          "straight up would leave that part of the floor without support. An outer brim of 5 mm is advised: the part "
          f"stands {fmt(prt_rep['size'][2])} mm tall on a {fmt(c['rim_width'])} mm ring and the island top. The grams and "
          "hours of the supports are estimates from the open volume, the slicer has the last word."]
    L += ["", "## Interference", "",
          f"Pan {sw['pans'][0]:.0f} to {sw['pans'][1]:.0f} and tilt {sw['tilts'][0]:.0f} to {sw['tilts'][1]:.0f} in steps of "
          f"{sw['pans'][2]:.0f}, {sw['poses']} poses.", "",
          "| pair | largest overlap mm3 | smallest gap mm |", "|---|---|---|"]
    L.append(f"| base and neck | {sw['base_neck']:.3f} | the foot rides on the island, contact |")
    L.append(f"| neck and head | {sw['neck_head']:.3f} | {sw['gap_neck_head']:.2f} at tilt {sw['gap_neck_head_pose']:.0f} |")
    gp = sw["gap_head_base_pose"]
    L.append(f"| base and head | {sw['base_head']:.3f} | {sw['gap_head_base']:.2f} at pan {gp[0]:.0f}, tilt {gp[1]:.0f} |")
    L += ["", "| head to | smallest gap mm | pose |", "|---|---|---|"]
    for k, (g, pose) in sorted(zones.items(), key=lambda kv: kv[1][0]):
        L.append(f"| {k} | {g:.2f} | pan {pose[0]:.0f}, tilt {pose[1]:.0f} |")
    bad = [(g, a, b, round(v, 2)) for g, a, b, v in res["static"] if v > checks.CONTACT_TOL]
    L += ["", f"Static pairs inside each group: {'no overlap above ' + str(checks.CONTACT_TOL) + ' mm3' if not bad else bad}. "
          f"On every table a board keep out of {fmt(P.BED_BOARD[0] - 2 * P.FIT_SLIDE)} x "
          f"{fmt(P.BED_BOARD[1] - 2 * P.FIT_SLIDE)} x {fmt(P.BED_BOARD_STACK)} mm and two plug keep outs at the same height.", ""]
    L += ["## Fit to the tray", "",
          f"Smallest gap to the tray {fit['bedlid']:.2f} mm, overlap {fit['bedlid_overlap']:.3f} mm3, the printed lid from its "
          f"stl: {fit['lid']:.2f} mm and {fit['lid_overlap']:.3f} mm3. The columns stand on the tray floor, so both touch it.", ""]
    under, top_rows, zone_area = res["same"]
    L += ["Slices of the bed lid against the printed lid (its stl), xor area in mm2. Under the plate, outside and inside "
          f"a circle of {fmt(P.BED_ISLAND_BORE_R + 0.5)} round the pan axis where the pad of the lid was:", "",
          "| z | outside | inside |", "|---|---|---|"]
    L += [f"| {fmt(z)} | {fmt(a, 2)} | {fmt(b, 2)} |" for z, a, b in under]
    L += ["", f"The neck interface, the lid round the axis against the island top {fmt(B.LIFT)} higher, under the plate "
          f"inside the bore, in the plate inside a circle of {fmt(P.BED_ISLAND_R - 1.5)}. The only allowed difference is the "
          f"zone of the old and the new slot with their rims, {fmt(zone_area, 0)} mm2:", "",
          "| z lid | z bed lid | xor outside the slot zone | xor inside it | area of the lid |", "|---|---|---|---|---|"]
    L += [f"| {fmt(z, 2)} | {fmt(z2, 2)} | {fmt(x, 2)} | {fmt(xi, 1)} | {fmt(a, 0)} |" for z, z2, x, xi, a in top_rows]
    L += ["", "## Cable budget", "",
          "Lengths in mm between the backs of the plug housings as in reports/checks.md. The way through the plate under "
          "the foot is counted for every cable here, the build counts it only for the servo leads.", "",
          f"With {P.BED_PHOTO_CABLE:.0f} mm 3 pin cables for the photoresistors:", ""]
    L += budget_table(budget)
    L += ["", "With the 200 mm 3 pin cables of the kit:", ""]
    L += budget_table(budget_kit[:4])
    L += ["", "The lid as printed, counted the same way:", ""]
    L += budget_table(budget_now[:4])
    L += ["", "## Cable exit", "",
          f"Way in at the worst pan angle {fmt(ex['way_min'])} mm2, seven cables fill {fmt(100 * ex['fill'], 0)} %, the "
          f"{ex['plug_name']} plug and six cables fill {fmt(100 * ex['thread_fill'], 0)} % of the exit, the plug "
          f"{'fits' if ex['plug_fits'] else 'does not fit'}, limit {100 * P.CABLE_FILL_MAX:.0f} %. Measured over the C slot "
          "of the island for every pan angle.", ""]
    path.write_text(LF.join(L) + LF, encoding="utf-8", newline=LF)


# pictures


def scene_items(parts, elec, pan, tilt, cut=None, skip=(), boards="thin"):
    from cad.render import FILAMENT
    from cad.views import kit_color
    items = []
    for p in parts:
        m = B.pose_matrix(p.group, pan, tilt)
        for pm in p.placed_meshes():
            items.append((transformed(pm, m), FILAMENT[p.role], 1.0, p.role))
    for g, d in elec.items():
        m = B.pose_matrix(g, pan, tilt)
        for k, mesh in d.items():
            if k == "panel" or k in skip:
                continue
            if k.startswith(("board_", "plug_")):
                if boards is None or (boards == "thin" and k.startswith("plug_")):
                    continue
                if boards == "thin":
                    mesh = mesh.copy()
                    z0 = mesh.vertices[:, 2].min()
                    mesh.vertices[:, 2] = np.minimum(mesh.vertices[:, 2], z0 + 1.6)
                colour = "#3e6b4f" if k.startswith("board_") else "#8a5a3c"
                items.append((transformed(mesh, m), colour, 1.0 if boards == "thin" else 0.45, "kit"))
                continue
            items.append((transformed(mesh, m), kit_color(k), 1.0, "kit"))
    if cut is not None:
        items = [(mm,) + tuple(it[1:]) for it in items for mm in [cut_mesh(it[0], *cut)] if mm is not None]
    return items


def cut_mesh(mesh, origin, normal):
    """the part of a mesh on the side of the plane the normal points to, closed on the cut"""
    import trimesh
    n = np.asarray(normal, float)
    keep = (mesh.vertices - np.asarray(origin, float)) @ n >= 0
    if keep.all():
        return mesh
    if not keep.any():
        return None
    try:
        man = checks.to_manifold(mesh).trim_by_plane(tuple(n), float(np.dot(n, origin)))
    except ValueError:
        faces = mesh.faces[keep[mesh.faces].all(axis=1)]
        return trimesh.Trimesh(mesh.vertices, faces, process=True) if len(faces) else None
    out = man.to_mesh()
    if not len(out.tri_verts):
        return None
    return trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=True)


def panel(pan, tilt):
    return [tuple(np.asarray(c) + (0, 0, B.LIFT)) for c in A.panel_corners(pan, tilt)]


def closest_shots(zones):
    """the poses of the smallest gap to a board and to the rim, each as a section seen square on"""
    from cad.render import camera
    out = []
    board = min((kv for kv in zones.items() if kv[0].startswith("board")), key=lambda kv: kv[1][0])
    name, (g, (pan, tilt)) = board
    sx, sy = B.CORNERS[name.split(" ", 1)[1].replace(" ", "_")]
    cx, cy = B.table_layout(sx, sy)["board"]
    a = math.radians(pan)
    u = np.array([math.cos(a), -math.sin(a), 0.0])
    n = np.array([math.sin(a), math.cos(a), 0.0])
    az = math.degrees(math.atan2(-u[0], -u[1]))
    t = np.array([P.TURRET_X, P.TURRET_Y, 0.0])
    s = min(float(np.dot(np.array([cx, cy, 0.0]) - t, u)), P.HEAD_W / 2 - 8.0)
    c = t + u * s + n * float(np.dot(np.array([cx, cy, 0.0]) - t, n))
    out.append(("closest_board", pan, tilt, camera((c[0], c[1], B.seat_z() + 6.0), az, 0, 500), 4.0,
                (tuple(t + u * s), tuple(u))))
    g, (pan, tilt) = zones["rim and wall"]
    a = math.radians(pan)
    n = np.array([math.sin(a), math.cos(a), 0.0])
    o = np.array([P.TURRET_X, P.TURRET_Y, 0.0]) + n * (P.HEAD_OFFSET + P.HEAD_T / 2)
    az = math.degrees(math.atan2(-n[0], -n[1]))
    out.append(("closest_rim", pan, tilt, camera((o[0], o[1], B.top() + 25.0), az, 0, 600), 1.7,
                (tuple(o), tuple(n))))
    return out


def sample_board(sx=1, sy=1):
    """a 20 x 25 board on the front right table with its sensor, a header and a plug sticking out
    sideways toward the middle, and the way of its cable to the opening and down the post"""
    import trimesh
    from cad.helpers import box, cyl
    from cad.mesh import to_trimesh
    t = B.table_layout(sx, sy)
    (bx, by), (px, py), rc = t["board"], t["post"], t["r_collar"]
    zs = B.seat_z()
    bw, bl = 20.0, 25.0
    x0 = bx - bw / 2
    items = [(to_trimesh(box(x0, x0 + bw, by - bl / 2, by + bl / 2, zs, zs + 1.6)), "#2f6b4a", 1.0, "kit"),
             (to_trimesh(cyl("z", 2.5, zs + 1.6, zs + 4.0, (bx + 2.0, by))), "#a39782", 1.0, "kit"),
             (to_trimesh(box(x0 + 0.5, x0 + 3.0, by - 5.1, by + 5.1, zs + 1.6, zs + 4.1)), "#2a2a2d", 1.0, "kit"),
             (to_trimesh(box(x0 - 14.0, x0 + 0.5, by - 5.1, by + 5.1, zs + 1.8, zs + 4.3)), "#2a2a2d", 1.0, "kit")]
    zp1, _ = B.table_z()
    zc = zp1 + P.BED_COLLAR[1]
    route = [(x0 - 14.0, by, zs + 3.0), (x0 - 18.0, by + 2.0, zs + 1.0), (x0 - 18.5, by + 12.0, zp1 + 1.5),
             (x0 - 14.0, py - sy * 14.0, zp1 + 1.5), (px - 4.0, py - sy * 8.0, zc + 1.5), (px - 2.0, py - sy * 2.0, zc),
             (px - 2.0, py, zc - 8.0), (px - 2.0, py, B.floor_top() - 4.0)]
    tie = [(x0 - 1.0, by + P.BED_TIE[2], zs + 2.2), (x0 + bw + 1.0, by + P.BED_TIE[2], zs + 2.2)]
    _ = trimesh
    return items, [(route, "#d9a441", 1.4, "accent"), (tie, "#ff8b4b", 0.6, "accent")]


def renders(parts, elec, out, zones, cast=True, only=None):
    from cad.render import FILAMENT, camera, render
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bed = next(p for p in parts if p.name == "bedlid")
    body = (bed.mesh(), FILAMENT["body"], 1.0, "body")
    written = []

    def shot(name, items, cam, **kw):
        if only and name not in only:
            return
        path = out / f"{name}.png"
        render(items, path, cam, cast=cast, **kw)
        written.append(path)

    shot("bedlid_above", [body], camera((0, 0, 70), 30, 52, 470), size=(1200, 900))
    shot("bedlid_below", [body], camera((0, 0, 50), 205, -48, 470), size=(1200, 900), floor=False)
    shot("bedlid_on_the_bed", [(bed.print_mesh(), FILAMENT["body"], 1.0, "body")],
         camera((0, 0, 50), 30, 30, 500), size=(1200, 900))
    tgt = (0.0, -10.0, 120.0)
    shot("tracker_side", scene_items(parts, elec, 0, 45), camera(tgt, 90, 2, 700), size=(1200, 1000),
         panels=[panel(0, 45)], parallel=True, zoom=1.1)
    shot("tracker_angle", scene_items(parts, elec, 60, 40), camera(tgt, 36, 22, 720), size=(1200, 1000),
         panels=[panel(60, 40)])
    cut = ((0.0, P.TURRET_Y, 0.0), (0.0, -1.0, 0.0))
    shot("section_middle", scene_items(parts, elec, 0, 180, cut=cut), camera((0.0, P.TURRET_Y, 85.0), 18, 12, 560),
         size=(1300, 1000), floor=False)
    for name, pan, tilt, cam, zoom, c in closest_shots(zones):
        shot(name, scene_items(parts, elec, pan, tilt, cut=c, boards="keep"), cam, size=(1200, 900),
             parallel=True, zoom=zoom, floor=False)
    # one table with a sample board, its plug and the way of its cable, cut through the post
    sx, sy = 1, 1
    (px, py) = B.table_layout(sx, sy)["post"]
    board, lines = sample_board(sx, sy)
    tcut = ((0.0, py, 0.0), (0.0, -1.0, 0.0))
    items = [(cut_mesh(bed.mesh(), *tcut), FILAMENT["body"], 1.0, "body")] + board
    shot("seat_with_board", items, camera((48.0, 36.0, B.seat_z() - 12.0), 25, 32, 230), size=(1200, 900),
         lines=lines, floor=False)
    # the island top with the new slot, the old slot and the foot at pan 0 drawn on it
    zt = B.top() + 0.25
    old = [(x, y, zt) for x, y in B.old_slot_section().to_polygons()[0]]
    foot = [(x, y, zt) for x, y in B.foot_outline().to_polygons()[0]]
    lines = [(old + old[:1], "#ff8b4b", 0.25, "accent"), (foot + foot[:1], "#3b3b3e", 0.25, "dark")]
    shot("island_slot_above", [body], camera((0.0, P.TURRET_Y, B.top()), 15, 62, 150), size=(1200, 900),
         lines=lines, floor=False)
    ucut = ((0.0, 0.0, B.top() - 14.0), (0.0, 0.0, 1.0))
    shot("island_slot_below", [(cut_mesh(bed.mesh(), *ucut), FILAMENT["body"], 1.0, "body")],
         camera((0.0, P.TURRET_Y, B.top() - 4.0), 200, -62, 150), size=(1200, 900), floor=False)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="30 degree sweep, no exports, no report")
    ap.add_argument("--renders", metavar="DIR", help="also write the pictures into DIR")
    ap.add_argument("--flat", action="store_true", help="pictures without shadows, faster")
    ap.add_argument("--only", nargs="+", metavar="NAME", help="only these pictures, like bedlid_above section_middle")
    args = ap.parse_args()
    t0 = time.time()
    parts = B.build_parts()
    for p in parts:
        p.mesh()
    elec = B.electronics()
    log(f"built {len(parts)} parts", t0)
    bed = next(p for p in parts if p.name == "bedlid")
    prt_rep = B.print_report(bed)
    est = estimate.estimate("bedlid", bed.print_mesh())
    sup = B.support_estimate(prt_rep)
    log("print checks", t0)
    res = run_checks(parts, elec, 30.0 if args.quick else 10.0, t0)
    room = B.room_report(elec)
    soil = B.soil_report(bed.mesh())
    budget = B.cable_budget()
    budget_kit = B.cable_budget(photo=P.PHOTO_CABLE)
    budget_now = B.cable_budget(lift_z=0.0, photo=P.PHOTO_CABLE)
    log("soil and cable budget", t0)
    failures = failures_of(res, prt_rep, budget)
    sl, s, c = res["slot"], prt_rep["support"], prt_rep["contact"]
    print(f"soil {soil['depth']:.1f} mm deep, {soil['soil']:.2f} l, rim {soil['rim']:.2f} l")
    print(f"print {' x '.join(fmt(v) for v in prt_rep['size'])} mm, {est['grams']:.0f} g, {est['minutes'] / 60:.1f} h, "
          f"free bridge {prt_rep['free']['bridge_max']:.1f}, steep {prt_rep['free']['steep_area']:.1f}")
    print(f"supported {prt_rep['supported']}, open volume {s['volume'] / 1000:.0f} cm3, above the part: floor "
          f"{s['onto_part_area_floor']:.0f} mm2, tables {s['onto_part_area_tables']:.0f} mm2")
    for k, v in sup.items():
        print(f"  {k} supports {v['grams']:.0f} g, {v['minutes'] / 60:.1f} h")
    print(f"on the plate: rim {c['rim']:.0f} mm2, island {c['island']:.0f} mm2")
    print(f"slot {sl['old_width']} -> {sl['new_width']}, area {sl['old_area']:.0f} -> {sl['new_area']:.0f}, reach "
          f"{sl['old_reach']} -> {sl['new_reach']}, bearing {sl['bearing']}, open beside the foot {sl['uncovered']:.2f}, "
          f"needs {sl['need']:.0f} deg")
    under, top_rows, zone_area = res["same"]
    print(f"same as lid: under {max(a for _, a, _ in under):.2f}, interface outside the slot zone "
          f"{max(x for _, _, x, _, _ in top_rows):.2f}")
    print(f"exit: way {res['exit']['way_min']:.1f}, fill {res['exit']['fill']:.2f}, thread {res['exit']['thread_fill']:.2f}")
    for k, (g, pose) in sorted(res["zones"].items(), key=lambda kv: kv[1][0]):
        print(f"  head to {k}: {g:.2f} at {pose}")
    print(f"upright plug room above the seat {upright_room(res['zones']):.1f}")
    for r in budget:
        print(f"  {r['cable']}: slack {r['slack']:.1f} with {r['length']:.0f}, shortest {r['shortest']:.0f}")
    if failures:
        print("checks failed:")
        for f in failures:
            print("  " + f)
    if not args.quick and not failures:
        path, count, lo, hi = export_3mf(bed, HERE / "export")
        print(f"  wrote {path} with {count} object, from {np.round(lo, 2).tolist()} to {np.round(hi, 2).tolist()}", flush=True)
        for f in exporting.export_parts([bed], HERE / "export"):
            print("  wrote", f)
        mass = B.mass_zones(bed.mesh())
        layers = [B.estimate_at(bed.print_mesh(), h) for h in (0.2, 0.28)]
        write_report(HERE / "reports" / "bedlid.md", prt_rep, est, sup, res, room, soil, budget, budget_kit, budget_now,
                     failures, hi - lo, slim_lines(mass, layers, sup))
        log("exports and reports/bedlid.md", t0)
    if args.renders:
        for f in renders(parts, elec, args.renders, res["zones"], cast=not args.flat, only=args.only):
            print("  picture", f)
        log("pictures", t0)
    if failures:
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
