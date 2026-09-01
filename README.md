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

Detach with `Ctrl-b`, then `d`; reattach with `tmux attach -t pond-api`. Put a reverse proxy or tunnel in front of port 8000 to obtain the public working API URL. Do not commit SSH credentials, tokens, or private connection details.

