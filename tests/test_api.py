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
            files={"contour_map": (SAMPLE.name, source, "application/vnd.google-earth.kml+xml")},
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
    response = client.post("/analyzeContour", files={"contour_map": ("map.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_sample_kmz_is_supported():
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr("doc.kml", SAMPLE.read_bytes())
    response = client.post(
        "/analyzeContour?grid_size=50&max_candidates=1",
        files={"contour_map": ("contours.kmz", archive.getvalue(), "application/vnd.google-earth.kmz")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["input"]["format"] == "KMZ"


def test_config_exposes_google_key_only_when_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert client.get("/api/config").json()["google_maps_key"] is None
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "  test-browser-key  ")
    assert client.get("/api/config").json()["google_maps_key"] == "test-browser-key"


def test_env_file_sets_defaults_without_overriding(tmp_path, monkeypatch):
    from app.settings import load_env_file

    env = tmp_path / ".env"
    env.write_text("# comment\nPOND_TEST_A=from-file\nPOND_TEST_B='quoted'\nnot a setting\n", encoding="utf-8")
    monkeypatch.delenv("POND_TEST_A", raising=False)
    monkeypatch.setenv("POND_TEST_B", "from-env")
    load_env_file(env)
    import os
    assert os.environ["POND_TEST_A"] == "from-file"
    assert os.environ["POND_TEST_B"] == "from-env"
    monkeypatch.delenv("POND_TEST_A")
