from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .terrain import AnalysisError, analyze_contour_file


app = FastAPI(
    title="AI Village Pond Planning API",
    description=(
        "Analyze uploaded KML/KMZ contour maps and estimate terrain-derived "
        "pond locations and contributing catchments."
    ),
    version="0.1.0",
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

    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(payload) > 75 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The uploaded file is larger than 75 MB")

    try:
        return analyze_contour_file(
            payload,
            filename=filename,
            grid_size=grid_size,
            max_candidates=max_candidates,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # keep parser failures as safe API errors
        raise HTTPException(status_code=422, detail=f"Unable to analyze contour map: {exc}") from exc


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
