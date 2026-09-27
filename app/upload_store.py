"""Small, process-local cache of user-uploaded contour datasets.

Uploads are deliberately temporary. They are not public static files and are
discarded on server restart or after two hours of inactivity.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any


MAX_DATASETS = 8
TTL_SECONDS = 2 * 60 * 60


@dataclass
class UploadedTerrain:
    dataset_id: str
    filename: str
    grid: Any
    bounds: list[float]
    contour_geojson: dict
    contour_features: int
    elevation_min_m: float
    elevation_max_m: float
    expires_at: float


_lock = RLock()
_datasets: OrderedDict[str, UploadedTerrain] = OrderedDict()


def save_upload(*, filename: str, grid: Any, bounds: list[float], contour_geojson: dict,
                contour_features: int, elevation_min_m: float, elevation_max_m: float) -> UploadedTerrain:
    now = time.monotonic()
    with _lock:
        for key in list(_datasets):
            if _datasets[key].expires_at < now:
                del _datasets[key]
        while len(_datasets) >= MAX_DATASETS:
            _datasets.popitem(last=False)
        item = UploadedTerrain(
            secrets.token_urlsafe(18), filename, grid, bounds, contour_geojson,
            contour_features, elevation_min_m, elevation_max_m, now + TTL_SECONDS,
        )
        _datasets[item.dataset_id] = item
        return item


def get_upload(dataset_id: str) -> UploadedTerrain | None:
    if not dataset_id or len(dataset_id) > 80:
        return None
    now = time.monotonic()
    with _lock:
        item = _datasets.get(dataset_id)
        if item is None:
            return None
        if item.expires_at < now:
            del _datasets[dataset_id]
            return None
        item.expires_at = now + TTL_SECONDS
        _datasets.move_to_end(dataset_id)
        return item
