# Village Pond Planner — Phase 3 handover

Status checked on **27 September 2026** in `D:\ai village planning`
(supersedes the 26 September handover).

## What works now

The planner is **live on the IIT network at <http://10.1.75.53:3233/>** (API docs
at `/docs`; see "Git and deployment state"). Locally it runs at
<http://127.0.0.1:8000/>, which is **not** an evaluator-facing URL.

A user can search for a place or pick a curated example area, draw a polygon
or rectangle, and analyze it with the supplied Khapri contour map (next to IIT Bhilai), an
uploaded KML/KMZ contour map, or Copernicus GLO-30 anywhere between 60° S and
60° N. Rainfall is a CHIRPS v3 June–September season, calendar year or single
month, or a manual value. The app ranks three alternative pond outlets by
illustrative collectable volume and shows each catchment, pond, stage–storage
curve, indicative embankment length and warnings. Maps: topographic,
Sentinel-2 satellite or street basemap, labelled contours, MapLibre 3D terrain
and globe view, plus a Three.js model of the analysis grid with an optional
satellite drape. Exports: Google Earth KML, GeoJSON and contour KML (the last
for any selected area, re-uploadable).

This is a deterministic screening tool, **not** an engineering design or a
verified government-land decision. No LLM produces numbers.

## Review of the 26 September build: defects fixed

| Area | Defect found | Fix |
| --- | --- | --- |
| Pond storage | Pond cells spread downstream/laterally outside the outlet's own catchment; storage was inflated 37–270 % on the sample (site 2: 51,368 m³ reported vs 13,811 m³ physically upstream). | Impoundment model: only catchment cells below the crest are stored; lower ground outside the catchment gives the embankment length (`app/hydrology.py`). |
| Ranking | Sites were the cells just under an arbitrary 98th-percentile "channel" cutoff (all three ≈ 32–36 ha on the sample, ≈ 72 ha at Dongargarh); storage never affected rank. | 40 separated outlets are evaluated and ranked by min(runoff, storage), then storage per metre of bund. Streams above `max_catchment_ha` (default 100 ha) are excluded as small-pond outlets. |
| OSM screening | Used the OSM *editing* API, whose policy forbids read-only use, and it failed ("unavailable") for larger areas (e.g. 14 × 12 km Bhilai–Durg). A flat 35 m buffer around every footpath removed village land. | Overpass API with three servers; a partial or timed-out answer is treated as failure; buffers by road class (4–35 m); wetlands and `water=*` added. The big area now screens 249 water + 15,361 built features. |
| Rainfall | One month (Aug 2025) was used as if it were the planning rainfall. | Monsoon (Jun–Sep) and annual CHIRPS totals, fetched in parallel, with a monthly chart. |
| Performance | DEM, OSM and CHIRPS were fetched in sequence (12.9 s for Dongargarh); Phase 2 `/analyzeContour` ran CPU work on the event loop. | Network lookups run in parallel and Copernicus grids are cached (6.3 s cold, 0.3 s repeat); Phase 2 route uses the thread pool. |
| Map | Switching terrain source destroyed and rebuilt the map, so the drawn selection vanished while the panel still said "Area selected". | Map created once; layers updated in place. |
| Usability | No way to reach another area except panning; drawing outside the survey just errored. | Place search (Photon), curated examples, automatic switch to Copernicus, live area/size readout with client-side validation. |
| 3D | Fixed 15× exaggeration made flat plains spike; skirt dominated at high exaggeration. | Auto exaggeration (~12 % of width), hypsometric ramp, thin skirt, draped contours, selection outline, numbered outlets, satellite drape. |
| Accessibility | ~30 grey text colours below WCAG AA (e.g. `#99a5a9` ≈ 2.6:1); 8–9 px text. | Darkened to ≥ 4.5:1; minimum text size raised. |
| Sample provenance | The sample was described as an IIT Bhilai survey. It actually covers Khapri farmland west of the campus (≈ 3.5 % overlap; campus centre ≈ 81.318 E, 21.245 N), and its structure matches a Contour Map Generator export traced from ~30 m satellite elevation, so the 1 m interval is false precision. | Relabelled everywhere; the limitation is shown in results and the README. Say this in the report. |
| Runoff presets | Presets had no source and were high for bunded paddy (0.30–0.40). | Presets follow CGWB manual ranges (paddy 0.20, hilly 0.35, …); results also compare each pond with Mission Amrit Sarovar (≥ 1 acre, ~10,000 m³) and MGNREGA farm-pond (≈ 880 m³) norms. |
| Misc | "Local" badge hard-coded; `contourpy` missing; broken backticks in README; unbounded Phase 2 upload read; exception text echoed to clients. | Fixed. |

## Important code and artifacts

| Path | Purpose |
| --- | --- |
| `app/main.py` | Routes and request models (`/api/analyze-area`, `/api/export/contours.kml`, uploads, config). |
| `app/planning.py` | AOI validation, grid sources, Copernicus cache, ranking and response assembly. |
| `app/hydrology.py` | Upstream index, impoundment, candidate pool, stage–storage table. |
| `app/contours.py` | Contour tracing (GeoJSON for maps, KML export). |
| `app/rainfall.py` | CHIRPS v3 month/season/year totals. |
| `app/osm.py` | Overpass screening and tag classification. |
| `app/examples.py` | Curated example areas (UI convenience only). |
| `frontend/src/App.tsx`, `MapCanvas.tsx`, `ResultsPanel.tsx`, `StageChart.tsx`, `PlaceSearch.tsx`, `TerrainInspector.tsx`, `exporters.ts`, `basemaps.ts` | Front end. |
| `contour-maps/real/` | GLO-30 contour KMLs for the 10 verified example areas (`scripts/create_copernicus_contour_demo.py`): Dongargarh–Khairagarh ridge (~48 km W), Maikal ridge front, Kanker west, Sihawa, Mainpat, Ralegan Siddhi, Hiware Bazar, Alwar johads, Sukhomajri and Abreha we Atsbeha (Ethiopia). A test uploads and analyzes every file. |
| `tests/test_hydrology.py` | New regression tests (pond ⊆ catchment, ranking, stage curve, Overpass parser, export round trip, rainfall periods). |

## Run and verify locally

```powershell
Set-Location frontend
npm run build
node scripts\smoke.mjs
node scripts\smoke-upload-3d.mjs
node scripts\walkthrough.mjs   # optional visual tour -> tmp\shots
Set-Location ..
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe run.py
```

At this handover: 32 backend tests, the production build, both smoke scripts
(desktop + mobile) and the walkthrough passed with no browser errors. The venv
was created with `uv` and has no pip; use
`uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.

## Git and deployment state

- GitHub `master` is up to date with this work (commits `af86e61` onward).
- **Deployed and verified on 28 September 2026** at <http://10.1.75.53:3233/>
  (`/docs`, `/analyzeContour`) on sys1, SSH port 2233, in tmux session
  `pond-app` running `scripts/run_server.sh` (internal port 3000, logs in
  `~/ai-village-pond-planning/logs/app.log`). All 32 tests pass on the server;
  the browser walkthrough and upload/3D smoke suites pass against the live URL
  (`POND_URL=http://10.1.75.53:3233/ node scripts/walkthrough.mjs`).
- sys1 was cleaned at the user's request: the graded lab6 load balancer and all
  old lab/Phase 2 files and tool caches were removed.
- **Network caveats found during deployment:**
  - The container's DNS (1.1.1.1/8.8.8.8) drops lookups at random, taking
    ~20 s per failure. The app keeps the last good answers and retries remote
    reads.
  - Example areas are pre-cached in `cache/`, so they need no outbound
    access.
  - A new area takes about 3–25 s on the server.
  - From campus Wi-Fi (10.50.x) about half of new TCP connections to
    10.1.75.53 are dropped. From inside the server network they all succeed.
    The front end retries API calls; if the first page load fails, refresh.
    Use wired LAN for the demo video if possible.
- The server has no Node and no reliable PyPI access; see README "Remote
  deployment with tmux" for the offline wheelhouse procedure.

## Remaining submission work

1. Phase 3 report: **drafted** at
   `output/pdf/AI_Village_Pond_Planning_Phase_3_Report.pdf` (24 pages, source
   `latex/phase3_report.tex`, live screenshots, AI-use disclosure in
   Section 12). Before submitting:
   - add team names and roll numbers;
   - confirm or extend the AI-use disclosure for any tools used before
     27 September;
   - if the template's 10-page limit applies, move Sections 2–13 into the
     template and cut or shorten the appendices and figures.
2. Public demo video (≤ 5 minutes): example area → analyze → satellite/3D →
   compare sites → export KML to Google Earth; explain why numbers are
   screening estimates.

**Known limits to disclose:** contour interpolation/extrapolation; GLO-30 is a
30 m surface model; catchments may be truncated at the grid edge (flagged);
coarse CHIRPS; incomplete OSM; no seepage, evaporation, siltation, spillway or
earthwork design; no verified parcel, soil or ownership data. EOxCloudless
imagery is licensed for non-commercial use only.
