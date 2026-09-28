"""Generate the worked-example figures for the Phase 3 report.

Runs the planner's own routines on a small synthetic valley and writes
TikZ/pgfplots snippets and number macros to latex/generated/, so every value in
the "How the water volume is calculated" section comes from the same code
the deployed planner runs:

  priority flood      app.planning._condition_dem
  D8 + accumulation   app.terrain._flow_graph
  catchment           app.hydrology.UpstreamIndex
  pond storage        app.hydrology.impoundment / stage_curve
  contour gridding    app.terrain._grid_from_contours

    python scripts/report_figures.py
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import contourpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.hydrology import UpstreamIndex, impoundment, stage_curve  # noqa: E402
from app.planning import _condition_dem  # noqa: E402
from app.terrain import ContourPointSet, _flow_graph, _grid_from_contours  # noqa: E402

OUT = ROOT / "latex" / "generated"
ROWS = COLS = 7
CELL_M = 20.0
STAGE_M = 2.0
OUTLET = (5, 3)
RADIUS_M = 100.0
RAIN_MM = 1287.0  # Kanker west June-September 2025 CHIRPS total, used for the toy example too
RUNOFF_C = 0.35
S = 0.72  # TikZ cell size (cm)


def synthetic_valley() -> np.ndarray:
    """A valley draining south with a pit on its floor, rounded to 0.1 m."""
    r = np.arange(ROWS)[:, None]
    c = np.arange(COLS)[None, :]
    z = 100 + 0.6 * (ROWS - 1 - r) + 0.45 * np.abs(c - 3) ** 1.7
    z = z + np.random.default_rng(7).normal(0, 0.12, z.shape)
    z[2, 3] -= 1.4
    return np.round(z, 1)


def fmt(value: float, digits: int = 0) -> str:
    """Thousands with a comma, in math mode for LaTeX; halves round up, as in the UI."""
    quantum = Decimal(1).scaleb(-digits)
    text = f"{Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP):,}"
    return text.replace(",", "{,}")


def shade(z: float, lo: float, hi: float) -> str:
    return f"terrainhi!{round(100 * (z - lo) / (hi - lo))}!terrainlo"


def cell_box(r: int, c: int) -> str:
    return f"({c * S:.3f},{-r * S:.3f}) rectangle ({(c + 1) * S:.3f},{-(r + 1) * S:.3f})"


def centre(r: int, c: int) -> tuple[float, float]:
    return (c + 0.5) * S, -(r + 0.5) * S


def frame(extra: str = "") -> list[str]:
    lines = [f"\\draw[line,thin] (0,0) rectangle ({COLS * S:.3f},{-ROWS * S:.3f});"]
    for c in range(COLS):
        lines.append(f"\\node[font=\\tiny,text=muted] at ({(c + 0.5) * S:.3f},0.22) {{{c}}};")
    for r in range(ROWS):
        lines.append(f"\\node[font=\\tiny,text=muted] at (-0.22,{-(r + 0.5) * S:.3f}) {{{r}}};")
    return lines


def boundary_edges(mask: np.ndarray) -> list[str]:
    """Segments between True and False cells (and the grid edge)."""
    segs = []
    for r in range(ROWS):
        for c in range(COLS):
            if not mask[r, c]:
                continue
            x0, x1, y0, y1 = c * S, (c + 1) * S, -r * S, -(r + 1) * S
            if r == 0 or not mask[r - 1, c]:
                segs.append(f"({x0:.3f},{y0:.3f})--({x1:.3f},{y0:.3f})")
            if r == ROWS - 1 or not mask[r + 1, c]:
                segs.append(f"({x0:.3f},{y1:.3f})--({x1:.3f},{y1:.3f})")
            if c == 0 or not mask[r, c - 1]:
                segs.append(f"({x0:.3f},{y0:.3f})--({x0:.3f},{y1:.3f})")
            if c == COLS - 1 or not mask[r, c + 1]:
                segs.append(f"({x1:.3f},{y0:.3f})--({x1:.3f},{y1:.3f})")
    return segs


def write(name: str, lines: list[str]) -> None:
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    z = synthetic_valley()
    lo, hi = float(z.min()), float(z.max())
    filled = _condition_dem(z)
    cell_area = CELL_M * CELL_M
    downstream, accumulation = _flow_graph(filled, cell_area, CELL_M, CELL_M)
    counts = np.rint(accumulation / cell_area).astype(int)
    upstream = UpstreamIndex(downstream)
    catch = np.zeros(z.size, dtype=bool)
    catch[upstream.catchment(OUTLET[0] * COLS + OUTLET[1])] = True
    catch = catch.reshape(z.shape)
    allowed = np.ones_like(catch)
    pond = impoundment(z, OUTLET, STAGE_M, catch, allowed, CELL_M, CELL_M, RADIUS_M)
    crest = float(z[OUTLET]) + STAGE_M
    pond_mask = np.zeros(z.size, dtype=bool)
    pond_mask[pond.cells] = True
    pond_mask = pond_mask.reshape(z.shape)
    depth = np.where(pond_mask, crest - z, 0.0)
    curve = stage_curve(z, OUTLET, catch, allowed, CELL_M, CELL_M, RADIUS_M, [0.5, 1.0, 1.5, 2.0, 2.5, 3.0])

    # Embankment edges: pond cell next to lower ground outside the catchment (as in impoundment()).
    bund = []
    for r, c in zip(*np.nonzero(pond_mask)):
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < ROWS and 0 <= cc < COLS and not catch[rr, cc] and z[rr, cc] <= crest:
                bund.append((int(r), int(c), int(rr), int(cc)))
    assert abs(len(bund) * CELL_M - pond.embankment_length_m) < 1e-6, (bund, pond.embankment_length_m)

    catchment_cells = int(catch.sum())
    area_c = catchment_cells * cell_area
    runoff = RAIN_MM / 1000 * area_c * RUNOFF_C
    collect = min(runoff, pond.storage_m3)
    pit = (2, 3)

    # ---- macros -------------------------------------------------------------------
    depth_terms = " + ".join(f"{depth[r, c]:.1f}" for r, c in sorted(zip(*np.nonzero(pond_mask)), key=lambda rc: (-rc[0], rc[1])))
    macros = {
        "WEcell": fmt(CELL_M), "WEcellarea": fmt(cell_area), "WEstage": f"{STAGE_M:g}",
        "WEoutletz": f"{z[OUTLET]:.1f}", "WEcrest": f"{crest:.1f}", "WEpondcells": str(int(pond_mask.sum())),
        "WEdepthsum": f"{depth.sum():.1f}", "WEdepthterms": depth_terms,
        "WEstorage": fmt(pond.storage_m3), "WEstoragenum": f"{pond.storage_m3:.0f}", "WEfootprint": fmt(pond.footprint_m2),
        "WEbundedges": str(len(bund)), "WEbund": fmt(pond.embankment_length_m),
        "WEcatchcells": str(catchment_cells), "WEcatcharea": fmt(area_c), "WEcatchha": f"{area_c / 10_000:.2f}",
        "WErain": fmt(RAIN_MM), "WEC": f"{RUNOFF_C:.2f}", "WErunoff": fmt(runoff), "WEcollect": fmt(collect),
        "WEfill": f"{runoff / pond.storage_m3:.2f}", "WEmaxdepth": f"{pond.max_depth_m:.1f}",
        "WEpitz": f"{z[pit]:.1f}", "WEpitfilled": f"{filled[pit]:.1f}", "WEpitdepth": f"{depth[pit]:.1f}",
        "WEmeandepth": f"{pond.storage_m3 / pond.footprint_m2:.2f}",
        "WElo": f"{lo:.1f}", "WEhi": f"{hi:.1f}",
    }

    # ---- 1. raw DEM and filled DEM ----------------------------------------------------------
    for name, grid, note in (("we_dem_raw.tex", z, "raw"), ("we_dem_filled.tex", filled, "filled")):
        lines = []
        for r in range(ROWS):
            for c in range(COLS):
                value = grid[r, c]
                x, y = centre(r, c)
                lines.append(f"\\fill[{shade(min(value, hi), lo, hi)}] {cell_box(r, c)};")
                changed = abs(filled[r, c] - z[r, c]) > 1e-3
                label = f"{value:.1f}"
                style = "font=\\tiny\\bfseries,text=navy" if changed else "font=\\tiny,text=ink"
                lines.append(f"\\node[{style}] at ({x:.3f},{y:.3f}) {{{label}}};")
        lines += [f"\\draw[line,very thin] {cell_box(r, c)};" for r in range(ROWS) for c in range(COLS)]
        if note == "raw":
            lines.append(f"\\draw[navy,very thick] {cell_box(*pit)};")
            lines.append(f"\\node[font=\\tiny,text=navy,anchor=west] at ({COLS * S + 0.08:.3f},{-(pit[0] + 0.5) * S:.3f}) {{$\\leftarrow$ pit}};")
        else:
            lines.append(f"\\draw[gold,very thick] {cell_box(*pit)};")
            lines.append(f"\\node[font=\\tiny,text=warnfg,anchor=west] at ({COLS * S + 0.08:.3f},{-(pit[0] + 0.5) * S:.3f}) {{$\\leftarrow$ raised}};")
        write(name, frame() + lines)

    # ---- 2. D8 directions, accumulation and the outlet catchment -------------------------------------
    lines = [f"\\fill[runoff!22] {cell_box(r, c)};" for r in range(ROWS) for c in range(COLS) if catch[r, c]]
    lines += [f"\\draw[line,very thin] {cell_box(r, c)};" for r in range(ROWS) for c in range(COLS)]
    for r in range(ROWS):
        for c in range(COLS):
            target = int(downstream[r, c])
            x, y = centre(r, c)
            if target >= 0:
                tr, tc = divmod(target, COLS)
                dx, dy = (tc - c), -(tr - r)
                norm = math.hypot(dx, dy)
                ax, ay = x + 0.34 * S * dx / norm, y + 0.34 * S * dy / norm
                bx, by = x - 0.12 * S * dx / norm, y - 0.12 * S * dy / norm
                lines.append(f"\\draw[-{{Stealth[length=1.3mm]}},navy,semithick] ({bx:.3f},{by:.3f}) -- ({ax:.3f},{ay:.3f});")
            else:
                lines.append(f"\\fill[navy] ({x:.3f},{y:.3f}) circle (0.4mm);")
            weight = "\\bfseries" if counts[r, c] >= 5 else ""
            lines.append(f"\\node[font=\\fontsize{{5}}{{6}}\\selectfont{weight},text=collect!80!black,anchor=north west,inner sep=0.6pt] at ({c * S:.3f},{-r * S:.3f}) {{{counts[r, c]}}};")
    lines.append("\\draw[runoff!80!black,thick] " + " ".join(boundary_edges(catch)) + ";")
    ox, oy = centre(*OUTLET)
    lines.append(f"\\draw[collect,very thick] ({ox:.3f},{oy:.3f}) circle (0.27);")
    write("we_d8.tex", frame() + lines)

    # ---- 3. plan view: pond depths, catchment and embankment edges -------------------------------------
    lines = [f"\\fill[runoff!18] {cell_box(r, c)};" for r in range(ROWS) for c in range(COLS) if catch[r, c]]
    lines += [f"\\fill[storage!{round(35 + 55 * depth[r, c] / STAGE_M)}] {cell_box(r, c)};"
              for r in range(ROWS) for c in range(COLS) if pond_mask[r, c]]
    lines += [f"\\draw[line,very thin] {cell_box(r, c)};" for r in range(ROWS) for c in range(COLS)]
    for r in range(ROWS):
        for c in range(COLS):
            x, y = centre(r, c)
            if pond_mask[r, c]:
                lines.append(f"\\node[font=\\tiny\\bfseries,text=white] at ({x:.3f},{y:.3f}) {{{depth[r, c]:.1f}}};")
            else:
                colour = "ink" if catch[r, c] else "old"
                lines.append(f"\\node[font=\\fontsize{{5}}{{6}}\\selectfont,text={colour}] at ({x:.3f},{y:.3f}) {{{z[r, c]:.1f}}};")
    lines.append("\\draw[runoff!80!black,thick] " + " ".join(boundary_edges(catch)) + ";")
    for r, c, rr, cc in bund:
        if rr != r:
            yb = -max(r, rr) * S
            lines.append(f"\\draw[collect,line width=2.2pt,line cap=round] ({c * S:.3f},{yb:.3f}) -- ({(c + 1) * S:.3f},{yb:.3f});")
        else:
            xb = max(c, cc) * S
            lines.append(f"\\draw[collect,line width=2.2pt,line cap=round] ({xb:.3f},{-r * S:.3f}) -- ({xb:.3f},{-(r + 1) * S:.3f});")
    lines.append(f"\\draw[collect,very thick] ({ox:.3f},{oy:.3f}) circle (0.27);")
    write("we_plan.tex", frame() + lines)

    # ---- 4. sections: along the valley (column 3) and across it (row 4) ----------------------------------------
    base, xs, ys = 99.0, 1.05, 0.62

    def section(cells: list[tuple[int, int]], label_first: str, label_last: str) -> list[str]:
        out = []
        n = len(cells)
        for i, (r, c) in enumerate(cells):
            x0, x1 = i * xs, (i + 1) * xs
            top = (z[r, c] - base) * ys
            fill = "terrainhi!55!terrainlo" if catch[r, c] else "terrainhi!25!terrainlo"
            out.append(f"\\fill[{fill}] ({x0:.3f},0) rectangle ({x1:.3f},{top:.3f});")
            if not catch[r, c]:
                out.append(f"\\fill[pattern=north east lines,pattern color=old] ({x0:.3f},0) rectangle ({x1:.3f},{top:.3f});")
            out.append(f"\\draw[terrainhi!80!black,thick] ({x0:.3f},{top:.3f}) -- ({x1:.3f},{top:.3f});")
            if pond_mask[r, c]:
                ctop = (crest - base) * ys
                out.append(f"\\fill[storage!55] ({x0:.3f},{top:.3f}) rectangle ({x1:.3f},{ctop:.3f});")
                out.append(f"\\draw[{{Stealth[length=1.2mm]}}-{{Stealth[length=1.2mm]}},white,thin] ({(x0 + x1) / 2:.3f},{top + 0.02:.3f}) -- ({(x0 + x1) / 2:.3f},{ctop - 0.02:.3f});")
                # Keep the depth label clear of the dashed filled surface in the pit.
                label_top = (filled[r, c] - base) * ys if abs(filled[r, c] - z[r, c]) > 1e-3 else ctop
                out.append(f"\\node[font=\\tiny\\bfseries,text=white,fill=storage!85!black,inner sep=1pt,rounded corners=1pt] at ({(x0 + x1) / 2:.3f},{(top + label_top) / 2:.3f}) {{{depth[r, c]:.1f}}};")
            if abs(filled[r, c] - z[r, c]) > 1e-3:
                # Drawn over the water so the filled (routing) surface stays visible.
                ftop = (filled[r, c] - base) * ys
                out.append(f"\\draw[navy,thick,densely dashed] ({x0:.3f},{ftop:.3f}) -- ({x1:.3f},{ftop:.3f});")
                out.append(f"\\node[font=\\fontsize{{5}}{{6}}\\selectfont,text=navy,anchor=south west,inner sep=0.5pt] at ({x0 + 0.02:.3f},{ftop:.3f}) {{$z'$}};")
            out.append(f"\\node[font=\\fontsize{{5}}{{6}}\\selectfont,text=muted] at ({(x0 + x1) / 2:.3f},-0.18) {{({r},{c})}};")
            out.append(f"\\node[font=\\fontsize{{5}}{{6}}\\selectfont,text=ink,anchor=south] at ({(x0 + x1) / 2:.3f},{top:.3f}) {{{z[r, c]:.1f}}};" if not pond_mask[r, c] else "")
        ctop = (crest - base) * ys
        out.append(f"\\draw[storage!80!black,densely dashed] (-0.1,{ctop:.3f}) -- ({n * xs + 0.1:.3f},{ctop:.3f});")
        # Label the crest over open water, where no ground value is printed.
        first_wet = next(i for i, (r, c) in enumerate(cells) if pond_mask[r, c])
        out.append(f"\\node[font=\\tiny,text=storage!80!black,anchor=south west,inner sep=1pt] at ({first_wet * xs + 0.04:.3f},{ctop + 0.02:.3f}) {{crest $h_c={crest:.1f}$\\,m}};")
        peak = max(max(float(z[r, c]) for r, c in cells), crest) + 0.6
        out.append(f"\\draw[muted,->] (0,0) -- (0,{(peak - base) * ys:.3f}) node[above,font=\\tiny] {{$z$ (m)}};")
        for level in range(int(base), int(peak) + 1):
            yl = (level - base) * ys
            out.append(f"\\draw[muted] (-0.05,{yl:.3f}) -- (0.05,{yl:.3f}) node[left=1pt,font=\\fontsize{{5}}{{6}}\\selectfont] {{{level}}};")
        out.append(f"\\node[font=\\tiny,text=muted,anchor=north west] at (0,-0.34) {{{label_first}}};")
        out.append(f"\\node[font=\\tiny,text=muted,anchor=north east] at ({n * xs:.3f},-0.34) {{{label_last}}};")
        return out

    along = [(r, 3) for r in range(ROWS)]
    lines = section(along, "north (upstream)", "south (downstream)")
    # The bund closes the outlet's downstream edge.
    xb = (OUTLET[0] + 1) * xs
    ctop = (crest - base) * ys
    ztop = (z[OUTLET] - base) * ys
    lines.append(f"\\fill[collect] ({xb - 0.12:.3f},{ztop:.3f}) -- ({xb - 0.05:.3f},{ctop + 0.12:.3f}) -- ({xb + 0.05:.3f},{ctop + 0.12:.3f}) -- ({xb + 0.16:.3f},{(z[6, 3] - base) * ys:.3f}) -- cycle;")
    lines.append(f"\\node[font=\\tiny,text=collect!80!black,anchor=south] at ({xb:.3f},{ctop + 0.14:.3f}) {{bund}};")
    lines.append(f"\\draw[collect!80!black,{{Stealth[length=1.2mm]}}-{{Stealth[length=1.2mm]}}] ({OUTLET[0] * xs + 0.12:.3f},{ztop:.3f}) -- ({OUTLET[0] * xs + 0.12:.3f},{ctop:.3f}) node[midway,left,font=\\tiny] {{$h$}};")
    write("we_section_along.tex", [line for line in lines if line])
    across = [(4, c) for c in range(COLS)]
    write("we_section_across.tex", [line for line in section(across, "west", "east") if line])

    # ---- 5. 3D wireframe with the water plane ---------------------------------------------------------
    def world(r: float, c: float) -> tuple[float, float]:
        return c * CELL_M, (ROWS - r) * CELL_M

    mesh = ["\\addplot3[surf,shader=faceted,faceted color=terrainhi!70!black,colormap name=terrain,mesh/rows=%d,mesh/cols=%d,line width=0.3pt] coordinates {" % (ROWS, COLS)]
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            x, y = world(r + 0.5, c + 0.5)
            row.append(f"({x:.0f},{y:.0f},{z[r, c]:.2f})")
        mesh.append(" ".join(row))
    mesh.append("};")
    water = []
    for r, c in zip(*np.nonzero(pond_mask)):
        x0, y1 = world(r, c)
        x1, y0 = world(r + 1, c + 1)
        water.append(f"\\fill[storage,fill opacity=0.55] (axis cs:{x0:.0f},{y0:.0f},{crest:.2f}) -- (axis cs:{x1:.0f},{y0:.0f},{crest:.2f}) -- (axis cs:{x1:.0f},{y1:.0f},{crest:.2f}) -- (axis cs:{x0:.0f},{y1:.0f},{crest:.2f}) -- cycle;")
    for r, c, rr, cc in bund:
        if rr != r:
            yb = (ROWS - max(r, rr)) * CELL_M
            a, b = (c * CELL_M, yb), ((c + 1) * CELL_M, yb)
        else:
            xb = max(c, cc) * CELL_M
            a, b = (xb, (ROWS - r) * CELL_M), (xb, (ROWS - r - 1) * CELL_M)
        water.append(f"\\draw[collect,line width=2pt] (axis cs:{a[0]:.0f},{a[1]:.0f},{crest + 0.15:.2f}) -- (axis cs:{b[0]:.0f},{b[1]:.0f},{crest + 0.15:.2f});")
    x, y = world(OUTLET[0] + 0.5, OUTLET[1] + 0.5)
    water.append(f"\\draw[collect,thick] (axis cs:{x:.0f},{y:.0f},{z[OUTLET]:.2f}) -- (axis cs:{x:.0f},{y:.0f},{crest + 1.6:.2f}) node[above,font=\\tiny,text=collect!80!black] {{outlet $o$}};")
    write("we_wireframe.tex", mesh + water)

    # ---- 6. stage-storage table -----------------------------------------------------------------------
    table = [f"{row['stage_m']:.1f} & {fmt(row['area_m2'])} & {fmt(row['storage_m3'])} & {fmt(row['embankment_length_m'])}\\\\" for row in curve]
    write("we_stage_rows.tex", table)
    write("we_stage_plot.tex", [r"\addplot[storage,very thick,mark=*,mark size=1.6pt] coordinates {(0,0) "
                                + " ".join(f"({row['stage_m']},{row['storage_m3']})" for row in curve) + "};"])

    # ---- 6b. the D8 choice for one cell beside the outlet ---------------------------------------------
    probe = (5, 2)
    grades = []
    for dr, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        rr, cc = probe[0] + dr, probe[1] + dc
        dist = math.hypot(dr * CELL_M, dc * CELL_M)
        drop = float(filled[probe] - filled[rr, cc])
        grades.append((rr, cc, float(filled[rr, cc]), dist, drop, drop / dist))
    chosen = divmod(int(downstream[probe]), COLS)
    best = max(grades, key=lambda g: g[5])
    assert (best[0], best[1]) == chosen
    rows_tex = []
    for rr, cc, zn, dist, drop, grade in grades:
        mark = "\\textbf{" if (rr, cc) == chosen else "{"
        rows_tex.append(f"{mark}({rr},{cc})}} & {zn:.1f} & {dist:.1f} & {drop:+.1f} & {mark}{grade:+.4f}}}\\\\")
    write("we_grades_rows.tex", rows_tex)
    macros.update({"WEprobe": f"({probe[0]},{probe[1]})", "WEprobez": f"{z[probe]:.1f}",
                   "WEprobeto": f"({chosen[0]},{chosen[1]})"})

    # ---- 7. linear versus bounded smooth contour interpolation ------------------------------------------------
    interp = contour_profiles()
    macros.update(interp["macros"])
    write("we_interp_coords.tex", interp["plots"])

    # ---- 8. real example (Kanker west) from the live or local API -------------------------------------------
    macros.update(kanker_macros())

    lines = [f"\\newcommand{{\\{key}}}{{{value}}}" for key, value in macros.items()]
    write("we_values.tex", lines)
    print(json.dumps({k: v for k, v in macros.items()}, indent=1))


def contour_profiles() -> dict:
    """A 1.2 km ridge sampled as 20 m contours, gridded both ways by the planner."""
    n = 241
    xs = np.linspace(-600, 600, n)
    xx, yy = np.meshgrid(xs, xs)
    true = 300 + 95 * np.exp(-((xx / 330) ** 2 + (yy / 520) ** 2)) - 0.02 * yy
    levels = np.arange(300, 400, 20.0)
    generator = contourpy.contour_generator(xs, xs, true)
    lon0, lat0 = 81.3, 21.2
    rad = 6_371_000.0
    points = []
    for level in levels:
        for line in generator.lines(level):
            for x, y in line[:: max(1, len(line) // 160)]:
                lon = lon0 + math.degrees(x / (rad * math.cos(math.radians(lat0))))
                lat = lat0 + math.degrees(y / rad)
                points.append((lon, lat, level))
    cs = ContourPointSet(points=np.asarray(points), features=len(levels), elevations=list(levels))
    gx, gy, linear, _, _ = _grid_from_contours(cs, 120, smooth=False)
    _, _, smooth, _, _ = _grid_from_contours(cs, 120, smooth=True)
    row = int(np.argmin(np.abs(gy[:, 0])))
    x_line = gx[row]
    true_line = 300 + 95 * np.exp(-((x_line / 330) ** 2)) - 0.02 * gy[row, 0]
    mask = np.abs(x_line) <= 560

    def coords(values):
        return " ".join(f"({x:.0f},{v:.2f})" for x, v in zip(x_line[mask][::2], values[mask][::2]))

    def flat_share(grid):
        gyy, gxx = np.gradient(grid, gy[:, 0], gx[0])
        # Inside the closed 340 m contour; the open lower contours run off the synthetic grid.
        inside = (300 + 95 * np.exp(-((gx / 330) ** 2 + (gy / 520) ** 2)) - 0.02 * gy) > 340
        return 100 * float(((np.hypot(gxx, gyy) < 0.002) & inside).sum() / inside.sum())

    return {
        "plots": [
            "\\addplot[old,thick] coordinates {" + coords(true_line) + "};",
            "\\addplot[collect,thick] coordinates {" + coords(linear[row]) + "};",
            "\\addplot[storage,thick] coordinates {" + coords(smooth[row]) + "};",
        ],
        "macros": {
            "WEflatlinear": f"{flat_share(linear):.1f}",
            "WEflatsmooth": f"{flat_share(smooth):.1f}",
            "WElinpeak": f"{linear[row][mask].max():.1f}", "WEsmoothpeak": f"{smooth[row][mask].max():.1f}",
            "WEtruepeak": f"{true_line[mask].max():.1f}",
        },
    }


def kanker_macros() -> dict:
    body = json.dumps({
        "area": {"type": "Polygon", "coordinates": [[[81.4178, 20.2506], [81.4561, 20.2506], [81.4561, 20.2867], [81.4178, 20.2867], [81.4178, 20.2506]]]},
        "source": "copernicus", "rainfall_source": "chirps", "rainfall_period": "monsoon", "rainfall_year": 2025,
        "runoff_coefficient": RUNOFF_C, "stage_m": 2.5,
    }).encode()
    for base in ("http://127.0.0.1:8000", "http://10.1.75.53:3233"):
        try:
            request = urllib.request.Request(f"{base}/api/analyze-area", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            break
        except OSError:
            continue
    else:
        raise SystemExit("no planner reachable for the Kanker west example")
    site = result["recommendations"][0]
    (OUT / "kanker_site1.json").write_text(json.dumps({"rainfall": result["rainfall"], "site": site}, indent=1), encoding="utf-8")
    water, pond, catchment = site["water"], site["pond"], site["catchment"]
    write("kw_stage_plot.tex", [
        r"\addplot[storage,very thick,mark=*,mark size=1.6pt] coordinates {(0,0) "
        + " ".join(f"({row['stage_m']},{row['storage_m3']})" for row in pond["stage_curve"]) + "};",
        r"\addlegendentry{Pond storage $V_S(h)$}",
        rf"\addplot[runoff,very thick,dashed,domain=0:6.2] {{{water['potential_runoff_m3']:.0f}}};",
        r"\addlegendentry{June--September runoff $V_R$}",
        rf"\draw[collect,thick] (axis cs:{pond['stage_m']},0) -- (axis cs:{pond['stage_m']},{pond['screening_storage_m3']:.0f});",
    ])
    rain = result["rainfall"]
    return {
        "KWrain": fmt(rain["depth_mm"], 1),
        "KWcatchha": f"{catchment['area_hectares']:.2f}",
        "KWcatchm": fmt(catchment["area_hectares"] * 10_000),
        "KWrunoff": fmt(water["potential_runoff_m3"]),
        "KWstorage": fmt(pond["screening_storage_m3"]),
        "KWcollect": fmt(water["capturable_scenario_m3"]),
        "KWfill": f"{water['potential_runoff_m3'] / pond['screening_storage_m3']:.2f}",
        "KWfootprint": fmt(pond["footprint_m2"]),
        "KWcrest": f"{pond['crest_elevation_m']:.1f}" if "crest_elevation_m" in pond else "",
        "KWbund": fmt(pond.get("embankment_length_m", 0)),
        "KWmeandepth": f"{pond['screening_storage_m3'] / pond['footprint_m2']:.2f}",
    }


if __name__ == "__main__":
    main()
