from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SyntheticGpsPoint:
    path: Path
    lat: float
    lon: float
    capture_time: datetime | None = None


def synthetic_point(
    name: str,
    x: float,
    y: float,
    capture_time: datetime | None = None,
) -> SyntheticGpsPoint:
    return SyntheticGpsPoint(Path(name), y, x, capture_time)


def points_from_xy(
    coordinates: list[tuple[float, float]],
    *,
    prefix: str = "img",
    capture_times: list[datetime | None] | None = None,
) -> tuple[list[SyntheticGpsPoint], np.ndarray]:
    times = capture_times or [None] * len(coordinates)
    points = [
        synthetic_point(f"{prefix}_{index:03d}.jpg", x, y, times[index])
        for index, (x, y) in enumerate(coordinates)
    ]
    return points, np.array(coordinates, dtype=float)


def lawnmower_xy(
    *,
    rows: int = 5,
    columns: int = 8,
    spacing: float = 20.0,
    row_gap: float = 12.0,
) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    for row in range(rows):
        xs = [column * spacing for column in range(columns)]
        if row % 2:
            xs.reverse()
        y = row * row_gap
        coordinates.extend((x, y) for x in xs)
    return coordinates


def rectangle_trace_xy(width: float = 100.0, height: float = 60.0) -> list[tuple[float, float]]:
    return [
        (0, 0),
        (25, 0),
        (50, 0),
        (75, 0),
        (100, 0),
        (100, 20),
        (100, 40),
        (100, 60),
        (75, 60),
        (50, 60),
        (25, 60),
        (0, 60),
        (0, 40),
        (0, 20),
    ]
