# Phase 2 Report — AI-based Village Pond Planning System

## GitHub repository

**https://github.com/Galabavamsi/ai-village-pond-planning**

The submitted PDF is generated from \`latex/phase2_report.tex\`; its equations
are rendered as LaTeX mathematics and its conceptual visuals are stored in
\`output/imagegen/\`.

## Working API route

Local development route: `POST http://127.0.0.1:8000/analyzeContour`

Remote host route: `POST http://10.1.75.53:3233/analyzeContour`

SSH-tunnel route from the developer PC: `POST http://127.0.0.1:18000/analyzeContour`

Public evaluator route: `POST https://reaching-combine-latest-claire.trycloudflare.com/analyzeContour`

Public Swagger documentation: **https://reaching-combine-latest-claire.trycloudflare.com/docs**

This is a Cloudflare Quick Tunnel for evaluation. It remains available while the remote `cf-pond` tmux process and its outbound connection remain alive; the hostname changes if the tunnel is restarted, and Quick Tunnels have no uptime guarantee.
The route accepts a KML/KMZ file in a multipart field named `file`. Interactive documentation is generated at `/docs`.

## Catchment estimation approach

The service extracts contour geometry and elevation from the uploaded input. It creates a local metric elevation grid by interpolating contour observations, routes flow from each cell to the steepest downhill neighbor, and accumulates upstream cell area. Interior cells with high contributing area and low-point preference are ranked as pond candidates. The candidate's upstream cells are merged into a GeoJSON catchment polygon/multipolygon, and the API reports its area in square metres and hectares.

No coordinate, location, or result is hard-coded for the supplied sample. The parser supports both KML and KMZ and recognizes elevation in placemark names plus common ExtendedData field names.

## Formulas and algorithm details

The input WGS84 longitude/latitude is converted to local metres around the input center using an equirectangular approximation:

~~~text
x = R cos(phi0) (lambda - lambda0)
y = R (phi - phi0)
~~~

where R = 6,371,000 m. Grid-cell area is A_cell = abs(dx * dy). For each cell, D8 routing selects the lowest strictly lower neighbour:

~~~text
f(i) = argmin z(n), n in N8(i), z(n) < z(i)
~~~

Flow accumulation is:

~~~text
A(i) = A_cell + sum A(k), for all upstream k where f(k) = i
~~~

The selected catchment is the union of all cells that eventually flow to the pond cell. Its reported area is catchment_area_m2 = geometric_area(catchment) and catchment_area_hectares = catchment_area_m2 / 10,000. Candidate cells are interior cells with accumulation at or above the 85th percentile; they are ranked by descending accumulation and then elevation, with spatial separation between returned candidates.

For this phase, pond storage is a conservative approximation:

~~~text
pond_depth_m = clamp(2.5 * contour_interval_m, 1, 8)
storage_m3 = 0.75 * pond_footprint_area_m2 * pond_depth_m
~~~

The future rainfall extension can use runoff_volume_m3 = rainfall_m * catchment_area_m2 * runoff_coefficient. The current storage value is for screening only and must be replaced by a detailed stage-area-volume design before construction.

## Demonstration using the supplied contour map

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour?grid_size=100&max_candidates=3" \
  -F "file=@contour-maps/contours_1m.kml"
```

The JSON response includes:

- contour feature count, elevation range, and contour interval;
- terrain-grid dimensions and cell area;
- ranked pond locations and GeoJSON pond regions;
- estimated pond depth and storage;
- catchment area and GeoJSON catchment geometry.

Local demonstration result using `grid_size=70&max_candidates=2`: the service detected 2,710 contour features, an elevation range of 267–298 m, and a 1 m contour interval. It returned two candidates; the first was at `[81.2899372847, 21.2499875606]`, elevation 267 m, with an estimated 16.0327 ha catchment and 4,233.98 m³ conservative storage estimate. These are observed outputs for the supplied sample, not values embedded in the implementation.

## Limitations and next phase

This phase estimates terrain-only catchments. Rainfall intensity, runoff coefficient, soil infiltration, government land, satellite imagery, hydraulic outlet design, and field survey validation are intentionally excluded and should be added as separate data/analysis layers in later phases.
