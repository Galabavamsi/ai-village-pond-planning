import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, shape
from shapely.ops import transform

from app.main import app
from app.osm import WaterScreening, _parse_water
from app.planning import sample_grid
from app.terrain import _local_xy


client = TestClient(app)


@pytest.fixture(autouse=True)
def offline_water_screening(monkeypatch):
    # The API tests must remain deterministic when the public OSM service is offline.
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "OSM unavailable during this test",
    ))


def rectangle(bounds, left, bottom, right, top):
    west, south, east, north = bounds
    x, y = east - west, north - south
    w, s, e, n = west + left * x, south + bottom * y, west + right * x, south + top * y
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def test_sample_area_returns_real_geometries_and_water_formula():
    bounds = client.get("/api/config").json()["sample_bounds"]
    area = rectangle(bounds, 0.08, 0.08, 0.92, 0.92)
    response = client.post("/api/analyze-area", json={"area": area, "rainfall_source": "manual", "rainfall_mm": 200, "runoff_coefficient": 0.4})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["algorithm_version"] == "priority-flood-d8-impoundment-v4"
    assert body["rainfall"]["source"] == "manual"
    assert len(body["recommendations"]) == 3
    site = body["recommendations"][0]
    assert shape(area).covers(Point(site["location"]["coordinates"]))
    assert site["catchment"]["area_m2"] > 0
    assert shape(site["catchment"]["geometry"]).is_valid
    assert abs(site["water"]["potential_runoff_m3"] - 0.2 * site["catchment"]["area_m2"] * 0.4) < 0.2
    assert site["water"]["capturable_scenario_m3"] == min(site["water"]["potential_runoff_m3"], site["pond"]["screening_storage_m3"])


def test_different_selected_land_changes_candidate():
    bounds = client.get("/api/config").json()["sample_bounds"]
    west = rectangle(bounds, 0.08, 0.1, 0.43, 0.9)
    east = rectangle(bounds, 0.57, 0.1, 0.92, 0.9)
    left = client.post("/api/analyze-area", json={"area": west, "rainfall_source": "manual"})
    right = client.post("/api/analyze-area", json={"area": east, "rainfall_source": "manual"})
    assert left.status_code == right.status_code == 200
    left_site, right_site = left.json()["recommendations"][0], right.json()["recommendations"][0]
    assert left_site["location"]["coordinates"] != right_site["location"]["coordinates"]
    assert shape(west).covers(Point(left_site["location"]["coordinates"]))
    assert shape(east).covers(Point(right_site["location"]["coordinates"]))


def test_invalid_or_outside_area_is_rejected():
    bounds = client.get("/api/config").json()["sample_bounds"]
    outside = rectangle(bounds, 1.1, 0.1, 1.3, 0.5)
    response = client.post("/api/analyze-area", json={"area": outside, "rainfall_source": "manual"})
    assert response.status_code == 422
    assert "Copernicus" in response.json()["detail"]


def test_contour_overlay_has_real_lines():
    response = client.get("/api/sample-contours")
    assert response.status_code == 200
    features = response.json()["features"]
    assert len(features) > 100
    assert all(item["geometry"]["type"] == "LineString" for item in features)


def test_site_ranking_excludes_mapped_water(monkeypatch):
    bounds = client.get("/api/config").json()["sample_bounds"]
    area = rectangle(bounds, 0.08, 0.08, 0.92, 0.92)
    baseline = client.post("/api/analyze-area", json={"area": area, "rainfall_source": "manual"}).json()
    first_lon, first_lat = baseline["recommendations"][0]["location"]["coordinates"]
    grid = sample_grid()
    xx, yy = _local_xy(np.array([first_lon]), np.array([first_lat]), grid.lon0, grid.lat0)
    excluded = Point(float(xx[0]), float(yy[0])).buffer(130)
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        excluded, "mapped-water-excluded", 1, 40.0, "test water feature",
    ))
    response = client.post("/api/analyze-area", json={"area": area, "rainfall_source": "manual"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["water_screening"]["status"] == "mapped-water-excluded"
    for site in body["recommendations"]:
        lon, lat = site["location"]["coordinates"]
        x, y = _local_xy(np.array([lon]), np.array([lat]), grid.lon0, grid.lat0)
        assert not excluded.covers(Point(float(x[0]), float(y[0])))
        assert site["site_screening"]["distance_to_water_exclusion_m"] > 0
        pond = transform(lambda lon, lat, z=None: _local_xy(np.array(lon), np.array(lat), grid.lon0, grid.lat0),
                         shape(site["pond_region"]))
        assert pond.intersection(excluded).area == 0

    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "mapped-water-excluded", 0, 40.0, "test road feature",
        land_geometry=excluded, land_feature_count=1,
    ))
    built_response = client.post("/api/analyze-area", json={"area": area, "rainfall_source": "manual"})
    assert built_response.status_code == 200, built_response.text
    for site in built_response.json()["recommendations"]:
        lon, lat = site["location"]["coordinates"]
        x, y = _local_xy(np.array([lon]), np.array([lat]), grid.lon0, grid.lat0)
        assert not excluded.covers(Point(float(x[0]), float(y[0])))
        assert site["site_screening"]["distance_to_built_exclusion_m"] > 0
        pond = transform(lambda lon, lat, z=None: _local_xy(np.array(lon), np.array(lat), grid.lon0, grid.lat0),
                         shape(site["pond_region"]))
        assert pond.intersection(excluded).area == 0


def test_osm_parser_excludes_water_area_and_stream():
    xml = b"""<osm>
      <node id="1" lon="0" lat="0"/><node id="2" lon="0.001" lat="0"/>
      <node id="3" lon="0.001" lat="0.001"/><node id="4" lon="0" lat="0.001"/>
      <node id="7" lon="0.002" lat="0"/><node id="8" lon="0.002" lat="0.001"/>
      <way id="5"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
        <tag k="natural" v="water"/></way>
      <way id="6"><nd ref="2"/><nd ref="3"/><tag k="waterway" v="stream"/></way>
      <way id="9"><nd ref="7"/><nd ref="8"/><tag k="highway" v="primary"/></way>
    </osm>"""
    screen = _parse_water(xml, 0, 0)
    assert screen.feature_count == 2
    assert screen.land_feature_count == 1
    assert screen.geometry.covers(Point(50, 50))
    assert screen.land_geometry.covers(Point(222, 50))
