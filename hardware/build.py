"""regenerate every part, run the checks, export and render

    uv run build.py              everything, takes a few minutes
    uv run build.py --quick      coarse sweep and no renders, for trying a parameter
    uv run build.py --no-renders everything except the PNG files
    uv run build.py --drawings   only the technical drawings in ../docs/drawings.pdf
    uv run build.py --only steps/usb product_views   only these renders, no checks and no exports

the exit code is 1 when a check fails, the report in reports/checks.md says which one
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cad import assembly, cables, checks, drawings, estimate, exporting, fasteners, kit, views  # noqa: E402
from cad import params as P  # noqa: E402

LF = chr(10)  # write unix line ends on windows too, the repo keeps lf


def log(msg, t0):
    print(f"[{time.time() - t0:6.1f} s] {msg}", flush=True)


def fmt(v, nd=1):
    return f"{v:.{nd}f}"


def engraving_lines(eng):
    """the section about the signature on the lid"""
    L = ["## Signature on the lid", ""]
    if eng is None:
        L += ["The signature is switched off in `cad/params.py`, the lid is plain.", ""]
        return L
    s, sp = eng["sizes"], eng["spans"]
    L.append(f"Inter SemiBold at {fmt(s['x_height'])} mm x height ({fmt(s['url_cap'])} mm caps) for the name line, "
             f"JetBrains Mono ExtraBold at {fmt(s['tag_cap'])} mm cap height for the class tag, the fhv mark "
             f"{fmt(s['logo_height'])} mm tall. {fmt(s['depth'])} mm deep, {fmt(s['width'])} x {fmt(s['height'])} mm, "
             f"front edge at y = {fmt(s['box'][3])}.")
    L.append("Measured on the lid mesh, sliced half way down the recess.")
    L.append("")
    L.append("| value | measured | limit |")
    L.append("|---|---|---|")
    L.append(f"| narrowest stroke or join | {fmt(eng['stroke_min'], 2)} mm | {P.ENGRAVE_STROKE_MIN} |")
    L.append(f"| narrowest counter, gap or wall between recesses | {fmt(eng['island_min'], 2)} mm | {P.ENGRAVE_ISLAND_MIN} |")
    L.append(f"| solid lid behind the floor | {fmt(eng['skin'])} mm | {P.ENGRAVE_SKIN_MIN} |")
    L.append(f"| clear distance to an edge, a hole or the sun mark | {fmt(eng['clear'])} mm | {P.ENGRAVE_CLEAR_MIN} |")
    L.append(f"| widest span: name line, tag, fhv mark, rule | {fmt(sp['url'])}, {fmt(sp['tag'])}, "
             f"{fmt(sp['logo'])}, {fmt(sp['rule'])} mm | about {P.ENGRAVE_SPAN_MAX} |")
    L.append(f"| pieces and holes | {eng['pieces']} and {eng['holes']}, "
             f"{'the same as the font outlines' if eng['same_topology'] else 'different from the font outlines'} | the same |")
    L.append("")
    L.append("Strokes: the recess shrunk by half the limit keeps every piece whole. Islands: the recess grown by half")
    L.append(f"the limit lets no two pieces meet and closes no counter. Before the cut each letter is closed by "
             f"{fmt(s['fill'], 2)} mm, so")
    L.append("the notches where a bowl meets a stem and the slivers inside M and N, all too thin to print, go with the")
    L.append("letter.")
    L.append("")
    return L


def write_report(path, parts_rep, static_bad, sweep, cable_rows, fast_rows, web_sizes, est, failures, engraving=None):
    L = []
    L.append("# brainSOL hardware checks")
    L.append("")
    L.append("Written by `uv run build.py`. Do not edit by hand, run the build again instead.")
    L.append("")
    L.append("## Result")
    L.append("")
    if failures:
        L.append("Failed checks:")
        L.append("")
        for f in failures:
            L.append(f"- {f}")
    else:
        L.append("All checks passed.")
    L.append("")
    L.append("## Parts")
    L.append("")
    L.append("| part | count | size on the bed mm | closed solid | watertight | fits | steep overhang mm2 | widest bridge mm | thin wall share | grams | minutes |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in parts_rep:
        e = est[r["name"]]
        size = " x ".join(fmt(s) for s in r["size"])
        L.append(f"| {r['name']} | {r['count']} | {size} | {'yes' if r['valid'] and r['solids'] == 1 else 'no'} | "
                 f"{'yes' if r['watertight'] else 'no'} | {'yes' if r['fits'] else 'no'} | {fmt(r['steep_area'])} | "
                 f"{fmt(r['bridge_max'])} | {fmt(100 * r['share_thin'])} % | {fmt(e['grams'] * r['count'])} | "
                 f"{fmt(e['minutes'] * r['count'], 0)} |")
    L.append("")
    L.append("Steep overhang counts downward faces steeper than 45 degrees and wider than 3 mm. Thin wall share is the")
    L.append("part of the surface where a ray straight into the part leaves it again within 1.6 mm, most of it sits on")
    L.append("chamfered edges and the lip of the bezel, which are thin on purpose.")
    L.append("")
    L.append("## Interference")
    L.append("")
    L.append(f"Pan swept from {sweep['pans'][0]:.0f} to {sweep['pans'][1]:.0f} in steps of {sweep['pans'][2]:.0f} degrees, "
             f"tilt from {sweep['tilts'][0]:.0f} to {sweep['tilts'][1]:.0f} in steps of {sweep['tilts'][2]:.0f}, "
             f"{sweep['poses']} poses for head against base.")
    L.append("")
    L.append("| pair | largest overlap mm3 | smallest gap mm |")
    L.append("|---|---|---|")
    L.append(f"| base and neck | {sweep['base_neck']:.3f} | the foot rides on the lid, contact |")
    L.append(f"| neck and head | {sweep['neck_head']:.3f} | {sweep['gap_neck_head']:.2f} at tilt {sweep['gap_neck_head_pose']:.0f} |")
    gp = sweep["gap_head_base_pose"]
    L.append(f"| base and head | {sweep['base_head']:.3f} | {sweep['gap_head_base']:.2f} at pan {gp[0]:.0f}, tilt {gp[1]:.0f} |")
    L.append("")
    L.append(f"Static pairs inside each group (printed parts against each other and against the kit keep outs): "
             f"{'no overlap above ' + str(checks.CONTACT_TOL) + ' mm3' if not static_bad else str(static_bad)}.")
    L.append("")
    L += engraving_lines(engraving)
    L.append("## Sensor eyes")
    L.append("")
    L.append(f"Shade wall height above the photoresistor face {P.SHADE_H:.1f} mm over a sensor width of {P.LDR_D:.1f} mm, "
             f"k = {P.SHADE_K_ACTUAL:.2f}, the simulation uses {P.SHADE_K:.2f}.")
    L.append("")
    L.append("## Cable budget")
    L.append("")
    reading = "tip to tip, so the wire between the plug housings is shorter by two housings" if P.CABLE_LEN_INCLUDES_PLUGS else "between the housings"
    L.append(f"Lengths in mm between the backs of the plug housings. The kit length is read as {reading}.")
    L.append("Free segments are measured for the worst pose and get an allowance for bends.")
    L.append("")
    L.append("| cable | uno to slot | through the neck | service loop | inside the head | needed | available | slack | worst pose |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in cable_rows:
        L.append(f"| {r['cable']} | {fmt(r['uno'])} | {fmt(r['neck'])} | {fmt(r['loop'])} | {fmt(r['head'])} | "
                 f"{fmt(r['total'])} | {fmt(r['available'])} | {fmt(r['slack'])} | {r['worst']} |")
    L.append("")
    L.append("## Fasteners")
    L.append("")
    L.append("| screw | where | count |")
    L.append("|---|---|---|")
    for kind, where, n in fasteners.uses():
        L.append(f"| {kind} | {where} | {n} |")
    L.append("")
    L.append("| type | used | in the kit | spare |")
    L.append("|---|---|---|---|")
    for kind, used, have, spare in fast_rows:
        L.append(f"| {kind} | {used} | {have} | {spare} |")
    L.append("")
    L.append("## Web files")
    L.append("")
    L.append("| file | bytes | triangles |")
    L.append("|---|---|---|")
    for k, (size, tris) in web_sizes.items():
        L.append(f"| {k}.glb | {size} | {tris} |")
    L.append(f"| together | {sum(s for s, _ in web_sizes.values())} | {sum(t for _, t in web_sizes.values())} |")
    L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8", newline=LF)


def make_drawings(parts, path, t0):
    """the drawings pdf, a text that runs into a line is reported but does not fail the build"""
    findings = drawings.make(parts, path, log=lambda msg: log(msg, t0))
    for sheet, bad in findings.items():
        for text, what in bad:
            print(f"  drawing {sheet}: {text} touches {what}")
    log(f"drawings in {path.name}", t0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="coarse sweep, no renders, no 3mf")
    ap.add_argument("--no-renders", action="store_true", help="skip the PNG renders")
    ap.add_argument("--drawings", action="store_true", help="only the technical drawings, no checks and no exports")
    ap.add_argument("--only", nargs="+", metavar="VIEW",
                    help="only these renders, a group of cad/views.py like product_views or a step picture like steps/usb")
    args = ap.parse_args()
    t0 = time.time()
    drawing_pdf = HERE.parent / "docs" / "drawings.pdf"
    if args.drawings:
        make_drawings(assembly.build_parts(), drawing_pdf, t0)
        return 0
    if args.only:
        parts = assembly.build_parts()
        log(f"built {len(parts)} parts", t0)
        views.all_views(parts, assembly.electronics(), HERE / "renders", only=args.only)
        log(f"renders {' '.join(args.only)}", t0)
        return 0
    export_dir = HERE / "export"
    render_dir = HERE / "renders"
    report_dir = HERE / "reports"
    report_dir.mkdir(exist_ok=True)

    parts = assembly.build_parts()
    for p in parts:
        p.mesh()
    elec = assembly.electronics()
    log(f"built {len(parts)} parts", t0)

    scene = checks.Scene(parts, elec)
    static = checks.static_checks(scene)
    static_bad = [(g, a, b, round(v, 2)) for g, a, b, v in static if v > checks.CONTACT_TOL]
    step = 15.0 if args.quick else 10.0
    sweep = checks.sweep(scene, step, step)
    log(f"interference sweep over {sweep['poses']} poses", t0)
    parts_rep = []
    est = {}
    for p in parts:
        r = checks.part_report(p)
        parts_rep.append(r)
        est[p.name] = estimate.estimate(p.name, p.print_mesh())
    log("part checks", t0)
    cable_rows = cables.budget()
    fast_rows = fasteners.totals()
    lid = next(p for p in parts if p.name == "lid")
    engraving = checks.engraving_report(lid.mesh()) if P.SIG_ON else None
    log("signature check", t0)

    fit = assembly.fit_test_part()
    parts_rep.append(checks.part_report(fit))
    est[fit.name] = estimate.estimate(fit.name, fit.print_mesh())
    exporting.export_parts(parts + [fit], export_dir)
    elec_shapes = {}
    elec_shapes.update(kit.base_electronics())
    elec_shapes.update(kit.neck_electronics())
    elec_shapes.update(kit.head_electronics())
    exporting.export_assembly_step(parts, elec_shapes, export_dir / "step" / "assembly.step")
    if not args.quick:
        exporting.export_3mf(parts, export_dir)
    web_sizes, web_json = exporting.export_web(parts, export_dir)
    log("exports", t0)

    failures = []
    for r in parts_rep:
        if not (r["valid"] and r["solids"] == 1 and r["watertight"]):
            failures.append(f"{r['name']} is not one closed solid")
        if not r["fits"]:
            failures.append(f"{r['name']} does not fit the bed")
        if r["steep_area"] > 1.0:
            failures.append(f"{r['name']} has {r['steep_area']:.1f} mm2 of overhang steeper than 45 degrees")
        if r["bridge_max"] > P.BRIDGE_MAX:
            failures.append(f"{r['name']} has a bridge of {r['bridge_max']:.1f} mm")
    if static_bad:
        failures.append(f"static overlap {static_bad}")
    for k in ("base_neck", "neck_head", "base_head"):
        if sweep[k] > checks.CONTACT_TOL:
            failures.append(f"{k} overlap {sweep[k]:.2f} mm3")
    for r in cable_rows:
        if r["slack"] < P.CABLE_SLACK_MIN:
            failures.append(f"{r['cable']} has only {r['slack']:.1f} mm of slack")
    if not fasteners.ok():
        failures.append("more screws than the kit has")
    for k, (size, _) in web_sizes.items():
        if size > exporting.glb_limit(k):
            failures.append(f"{k}.glb is {size} bytes")
    if sum(size for size, _ in web_sizes.values()) > exporting.GLB_TOTAL_LIMIT:
        failures.append(f"the web files are {sum(size for size, _ in web_sizes.values())} bytes together")
    if engraving is not None:
        failures += checks.engraving_failures(engraving)

    write_report(report_dir / "checks.md", parts_rep, static_bad, sweep, cable_rows, fast_rows, web_sizes, est, failures,
                 engraving)
    summary = {"failures": failures, "sweep": {k: v for k, v in sweep.items() if k != "worst"},
               "cables": cable_rows, "assembly": web_json, "engraving": engraving,
               "parts": [{k: v for k, v in r.items() if k not in ("steep_worst",)} for r in parts_rep],
               "estimate": est}
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8", newline=LF)
    log("reports", t0)

    if not (args.quick or args.no_renders):
        views.all_views(parts, elec, render_dir)
        views.print_views([fit], render_dir)
        log("renders", t0)
    if not args.quick:
        make_drawings(parts, drawing_pdf, t0)

    if failures:
        print("checks failed:")
        for f in failures:
            print("  " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
