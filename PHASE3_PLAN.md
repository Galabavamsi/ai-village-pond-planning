# Phase 3 plan — Village Pond Planning System

## Local implementation status (26 September 2026)

Implemented locally: one-origin FastAPI + React/MapLibre planner; selectable
polygon/rectangle; supplied, uploaded KML/KMZ, and Copernicus GLO-30 terrain
paths; area-restricted candidate selection; priority-flood and steepest-grade
D8 routing; mapped-water, roads and buildings screening where OSM is available;
CHIRPS v3 monthly or manual rainfall; stage-based screening storage;
desktop/mobile 2D overlays and an interactive Three.js elevation mesh. The
new upload route is `POST /api/terrain-upload`; the selected-area route is
`POST /api/analyze-area`; Phase 2 `POST /analyzeContour` is retained. Browser
and API tests analyze the supplied survey and an independent real GLO-30-derived
KML, select 3D sites, orbit the mesh and check mobile layout. See `README.md`.

Not yet done by request: remote deployment, final submission report in the
template, GitHub push, and public demo video. Land ownership/parcel status
remains unverified. Screening is not a field or engineering survey.

## Submission target

Deliver a working front-end URL, GitHub repository, final report in the supplied
Overleaf template (maximum 10 pages), and a public YouTube demo no longer than five
minutes. The site must let an administrator select land on a map, run an analysis,
and see pond location, catchment, and expected water volume overlaid on the map.
Host the application on the assigned IIT system, not a third-party deployment
service. The intended URL is `http://10.1.75.53:3233/` (inside the container,
Uvicorn listens on port 3000). Keep `/docs` and `/analyzeContour` functional.

## Remaining gaps

- Uploads are in single-process memory and expire after two hours; restart or
  multi-worker deployment requires re-upload. For a public service, replace
  this with durable, per-user storage and access control.
- Contour interpolation extrapolates outside the surveyed linework's convex
  hull. Do not rely on candidates in poorly covered areas without a denser
  elevation source. GLO-30, CHIRPS and OSM also have resolution/completeness
  limits documented in `README.md`.
- Land ownership, soil permeability, embankment design, site access and real
  field drainage must be checked outside the app. A verified parcel layer is
  needed before claiming government-land eligibility.
- Recheck campus LAN access and the assigned port when deploying. The old
  remote instance has not been updated with this local Phase 3 build.

## Build design

### 1. Data and analysis

Use three elevation inputs through one interface:

1. The supplied contour KML.
2. Arbitrary uploaded contour KML or KMZ with constant line elevation in a
   name, typed `ExtendedData`, or absolute coordinate altitude.
3. Copernicus DEM GLO-30 Cloud Optimized GeoTIFF for a drawn area, discovered
   through the Planetary Computer STAC catalog. An included independent
   DEM-derived contour KML provides an offline upload demo.

Project the analysis area to a local metre-based plane and use `rasterio` for
remote DEM reads.
Read an elevation buffer around the drawn polygon. Restrict pond candidates to
the selected polygon, while delineating their upstream catchments over the
larger DEM extent. Flag any catchment that touches the raster edge as truncated.
Condition the DEM (pits/depressions and flats), route D8 flow by downhill grade
(`elevation_drop / cell_distance`), accumulate upstream cells, and delineate
watersheds at candidate outlet cells. Use `pysheds` or WhiteboxTools if it runs
reliably on the IIT container; retain the existing NumPy path as a fallback.
Return candidate point, pond footprint, catchment polygon, area, elevation,
algorithm provenance, and quality warnings as GeoJSON and JSON.
Show uploaded contour lines as their real KML geometry; label the independent
demo file DEM-derived so it is not mistaken for a field survey.

For storage, derive a screening stage-area-volume curve from elevation cells in
the plausible impoundment footprint, with stage `h`:

`V_storage(h) = sum(max(0, h - z_i) * A_i)`

The stage and footprint assumptions must be visible. A 30 m digital surface
model includes vegetation and buildings, so its volume estimate must be
labelled approximate. Prefer higher-resolution uploaded contours or surveyed
terrain for site-level design.

### 2. Rainfall and water estimate

Use CHIRPS v3 monthly rainfall (0.05° grid) as the default historical rainfall
source. Cache the chosen area's monthly values and record product/version/date.
For month `t`, calculate potential runoff:

`V_runoff,t = (P_t_mm / 1000) * catchment_area_m2 * runoff_coefficient`

Show runoff potential separately from pond storage. For an illustrative filling
scenario, `V_captured,t = min(V_runoff,t, remaining_storage_m3)`. Expose the
runoff coefficient and rainfall period as scenario controls. Do not present the
result as a guaranteed yield or precise design volume; infiltration,
evaporation, demand and structures are not yet measured. CHIRPS 0.05° pixels
are wider than the sample map and cannot resolve rainfall differences between
adjacent pond candidates.

Government-land eligibility must be based on an uploaded/verified parcel layer
(GeoJSON or similar) or an authorized land-record source. Do not infer ownership
from satellite imagery or OSM land-use polygons. If no parcel layer is supplied,
display `land status: unverified`.

### 3. Front end

Build a React + TypeScript + Vite single-page app. Use MapLibre GL JS for the
map and Terra Draw for rectangle/polygon selection. The analysis view should
have: select area; optional contour/DEM upload; Analyze; progress/error state;
candidate markers; distinct pond and catchment overlays; and a side panel with
catchment area, rainfall scenario, runoff potential, estimated storage, and
data-quality warnings. Clicking a candidate focuses the map and its values.
Provide a neutral local map style so analysis overlays remain usable if an
external basemap tile service is unavailable during the campus demo.

The current 3D toggle opens a Three.js mesh from the same backend elevation
grid used for D8, with catchment, pond-stage and selected-site overlays.
Vertical relief is user-adjustable and visibly labelled exaggerated. 2D
MapLibre remains the location view. A stage-volume curve and verified parcel
overlay are possible later additions, not current features.

### 4. API and deployment

- Keep `POST /analyzeContour` and the required multipart name `contour_map`.
- Add `POST /api/analyze-area` accepting a drawn GeoJSON polygon and optional
  data-source settings. Validate polygon shape and analysis size.
- Optionally add `GET /api/demo` to load the sample-derived result instantly.
- Serve the built front-end from FastAPI `/` on internal port 3000; the IIT
  network maps it to external `http://10.1.75.53:3233/`.
- Cache source rasters and rainfall values by area/date to avoid repeated
  downloads and make the five-minute demonstration deterministic.
- Keep provider credentials in environment variables, never in the repo or
  front-end bundle.

## Order of work for a few-day deadline

1. **First: demonstrable vertical slice.** React map, polygon draw, call existing
   sample analysis, render point/catchment/pond overlays. Run it locally and
   confirm one complete user journey.
2. **Second: real area and rainfall.** Add DEM adapter, AOI-aware hydrology,
   CHIRPS values, computed volume and clear uncertainty labels. Pre-cache the
   sample area.
3. **Third: submission.** Deploy front end and backend together on IIT port
   mapping; verify browser and Postman requests from the campus network; finish
   report in the supplied template; record a <=5-minute public demo video.
4. **If time remains:** 3D terrain, richer constraints, Jev-assisted preference
   extraction and sensitivity analysis.

## Acceptance checks

- `http://10.1.75.53:3233/` opens the front end from the IIT network.
- Drawing a polygon and clicking Analyze produces visible pond point,
  catchment and pond-region overlays plus numeric area and water estimate.
- The sample KML works with multipart key `contour_map` and returns HTTP 200.
- A second polygon or uploaded map changes the results; no sample coordinates
  are hard-coded into the analysis.
- Results disclose source, spatial resolution, assumptions and warnings.
- Video shows the above flow; final report cites methods and stays within the
  template's 10-page limit.

## Jev and access decisions

Assumption: "Jev" means TypeSafe AI's Jev decision model. It accepts textual
state and typed questions and returns choice/score/boolean-like answers. Its
documentation warns against mathematical use. It could parse an administrator's
plain-language priorities (e.g. maximize storage versus minimize earthwork)
into typed preferences for a deterministic scoring function. It should not
calculate catchment area, rainfall or volume. It is not required for the core
demo, and no Jev key is needed to start.

The default Copernicus/CHIRPS data path does not require a user-supplied key
for the first implementation. An OpenTopography API key would be useful as a
backup DEM source, subject to its access limits. A verified government-land
parcel file and the exact Overleaf template link would improve the submission.

## Research sources

- [Copernicus GLO-30 on Planetary Computer](https://planetarycomputer.microsoft.com/dataset/cop-dem-glo-30)
- [Planetary Computer signed asset access](https://planetarycomputer.microsoft.com/docs/concepts/sas/)
- [OpenTopography developer API](https://opentopography.org/developers)
- [CHIRPS v3 description and access](https://www.chc.ucsb.edu/data/chirps3)
- [WhiteboxTools flow-routing manual](https://www.whiteboxgeo.com/manuals/qgis/hydrology-flow-routing.html)
- [pysheds repository](https://github.com/pysheds/pysheds)
- [MapLibre 3D terrain example](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/)
- [MapLibre Terra Draw example](https://maplibre.org/maplibre-gl-js/docs/examples/draw-geometries-with-terra-draw/)
- [TypeSafe Jev API quick start](https://docs.typesafe.ai/introduction/quickstart)
- [TypeSafe Jev math limitation](https://docs.typesafe.ai/model-jaggedness/jev-1.13#math-and-numbers)
- [India land records programme](https://dolr.gov.in/en/programmes-schemes/dilrmp/)
