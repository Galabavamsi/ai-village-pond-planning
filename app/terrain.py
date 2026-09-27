from __future__ import annotations

import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import QhullError
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union


KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"k": KML_NS}
EARTH_RADIUS_M = 6_371_000.0
MAX_KML_BYTES = 40 * 1024 * 1024
MAX_CONTOUR_POINTS = 350_000


class AnalysisError(ValueError):
    """An input map cannot produce a terrain analysis."""


@dataclass
class ContourPointSet:
    points: np.ndarray  # longitude, latitude, elevation
    features: int
    elevations: list[float]


def _local_xy(lon: np.ndarray, lat: np.ndarray, lon0: float, lat0: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def _geojson_point(x: float, y: float, lon0: float, lat0: float) -> list[float]:
    return [lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(lat0)))), lat0 + math.degrees(y / EARTH_RADIUS_M)]


def _geojson_geometry(geom, lon0: float, lat0: float) -> dict:
    """Convert a local metre geometry back to WGS84 GeoJSON."""
    result = mapping(geom)

    def convert(coords):
        if coords and isinstance(coords[0], (float, int)):
            return _geojson_point(float(coords[0]), float(coords[1]), lon0, lat0)
        return [convert(item) for item in coords]

    return {"type": result["type"], "coordinates": convert(result["coordinates"])}


def _parse_coordinates(text: str | None) -> list[tuple[float, float]]:
    return [(lon, lat) for lon, lat, _ in _parse_coordinate_tuples(text)]


def _parse_coordinate_tuples(text: str | None) -> list[tuple[float, float, float | None]]:
    if not text:
        return []
    points = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
            altitude = float(parts[2]) if len(parts) > 2 and parts[2] else None
        except ValueError:
            continue
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -85 <= lat <= 85):
            continue
        if altitude is not None and not math.isfinite(altitude):
            altitude = None
        points.append((lon, lat, altitude))
    return points


def _elevation_for_placemark(pm: ET.Element, line: ET.Element | None = None) -> float | None:
    # Prefer typed attributes or absolute coordinate altitude over a generic
    # placemark name, which may contain an unrelated identifier.
    candidates = []
    candidates.extend(
        item.text or ""
        for item in pm.findall(".//k:SimpleData", NS)
        if item.attrib.get("name", "").lower() in {"elevation", "elev", "z", "height", "level"}
    )
    candidates.extend(
        item.findtext("k:value", default="", namespaces=NS)
        for item in pm.findall(".//k:Data", NS)
        if item.attrib.get("name", "").lower() in {"elevation", "elev", "z", "height", "level"}
    )
    for value in candidates:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    if line is not None and line.findtext("k:altitudeMode", default="", namespaces=NS) == "absolute":
        altitudes = [alt for _, _, alt in _parse_coordinate_tuples(line.findtext("k:coordinates", namespaces=NS)) if alt is not None]
        if len(altitudes) >= 2 and max(altitudes) - min(altitudes) <= 0.5:
            return float(np.median(altitudes))
    name = pm.find("k:name", NS)
    if name is not None and name.text:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", name.text)
        if match:
            return float(match.group(0))
    return None


def _kml_bytes(payload: bytes, filename: str) -> bytes:
    if filename.lower().endswith(".kmz") or payload[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = [n for n in archive.infolist() if n.filename.lower().endswith(".kml")]
                if not members:
                    raise AnalysisError("KMZ archive does not contain a KML document")
                preferred = next((n for n in members if n.filename.lower().endswith("doc.kml")), members[0])
                if preferred.file_size > MAX_KML_BYTES:
                    raise AnalysisError("KML inside KMZ exceeds the 40 MB safety limit")
                with archive.open(preferred) as source:
                    data = source.read(MAX_KML_BYTES + 1)
                if len(data) > MAX_KML_BYTES:
                    raise AnalysisError("KML inside KMZ exceeds the 40 MB safety limit")
                return data
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise AnalysisError("The uploaded KMZ file is invalid or password-protected") from exc
    if len(payload) > MAX_KML_BYTES:
        raise AnalysisError("KML exceeds the 40 MB safety limit")
    return payload


def parse_contours(payload: bytes, filename: str) -> ContourPointSet:
    try:
        root = ET.fromstring(_kml_bytes(payload, filename))
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise AnalysisError("The file is not valid KML/XML") from exc

    rows: list[tuple[float, float, float]] = []
    features = 0
    elevations: list[float] = []
    for placemark in root.findall(".//k:Placemark", NS):
        for line in placemark.findall(".//k:LineString", NS):
            elevation = _elevation_for_placemark(placemark, line)
            if elevation is None:
                continue
            points = _parse_coordinates(line.findtext("k:coordinates", namespaces=NS))
            if len(points) < 2:
                continue
            features += 1
            elevations.append(elevation)
            rows.extend((lon, lat, elevation) for lon, lat in points)
            if len(rows) > MAX_CONTOUR_POINTS:
                raise AnalysisError("Contour map exceeds the 350,000-vertex safety limit")

    if len(rows) < 10 or len(set(elevations)) < 2:
        raise AnalysisError("No usable contour lines with at least two elevation levels were found")
    return ContourPointSet(np.asarray(rows, dtype=float), features, elevations)


def _grid_from_contours(contours: ContourPointSet, requested_size: int):
    lon = contours.points[:, 0]
    lat = contours.points[:, 1]
    lon0, lat0 = float(lon.mean()), float(lat.mean())
    x, y = _local_xy(lon, lat, lon0, lat0)
    span_x, span_y = float(x.max() - x.min()), float(y.max() - y.min())
    longer = max(span_x, span_y)
    if longer <= 0:
        raise AnalysisError("Contour map has no geographic extent")
    nx = max(40, round(requested_size * span_x / longer))
    ny = max(40, round(requested_size * span_y / longer))
    # Include a small margin so boundary contour points do not become edge cells.
    margin_x, margin_y = max(1.0, span_x * 0.005), max(1.0, span_y * 0.005)
    gx = np.linspace(x.min() - margin_x, x.max() + margin_x, nx)
    gy = np.linspace(y.min() - margin_y, y.max() + margin_y, ny)
    xx, yy = np.meshgrid(gx, gy)
    samples = np.column_stack((x, y))
    values = contours.points[:, 2]
    # Duplicate contour vertices are harmless, but thinning makes large KMLs fast.
    if len(samples) > 45_000:
        keep = np.linspace(0, len(samples) - 1, 45_000, dtype=int)
        samples, values = samples[keep], values[keep]
    try:
        dem = griddata(samples, values, (xx, yy), method="linear")
    except (QhullError, ValueError) as exc:
        raise AnalysisError("Contour lines must cover a two-dimensional area, not a single line") from exc
    missing = np.isnan(dem)
    if missing.any():
        dem[missing] = griddata(samples, values, (xx[missing], yy[missing]), method="nearest")
    return xx, yy, dem, lon0, lat0


def _flow_graph(dem: np.ndarray, cell_area: float, dx: float | None = None, dy: float | None = None):
    rows, cols = dem.shape
    downstream = np.full((rows, cols), -1, dtype=np.int64)
    dx = dx or math.sqrt(cell_area)
    dy = dy or math.sqrt(cell_area)
    directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for r in range(rows):
        for c in range(cols):
            best_grade = 0.0
            best_index = -1
            for dr, dc in directions:
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    grade = (float(dem[r, c]) - float(dem[rr, cc])) / math.hypot(dc * dx, dr * dy)
                    if grade > best_grade:
                        best_grade = grade
                        best_index = rr * cols + cc
            downstream[r, c] = best_index

    accumulation = np.full(rows * cols, cell_area, dtype=float)
    indegree = np.zeros(rows * cols, dtype=int)
    for target in downstream.ravel():
        if target >= 0:
            indegree[target] += 1
    queue = deque(np.flatnonzero(indegree == 0).tolist())
    processed = 0
    while queue:
        source = queue.popleft()
        processed += 1
        target = int(downstream.ravel()[source])
        if target >= 0:
            accumulation[target] += accumulation[source]
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if processed != rows * cols:
        # Equal/near-equal cells can create cycles only if the input has NaNs or
        # an unexpected numerical condition. Keep the analysis usable.
        accumulation = np.maximum(accumulation, cell_area)
    return downstream, accumulation.reshape(rows, cols)


def _contributing_cells(downstream: np.ndarray, candidate: tuple[int, int]) -> set[int]:
    rows, cols = downstream.shape
    reverse: dict[int, list[int]] = {}
    for source, target in enumerate(downstream.ravel()):
        if target >= 0:
            reverse.setdefault(int(target), []).append(source)
    start = candidate[0] * cols + candidate[1]
    visited = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for source in reverse.get(current, []):
            if source not in visited:
                visited.add(source)
                queue.append(source)
    return visited


def _cells_geometry(cells: Iterable[int], rows: int, cols: int, gx: np.ndarray, gy: np.ndarray):
    dx = float(np.median(np.diff(gx)))
    dy = float(np.median(np.diff(gy)))
    # Build shared edges once. Recomputing each box from its centre can leave
    # sub-nanometre gaps and produce thousands of separate GeoJSON polygons.
    x_edges = float(gx[0]) - dx / 2 + np.arange(cols + 1) * dx
    y_edges = float(gy[0]) - dy / 2 + np.arange(rows + 1) * dy
    polygons = []
    for index in cells:
        r, c = divmod(index, cols)
        polygons.append(box(x_edges[c], y_edges[r], x_edges[c + 1], y_edges[r + 1]))
    return unary_union(polygons)


def _candidate_indices(
    dem: np.ndarray,
    accumulation: np.ndarray,
    max_candidates: int,
    eligible_mask: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    rows, cols = dem.shape
    boundary = max(2, round(min(rows, cols) * 0.04))
    eligible = np.ones_like(dem, dtype=bool)
    eligible[:boundary, :] = eligible[-boundary:, :] = False
    eligible[:, :boundary] = eligible[:, -boundary:] = False
    if eligible_mask is not None:
        eligible &= eligible_mask
    # Prefer meaningful flow concentration while retaining lower terrain.
    positive = accumulation[eligible]
    if not len(positive):
        raise AnalysisError("The map does not contain an interior area to evaluate")
    threshold = float(np.percentile(positive, 85))
    eligible &= accumulation >= threshold
    # Rank by accumulation, then elevation. Enforce spatial separation so the
    # response gives distinct regions rather than adjacent cells on one stream.
    ranked = sorted(zip(*np.where(eligible)), key=lambda rc: (-accumulation[rc], dem[rc]))
    chosen: list[tuple[int, int]] = []
    separation = max(3, round(min(rows, cols) * 0.08))
    for rc in ranked:
        if all(abs(rc[0] - old[0]) > separation or abs(rc[1] - old[1]) > separation for old in chosen):
            chosen.append(rc)
        if len(chosen) >= max_candidates:
            break
    if not chosen:
        flat = np.argwhere(~np.isnan(dem))
        flat_values = dem[flat[:, 0], flat[:, 1]]
        chosen = [tuple(flat[np.argmin(flat_values)])]
    return chosen


def analyze_contour_file(payload: bytes, *, filename: str, grid_size: int, max_candidates: int) -> dict:
    contours = parse_contours(payload, filename)
    xx, yy, dem, lon0, lat0 = _grid_from_contours(contours, grid_size)
    gx, gy = xx[0, :], yy[:, 0]
    cell_area = abs(float(np.median(np.diff(gx))) * float(np.median(np.diff(gy))))
    downstream, accumulation = _flow_graph(dem, cell_area)
    candidate_cells = _candidate_indices(dem, accumulation, max_candidates)
    contour_interval = float(np.median(np.diff(np.unique(np.round(contours.elevations, 3)))))
    candidates = []
    for index, (r, c) in enumerate(candidate_cells, start=1):
        contributors = _contributing_cells(downstream, (r, c))
        catchment = _cells_geometry(contributors, dem.shape[0], dem.shape[1], gx, gy)
        # The pond footprint is a compact cell-sized region around the selected
        # outlet, not the complete catchment.
        pond = _cells_geometry({r * dem.shape[1] + c}, dem.shape[0], dem.shape[1], gx, gy)
        area_m2 = float(catchment.area)
        depth = max(1.0, min(8.0, contour_interval * 2.5))
        # A conservative geometric estimate; rainfall/runoff coefficients enter
        # in a later phase when rainfall data is available.
        storage = float(pond.area * depth * 0.75)
        point = _geojson_point(float(xx[r, c]), float(yy[r, c]), lon0, lat0)
        candidates.append(
            {
                "site_id": f"pond-{index}",
                "location": {"type": "Point", "coordinates": point},
                "pond_region": _geojson_geometry(pond, lon0, lat0),
                "elevation_m": round(float(dem[r, c]), 2),
                "estimated_pond_depth_m": round(depth, 2),
                "estimated_storage_m3": round(storage, 2),
                "catchment": {
                    "area_m2": round(area_m2, 2),
                    "area_hectares": round(area_m2 / 10_000, 4),
                    "geometry": _geojson_geometry(catchment, lon0, lat0),
                    "flow_accumulation_cells": len(contributors),
                },
                "ranking_basis": "high terrain-derived contributing area with interior low-point preference",
            }
        )

    return {
        "analysis": {"status": "completed", "algorithm_version": "terrain-d8-v1"},
        "input": {
            "filename": filename,
            "format": "KMZ" if filename.lower().endswith(".kmz") else "KML",
            "contour_features": contours.features,
            "elevation_min_m": round(min(contours.elevations), 2),
            "elevation_max_m": round(max(contours.elevations), 2),
            "contour_interval_m": round(contour_interval, 3),
        },
        "terrain_grid": {
            "rows": int(dem.shape[0]),
            "columns": int(dem.shape[1]),
            "cell_area_m2": round(cell_area, 2),
            "crs": "WGS84 geographic input; local equirectangular metric analysis",
        },
        "recommendations": candidates,
        "limitations": [
            "Catchment is estimated from contour-derived elevation and D8 flow routing.",
            "Rainfall, soil infiltration, land ownership, drainage structures, and field survey constraints are not included in this phase.",
            "Pond storage uses a conservative footprint/depth approximation and must be validated during detailed design.",
        ],
    }
