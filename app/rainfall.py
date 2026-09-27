"""Historical CHIRPS v3 rainfall at the study-area centroid."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache

import numpy as np

from .cache import cache_key, read_json, retry, write_json
from .terrain import AnalysisError

CHIRPS_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/cogs"
CHIRPS_CITATION = "https://www.chc.ucsb.edu/data/chirps3"
PERIOD_MONTHS = {"monsoon": (6, 7, 8, 9), "annual": tuple(range(1, 13))}
PERIOD_LABELS = {"month": "single month", "monsoon": "June–September season", "annual": "calendar year"}


@lru_cache(maxsize=256)
def chirps_month(month: str, lon: float, lat: float) -> float:
    import rasterio
    from rasterio.errors import RasterioIOError

    key = cache_key("chirps-v3-monthly", month, lon, lat)
    cached = read_json("chirps", key)
    if isinstance(cached, (int, float)):
        return float(cached)
    year, number = month.split("-")
    url = f"{CHIRPS_URL}/chirps-v3.0.{year}.{number}.cog"

    def read() -> float:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="1",
                          GDAL_HTTP_RETRY_DELAY="1", GDAL_HTTP_CONNECTTIMEOUT="20", GDAL_HTTP_TIMEOUT="60"):
            with rasterio.open(url) as raster:
                return float(next(raster.sample([(lon, lat)]))[0])

    value = retry(read, attempts=3, retry_on=(RasterioIOError, OSError))
    # Ocean pixels are -9999; CHIRPS declares no nodata value.
    if not np.isfinite(value) or value < 0 or value > 10_000:
        raise AnalysisError("No valid CHIRPS rainfall pixel covers this area")
    write_json("chirps", key, value)
    return value


def period_months(period: str, month: str, year: int) -> list[str]:
    if period == "month":
        return [month]
    if period not in PERIOD_MONTHS:
        raise AnalysisError("Rainfall period must be month, monsoon or annual")
    return [f"{year:04d}-{number:02d}" for number in PERIOD_MONTHS[period]]


def validate_months(months: list[str]) -> None:
    latest = date.today().replace(day=1)
    for month in months:
        if not (len(month) == 7 and month[4] == "-" and month[:4].isdigit() and month[5:].isdigit()):
            raise AnalysisError("Rainfall month must be YYYY-MM")
        try:
            first_day = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise AnalysisError("Rainfall month must be a valid calendar month") from exc
        if not date(1981, 1, 1) <= first_day < latest:
            raise AnalysisError("Choose completed months between January 1981 and last month")


def chirps_total(months: list[str], lon: float, lat: float) -> tuple[float, dict[str, float]]:
    """Sum monthly CHIRPS totals; raises if any month is unavailable."""
    if not -60 <= lat <= 60:
        raise AnalysisError("CHIRPS is only available between 60°S and 60°N")
    lon, lat = round(lon, 3), round(lat, 3)
    with ThreadPoolExecutor(max_workers=min(6, len(months))) as pool:
        values = list(pool.map(lambda month: chirps_month(month, lon, lat), months))
    monthly = {month: round(value, 1) for month, value in zip(months, values)}
    return float(sum(values)), monthly
