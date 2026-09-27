"""Fill the disk cache for the curated example areas.

Run where the network is reliable, then copy ``cache/`` to the server, so the
demo areas never depend on the server's own outbound connection:

    python scripts/prewarm_cache.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.examples import EXAMPLE_AREAS  # noqa: E402
from app.planning import analyze_area, export_contours, sample_bounds  # noqa: E402

RAINFALL = [
    {"rainfall_period": "monsoon", "rainfall_year": 2025},
    {"rainfall_period": "annual", "rainfall_year": 2025},
    {"rainfall_period": "month", "rainfall_month": "2025-08"},
]


def sample_selection() -> list[float]:
    # Mirrors the front end's default: the sample extent inset by 8 %.
    west, south, east, north = sample_bounds()
    x, y = (east - west) * 0.08, (north - south) * 0.08
    return [west + x, south + y, east - x, north - y]


def main() -> None:
    areas = [("Supplied sample", "sample", sample_selection())]
    areas += [(item["name"], "copernicus", item["bbox"]) for item in EXAMPLE_AREAS if item["bbox"]]
    for name, source, bbox in areas:
        started = time.time()
        geometry = mapping(box(*bbox))
        statuses = []
        for rain in RAINFALL:
            result = analyze_area(geometry, source=source, rainfall_source="chirps", **rain)
            statuses.append(f"{rain['rainfall_period']}={result['rainfall']['source']}")
        if source == "copernicus":
            export_contours(geometry, source=source)
        print(f"{name}: screening={result['water_screening']['status']} {' '.join(statuses)} "
              f"({time.time() - started:.1f}s)")


if __name__ == "__main__":
    main()
