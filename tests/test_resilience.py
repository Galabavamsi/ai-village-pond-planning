import io

import numpy as np
import pytest

from app import cache, planning


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


def test_aws_tile_names_cover_hemispheres_and_cell_seams():
    urls = planning._aws_copernicus_urls(80.99, 21.2, 81.01, 21.3)
    assert [url.rsplit("/", 1)[-1] for url in urls] == [
        "Copernicus_DSM_COG_10_N21_00_E080_00_DEM.tif", "Copernicus_DSM_COG_10_N21_00_E081_00_DEM.tif"]
    south_west = planning._aws_copernicus_urls(-0.5, -1.5, -0.2, -1.2)
    assert south_west[0].endswith("Copernicus_DSM_COG_10_S02_00_W001_00_DEM.tif")
    # A box ending exactly on a degree line needs no extra tile.
    assert len(planning._aws_copernicus_urls(81.2, 21.0, 82.0, 21.5)) == 1


def test_retry_recovers_from_transient_failures_and_gives_up_eventually():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("temporary DNS failure")
        return "ok"

    assert cache.retry(flaky, attempts=3, delay_s=0) == "ok"
    with pytest.raises(OSError):
        cache.retry(lambda: (_ for _ in ()).throw(OSError("down")), attempts=2, delay_s=0)
    with pytest.raises(KeyError):
        cache.retry(lambda: {}["missing"], attempts=5, delay_s=0, retry_on=(OSError,))


def test_disk_cache_round_trips(cache_dir):
    cache.write_json("overpass", "abc", {"elements": [1, 2]})
    assert cache.read_json("overpass", "abc") == {"elements": [1, 2]}
    assert cache.read_json("overpass", "missing") is None
    cache.write_bytes("dem", "k", ".npy", b"123")
    assert cache.read_bytes("dem", "k", ".npy") == b"123"
    assert not list(cache_dir.rglob("*.part"))


def test_cached_dem_grid_is_used_without_network(cache_dir, monkeypatch):
    bounds, origin = (81.30, 21.20, 81.32, 21.22), (81.31, 21.21)
    planning._copernicus_grid.cache_clear()
    monkeypatch.setattr(planning, "_mosaic", lambda *args: (_ for _ in ()).throw(AssertionError("network used")))
    # Work out the grid shape the loader expects, then plant a cached copy.
    rows = cols = None
    for attempt in range(2):
        try:
            grid = planning._copernicus_grid(bounds, origin)
            break
        except AssertionError:
            import math
            west, south, east, north = bounds
            bl, bt = max((east - west) * 0.3, 0.009), max((north - south) * 0.3, 0.009)
            xs, ys = planning._local_xy(np.array([west - bl, east + bl]), np.array([south - bt, north + bt]), *origin)
            cols = min(280, max(50, math.ceil(float(np.ptp(xs)) / 30)))
            rows = min(280, max(50, math.ceil(float(np.ptp(ys)) / 30)))
            buffer = io.BytesIO()
            np.save(buffer, np.full((rows, cols), 250.0))
            cache.write_bytes("dem", cache.cache_key("glo30-v1", bounds, origin), ".npy", buffer.getvalue())
    assert grid.z.shape == (rows, cols) and float(grid.z.max()) == 250.0
    planning._copernicus_grid.cache_clear()


def test_dns_cache_serves_last_good_answer_when_lookup_fails(monkeypatch):
    import socket

    answers = {"calls": 0}

    def fake(host, port, *args, **kwargs):
        answers["calls"] += 1
        if answers["calls"] > 1:
            raise socket.gaierror("temporary failure in name resolution")
        return [("family", "type", 6, "", ("192.0.2.1", port))]

    monkeypatch.setattr(cache, "_real_getaddrinfo", None)
    monkeypatch.setattr(cache, "_resolved", {})
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    cache.install_dns_cache(prewarm=())
    try:
        first = socket.getaddrinfo("example.test", 443)
        assert socket.getaddrinfo("example.test", 443) == first
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("never-resolved.test", 443)
    finally:
        monkeypatch.setattr(cache, "_real_getaddrinfo", None)
