"""Screen candidate pond sites against mapped features in OpenStreetMap.

Features are queried for each study area through public Overpass API servers;
no sample coordinates are baked in. The OSM editing API is deliberately not
used: its usage policy reserves it for editing, not read-only applications.
Missing OSM features do not establish that a site is dry or buildable.
"""

from __future__ import annotations

import json
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import requests
from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize, unary_union

from .cache import cache_key, read_json, write_json
from .terrain import _local_xy


OSM_SOURCE_URL = "https://www.openstreetmap.org/copyright"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
MAX_RESPONSE_BYTES = 40_000_000
USER_AGENT = "VillagePondPlanner/0.4 (academic pond screening; IIT Bhilai)"
WATERWAYS = {"river", "stream", "canal", "ditch", "drain"}
BUILT_LANDUSE = {"residential", "commercial", "industrial", "retail", "military", "cemetery"}
WATER_SETBACK_M = 40.0
# Approximate half-widths plus a working margin; not legal setbacks.
ROAD_BUFFERS_M = {
    "motorway": 35.0, "trunk": 35.0, "primary": 30.0, "secondary": 25.0,
    "tertiary": 18.0, "unclassified": 12.0, "residential": 12.0, "service": 8.0,
    "living_street": 8.0, "road": 12.0,
}
MINOR_PATH_BUFFER_M = 4.0  # tracks, footways and paths
RAILWAY_BUFFER_M = 30.0
OVERPASS_BUDGET_S = 90.0


@dataclass
class WaterScreening:
    geometry: object | None  # local metric exclusion geometry
    status: str
    feature_count: int
    setback_m: float
    note: str
    land_geometry: object | None = None  # mapped buildings, roads, built-up areas
    land_feature_count: int = 0
    provider: str | None = None


def _metric_ring(coordinates: list[tuple[float, float]], lon0: float, lat0: float):
    if len(coordinates) < 2:
        return None
    lon = np.array([point[0] for point in coordinates], dtype=float)
    lat = np.array([point[1] for point in coordinates], dtype=float)
    xx, yy = _local_xy(lon, lat, lon0, lat0)
    return LineString(zip(xx.tolist(), yy.tolist()))


def _is_water_area(tags: dict[str, str]) -> bool:
    return (tags.get("natural") in {"water", "wetland"} or tags.get("landuse") in {"reservoir", "basin"}
            or tags.get("waterway") == "riverbank" or "water" in tags)


def _is_built_area(tags: dict[str, str]) -> bool:
    return (("building" in tags and tags["building"] != "no")
            or tags.get("landuse") in BUILT_LANDUSE)


def _road_buffer(tags: dict[str, str]) -> float | None:
    highway = tags.get("highway")
    if highway and highway not in {"proposed", "construction", "abandoned", "razed"}:
        base = highway.removesuffix("_link")
        return ROAD_BUFFERS_M.get(base, MINOR_PATH_BUFFER_M)
    if tags.get("railway") in {"rail", "light_rail"}:
        return RAILWAY_BUFFER_M
    return None


def _polygon(line: LineString):
    polygon = Polygon(line)
    return polygon if polygon.is_valid else polygon.buffer(0)


def _screen(ways, relations, lon0: float, lat0: float, clip=None, provider: str | None = None) -> WaterScreening:
    """Build exclusions from ``ways`` [(tags, [(lon, lat)])] and relations [(tags, [[(lon, lat)]])]."""
    excluded, built_excluded = [], []
    count = built_count = 0

    def keep(geometry):
        return geometry if clip is None else geometry.intersection(clip)

    for tags, coordinates in ways:
        water_area, waterway = _is_water_area(tags), tags.get("waterway")
        built_area, road = _is_built_area(tags), _road_buffer(tags)
        if not water_area and waterway not in WATERWAYS and not built_area and road is None:
            continue
        line = _metric_ring(coordinates, lon0, lat0)
        if line is None:
            continue
        if water_area and line.is_ring:
            polygon = _polygon(line)
            if not polygon.is_empty:
                excluded.append(keep(polygon.buffer(WATER_SETBACK_M)))
                count += 1
        elif waterway in WATERWAYS:
            excluded.append(keep(line.buffer(45.0 if waterway in {"river", "canal"} else 25.0)))
            count += 1
        if built_area and line.is_ring:
            polygon = _polygon(line)
            if not polygon.is_empty:
                built_excluded.append(keep(polygon.buffer(12.0)))
                built_count += 1
        if road is not None:
            built_excluded.append(keep(line.buffer(road)))
            built_count += 1

    # Multipolygon relations may consist of separate, untagged outer ways.
    for tags, outer_ways in relations:
        water_area, built_area = _is_water_area(tags), _is_built_area(tags)
        if not water_area and not built_area:
            continue
        outer_lines = [line for line in (_metric_ring(way, lon0, lat0) for way in outer_ways) if line is not None]
        if not outer_lines:
            continue
        polygons = list(polygonize(outer_lines))
        shapes = polygons or outer_lines  # incomplete relation: exclude its mapped boundary only
        if water_area:
            excluded.extend(keep(item.buffer(WATER_SETBACK_M)) for item in shapes)
            count += len(shapes)
        if built_area:
            built_excluded.extend(keep(item.buffer(12.0)) for item in shapes)
            built_count += len(shapes)

    geometry = unary_union(excluded) if excluded else None
    land_geometry = unary_union(built_excluded) if built_excluded else None
    return WaterScreening(
        geometry, "mapped-water-excluded", count, WATER_SETBACK_M,
        "OpenStreetMap water, wetlands, waterways, buildings, roads and built-up areas are screened with "
        "approximate setbacks (© OpenStreetMap contributors, ODbL). Unmapped features, seasonal water, "
        "soil and land ownership remain unverified.",
        land_geometry, built_count, provider,
    )


def _parse_water(xml_data: bytes, lon0: float, lat0: float) -> WaterScreening:
    """Parse OSM XML (an ``.osm`` extract or API v0.6 ``/map`` document)."""
    root = ET.fromstring(xml_data)
    nodes = {
        item.attrib["id"]: (float(item.attrib["lon"]), float(item.attrib["lat"]))
        for item in root.findall("node")
    }
    way_nodes, ways = {}, []
    for item in root.findall("way"):
        coordinates = [nodes[node.attrib["ref"]] for node in item.findall("nd") if node.attrib["ref"] in nodes]
        way_nodes[item.attrib["id"]] = coordinates
        ways.append(({tag.attrib["k"]: tag.attrib["v"] for tag in item.findall("tag")}, coordinates))
    relations = []
    for relation in root.findall("relation"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in relation.findall("tag")}
        outer = [way_nodes.get(member.attrib.get("ref", ""), []) for member in relation.findall("member")
                 if member.attrib.get("type") == "way" and member.attrib.get("role") == "outer"]
        relations.append((tags, outer))
    return _screen(ways, relations, lon0, lat0, provider="OSM API")


def _parse_overpass(data: dict, lon0: float, lat0: float, clip=None) -> WaterScreening:
    """Parse an Overpass ``[out:json]`` response produced with ``out geom``."""
    ways, relations = [], []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        if element.get("type") == "way":
            ways.append((tags, [(point["lon"], point["lat"]) for point in element.get("geometry", []) if point]))
        elif element.get("type") == "relation":
            outer = [[(point["lon"], point["lat"]) for point in member.get("geometry", []) if point]
                     for member in element.get("members", [])
                     if member.get("type") == "way" and member.get("role") in {"outer", ""}]
            relations.append((tags, outer))
    return _screen(ways, relations, lon0, lat0, clip, provider="Overpass API")


def overpass_query(south: float, west: float, north: float, east: float) -> str:
    return f"""[out:json][timeout:40][maxsize:{MAX_RESPONSE_BYTES}][bbox:{south:.6f},{west:.6f},{north:.6f},{east:.6f}];
(
  way["natural"~"^(water|wetland)$"]; relation["natural"~"^(water|wetland)$"];
  way["water"]; relation["water"];
  way["landuse"~"^(reservoir|basin)$"]; relation["landuse"~"^(reservoir|basin)$"];
  way["waterway"~"^(river|stream|canal|ditch|drain|riverbank)$"];
  way["building"]; relation["building"];
  way["landuse"~"^(residential|commercial|industrial|retail|military|cemetery)$"];
  relation["landuse"~"^(residential|commercial|industrial|retail|military|cemetery)$"];
  way["highway"]; way["railway"~"^(rail|light_rail)$"];
);
out geom qt;"""


def _read_limited(response: requests.Response) -> bytes:
    payload = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("OSM response exceeds analysis limit")
    return bytes(payload)


@lru_cache(maxsize=64)
def _cached_water_screening(west: float, south: float, east: float, north: float, lon0: float, lat0: float) -> WaterScreening:
    # Include waterways just outside the selected boundary and avoid false precision.
    longitude_margin = 0.002 / max(0.2, math.cos(math.radians(lat0)))
    bbox = (west - longitude_margin, south - 0.002, east + longitude_margin, north + 0.002)
    x_bounds, y_bounds = _local_xy(np.array([bbox[0], bbox[2]]), np.array([bbox[1], bbox[3]]), lon0, lat0)
    clip = box(float(x_bounds[0]) - 100, float(y_bounds[0]) - 100, float(x_bounds[1]) + 100, float(y_bounds[1]) + 100)
    key = cache_key("overpass-v1", [round(value, 6) for value in bbox])
    cached = read_json("overpass", key)
    if isinstance(cached, dict):
        return _parse_overpass(cached, lon0, lat0, clip)
    headers = {"User-Agent": USER_AGENT}
    query = overpass_query(bbox[1], bbox[0], bbox[3], bbox[2])
    deadline = time.monotonic() + OVERPASS_BUDGET_S
    # Cycle through the servers until one answers completely or time runs out;
    # slow campus DNS and TCP handshakes make single attempts unreliable.
    # The main server answers most often; give it two tries before the mirrors.
    for url in (OVERPASS_URLS[0],) + OVERPASS_URLS * 3:
        remaining = deadline - time.monotonic()
        if remaining < 8:
            break
        response = None
        try:
            response = requests.post(url, data={"data": query}, timeout=(min(20, remaining), min(60, remaining)),
                                     headers=headers, stream=True)
            response.raise_for_status()
            data = json.loads(_read_limited(response))
            remark = str(data.get("remark", "")).lower()
            if "error" in remark or "timed out" in remark:
                # A partial answer could silently miss mapped water; try the next server.
                raise ValueError("Overpass returned an incomplete result")
            write_json("overpass", key, data)
            return _parse_overpass(data, lon0, lat0, clip)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(1)
            continue
        finally:
            if response is not None:
                response.close()
    return WaterScreening(
        None, "unavailable", 0, WATER_SETBACK_M,
        "Mapped-water screening was unavailable. Terrain low points have NOT been checked against existing rivers or ponds.",
    )


def water_screening(west: float, south: float, east: float, north: float, lon0: float, lat0: float) -> WaterScreening:
    result = _cached_water_screening(west, south, east, north, lon0, lat0)
    if result.status == "unavailable":
        # Temporary upstream failures must not become permanent for this server.
        _cached_water_screening.cache_clear()
    return result
