"""Create real DEM-derived contour KMLs for the curated example areas.

Each file is traced from Copernicus DEM GLO-30 (via Microsoft Planetary
Computer) with the same code path as the app's "Get contour KML" export, so it
opens in Google Earth and can be uploaded back into the planner. These are
remote-sensing contours, not field surveys.

    python scripts/create_copernicus_contour_demo.py            # all examples
    python scripts/create_copernicus_contour_demo.py dongargarh-hills

The original independent demo (``contour-maps/copernicus_glo30_demo.kml``) is
kept unchanged because the tests use it as a fixed fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.examples import EXAMPLE_AREAS  # noqa: E402
from app.planning import export_contours  # noqa: E402

OUTPUT = ROOT / "contour-maps" / "real"


def main(selected: list[str]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for example in EXAMPLE_AREAS:
        if example["bbox"] is None or (selected and example["id"] not in selected):
            continue
        payload, _ = export_contours(mapping(box(*example["bbox"])), source="copernicus",
                                     interval_m=example.get("contour_interval_m"))
        target = OUTPUT / f"{example['id']}_glo30.kml"
        target.write_bytes(payload)
        print(f"{example['name']}: {payload.count(b'<Placemark>')} contour lines -> {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
