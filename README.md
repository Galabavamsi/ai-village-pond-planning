# AI Village Pond Planning — Phase 3

An interactive pond-planning workspace built on the Phase 2 KML/KMZ API. Search
for any place or pick an example area, draw the land, and the planner finds
candidate pond outlets, their upstream catchments, the water an embankment
could hold, and the runoff a real rainfall record would deliver. It works on
the supplied contour map (Khapri, beside IIT Bhilai), on any uploaded KML/KMZ contour map,
and **anywhere on Earth between 60° S and 60° N** with Copernicus GLO-30
elevation, CHIRPS v3 rainfall and OpenStreetMap screening. Results appear on a
2D map (topographic, Sentinel-2 satellite or street basemap), on a tilted
**3D terrain / globe view**, and in a Three.js model of the exact analysis grid.
They can be exported to **Google Earth KML**, GeoJSON and contour KML.

This is a deterministic terrain-screening tool, not an engineering design or a
land-eligibility decision. No language model produces any number.

## Run locally

PowerShell from the repository root (Python 3.12 and Node.js 20+):

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
& .\.venv\Scripts\python.exe run.py
```

Open the [planning app](http://127.0.0.1:8000/) or the [interactive API
docs](http://127.0.0.1:8000/docs). The server binds to `127.0.0.1` by default
(`POND_HOST`/`POND_PORT` override it) and serves the built front end at the same
origin. Basemap tiles, 3D terrain tiles, place search, Copernicus DEM, CHIRPS
and Overpass need internet access. If mapped-feature screening fails, results
are labelled **unverified terrain candidates**, never silently "clear".

Quick demo:

1. Click **Analyze selected area** to use the supplied contours with the CHIRPS
   June–September 2025 monsoon total.
2. Open **Example areas with real terrain** (or type a village in the search
   box) to jump to another region; the planner switches to Copernicus GLO-30.
   Drawing outside a survey also switches automatically.
3. Toggle **Satellite** and **3D** in the map toolbar for an earth view; the
   globe button (top right) zooms out to the whole planet.
4. Compare the three ranked sites, read the stage–storage chart, open
   **Inspect 3D model** (try **Satellite drape**), and export KML/GeoJSON.
5. **Get contour KML** traces real contours for any selected area; the file
   opens in Google Earth and can be uploaded back as a contour survey.

To verify locally:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm run build
node scripts\smoke.mjs
node scripts\smoke-upload-3d.mjs
```

**Remote data cache.** DEM grids, CHIRPS values and Overpass responses are
stored under `cache/` (or `POND_CACHE_DIR`) and reused, because the IIT
container's outbound network drops DNS lookups and connections at random.
`python scripts/prewarm_cache.py` fills the cache for the example areas and the
default sample selection (monsoon, annual and August 2025 rainfall); copy
`cache/` to the server so the demo areas need no outbound access. Delete the
directory to refresh OSM data.

The browser smoke tests use an installed local Chrome and save desktop/mobile
screenshots under `output/screenshots/`. They draw a second area, upload both
the supplied and independent contour files, open and orbit the 3D mesh, change
sites and vertical exaggeration, and check for browser errors.
`node scripts\walkthrough.mjs` captures a tour of the newer features
(satellite, 3D terrain, example area, satellite drape, search) in `tmp/shots/`.

## Phase 3 API

`POST /api/analyze-area` accepts JSON:

```json
{
  "area": {"type":"Polygon","coordinates":[[[81.29,21.25],[81.30,21.25],[81.30,21.26],[81.29,21.26],[81.29,21.25]]]},
  "source": "sample",
  "rainfall_source": "chirps",
  "rainfall_period": "monsoon",
  "rainfall_year": 2025,
  "runoff_coefficient": 0.35,
  "stage_m": 2.5,
  "max_catchment_ha": 100
}
```

- `source`: `sample`, `upload` (with `dataset_id` from `/api/terrain-upload`)
  or `copernicus`.
- `rainfall_source`: `chirps` or `manual` (`rainfall_mm`). `rainfall_period`:
  `monsoon` (June–September of `rainfall_year`), `annual` (calendar year) or
  `month` (`rainfall_month`, `YYYY-MM`). Clients that send only
  `rainfall_month` keep the Phase 3 single-month behaviour. Only completed
  months are accepted; if CHIRPS cannot be read the manual value is used and
  labelled `manual-fallback`.
- `stage_m` (0.5–8 m) is the embankment height above the outlet ground.
- `max_catchment_ha` (5–5,000, default 100): drainage lines with a larger
  upstream area are treated as streams that need an engineered spillway, and
  are not offered as small-pond outlets.

The response contains ranked `recommendations` (point, pond polygon, catchment
polygon, storage, runoff, collectable volume, crest level, depth, indicative
embankment length, a `stage_curve` table and per-site `notes`), `rainfall`
with `monthly_mm`, `water_screening`, `parameters`, `limitations`,
`terrain_preview` (the downsampled analysis grid for 3D) and `contours`
(GeoJSON lines traced from the analysis grid).

Other routes: `POST /api/terrain-upload` (multipart `contour_map`, max 20 MB,
temporary in-process dataset), `GET /api/terrain/{dataset_id}/contours`,
`POST /api/export/contours.kml` (`area`, `source`, optional `dataset_id` and
`interval_m`; returns a KML download), `GET /api/config` (sample extent,
defaults and curated `examples`), `GET /api/sample-contours`, `GET /health`
and `/docs`. The Phase 2 route `POST /analyzeContour` (multipart
`contour_map`) and its `/findCatchment` alias are unchanged.

A contour line must carry a constant elevation through its placemark name
(e.g. `Contour 280 m`), an `ExtendedData` field named `elevation`, `elev`, `z`,
`height` or `level`, or constant absolute coordinate altitude. Uploads live in
process memory for two hours of inactivity (maximum eight datasets), so run
**one Uvicorn worker**.

## Phase 3 estimation method (algorithm `priority-flood-d8-impoundment-v4`)

1. **Area and elevation.** Validate the polygon (0.25–10,000 ha, at most 20 km
   across). Contour surveys are linearly interpolated to a grid
   (nearest-value outside the linework's hull). Elsewhere, Copernicus GLO-30
   tiles are read from the public AWS Open Data bucket (Microsoft Planetary
   Computer fills any gap) for the area plus a 30 % (≥ 1 km) buffer and
   resampled to ≤ 280 × 280 cells. OSM screening and CHIRPS are fetched in
   parallel with the DEM; every remote read is retried and cached (below).
2. **Routing.** Priority-flood fills sinks to the grid edge with a tiny
   gradient across flats; each cell drains to its steepest lower neighbour
   (D8, drop ÷ orthogonal or diagonal distance); contributing area is
   accumulated along that graph.
3. **Screening.** Overpass API features (water, wetlands, waterways, buildings,
   built-up land use, roads, railways) become exclusions with approximate
   setbacks: 40 m around water bodies, 25–45 m around waterways, 12 m around
   buildings and built-up land, and 4–35 m around roads by road class (a
   footpath is not treated like a highway). Cells draining more than
   `max_catchment_ha`, and their neighbours, are not outlets.
4. **Candidates.** Up to 40 outlets inside the selected land, each draining at
   least 1 ha and at least 200 m apart, are taken in order of contributing area.
5. **Impoundment.** For each outlet an embankment raises water to the crest
   `z_outlet + h`. Only cells that drain to the outlet (its catchment), are
   connected to it, lie below the crest, are on allowed land and are within
   `max(100 m, 4 cells)` are flooded:
   `V_storage = Σ (z_outlet + h − z_i) · A_cell`. Lower ground *outside* the
   catchment next to the pond is where water would escape; its edge length is
   the indicative embankment length. The same model gives the stage–storage
   table. (Phase 3.0 also counted cells downstream of the outlet, which a pond
   cannot hold; that over-estimated storage by 37–270 % on the sample.)
6. **Water and ranking.** `V_runoff = P_mm / 1000 × A_catchment × C`, with `P`
   from CHIRPS v3 at the area centroid (a 0.05° pixel) or a manual value.
   Collectable volume is `min(V_runoff, V_storage)` for one fill. Outlets are
   ranked by collectable volume, then storage per metre of embankment, then
   catchment area; the top three with non-overlapping ponds are returned.
   They are alternatives; their runoff is not additive.
7. **Display.** The browser receives a downsampled copy of the same grid for
   the Three.js model (vertical exaggeration auto-set to about 12 % of the map
   width and adjustable; it never changes the numbers) and contour lines traced
   from that grid. The MapLibre 3D view uses separate global terrain tiles
   for context only.

**Known limits.** GLO-30 is a ~30 m surface model (trees and buildings raise
it) and misses small channels and bunds; contour grids are interpolations; a
catchment reaching the grid edge is flagged as possibly truncated; CHIRPS is
coarse; OSM is incomplete; seepage, evaporation, siltation, soil, spillway and
earthwork design, protected status and land ownership are not modelled or
verified. The 3D pond is an illustrative water surface, not an excavation.

## Data sources, licences and attribution

| Data | Use | Licence / terms |
| --- | --- | --- |
| Copernicus DEM GLO-30 via [AWS Open Data](https://registry.opendata.aws/copernicus-dem/) (fallback: [Planetary Computer](https://planetarycomputer.microsoft.com/dataset/cop-dem-glo-30)) | Analysis elevation (surface model, heights above EGM2008), contour export | © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the EU and ESA |
| [CHIRPS v3](https://www.chc.ucsb.edu/data/chirps3) monthly COGs | Rainfall | CC BY 4.0; cite doi:10.15780/G2JQ0P |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) via [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) | Water/built-land screening | ODbL; public Overpass servers with fallback, fair use |
| [OpenTopoMap](https://opentopomap.org/about) | Topographic basemap | CC-BY-SA |
| [EOxCloudless 2025](https://cloudless.eox.at) | Satellite basemap and 3D drape | CC BY-NC-SA 4.0 (non-commercial/academic; commercial use needs a licence) |
| [OSM standard tiles](https://operations.osmfoundation.org/policies/tiles/) | Street basemap | OSMF tile usage policy |
| [Terrain Tiles on AWS](https://registry.opendata.aws/terrain-tiles/) | MapLibre 3D terrain and hillshade only | SRTM/GMTED2010 courtesy USGS, ETOPO1 courtesy NOAA |
| [Photon](https://photon.komoot.io) | Place search | OSM data; fair-use public server |

Esri World Imagery is intentionally **not** used: its terms require an ArcGIS
account or Esri software. The OSM editing API is not used for screening
because its policy reserves it for editing.

## Real contour and terrain data for other areas

**About the supplied sample.** `contour-maps/contours_1m.kml` covers Khapri
village farmland between the IIT Bhilai campus and the Shivnath river (only a
thin strip overlaps the campus, whose centre is about 81.318 E, 21.245 N). Its
structure matches exports from the free
[Contour Map Generator](https://map.contourmapgenerator.com), which traces
~30 m satellite elevation, so its 1 m interval is finer than the data's real
precision. Treat it as DEM-derived, not as a field survey.

**Verified example areas** (in the app under *Example areas with real terrain*;
contours in `contour-maps/real/`, regenerated with
`python scripts/create_copernicus_contour_demo.py`). Each was run end to end
with GLO-30, CHIRPS June–September 2025 and Overpass screening:

| Example | Where | GLO-30 relief | 2025 monsoon |
| --- | --- | --- | --- |
| Dongargarh–Khairagarh ridge | ~48 km W of IIT Bhilai | 338–632 m | 1,337 mm |
| Maikal ridge front (south of Bhoramdeo) | ~90 km N | 353–741 m | 1,141 mm |
| Kanker west | ~110 km S | 392–682 m | 1,287 mm |
| Sihawa, Mahanadi source | ~120 km SE | 426–550 m | 1,287 mm |
| Mainpat plateau | ~265 km NE | 1,026–1,120 m | 1,626 mm |
| Ralegan Siddhi / Hiware Bazar | Maharashtra | 611–876 m | 623–665 mm |
| Bheekampura johads (Alwar) | Rajasthan | 393–634 m | 1,130 mm |
| Sukhomajri | Haryana | 426–606 m | 1,538 mm |
| Abreha we Atsbeha | Tigray, Ethiopia | 1,926–2,539 m | 681 mm |

The rural Chhattisgarh boxes have sparse OpenStreetMap coverage, so screening
there removes few features; check the satellite basemap. Forest land and the
Bhoramdeo sanctuary are not screened.

**Any other area, in the app:** select it and click **Get contour KML**. Lines
are traced from Copernicus GLO-30 at a relief-based interval (2 m on the flat
Khapri plain, 10–20 m in the hills), carry elevation in the placemark name and
`ExtendedData`, are clamped to the ground in Google Earth, and can be uploaded
back into the planner.

**Better or official sources for a real project:**

- [Survey of India Online Maps Portal](https://onlinemaps.surveyofindia.gov.in):
  1:50,000 Open Series Maps are free GeoPDF rasters with a 20 m contour
  interval (registration by mobile OTP); they need digitising. Vector topo
  sheets (SHP/GDB) and the 1:50,000 DTM are sold per sheet
  ([pricing](https://onlinemaps.surveyofindia.gov.in/PricingPolicy.aspx)) and
  are free for registered government users.
- [ISRO Bhuvan CartoDEM v3 R1](https://bhuvan-app3.nrsc.gov.in/data/download/index.php):
  ~30 m surface-model GeoTIFF, login required.
- [OpenTopography API](https://portal.opentopography.org/apidocs/): free API
  key (academic keys allow 200 calls a day); COP30, NASADEM, AW3D30, SRTMGL1
  and bare-earth GEDTM30 as GeoTIFF. FABDEM is not offered there.
- [FABDEM](https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn):
  bare-earth 30 m (trees and buildings removed), University of Bristol,
  CC BY-NC-SA 4.0.
- [OpenDEM](https://www.opendem.info/download_contours.html): SRTM-based
  25 m contour shapefiles (ODbL).
- Convert any DEM to KML contours with
  `gdal_contour -f KML -i 5 -a elevation dem.tif contours.kml`; the
  `elevation` attribute is read by this planner.
- For site design, a village DGPS or drone survey exported as contour KML is
  far better than any 30 m model.

**Planning norms used as benchmarks:** Mission Amrit Sarovar phase 2 (MoRD,
2024): plains ponds of at least 1 acre and about 10,000 m³ (hilly areas
0.25 acre, 2,500 m³). MGNREGA model farm pond (MoRD circular, 2016): 20 × 20 m
top, 3 m deep, ≈ 880 m³, 0.5–1 ha catchment where annual rain ≥ 1,000 mm.
Runoff presets follow the ranges in the CGWB
[Manual on Artificial Recharge](https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1679997242339591060file.pdf).
For comparison, IMD 1991–2020 normals for Raipur give about 1,145 mm for
June–September.

## Phase 2 API and prior submission

## Planned IIT Bhilai local-network evaluation (not deployed now)

The evaluator-facing URL is:
<http://10.1.75.53:3233/docs>

The upload route is:
<http://10.1.75.53:3233/analyzeContour>

This is the assigned Application 1 port mapping. It is **not the current local
app URL**; deploy and verify it from the IIT Bhilai network at submission time.

## Analyze the supplied sample

```powershell
curl.exe -X POST "http://127.0.0.1:8000/analyzeContour?grid_size=100&max_candidates=3" `
  -F "contour_map=@contour-maps/contours_1m.kml"
```

The same route accepts `.kmz` files and extracts the first `doc.kml` (or first KML member) from the archive. `/findCatchment` is provided as a compatibility alias.

## Approach

1. Parse contour elevations from KML placemark names or supported `ExtendedData` fields.
2. Convert WGS84 coordinates to a local metre-based projection centered on the input extent.
3. Interpolate contour observations into a regular elevation grid.
4. Route each grid cell to its steepest lower neighbor using D8 flow routing.
5. Accumulate contributing cell areas and rank interior cells with high accumulated flow.
6. Convert each selected cell and its upstream cells into GeoJSON geometries in the original WGS84 coordinate system.

This is deliberately terrain-only for phase 2. Rainfall, land ownership, soil, satellite imagery, and field validation can be added as independent layers in later phases.

## Formulas and algorithm details

Let the input KML longitude/latitude be (lambda, phi) in radians and let (lambda0, phi0) be the center of the input extent. The service uses a local equirectangular metric approximation:

~~~text
x = R * cos(phi0) * (lambda - lambda0)
y = R * (phi - phi0)
~~~

where R = 6,371,000 m. If the grid spacing is dx by dy, one cell represents:

~~~text
A_cell = abs(dx * dy) square metres
~~~

For every grid cell i, the D8 neighbourhood N8(i) contains up to eight adjacent cells. The flow target is the strictly lower neighbour with maximum downhill grade:

~~~text
f(i) = argmax[(z(i)-z(n))/distance(i,n)] for n in N8(i), where z(n) < z(i)
~~~

If no lower neighbour exists, the cell is treated as a local sink. Flow accumulation is calculated from high cells toward lower cells:

~~~text
A(i) = A_cell + sum(A(k)) for every upstream cell k where f(k) = i
~~~

For a selected pond cell p, the catchment is the union of all cells that eventually route to p:

~~~text
C(p) = union of all upstream cells of p
catchment_area_m2 = geometric_area(C(p))
catchment_area_hectares = catchment_area_m2 / 10,000
~~~

Candidate cells exclude the outer boundary, must have accumulation at or above the 85th percentile of eligible cells, and are ranked by descending accumulation followed by lower elevation. Candidates are spatially separated so the response contains distinct regions.

The current phase uses a conservative planning approximation for pond storage:

~~~text
pond_depth_m = clamp(2.5 * contour_interval_m, 1, 8)
storage_m3 = 0.75 * pond_footprint_area_m2 * pond_depth_m
~~~

The factor 0.75 represents a conservative effective-volume factor. It is not a substitute for a detailed stage-area-volume survey. In a later rainfall phase, runoff volume can be estimated using:

~~~text
runoff_volume_m3 = rainfall_m * catchment_area_m2 * runoff_coefficient
~~~

This formula requires rainfall in metres and a locally justified runoff coefficient.

## Build the submission report

The submitted PDF is generated from the LaTeX source at
`latex/phase2_report.tex`. It contains the equations as rendered mathematical
displays, the algorithm summary, API documentation, deployment notes, Swagger
screenshots, and clearly marked conceptual illustrations.

From the repository root on Windows:

```powershell
New-Item -ItemType Directory -Force tmp\latex-build | Out-Null
pdflatex -interaction=nonstopmode -halt-on-error `
  -output-directory tmp\latex-build latex\phase2_report.tex
pdflatex -interaction=nonstopmode -halt-on-error `
  -output-directory tmp\latex-build latex\phase2_report.tex
Copy-Item -Force tmp\latex-build\phase2_report.pdf `
  output\pdf\AI_Village_Pond_Planning_Phase_2_Report.pdf
```

The report's generated image assets are stored in `output/imagegen/`.

## API summary

`POST /analyzeContour`

- Multipart field: `contour_map` — `.kml` or `.kmz` contour map required for evaluation.
- Compatibility field: `file` — accepted for older clients.
- Query: `grid_size` (40–220, default 100), `max_candidates` (1–5, default 3).
- Success: JSON containing input statistics, grid metadata, and ranked `recommendations`.
- Each recommendation includes a WGS84 `location`, `pond_region`, elevation, estimated pond depth/storage, and a catchment `geometry` with area in square metres/hectares.

Errors use standard HTTP status codes: 415 for unsupported extensions, 413 for files over 75 MB, 400 for empty uploads, and 422 for invalid/unusable contour maps.

## Remote deployment with tmux

After pushing this repository to GitHub and cloning it on the remote host:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend
npm ci && npm run build
cd ..
tmux new -s pond-api
uvicorn app.main:app --host 0.0.0.0 --port 3000
```

Detach with `Ctrl-b`, then `d`; reattach with `tmux attach -t pond-api`. The
IIT system maps internal port 3000 to assigned external port 3233 derived
from SSH port 2233. Re-test both the app root and `/docs` from the campus
network after deployment; the remote URL is not claimed to be live now.
Do not commit SSH credentials, tokens, or private connection details.
