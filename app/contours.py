"""Contour lines traced from an analysis elevation grid.

These lines are derived from the same grid used for routing, so they are only
as accurate as that grid: Copernicus GLO-30 is a ~30 m surface model, and a
contour-derived grid is an interpolation of the source survey.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date

import numpy as np
from contourpy import LineType, contour_generator
from shapely.geometry import LineString, box

from .terrain import _geojson_point

KML_NS = "http://www.opengis.net/kml/2.2"
NICE_INTERVALS = (0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 200.0)
COPERNICUS_ATTRIBUTION = (
    "Contains modified Copernicus DEM GLO-30 data: © DLR e.V. 2010-2014 and © Airbus Defence "
    "and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA."
)


def nice_interval(relief_m: float, target_lines: int = 25) -> float:
    raw = max(relief_m, 0.1) / target_lines
    return next((value for value in NICE_INTERVALS if value >= raw), NICE_INTERVALS[-1])


def _levels(z: np.ndarray, interval: float) -> np.ndarray:
    low = math.ceil(float(np.nanmin(z)) / interval) * interval
    high = math.floor(float(np.nanmax(z)) / interval) * interval
    if high < low:
        return np.array([])
    return np.arange(low, high + interval / 2, interval)


def trace_contours(grid, interval_m: float | None = None, clip_local_bounds=None,
                   max_vertices: int = 60_000) -> tuple[list[tuple[float, list[list[float]]]], float]:
    """Return ``[(elevation, [[lon, lat], ...]), ...]`` and the interval used."""
    z = np.asarray(grid.z, dtype=float)
    interval = interval_m or nice_interval(float(np.nanmax(z) - np.nanmin(z)))
    levels = _levels(z, interval)
    if len(levels) > 400:
        interval = nice_interval(float(np.nanmax(z) - np.nanmin(z)), 60)
        levels = _levels(z, interval)
    generator = contour_generator(x=grid.gx, y=grid.gy, z=z, line_type=LineType.Separate)
    clip = box(*clip_local_bounds) if clip_local_bounds is not None else None
    tolerance = 0.25 * min(abs(float(grid.gx[1] - grid.gx[0])), abs(float(grid.gy[1] - grid.gy[0])))
    lines: list[tuple[float, list[list[float]]]] = []
    vertices = 0
    for level in levels:
        for path in generator.lines(float(level)):
            if len(path) < 3:
                continue
            geometry = LineString(path).simplify(tolerance, preserve_topology=False)
            if clip is not None:
                geometry = geometry.intersection(clip)
            parts = getattr(geometry, "geoms", [geometry])
            for part in parts:
                if part.is_empty or part.geom_type != "LineString" or len(part.coords) < 2:
                    continue
                coordinates = [
                    [round(value, 7) for value in _geojson_point(x, y, grid.lon0, grid.lat0)]
                    for x, y in part.coords
                ]
                lines.append((round(float(level), 3), coordinates))
                vertices += len(coordinates)
                if vertices > max_vertices:
                    return lines, interval
    return lines, interval


def contours_geojson(grid, interval_m: float | None = None, clip_local_bounds=None) -> dict:
    lines, interval = trace_contours(grid, interval_m, clip_local_bounds)
    major = interval * 5
    features = [{
        "type": "Feature",
        "properties": {
            "elevation_m": level,
            "major": bool(abs(level / major - round(level / major)) < 1e-6),
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    } for level, coordinates in lines]
    return {"type": "FeatureCollection", "interval_m": interval, "features": features}


def contours_kml(grid, *, interval_m: float | None = None, clip_local_bounds=None,
                 title: str, source_note: str) -> bytes:
    """KML readable by Google Earth and by this app's own contour uploader."""
    lines, interval = trace_contours(grid, interval_m, clip_local_bounds, max_vertices=250_000)
    ET.register_namespace("", KML_NS)

    def tag(name: str) -> str:
        return f"{{{KML_NS}}}{name}"

    root = ET.Element(tag("kml"))
    document = ET.SubElement(root, tag("Document"))
    ET.SubElement(document, tag("name")).text = title
    ET.SubElement(document, tag("description")).text = (
        f"{source_note} Contour interval {interval:g} m, generated {date.today().isoformat()} by "
        "Village Pond Planner. DEM-derived lines, not a field survey."
    )
    for style_id, colour, width in (("minor", "ff4f7f93", "1"), ("major", "ff1d4f63", "2.2")):
        style = ET.SubElement(document, tag("Style"), id=style_id)
        line_style = ET.SubElement(style, tag("LineStyle"))
        ET.SubElement(line_style, tag("color")).text = colour
        ET.SubElement(line_style, tag("width")).text = width
    folder = ET.SubElement(document, tag("Folder"))
    ET.SubElement(folder, tag("name")).text = f"Contours {interval:g} m"
    major = interval * 5
    for level, coordinates in lines:
        placemark = ET.SubElement(folder, tag("Placemark"))
        ET.SubElement(placemark, tag("name")).text = f"{level:g} m"
        is_major = abs(level / major - round(level / major)) < 1e-6
        ET.SubElement(placemark, tag("styleUrl")).text = "#major" if is_major else "#minor"
        extended = ET.SubElement(placemark, tag("ExtendedData"))
        data = ET.SubElement(extended, tag("Data"), name="elevation")
        ET.SubElement(data, tag("value")).text = f"{level:g}"
        line = ET.SubElement(placemark, tag("LineString"))
        ET.SubElement(line, tag("tessellate")).text = "1"
        ET.SubElement(line, tag("altitudeMode")).text = "clampToGround"
        ET.SubElement(line, tag("coordinates")).text = " ".join(
            f"{lon:.7f},{lat:.7f},{level:g}" for lon, lat in coordinates
        )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
