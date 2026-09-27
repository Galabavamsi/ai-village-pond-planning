"""Retry and persistent disk-cache helpers for remote data.

The IIT container's outbound network drops DNS lookups and connections at
random, so every remote read is retried, and results that never change
(historical DEM tiles and rainfall) or change slowly (OSM features) are kept on
disk. ``POND_CACHE_DIR`` sets the location; delete the directory to refresh.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")
CACHE_DIR = Path(os.environ.get("POND_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache"))


def retry(function: Callable[[], T], *, attempts: int = 3, delay_s: float = 1.5,
          retry_on: tuple[type[BaseException], ...] = (Exception,), give_up_on: tuple[type[BaseException], ...] = ()) -> T:
    """Call ``function`` until it succeeds, backing off between attempts."""
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except give_up_on:
            raise
        except retry_on:
            if attempt == attempts:
                raise
            time.sleep(delay_s * attempt)
    raise AssertionError("unreachable")


def cache_key(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def cache_path(kind: str, key: str, suffix: str) -> Path:
    return CACHE_DIR / kind / f"{key}{suffix}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_json(kind: str, key: str) -> Any | None:
    path = cache_path(kind, key, ".json.gz")
    try:
        return json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError):
        return None


def write_json(kind: str, key: str, value: Any) -> None:
    try:
        _atomic_write(cache_path(kind, key, ".json.gz"), gzip.compress(json.dumps(value).encode()))
    except OSError:
        pass  # A cache that cannot be written must never break an analysis.


def read_bytes(kind: str, key: str, suffix: str) -> bytes | None:
    try:
        return cache_path(kind, key, suffix).read_bytes()
    except OSError:
        return None


def write_bytes(kind: str, key: str, suffix: str, data: bytes) -> None:
    try:
        _atomic_write(cache_path(kind, key, suffix), data)
    except OSError:
        pass
