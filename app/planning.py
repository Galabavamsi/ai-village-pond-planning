"""Area-based pond screening for Phase 3.

All areas and volumes are estimates from gridded elevation, not construction designs.
The selected polygon restricts *outlets* and pond footprints; upstream terrain
may extend beyond it.
"""

from __future__ import annotations

import heapq
import io
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation
from shapely import contains_xy
from shapely.geometry import LineString, Point, Polygon, box, shape

from .cache import cache_key, read_bytes, retry, write_bytes
from .contours import COPERNICUS_ATTRIBUTION, contours_geojson, contours_kml
from .hydrology import UpstreamIndex, candidate_pool, impoundment, stage_curve
from .osm import OSM_SOURCE_URL, water_screening
from .rainfall import CHIRPS_CITATION, PERIOD_LABELS, chirps_month, chirps_total, period_months, validate_months
from .terrain import (
    NS,
    AnalysisError,
    _cells_geometry,
    _elevation_for_placemark,
    _flow_graph,
    _geojson_geometry,
    _geojson_point,
    _grid_from_contours,
    _kml_bytes,
    _local_xy,
    _parse_coordinates,
    parse_contours,
)
from .upload_store import get_upload, save_upload


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "contour-maps" / "contours_1m.kml"
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
ALGORITHM_VERSION = "priority-flood-d8-impoundment-v4"
DEFAULT_MAX_CATCHMENT_HA = 100.0
STAGE_TABLE_M = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
# Kept for callers of the Phase 3 prototype.
_chirps_at = chirps_month


@dataclass
class ElevationGrid:
    gx: np.ndarray  # local metres, west to east
    gy: np.ndarray  # local metres, south to north
    z: np.ndarray
    lon0: float
    lat0: float
    name: str
    nominal_resolution_m: float
    notes: list[str]


@lru_cache(maxsize=1)
def sample_grid() -> ElevationGrid:
    contours = parse_contours(SAMPLE.read_bytes(), SAMPLE.name)
    xx, yy, dem, lon0, lat0 = _grid_from_contours(contours, 125)
    return ElevationGrid(
        xx[0, :], yy[:, 0], dem, lon0, lat0,
        "Supplied contours, Khapri near IIT Bhilai (1 m interval)",
        float(np.median(np.diff(xx[0, :]))),
        ["Elevation between the supplied contours is linearly interpolated; the grid is not a measured DEM.",
         "The supplied KML has the structure of a Contour Map Generator export, which traces ~30 m satellite "
         "elevation; its 1 m interval is finer than that source's real precision, so treat it as DEM-derived."],
    )


def grid_bounds(grid: ElevationGrid) -> list[float]:
    sw = _geojson_point(float(grid.gx[0]), float(grid.gy[0]), grid.lon0, grid.lat0)
    ne = _geojson_point(float(grid.gx[-1]), float(grid.gy[-1]), grid.lon0, grid.lat0)
    return [sw[0], sw[1], ne[0], ne[1]]


def sample_bounds() -> list[float]:
    return grid_bounds(sample_grid())


def contour_lines_geojson(payload: bytes, filename: str, max_features: int = 1600) -> dict:
    """Simplified display lines from the uploaded map, not invented contours."""
    root = ET.fromstring(_kml_bytes(payload, filename))
    lines = []
    for placemark in root.findall(".//k:Placemark", NS):
        for line_node in placemark.findall(".//k:LineString", NS):
            level = _elevation_for_placemark(placemark, line_node)
            if level is None:
                continue
            points = _parse_coordinates(line_node.findtext("k:coordinates", namespaces=NS))
            if len(points) >= 2:
                lines.append((level, points))
    step = max(1, math.ceil(len(lines) / max_features))
    levels = sorted({level for level, _ in lines})
    interval = float(np.median(np.diff(levels))) if len(levels) > 1 else 1.0
    features = []
    for level, points in lines[::step]:
        line = LineString(points).simplify(0.00002, preserve_topology=False)
        if len(line.coords) < 2:
            continue
        major = interval > 0 and abs(level / (interval * 5) - round(level / (interval * 5))) < 1e-6
        features.append({
            "type": "Feature", "properties": {"elevation_m": level, "major": bool(major)},
            "geometry": {"type": "LineString", "coordinates": list(line.coords)},
        })
    return {"type": "FeatureCollection", "interval_m": interval, "features": features}


@lru_cache(maxsize=1)
def sample_contours_geojson() -> dict:
    return contour_lines_geojson(SAMPLE.read_bytes(), SAMPLE.name)


def register_uploaded_contours(payload: bytes, filename: str) -> dict:
    contours = parse_contours(payload, filename)
    lon, lat = contours.points[:, 0], contours.points[:, 1]
    lon0, lat0 = float(lon.mean()), float(lat.mean())
    px, py = _local_xy(lon, lat, lon0, lat0)
    span = max(float(np.ptp(px)), float(np.ptp(py)))
    if span > 20_000:
        raise AnalysisError("Uploaded contours span more than 20 km; split the survey into smaller maps")
    requested_size = min(220, max(100, math.ceil(span / 25)))
    xx, yy, dem, lon0, lat0 = _grid_from_contours(contours, requested_size)
    grid = ElevationGrid(
        xx[0, :], yy[:, 0], dem, lon0, lat0,
        f"Uploaded contours · {filename}",
        float(np.median(np.diff(xx[0, :]))),
        ["Elevation between uploaded contour lines is interpolated. Areas outside their convex hull use nearest-value extrapolation."],
    )
    item = save_upload(
        filename=filename, grid=grid, bounds=grid_bounds(grid),
        contour_geojson=contour_lines_geojson(payload, filename),
        contour_features=contours.features,
        elevation_min_m=float(min(contours.elevations)),
        elevation_max_m=float(max(contours.elevations)),
    )
    return {
        "dataset_id": item.dataset_id, "filename": filename, "bounds": item.bounds,
        "contour_features": item.contour_features,
        "elevation_min_m": round(item.elevation_min_m, 2),
        "elevation_max_m": round(item.elevation_max_m, 2),
        "analysis_cell_m": round(grid.nominal_resolution_m, 1),
        "contour_url": f"/api/terrain/{item.dataset_id}/contours",
        "expires_in_seconds": 7200,
    }


def uploaded_contours_geojson(dataset_id: str) -> dict:
    item = get_upload(dataset_id)
    if item is None:
        raise AnalysisError("Uploaded terrain is unavailable or expired; upload the file again")
    return item.contour_geojson


def terrain_preview(grid: ElevationGrid, max_dimension: int = 120) -> dict:
    rows, cols = grid.z.shape
    row_indices = np.unique(np.rint(np.linspace(0, rows - 1, min(rows, max_dimension))).astype(int))
    col_indices = np.unique(np.rint(np.linspace(0, cols - 1, min(cols, max_dimension))).astype(int))
    values = grid.z[np.ix_(row_indices, col_indices)]
    return {
        "rows": len(row_indices), "columns": len(col_indices),
        "x_m": np.round(grid.gx[col_indices], 2).tolist(),
        "y_m": np.round(grid.gy[row_indices], 2).tolist(),
        "elevation_m": np.round(values, 2).ravel().tolist(),
        "origin_lon": grid.lon0, "origin_lat": grid.lat0,
        "minimum_m": round(float(np.min(values)), 2),
        "maximum_m": round(float(np.max(values)), 2),
        "source": grid.name,
    }


def _metric_polygon(polygon: Polygon, lon0: float, lat0: float) -> Polygon:
    xx, yy = _local_xy(
        np.array([point[0] for point in polygon.exterior.coords]),
        np.array([point[1] for point in polygon.exterior.coords]),
        lon0, lat0,
    )
    return Polygon(zip(xx, yy))


def validate_area(geometry: dict) -> Polygon:
    try:
        polygon = shape(geometry)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise AnalysisError("Area must be a GeoJSON Polygon") from exc
    if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid:
        raise AnalysisError("Draw a valid, non-self-intersecting polygon")
    if len(polygon.exterior.coords) > 1000 or len(polygon.interiors) > 0:
        raise AnalysisError("Use a simple polygon with at most 1000 vertices and no holes")
    west, south, east, north = polygon.bounds
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise AnalysisError("Area coordinates must be valid longitude/latitude")
    metric = _metric_polygon(polygon, polygon.centroid.x, polygon.centroid.y)
    if metric.area < 2_500 or metric.area > 100_000_000:
        raise AnalysisError("Select between 0.25 and 10,000 hectares")
    minx, miny, maxx, maxy = metric.bounds
    if max(maxx - minx, maxy - miny) > 20_000:
        raise AnalysisError("Selected area must fit within a 20 km analysis span")
    return polygon


def _condition_dem(dem: np.ndarray) -> np.ndarray:
    """Priority-flood sinks to raster edge; epsilon drains flats without cycles."""
    rows, cols = dem.shape
    result = np.asarray(dem, dtype=float).copy()
    seen = np.zeros((rows, cols), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for r in range(rows):
        for c in (0, cols - 1):
            if not seen[r, c]:
                seen[r, c] = True
                heapq.heappush(heap, (result[r, c], r, c))
    for c in range(cols):
        for r in (0, rows - 1):
            if not seen[r, c]:
                seen[r, c] = True
                heapq.heappush(heap, (result[r, c], r, c))
    while heap:
        spill, r, c = heapq.heappop(heap)
        for dr, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < cols and not seen[rr, cc]:
                seen[rr, cc] = True
                result[rr, cc] = max(result[rr, cc], spill + 1e-5)
                heapq.heappush(heap, (result[rr, cc], rr, cc))
    return result


def _sample_eligible(polygon: Polygon, grid: ElevationGrid) -> np.ndarray:
    xx, yy = np.meshgrid(grid.gx, grid.gy)
    lon = grid.lon0 + np.degrees(xx / (6_371_000.0 * math.cos(math.radians(grid.lat0))))
    lat = grid.lat0 + np.degrees(yy / 6_371_000.0)
    return contains_xy(polygon, lon, lat)


def _copernicus_origin(polygon: Polygon) -> tuple[float, float]:
    return round(polygon.centroid.x, 7), round(polygon.centroid.y, 7)


def _load_copernicus_grid(polygon: Polygon) -> ElevationGrid:
    """Read the buffered AOI from signed GLO-30 COGs into a local metric grid."""
    return _copernicus_grid(tuple(round(value, 6) for value in polygon.bounds), _copernicus_origin(polygon))


AWS_COPERNICUS = "https://copernicus-dem-30m.s3.amazonaws.com"
GDAL_REMOTE = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "1", "GDAL_HTTP_RETRY_DELAY": "1",
    "GDAL_HTTP_CONNECTTIMEOUT": "20", "GDAL_HTTP_TIMEOUT": "60",
}
DEM_NOTE = ("GLO-30 is a ~30 m digital surface model (heights above the EGM2008 geoid), not a bare-earth "
            "survey; trees, buildings, local embankments and small channels may be misrepresented.")


def _aws_copernicus_urls(west: float, south: float, east: float, north: float) -> list[str]:
    """Public, unsigned GLO-30 COGs on AWS Open Data, one per 1° cell."""
    urls = []
    for lat in range(math.floor(south), math.floor(north - 1e-9) + 1):
        for lon in range(math.floor(west), math.floor(east - 1e-9) + 1):
            name = (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                    f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
            urls.append(f"{AWS_COPERNICUS}/{name}/{name}.tif")
    return urls


def _planetary_computer_urls(west: float, south: float, east: float, north: float) -> list[str]:
    import planetary_computer
    from pystac_client import Client

    catalog = Client.open(STAC_URL)
    items = list(catalog.search(collections=["cop-dem-glo-30"], bbox=[west, south, east, north], limit=30).items())
    return [planetary_computer.sign(item).assets["data"].href for item in items]


def _mosaic(urls: list[str], transform, rows: int, cols: int) -> np.ndarray:
    """Warp each tile into the destination grid; unreachable or missing tiles stay NaN."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.errors import RasterioIOError
    from rasterio.warp import reproject

    dst = np.full((rows, cols), np.nan, dtype=np.float32)

    def read(url: str) -> np.ndarray:
        tile = np.full((rows, cols), np.nan, dtype=np.float32)
        with rasterio.Env(**GDAL_REMOTE), rasterio.open(url) as source:
            reproject(
                source=rasterio.band(source, 1), destination=tile,
                src_transform=source.transform, src_crs=source.crs,
                src_nodata=source.nodata, dst_transform=transform,
                dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.bilinear,
            )
        return tile

    for url in urls:
        try:
            tile = retry(lambda: read(url), attempts=3, retry_on=(RasterioIOError, OSError))
        except (RasterioIOError, OSError):
            continue  # an ocean cell has no tile; a flaky one falls back below
        fill = np.isnan(dst) & np.isfinite(tile)
        dst[fill] = tile[fill]
    return dst


@lru_cache(maxsize=12)
def _copernicus_grid(bounds: tuple[float, float, float, float], origin: tuple[float, float]) -> ElevationGrid:
    from rasterio.transform import from_bounds

    lon0, lat0 = origin
    west, south, east, north = bounds
    span_lon, span_lat = east - west, north - south
    buffer_lon = max(span_lon * 0.3, 0.009)
    buffer_lat = max(span_lat * 0.3, 0.009)
    west, east = west - buffer_lon, east + buffer_lon
    south, north = south - buffer_lat, north + buffer_lat
    x_bounds, y_bounds = _local_xy(np.array([west, east]), np.array([south, north]), lon0, lat0)
    span_x, span_y = float(np.ptp(x_bounds)), float(np.ptp(y_bounds))
    cols = min(280, max(50, math.ceil(span_x / 30)))
    rows = min(280, max(50, math.ceil(span_y / 30)))
    gx = np.linspace(float(x_bounds[0]), float(x_bounds[1]), cols)
    gy = np.linspace(float(y_bounds[0]), float(y_bounds[1]), rows)

    key = cache_key("glo30-v1", bounds, origin)
    cached = read_bytes("dem", key, ".npy")
    if cached is not None:
        z = np.load(io.BytesIO(cached))
        if z.shape == (rows, cols):
            return ElevationGrid(gx, gy, z, lon0, lat0, "Copernicus DEM GLO-30 (cached tiles)", 30.0, [DEM_NOTE])

    # The destination is north-up for GDAL; reverse to south-up for hydrology.
    transform = from_bounds(west, south, east, north, cols, rows)
    dst = _mosaic(_aws_copernicus_urls(west, south, east, north), transform, rows, cols)
    provider = "AWS Open Data"
    if np.isnan(dst).any():
        # Fill gaps (or a failed AWS read) from Planetary Computer's copy.
        fallback = _mosaic(retry(lambda: _planetary_computer_urls(west, south, east, north), attempts=2), transform, rows, cols)
        gaps = np.isnan(dst) & np.isfinite(fallback)
        if gaps.any():
            dst[gaps] = fallback[gaps]
            provider = "AWS Open Data and Microsoft Planetary Computer"
    if np.isnan(dst).any():
        raise AnalysisError("Elevation tiles do not fully cover the selected and buffered area")
    z = np.flipud(dst).astype(float)
    buffer = io.BytesIO()
    np.save(buffer, z)
    write_bytes("dem", key, ".npy", buffer.getvalue())
    return ElevationGrid(gx, gy, z, lon0, lat0, f"Copernicus DEM GLO-30 via {provider}", 30.0, [DEM_NOTE])


def _resolve_grid(polygon: Polygon, source: str, dataset_id: str | None) -> tuple[ElevationGrid | None, tuple[float, float]]:
    """Return a ready contour grid, or (None, origin) when Copernicus must be loaded."""
    if source == "sample":
        grid = sample_grid()
        if not box(*sample_bounds()).covers(polygon):
            raise AnalysisError("The selected area extends beyond the sample contours; use Copernicus terrain")
        return grid, (grid.lon0, grid.lat0)
    if source == "upload":
        uploaded = get_upload(dataset_id or "")
        if uploaded is None:
            raise AnalysisError("Uploaded terrain is unavailable or expired; upload the KML/KMZ again")
        if not box(*uploaded.bounds).covers(polygon):
            raise AnalysisError("Selected area extends beyond the uploaded contours; draw inside the survey or use Copernicus")
        return uploaded.grid, (uploaded.grid.lon0, uploaded.grid.lat0)
    if source == "copernicus":
        return None, _copernicus_origin(polygon)
    raise AnalysisError("Elevation source must be sample, upload or copernicus")


def _read_copernicus(polygon: Polygon) -> ElevationGrid:
    try:
        return _load_copernicus_grid(polygon)
    except AnalysisError:
        raise
    except Exception as exc:
        # GDAL errors can contain a signed asset URL; never echo it to users.
        raise AnalysisError("Copernicus elevation could not be read right now. Try a smaller area or the sample contours.") from exc


def analyze_area(
    geometry: dict,
    *,
    source: str = "sample",
    dataset_id: str | None = None,
    rainfall_source: str = "chirps",
    rainfall_period: str = "month",
    rainfall_month: str = "2025-08",
    rainfall_year: int = 2025,
    rainfall_mm: float = 150.0,
    runoff_coefficient: float = 0.35,
    stage_m: float = 2.5,
    max_catchment_ha: float = DEFAULT_MAX_CATCHMENT_HA,
) -> dict:
    polygon = validate_area(geometry)
    if rainfall_source not in {"chirps", "manual"}:
        raise AnalysisError("Rainfall source must be chirps or manual")
    if not (0.0 < runoff_coefficient <= 1.0 and 0.5 <= stage_m <= 8.0 and 0 <= rainfall_mm <= 5000):
        raise AnalysisError("Runoff coefficient, pond stage or rainfall is outside the supported range")
    if not 5 <= max_catchment_ha <= 5000:
        raise AnalysisError("Maximum catchment must be between 5 and 5,000 hectares")
    months = period_months(rainfall_period, rainfall_month, rainfall_year)
    if rainfall_source == "chirps":
        validate_months(months)
    grid, (lon0, lat0) = _resolve_grid(polygon, source, dataset_id)

    # Network lookups run while the elevation grid is read and routed.
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        screen_future = pool.submit(water_screening, *polygon.bounds, lon0, lat0)
        rain_future = (pool.submit(chirps_total, months, polygon.centroid.x, polygon.centroid.y)
                       if rainfall_source == "chirps" else None)
        if grid is None:
            grid = _read_copernicus(polygon)
        return _screen_and_rank(
            polygon, geometry, grid, source, screen_future, rain_future, months, rainfall_source,
            rainfall_period, rainfall_mm, runoff_coefficient, stage_m, max_catchment_ha,
        )
    finally:
        # Do not hold an error response hostage to a slow OSM or CHIRPS read.
        pool.shutdown(wait=False, cancel_futures=True)


def _screen_and_rank(polygon, geometry, grid, source, screen_future, rain_future, months, rainfall_source,
                     rainfall_period, rainfall_mm, runoff_coefficient, stage_m, max_catchment_ha) -> dict:
    rows, cols = grid.z.shape
    in_area = _sample_eligible(polygon, grid)
    if int(np.count_nonzero(in_area)) < 5:
        raise AnalysisError("Area is too narrow for this terrain grid; draw a larger polygon")
    dx, dy = abs(float(np.median(np.diff(grid.gx)))), abs(float(np.median(np.diff(grid.gy))))
    cell_area = dx * dy
    routed = _condition_dem(grid.z)
    downstream, accumulation = _flow_graph(routed, cell_area, dx, dy)
    upstream = UpstreamIndex(downstream)

    screen = screen_future.result()
    xx, yy = np.meshgrid(grid.gx, grid.gy)
    # Inflate mapped exclusions by half a cell diagonal, so retained cell
    # footprints do not cross a screened road or water boundary.
    half_cell_diagonal = 0.5 * math.hypot(dx, dy)
    no_mask = np.zeros_like(in_area)
    water_mask = contains_xy(screen.geometry.buffer(half_cell_diagonal), xx, yy) if screen.geometry is not None else no_mask
    built_mask = contains_xy(screen.land_geometry.buffer(half_cell_diagonal), xx, yy) if screen.land_geometry is not None else no_mask
    allowed = in_area & ~water_mask & ~built_mask
    if int(np.count_nonzero(allowed)) < 5:
        raise AnalysisError("No land remains after excluding mapped water, roads and built-up areas")

    # Drainage lines larger than the cap would need a designed spillway; keep
    # small-pond outlets (and their embankments) at least one cell away.
    max_accumulation = max_catchment_ha * 10_000
    major_channel = binary_dilation(accumulation > max_accumulation, iterations=1)
    edge = np.zeros_like(in_area)
    band = 2
    edge[:band, :] = edge[-band:, :] = True
    edge[:, :band] = edge[:, -band:] = True
    outlet_ok = allowed & ~major_channel & ~edge
    min_accumulation = max(10_000.0, 5 * cell_area)
    separation = max(3, math.ceil(200.0 / max(dx, dy)))
    candidates = candidate_pool(accumulation, outlet_ok, min_accumulation, max_accumulation, separation)
    relaxed = None
    if not candidates:
        relaxed = "No small drainage line qualified, so outlets on larger drainage lines are shown; they need a designed spillway."
        candidates = candidate_pool(accumulation, allowed & ~edge, cell_area, math.inf, separation)
    if not candidates:
        raise AnalysisError("No candidate outlet remains inside the selected land; draw a larger area")

    rain_notes: list[str] = []
    monthly: dict[str, float] = {}
    if rain_future is not None:
        try:
            rainfall_mm, monthly = rain_future.result()
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "the CHIRPS server could not be read"
            rain_notes.append(f"CHIRPS lookup failed ({reason}); using the explicitly shown manual scenario value instead.")
            rainfall_source = "manual-fallback"
    if rainfall_source != "chirps":
        rain_notes.append("Rainfall is a user-entered scenario, not an observed or forecast total.")

    radius = max(100.0, 4.0 * max(dx, dy))
    evaluated = []
    for r, c in candidates:
        catchment = upstream.catchment(r * cols + c)
        catchment_mask = np.zeros(rows * cols, dtype=bool)
        catchment_mask[catchment] = True
        catchment_mask = catchment_mask.reshape(rows, cols)
        pond = impoundment(grid.z, (r, c), stage_m, catchment_mask, allowed, dx, dy, radius)
        area = float(len(catchment) * cell_area)
        runoff = rainfall_mm / 1000 * area * runoff_coefficient
        evaluated.append({
            "cell": (r, c), "catchment": catchment, "catchment_mask": catchment_mask, "pond": pond,
            "area": area, "runoff": runoff, "capturable": min(runoff, pond.storage_m3),
            "efficiency": pond.storage_m3 / max(pond.embankment_length_m, 1.0),
        })
    # Best illustrative collectable volume first; then storage per metre of
    # embankment (less earthwork for the same water); then larger catchment.
    evaluated.sort(key=lambda item: (-round(item["capturable"], 1), -item["efficiency"], -item["area"]))
    chosen, used = [], np.zeros(rows * cols, dtype=bool)
    for item in evaluated:
        if used[item["pond"].cells].any():
            continue
        chosen.append(item)
        used[item["pond"].cells] = True
        if len(chosen) == 3:
            break

    recommendations = []
    for rank, item in enumerate(chosen, start=1):
        r, c = item["cell"]
        pond, catchment, area, runoff = item["pond"], item["catchment"], item["area"], item["runoff"]
        catchment_rows, catchment_cols = np.divmod(catchment, cols)
        touches_edge = bool(np.any((catchment_rows == 0) | (catchment_rows == rows - 1)
                                   | (catchment_cols == 0) | (catchment_cols == cols - 1)))
        fill_ratio = runoff / pond.storage_m3 if pond.storage_m3 > 0 else None
        notes = []
        if touches_edge:
            notes.append("Catchment reaches the elevation-data boundary; its area and runoff may be underestimated.")
        if area > max_accumulation:
            notes.append(f"Drains more than {max_catchment_ha:g} ha: overflow needs an engineered spillway.")
        if fill_ratio is not None and fill_ratio > 3:
            notes.append("Scenario runoff is over three times the pond storage; plan a safe overflow path.")
        if fill_ratio is not None and fill_ratio < 0.5:
            notes.append("Scenario runoff fills less than half of this pond.")
        point = Point(float(grid.gx[c]), float(grid.gy[r]))
        crest = float(grid.z[r, c]) + stage_m
        recommendations.append({
            "site_id": f"site-{rank:02d}",
            "rank": rank,
            "location": {"type": "Point", "coordinates": _geojson_point(float(grid.gx[c]), float(grid.gy[r]), grid.lon0, grid.lat0)},
            "pond_region": _geojson_geometry(_cells_geometry(pond.cells.tolist(), rows, cols, grid.gx, grid.gy), grid.lon0, grid.lat0),
            "elevation_m": round(float(grid.z[r, c]), 2),
            "catchment": {
                "area_m2": round(area, 1), "area_hectares": round(area / 10_000, 3),
                "flow_accumulation_cells": int(len(catchment)),
                "geometry": _geojson_geometry(_cells_geometry(catchment.tolist(), rows, cols, grid.gx, grid.gy), grid.lon0, grid.lat0),
                "touches_dem_boundary": touches_edge,
            },
            "pond": {
                "footprint_m2": round(pond.footprint_m2, 1), "stage_m": stage_m,
                "screening_storage_m3": round(pond.storage_m3, 1),
                "crest_elevation_m": round(crest, 2),
                "max_depth_m": round(pond.max_depth_m, 2),
                "mean_depth_m": round(pond.storage_m3 / pond.footprint_m2, 2) if pond.footprint_m2 else 0.0,
                "embankment_length_m": round(pond.embankment_length_m, 1),
                "stage_curve": stage_curve(grid.z, (r, c), item["catchment_mask"], allowed, dx, dy, radius,
                                           sorted(set(STAGE_TABLE_M + [stage_m]))),
            },
            "water": {
                "potential_runoff_m3": round(runoff, 1),
                "capturable_scenario_m3": round(min(runoff, pond.storage_m3), 1),
                "fill_ratio": round(fill_ratio, 2) if fill_ratio is not None else None,
                "limited_by": "runoff" if runoff < pond.storage_m3 else "storage",
            },
            "site_screening": {
                "distance_to_water_exclusion_m": round(point.distance(screen.geometry), 1) if screen.geometry is not None else None,
                "distance_to_built_exclusion_m": round(point.distance(screen.land_geometry), 1) if screen.land_geometry is not None else None,
                "mapped_water_excluded": screen.status == "mapped-water-excluded",
                "mapped_infrastructure_excluded": screen.status == "mapped-water-excluded",
                "major_channel_excluded": True,
                "likely_channel_excluded": True,
            },
            "notes": notes,
            "land_status": "unverified",
            "ranking_basis": ("illustrative collectable volume = min(scenario runoff, impounded storage), then storage per "
                              "metre of embankment; outlets are off mapped water, roads and buildings"),
        })

    period_label = PERIOD_LABELS.get(rainfall_period, rainfall_period)
    metric_area = _metric_polygon(polygon, polygon.centroid.x, polygon.centroid.y).area
    return {
        "analysis": {"status": "completed", "algorithm_version": ALGORITHM_VERSION, "kind": "screening",
                     "candidates_evaluated": len(evaluated)},
        "selection": {"geometry": geometry, "area_hectares": round(metric_area / 10_000, 2)},
        "elevation": {"source": grid.name, "source_key": source, "nominal_resolution_m": round(grid.nominal_resolution_m, 1),
                      "analysis_cell_m": round(math.sqrt(cell_area), 1), "grid_rows": rows, "grid_columns": cols,
                      "minimum_m": round(float(np.min(grid.z)), 2), "maximum_m": round(float(np.max(grid.z)), 2)},
        "parameters": {"max_catchment_ha": max_catchment_ha, "min_catchment_ha": round(min_accumulation / 10_000, 2),
                       "pond_search_radius_m": round(radius, 1), "stage_m": stage_m,
                       "candidate_separation_m": round(separation * max(dx, dy), 1)},
        "terrain_preview": terrain_preview(grid),
        "contours": contours_geojson(grid),
        "rainfall": {"source": rainfall_source, "period": rainfall_period, "period_label": period_label,
                     "month": months[0] if rainfall_source == "chirps" and rainfall_period == "month" else None,
                     "months": months if rainfall_source == "chirps" else [],
                     "monthly_mm": monthly,
                     "depth_mm": round(rainfall_mm, 1), "runoff_coefficient": runoff_coefficient,
                     "citation_url": CHIRPS_CITATION if rainfall_source == "chirps" else None},
        "water_screening": {"status": screen.status, "feature_count": screen.feature_count,
                            "land_feature_count": screen.land_feature_count, "provider": screen.provider,
                            "setback_m": screen.setback_m, "source_url": OSM_SOURCE_URL, "note": screen.note},
        "recommendations": recommendations,
        "limitations": grid.notes + rain_notes + ([relaxed] if relaxed else []) + [screen.note,
            "Runoff potential = rainfall depth × upstream catchment area × runoff coefficient; it is not guaranteed harvest.",
            "Pond storage assumes an embankment at the outlet: only cells that drain to the outlet and lie below the crest "
            f"(outlet ground + {stage_m:g} m) within {radius:.0f} m are counted. Seepage, evaporation, siltation and "
            "earthwork design are not modelled.",
            "The three sites are alternatives, not a cascade; their runoff is not additive.",
            "Mapped water, buildings, roads and built-up areas are screened only when OSM data can be read; protected land is not screened.",
            "Land ownership, legal eligibility and field conditions are unverified. Visit and survey a candidate before construction.",
        ],
    }


def export_contours(geometry: dict, *, source: str = "copernicus", dataset_id: str | None = None,
                    interval_m: float | None = None) -> tuple[bytes, str]:
    """Contour KML for the selected area, traced from the chosen elevation grid."""
    polygon = validate_area(geometry)
    if interval_m is not None and not 0.5 <= interval_m <= 200:
        raise AnalysisError("Contour interval must be between 0.5 and 200 m")
    grid, _ = _resolve_grid(polygon, source, dataset_id)
    if grid is None:
        grid = _read_copernicus(polygon)
    metric = _metric_polygon(polygon, grid.lon0, grid.lat0)
    minx, miny, maxx, maxy = metric.bounds
    pad = 0.1 * max(maxx - minx, maxy - miny)
    lon, lat = polygon.centroid.x, polygon.centroid.y
    note = COPERNICUS_ATTRIBUTION if source == "copernicus" else f"Re-traced from the interpolated grid of {grid.name}."
    payload = contours_kml(
        grid, interval_m=interval_m, clip_local_bounds=(minx - pad, miny - pad, maxx + pad, maxy + pad),
        title=f"Contours near {abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}",
        source_note=note,
    )
    filename = f"contours_{source}_{abs(lat):.4f}{'N' if lat >= 0 else 'S'}_{abs(lon):.4f}{'E' if lon >= 0 else 'W'}.kml"
    return payload, filename
