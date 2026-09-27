import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, shape

from app import rainfall
from app.hydrology import UpstreamIndex, impoundment
from app.main import app
from app.osm import WaterScreening, _parse_overpass, _screen
from app.terrain import AnalysisError, _flow_graph


client = TestClient(app)


@pytest.fixture(autouse=True)
def offline_water_screening(monkeypatch):
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "OSM unavailable during this test",
    ))


def sample_area(fraction=0.08):
    west, south, east, north = client.get("/api/config").json()["sample_bounds"]
    dx, dy = (east - west) * fraction, (north - south) * fraction
    w, s, e, n = west + dx, south + dy, east - dx, north - dy
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def analyze(**overrides):
    body = {"area": sample_area(), "rainfall_source": "manual", "rainfall_mm": 400, **overrides}
    response = client.post("/api/analyze-area", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_pond_footprint_stays_inside_its_own_catchment():
    # Regression: storage used to include cells downstream of the outlet.
    for site in analyze()["recommendations"]:
        pond, catchment = shape(site["pond_region"]), shape(site["catchment"]["geometry"])
        assert catchment.buffer(1e-9).covers(pond)
        assert catchment.covers(Point(site["location"]["coordinates"]))
        assert site["pond"]["max_depth_m"] >= site["pond"]["stage_m"] - 1e-6


def test_sites_are_ranked_by_collectable_volume_and_have_consistent_stage_curves():
    sites = analyze()["recommendations"]
    volumes = [site["water"]["capturable_scenario_m3"] for site in sites]
    assert volumes == sorted(volumes, reverse=True)
    for site in sites:
        curve = site["pond"]["stage_curve"]
        storages = [row["storage_m3"] for row in curve]
        assert storages == sorted(storages)
        chosen = next(row for row in curve if row["stage_m"] == site["pond"]["stage_m"])
        assert chosen["storage_m3"] == pytest.approx(site["pond"]["screening_storage_m3"], abs=0.2)
        assert site["pond"]["embankment_length_m"] > 0
        assert site["water"]["limited_by"] in {"runoff", "storage"}


def test_pond_footprints_do_not_overlap():
    sites = analyze()["recommendations"]
    for index, first in enumerate(sites):
        for second in sites[index + 1:]:
            assert shape(first["pond_region"]).intersection(shape(second["pond_region"])).area < 1e-12


def test_higher_stage_holds_more_water():
    low = analyze(stage_m=1.0)["recommendations"][0]["pond"]
    high = analyze(stage_m=4.0)["recommendations"][0]["pond"]
    assert high["screening_storage_m3"] > low["screening_storage_m3"]


def test_response_includes_dem_contours():
    contours = analyze()["contours"]
    assert contours["interval_m"] > 0
    assert len(contours["features"]) > 20
    assert {feature["geometry"]["type"] for feature in contours["features"]} == {"LineString"}


def test_impoundment_on_a_valley_counts_only_upstream_cells():
    # A V-shaped valley draining south: the outlet's catchment is upstream only.
    y, x = np.mgrid[0:30, 0:21]
    dem = 100 + 0.5 * y + 0.8 * np.abs(x - 10)
    downstream, _ = _flow_graph(dem, 100.0, 10.0, 10.0)
    catchment = UpstreamIndex(downstream).catchment(10 * 21 + 10)
    mask = np.zeros(dem.size, dtype=bool)
    mask[catchment] = True
    mask = mask.reshape(dem.shape)
    pond = impoundment(dem, (10, 10), 2.0, mask, np.ones_like(mask), 10.0, 10.0, 500.0)
    rows = pond.cells // 21
    assert rows.min() >= 10  # nothing downstream (south) of the outlet row
    assert pond.storage_m3 > 0
    assert pond.embankment_length_m >= 10.0


def test_rainfall_periods_sum_monthly_chirps(monkeypatch):
    assert rainfall.period_months("monsoon", "2025-08", 2024) == ["2024-06", "2024-07", "2024-08", "2024-09"]
    assert len(rainfall.period_months("annual", "2025-08", 2020)) == 12
    monkeypatch.setattr(rainfall, "chirps_month", lambda month, lon, lat: float(month[-2:]))
    total, monthly = rainfall.chirps_total(["2024-06", "2024-07"], 81.3, 21.2)
    assert total == 13 and monthly == {"2024-06": 6.0, "2024-07": 7.0}
    with pytest.raises(AnalysisError):
        rainfall.validate_months(["2999-01"])
    with pytest.raises(AnalysisError):
        rainfall.chirps_total(["2024-06"], 10.0, 70.0)


def test_overpass_parser_and_road_classes():
    data = {"elements": [
        {"type": "way", "id": 1, "tags": {"natural": "water"}, "geometry": [
            {"lat": 0, "lon": 0}, {"lat": 0, "lon": 0.001}, {"lat": 0.001, "lon": 0.001},
            {"lat": 0.001, "lon": 0}, {"lat": 0, "lon": 0}]},
        {"type": "way", "id": 2, "tags": {"highway": "footway"}, "geometry": [
            {"lat": 0, "lon": 0.004}, {"lat": 0.001, "lon": 0.004}]},
        {"type": "way", "id": 3, "tags": {"highway": "primary"}, "geometry": [
            {"lat": 0, "lon": 0.008}, {"lat": 0.001, "lon": 0.008}]},
        {"type": "relation", "id": 4, "tags": {"landuse": "reservoir"}, "members": [
            {"type": "way", "role": "outer", "geometry": [
                {"lat": 0.003, "lon": 0}, {"lat": 0.003, "lon": 0.001}, {"lat": 0.004, "lon": 0.001},
                {"lat": 0.004, "lon": 0}, {"lat": 0.003, "lon": 0}]}]},
    ]}
    screen = _parse_overpass(data, 0, 0)
    assert screen.feature_count == 2 and screen.land_feature_count == 2
    assert screen.provider == "Overpass API"
    assert screen.geometry.covers(Point(50, 50)) and screen.geometry.covers(Point(50, 390))
    footway_x, primary_x = 444.8, 889.6
    assert screen.land_geometry.covers(Point(footway_x + 3, 50))
    assert not screen.land_geometry.covers(Point(footway_x + 10, 50))
    assert screen.land_geometry.covers(Point(primary_x + 25, 50))


def test_screen_ignores_untagged_or_proposed_features():
    screen = _screen([({"highway": "proposed"}, [(0, 0), (0.001, 0)]), ({}, [(0, 0), (0, 0.001)])], [], 0, 0)
    assert screen.geometry is None and screen.land_geometry is None


def test_contour_export_round_trips_through_upload():
    area = sample_area(0.2)
    response = client.post("/api/export/contours.kml", json={"area": area, "source": "sample", "interval_m": 2})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.google-earth.kml+xml")
    assert "attachment" in response.headers["content-disposition"]
    uploaded = client.post("/api/terrain-upload", files={"contour_map": ("exported.kml", response.content)})
    assert uploaded.status_code == 200, uploaded.text
    dataset = uploaded.json()
    assert dataset["contour_features"] > 10
    assert dataset["elevation_max_m"] - dataset["elevation_min_m"] >= 4


def test_contour_export_rejects_bad_interval():
    response = client.post("/api/export/contours.kml", json={"area": sample_area(), "source": "sample", "interval_m": 0.1})
    assert response.status_code == 422
