from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cache import install_dns_cache
from .examples import EXAMPLE_AREAS
from .planning import (
    DEFAULT_MAX_CATCHMENT_HA, analyze_area, export_contours, register_uploaded_contours,
    sample_bounds, sample_contours_geojson, uploaded_contours_geojson,
)
from .terrain import AnalysisError, analyze_contour_file


# The IIT container drops DNS queries at random; keep the last good answers.
install_dns_cache()

app = FastAPI(
    title="AI Village Pond Planning API",
    description=(
        "Select a land polygon, analyze supplied/uploaded KML/KMZ contours or "
        "Copernicus GLO-30 elevation, and estimate terrain-derived pond sites, "
        "upstream catchments and scenario water volumes. Numerical results are "
        "screening estimates, not engineering designs."
    ),
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pond-planning-api"}


class AreaRequest(BaseModel):
    area: dict[str, Any] = Field(description="Selected land as a valid GeoJSON Polygon in WGS84 longitude/latitude. Candidate outlets and pond footprints are restricted to this polygon.")
    source: Literal["sample", "upload", "copernicus"] = Field(default="sample", description="Elevation source. For upload, first POST a KML/KMZ to /api/terrain-upload.")
    dataset_id: str | None = Field(default=None, description="Temporary ID returned by /api/terrain-upload; required when source is upload.")
    rainfall_source: Literal["chirps", "manual"] = Field(default="chirps", description="Historical CHIRPS v3 rainfall or a manually assumed depth.")
    rainfall_period: Literal["month", "monsoon", "annual"] | None = Field(default=None, description="CHIRPS period: one month (rainfall_month), June–September of rainfall_year, or the calendar year. Defaults to month when rainfall_month is sent, otherwise monsoon.")
    rainfall_month: str = Field(default="2025-08", description="YYYY-MM historical month for a single-month CHIRPS lookup.")
    rainfall_year: int = Field(default=2025, ge=1981, le=2100, description="Year for monsoon or annual CHIRPS totals.")
    rainfall_mm: float = Field(default=150.0, ge=0, le=5000, description="Manual rainfall scenario in millimetres; also shown as a fallback when CHIRPS is unavailable.")
    runoff_coefficient: float = Field(default=0.35, gt=0, le=1, description="Assumed fraction of rainfall that becomes runoff, 0 < C <= 1.")
    stage_m: float = Field(default=2.5, ge=0.5, le=8, description="Screening water stage (embankment height) above outlet terrain, in metres.")
    max_catchment_ha: float = Field(default=DEFAULT_MAX_CATCHMENT_HA, ge=5, le=5000, description="Drainage lines with a larger upstream area are treated as major channels and avoided as small-pond outlets.")


class ContourExportRequest(BaseModel):
    area: dict[str, Any] = Field(description="GeoJSON Polygon whose extent is exported (plus a 10% margin).")
    source: Literal["sample", "upload", "copernicus"] = Field(default="copernicus")
    dataset_id: str | None = None
    interval_m: float | None = Field(default=None, ge=0.5, le=200, description="Contour interval; chosen from the relief when omitted.")


@app.get("/api/config")
async def config() -> dict:
    bounds = await run_in_threadpool(sample_bounds)
    return {"sample_bounds": bounds, "sources": ["sample", "upload", "copernicus"],
            "default_rainfall_month": "2025-08", "default_rainfall_year": 2025,
            "default_rainfall_period": "monsoon", "default_max_catchment_ha": DEFAULT_MAX_CATCHMENT_HA,
            "examples": EXAMPLE_AREAS}


@app.get("/api/sample-contours")
async def sample_contours() -> dict:
    return await run_in_threadpool(sample_contours_geojson)


@app.post("/api/terrain-upload")
async def terrain_upload(contour_map: UploadFile = File(description="Contour lines in KML or KMZ format")) -> dict:
    """Parse a contour survey and return a temporary dataset ID, bounds and line-overlay URL."""
    filename = (contour_map.filename or "uploaded-contours").replace("\\", "/").rsplit("/", 1)[-1][:180]
    if not filename.lower().endswith((".kml", ".kmz")):
        raise HTTPException(status_code=415, detail="Upload a .kml or .kmz contour file")
    payload = await contour_map.read(20 * 1024 * 1024 + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded contour file is empty")
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Contour upload exceeds the 20 MB limit")
    try:
        return await run_in_threadpool(register_uploaded_contours, payload, filename)
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/terrain/{dataset_id}/contours")
async def uploaded_contours(dataset_id: str) -> dict:
    try:
        return await run_in_threadpool(uploaded_contours_geojson, dataset_id)
    except AnalysisError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/analyze-area")
async def analyze_selected_area(request: AreaRequest) -> dict:
    """Return ranked sites, catchment/pond GeoJSON, rainfall and storage screening, contours and a 3D elevation preview."""
    period = request.rainfall_period or ("month" if "rainfall_month" in request.model_fields_set else "monsoon")
    try:
        return await run_in_threadpool(
            analyze_area, request.area, source=request.source, dataset_id=request.dataset_id,
            rainfall_source=request.rainfall_source,
            rainfall_period=period,
            rainfall_month=request.rainfall_month,
            rainfall_year=request.rainfall_year,
            rainfall_mm=request.rainfall_mm,
            runoff_coefficient=request.runoff_coefficient,
            stage_m=request.stage_m,
            max_catchment_ha=request.max_catchment_ha,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/export/contours.kml", response_class=Response,
          responses={200: {"content": {"application/vnd.google-earth.kml+xml": {}}}})
async def export_contour_kml(request: ContourExportRequest) -> Response:
    """Download contour lines for the selected area as KML (opens in Google Earth; re-uploadable here)."""
    try:
        payload, filename = await run_in_threadpool(
            export_contours, request.area, source=request.source,
            dataset_id=request.dataset_id, interval_m=request.interval_m,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(payload, media_type="application/vnd.google-earth.kml+xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/analyzeContour")
async def analyze_contour(
    contour_map: Annotated[
        UploadFile | None,
        File(description="A .kml or .kmz contour map; preferred field name"),
    ] = None,
    file: Annotated[
        UploadFile | None,
        File(description="Legacy upload field; use contour_map for evaluation"),
    ] = None,
    grid_size: Annotated[
        int,
        Query(
            ge=40,
            le=220,
            description="Number of cells along the longer map dimension.",
        ),
    ] = 100,
    max_candidates: Annotated[int, Query(ge=1, le=5)] = 3,
) -> dict:
    """Analyze a contour map and return pond/catchment recommendations."""
    upload = contour_map or file
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Upload a KML/KMZ file using the multipart field 'contour_map'",
        )

    filename = upload.filename or "uploaded-contours"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"kml", "kmz"}:
        raise HTTPException(status_code=415, detail="Only .kml and .kmz files are supported")

    payload = await upload.read(75 * 1024 * 1024 + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(payload) > 75 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The uploaded file is larger than 75 MB")

    try:
        # CPU-bound: keep it off the event loop so other requests are served.
        return await run_in_threadpool(
            analyze_contour_file,
            payload,
            filename=filename,
            grid_size=grid_size,
            max_candidates=max_candidates,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # keep parser failures as safe API errors
        raise HTTPException(status_code=422, detail="Unable to analyze this contour map") from exc


@app.post("/findCatchment", include_in_schema=False)
async def find_catchment(
    contour_map: Annotated[
        UploadFile | None,
        File(description="A .kml or .kmz contour map; preferred field name"),
    ] = None,
    file: Annotated[
        UploadFile | None,
        File(description="Legacy upload field; use contour_map for evaluation"),
    ] = None,
    grid_size: Annotated[int, Query(ge=40, le=220)] = 100,
    max_candidates: Annotated[int, Query(ge=1, le=5)] = 3,
) -> dict:
    """Backward-compatible alias for /analyzeContour."""
    return await analyze_contour(contour_map, file, grid_size, max_candidates)


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    # Some Windows Python installations register .js as text/plain; module
    # scripts are then rejected by browsers even though the asset exists.
    mimetypes.add_type("text/javascript", ".js", strict=True)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    async def frontend_favicon() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "favicon.svg", media_type="image/svg+xml")
