# Phase 2 Report — AI-based Village Pond Planning System

## GitHub repository

**https://github.com/Galabavamsi/ai-village-pond-planning**

## Working API route

Local development route: `POST http://127.0.0.1:8000/analyzeContour`

Remote host route: `POST http://10.1.75.53:8000/analyzeContour`

SSH-tunnel route from the developer PC: `POST http://127.0.0.1:18000/analyzeContour`

Public reverse-proxy URL: **`<deployed public API URL>/analyzeContour`**

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

Local demonstration result using `grid_size=70&max_candidates=2`: the service detected 2,710 contour features, an elevation range of 267–298 m, and a 1 m contour interval. It returned two candidates; the first was at `[81.2899372847, 21.2499875606]`, elevation 267 m, with an estimated 16.0327 ha catchment and 4,233.98 m³ conservative storage estimate. These are observed outputs for the supplied sample, not values embedded in the implementation.

## Limitations and next phase

This phase estimates terrain-only catchments. Rainfall intensity, runoff coefficient, soil infiltration, government land, satellite imagery, hydraulic outlet design, and field survey validation are intentionally excluded and should be added as separate data/analysis layers in later phases.
