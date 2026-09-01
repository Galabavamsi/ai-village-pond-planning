from pathlib import Path
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "contour-maps" / "contours_1m.kml"
client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sample_contour_analysis():
    with SAMPLE.open("rb") as source:
        response = client.post(
            "/analyzeContour?grid_size=70&max_candidates=2",
            files={"file": (SAMPLE.name, source, "application/vnd.google-earth.kml+xml")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["status"] == "completed"
    assert body["input"]["contour_features"] > 100
    assert len(body["recommendations"]) == 2
    recommendation = body["recommendations"][0]
    assert recommendation["catchment"]["area_m2"] > 0
    assert recommendation["location"]["type"] == "Point"
    assert recommendation["catchment"]["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_rejects_unsupported_format():
    response = client.post("/analyzeContour", files={"file": ("map.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_sample_kmz_is_supported():
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr("doc.kml", SAMPLE.read_bytes())
    response = client.post(
        "/analyzeContour?grid_size=50&max_candidates=1",
        files={"file": ("contours.kmz", archive.getvalue(), "application/vnd.google-earth.kmz")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["input"]["format"] == "KMZ"
