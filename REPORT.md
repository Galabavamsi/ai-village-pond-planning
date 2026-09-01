# Phase 2 Report — AI-based Village Pond Planning System

## GitHub repository

To be filled after the repository is created and pushed: **`<GitHub repository URL>`**

## Working API route

Local development route: `POST http://127.0.0.1:8000/analyzeContour`

Remote deployment URL: **`<deployed API URL>/analyzeContour`**

The route accepts a KML/KMZ file in a multipart field named `file`. Interactive documentation is generated at `/docs`.

## Catchment estimation approach

The service extracts contour geometry and elevation from the uploaded input. It creates a local metric elevation grid by interpolating contour observations, routes flow from each cell to the steepest downhill neighbor, and accumulates upstream cell area. Interior cells with high contributing area and low-point preference are ranked as pond candidates. The candidate's upstream cells are merged into a GeoJSON catchment polygon/multipolygon, and the API reports its area in square metres and hectares.

No coordinate, location, or result is hard-coded for the supplied sample. The parser supports both KML and KMZ and recognizes elevation in placemark names plus common ExtendedData field names.

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

The sample response is generated during testing and should be copied into the final submission after the deployed endpoint is available.

## Limitations and next phase

This phase estimates terrain-only catchments. Rainfall intensity, runoff coefficient, soil infiltration, government land, satellite imagery, hydraulic outlet design, and field survey validation are intentionally excluded and should be added as separate data/analysis layers in later phases.

