"""Grid hydrology helpers for Phase 3 pond screening.

The pond model is a screening impoundment: an embankment of height ``stage``
at a candidate outlet cell holds water only over cells that drain to that
outlet (its D8 catchment). Cells downstream or across the catchment divide are
never counted as storage; where they are lower than the crest they instead
mark where an embankment would be needed.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class Impoundment:
    cells: np.ndarray  # flat indices of flooded cells
    storage_m3: float
    footprint_m2: float
    max_depth_m: float
    embankment_length_m: float


class UpstreamIndex:
    """Compressed reverse D8 graph, built once per analysis."""

    def __init__(self, downstream: np.ndarray):
        flat = downstream.ravel()
        self.shape = downstream.shape
        sources = np.flatnonzero(flat >= 0)
        targets = flat[sources]
        order = np.argsort(targets, kind="stable")
        self.sources = sources[order]
        counts = np.bincount(targets, minlength=flat.size)
        self.offsets = np.concatenate(([0], np.cumsum(counts)))

    def catchment(self, outlet: int) -> np.ndarray:
        """Every cell whose D8 path passes through ``outlet`` (outlet included)."""
        found = [outlet]
        stack = [outlet]
        offsets, sources = self.offsets, self.sources
        while stack:
            current = stack.pop()
            upstream = sources[offsets[current]:offsets[current + 1]]
            if len(upstream):
                found.extend(upstream.tolist())
                stack.extend(upstream.tolist())
        return np.asarray(found, dtype=np.int64)


def impoundment(
    dem: np.ndarray,
    outlet: tuple[int, int],
    stage_m: float,
    catchment_mask: np.ndarray,
    allowed_mask: np.ndarray,
    dx: float,
    dy: float,
    radius_m: float,
) -> Impoundment:
    """Flood connected catchment cells up to ``dem[outlet] + stage_m``."""
    rows, cols = dem.shape
    r0, c0 = outlet
    crest = float(dem[r0, c0]) + stage_m
    cell_area = abs(dx * dy)
    visited = np.zeros(dem.shape, dtype=bool)
    visited[r0, c0] = True
    queue = deque([(r0, c0)])
    cells = [r0 * cols + c0]
    embankment = 0.0
    while queue:
        r, c = queue.popleft()
        for dr, dc, edge in ((-1, 0, dx), (1, 0, dx), (0, -1, dy), (0, 1, dy)):
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols) or visited[rr, cc]:
                continue
            below_crest = dem[rr, cc] <= crest
            if not catchment_mask[rr, cc]:
                # Lower ground outside the catchment is where water would
                # escape; an embankment has to close that edge.
                if below_crest:
                    embankment += abs(edge)
                continue
            if (
                below_crest and allowed_mask[rr, cc]
                and math.hypot((rr - r0) * dy, (cc - c0) * dx) <= radius_m
            ):
                visited[rr, cc] = True
                queue.append((rr, cc))
                cells.append(rr * cols + cc)
    flat = np.asarray(cells, dtype=np.int64)
    depths = np.maximum(0.0, crest - dem.ravel()[flat])
    return Impoundment(
        cells=flat,
        storage_m3=float(depths.sum() * cell_area),
        footprint_m2=float(len(flat) * cell_area),
        max_depth_m=float(depths.max()) if len(depths) else 0.0,
        embankment_length_m=max(embankment, min(abs(dx), abs(dy))),
    )


def candidate_pool(
    accumulation: np.ndarray,
    eligible: np.ndarray,
    min_accumulation_m2: float,
    max_accumulation_m2: float,
    separation_cells: int,
    limit: int = 40,
) -> list[tuple[int, int]]:
    """Spatially separated outlet cells, highest contributing area first."""
    rows, cols = accumulation.shape
    mask = eligible & (accumulation >= min_accumulation_m2) & (accumulation <= max_accumulation_m2)
    flat = np.flatnonzero(mask.ravel())
    if not len(flat):
        return []
    order = flat[np.argsort(-accumulation.ravel()[flat], kind="stable")]
    chosen: list[tuple[int, int]] = []
    for index in order:
        r, c = divmod(int(index), cols)
        if all(max(abs(r - r1), abs(c - c1)) > separation_cells for r1, c1 in chosen):
            chosen.append((r, c))
            if len(chosen) >= limit:
                break
    return chosen


def stage_curve(
    dem: np.ndarray,
    outlet: tuple[int, int],
    catchment_mask: np.ndarray,
    allowed_mask: np.ndarray,
    dx: float,
    dy: float,
    radius_m: float,
    stages: list[float],
) -> list[dict]:
    """Screening stage-area-storage table for one outlet."""
    table = []
    for stage in stages:
        pond = impoundment(dem, outlet, stage, catchment_mask, allowed_mask, dx, dy, radius_m)
        table.append({
            "stage_m": round(stage, 2),
            "area_m2": round(pond.footprint_m2, 1),
            "storage_m3": round(pond.storage_m3, 1),
            "embankment_length_m": round(pond.embankment_length_m, 1),
        })
    return table
