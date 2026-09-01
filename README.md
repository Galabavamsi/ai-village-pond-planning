# AI Village Pond Planning — Phase 2

Backend API for deriving pond-site and catchment recommendations from an uploaded contour map.

## Run locally

PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
```

The interactive API documentation is available at <http://127.0.0.1:8000/docs>.

Current public evaluation URL (temporary Cloudflare Quick Tunnel):
<https://rate-unable-zope-gcc.trycloudflare.com/docs>

The upload route is:
<https://rate-unable-zope-gcc.trycloudflare.com/analyzeContour>

The public URL remains available while the remote `cf-pond2` tmux tunnel is running. A restart creates a new random hostname.

## Analyze the supplied sample

```powershell
curl.exe -X POST "http://127.0.0.1:8000/analyzeContour?grid_size=100&max_candidates=3" `
  -F "file=@contour-maps/contours_1m.kml"
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

For every grid cell i, the D8 neighbourhood N8(i) contains up to eight adjacent cells. The flow target is the lowest strictly lower neighbour:

~~~text
f(i) = argmin[z(n)] for n in N8(i), where z(n) < z(i)
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
\`latex/phase2_report.tex\`. It contains the equations as rendered mathematical
displays, the algorithm summary, API documentation, deployment notes, Swagger
screenshots, and clearly marked conceptual illustrations.

From the repository root on Windows:

\`\`\`powershell
New-Item -ItemType Directory -Force tmp\latex-build | Out-Null
pdflatex -interaction=nonstopmode -halt-on-error \`
  -output-directory tmp\latex-build latex\phase2_report.tex
pdflatex -interaction=nonstopmode -halt-on-error \`
  -output-directory tmp\latex-build latex\phase2_report.tex
Copy-Item -Force tmp\latex-build\phase2_report.pdf \`
  output\pdf\AI_Village_Pond_Planning_Phase_2_Report.pdf
\`\`\`

The report's generated image assets are stored in \`output/imagegen/\`.

## API summary

`POST /analyzeContour`

- Multipart field: `file` — required `.kml` or `.kmz` contour map.
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
tmux new -s pond-api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Detach with `Ctrl-b`, then `d`; reattach with `tmux attach -t pond-api`. The current evaluation setup uses a Cloudflare Quick Tunnel in a separate `cf-pond2` tmux session. Put a named tunnel or reverse proxy in front of port 8000 for a stable production URL. Do not commit SSH credentials, tokens, or private connection details.
