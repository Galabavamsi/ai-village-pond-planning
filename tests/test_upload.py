import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import Point, shape

from app.main import app
from app.osm import WaterScreening


client = TestClient(app)
SAMPLE = Path(__file__).resolve().parents[1] / "contour-maps" / "contours_1m.kml"
COPERNICUS_CONTOURS = Path(__file__).resolve().parents[1] / "contour-maps" / "copernicus_glo30_demo.kml"


def inset(bounds, fraction=0.12):
    west, south, east, north = bounds
    dx, dy = (east - west) * fraction, (north - south) * fraction
    return {"type": "Polygon", "coordinates": [[
        [west + dx, south + dy], [east - dx, south + dy],
        [east - dx, north - dy], [west + dx, north - dy],
        [west + dx, south + dy],
    ]]}


def test_real_sample_kml_upload_drives_area_analysis(monkeypatch):
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "offline test",
    ))
    response = client.post("/api/terrain-upload", files={"contour_map": (SAMPLE.name, SAMPLE.read_bytes())})
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["contour_features"] > 1000
    assert dataset["elevation_min_m"] < dataset["elevation_max_m"]
    lines = client.get(dataset["contour_url"])
    assert lines.status_code == 200
    assert len(lines.json()["features"]) > 100
    area = inset(dataset["bounds"])
    analyzed = client.post("/api/analyze-area", json={
        "area": area, "source": "upload", "dataset_id": dataset["dataset_id"],
        "rainfall_source": "manual", "rainfall_mm": 200,
    })
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body["elevation"]["source"].startswith("Uploaded contours")
    preview = body["terrain_preview"]
    assert len(preview["elevation_m"]) == preview["rows"] * preview["columns"]
    assert preview["minimum_m"] < preview["maximum_m"]
    assert body["recommendations"]
    assert shape(area).covers(Point(body["recommendations"][0]["location"]["coordinates"]))


def test_different_region_kmz_uses_absolute_coordinate_elevations(monkeypatch):
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "offline test",
    ))
    # An independent, small surveyed region; elevation is encoded in standard
    # KML absolute coordinate altitudes rather than placemark names.
    lines = []
    for index, height in enumerate((210, 215, 220, 225)):
        lat = 18.005 + index * 0.003
        coordinates = " ".join(f"78.{100 + col * 3:03d},{lat:.6f},{height}" for col in range(5))
        lines.append(f"<Placemark><name>survey line</name><LineString><altitudeMode>absolute</altitudeMode><coordinates>{coordinates}</coordinates></LineString></Placemark>")
    kml = ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document>" + "".join(lines) + "</Document></kml>").encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as kmz:
        kmz.writestr("doc.kml", kml)
    response = client.post("/api/terrain-upload", files={"contour_map": ("other-region.kmz", archive.getvalue())})
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["contour_features"] == 4
    assert dataset["elevation_min_m"] == 210
    assert dataset["elevation_max_m"] == 225
    assert dataset["bounds"][0] < 78.101 < dataset["bounds"][2]
    area = inset(dataset["bounds"], 0.18)
    analyzed = client.post("/api/analyze-area", json={
        "area": area, "source": "upload", "dataset_id": dataset["dataset_id"],
        "rainfall_source": "manual", "rainfall_mm": 120,
    })
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body["elevation"]["source"].endswith("other-region.kmz")
    assert body["recommendations"][0]["location"]["coordinates"][0] < 79
    assert body["terrain_preview"]["minimum_m"] >= 210


def test_independent_real_dem_contours_analyze_without_sample_coordinates(monkeypatch):
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "offline test",
    ))
    response = client.post("/api/terrain-upload", files={
        "contour_map": (COPERNICUS_CONTOURS.name, COPERNICUS_CONTOURS.read_bytes()),
    })
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["contour_features"] >= 50
    assert dataset["bounds"][0] > 81.3  # Not the supplied contour map's extent.
    analyzed = client.post("/api/analyze-area", json={
        "area": inset(dataset["bounds"], 0.15),
        "source": "upload", "dataset_id": dataset["dataset_id"],
        "rainfall_source": "manual", "rainfall_mm": 160,
    })
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body["recommendations"]
    assert body["elevation"]["source"].endswith(COPERNICUS_CONTOURS.name)
    assert body["terrain_preview"]["maximum_m"] > body["terrain_preview"]["minimum_m"]
    assert body["recommendations"][0]["location"]["coordinates"][0] > 81.3


def test_extended_data_elevations_take_precedence_over_numeric_line_names():
    lines = []
    for index, height in enumerate((302, 307, 312, 317)):
        lat = 19.0 + index * 0.003
        coords = " ".join(f"77.{100 + col * 3:03d},{lat:.6f},0" for col in range(5))
        lines.append(
            f"<Placemark><name>Line {index + 1}</name><ExtendedData><SchemaData>"
            f"<SimpleData name='ELEVATION'>{height} m</SimpleData></SchemaData></ExtendedData>"
            f"<LineString><coordinates>{coords}</coordinates></LineString></Placemark>"
        )
    kml = ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document>" + "".join(lines) + "</Document></kml>").encode()
    response = client.post("/api/terrain-upload", files={"contour_map": ("survey.kml", kml)})
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["contour_features"] == 4
    assert dataset["elevation_min_m"] == 302
    assert dataset["elevation_max_m"] == 317


def test_upload_rejects_invalid_files_and_missing_dataset():
    wrong_type = client.post("/api/terrain-upload", files={"contour_map": ("notes.txt", b"not a map")})
    assert wrong_type.status_code == 415
    invalid = client.post("/api/terrain-upload", files={"contour_map": ("broken.kml", b"<kml>broken")})
    assert invalid.status_code == 422
    area = inset(client.get("/api/config").json()["sample_bounds"])
    missing = client.post("/api/analyze-area", json={
        "area": area, "source": "upload", "dataset_id": "not-a-real-dataset",
        "rainfall_source": "manual",
    })
    assert missing.status_code == 422
    assert "upload" in missing.json()["detail"].lower()


def test_every_shipped_real_contour_kml_uploads_and_analyzes(monkeypatch):
    monkeypatch.setattr("app.planning.water_screening", lambda *args: WaterScreening(
        None, "unavailable", 0, 40.0, "offline test",
    ))
    files = sorted((Path(__file__).resolve().parents[1] / "contour-maps" / "real").glob("*.kml"))
    assert len(files) >= 5
    for path in files:
        uploaded = client.post("/api/terrain-upload", files={"contour_map": (path.name, path.read_bytes())})
        assert uploaded.status_code == 200, (path.name, uploaded.text)
        dataset = uploaded.json()
        analyzed = client.post("/api/analyze-area", json={
            "area": inset(dataset["bounds"], 0.15), "source": "upload", "dataset_id": dataset["dataset_id"],
            "rainfall_source": "manual", "rainfall_mm": 900,
        })
        assert analyzed.status_code == 200, (path.name, analyzed.text)
        sites = analyzed.json()["recommendations"]
        assert sites and all(site["pond"]["screening_storage_m3"] > 0 for site in sites), path.name
