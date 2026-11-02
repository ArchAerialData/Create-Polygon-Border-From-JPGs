"""Classify per-side inputs without building buffers or loading GUI libraries."""
from __future__ import annotations

import argparse
import json
import math
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from kml_vector_input import VectorInputGeometry, load_vector_input


@dataclass(frozen=True)
class PolylineCompatibility:
    eligible: bool
    reason_code: str
    explanation: str
    line_count: int = 0


def classify_per_side_input(source: VectorInputGeometry) -> PolylineCompatibility:
    count = len(source.lines_wgs84)

    def reject(code: str, text: str) -> PolylineCompatibility:
        return PolylineCompatibility(False, code, text, count)

    if source.source_path.suffix.lower() != ".kmz":
        return reject("not_kmz", "Per-side buffers require a polyline-only KMZ.")
    if not count:
        return reject("no_lines", "The input contains no source polylines.")
    if source.geometry_inventory is None:
        return reject("unverified", "The source geometry inventory has not been checked.")
    if set(source.geometry_inventory) - {"LineString", "MultiGeometry"}:
        return reject("mixed_geometry", "The KMZ contains geometry other than polylines.")
    for line in source.lines_wgs84:
        if line.is_empty or line.length <= 0 or not line.is_valid:
            return reject("invalid_line", "A source polyline is empty or invalid.")
        if any(not math.isfinite(v) for coordinate in line.coords for v in coordinate):
            return reject("invalid_coordinates", "A source coordinate is not finite.")
        if any(not (-180 <= c[0] <= 180 and -90 <= c[1] <= 90) for c in line.coords):
            return reject("invalid_coordinates", "A source coordinate is outside WGS84 bounds.")
        if line.is_closed:
            return reject("closed_line", "Closed polylines are not supported in per-side mode.")
        if not line.is_simple:
            return reject("self_crossing", "Self-crossing polylines are not supported in per-side mode.")
    return PolylineCompatibility(True, "eligible", "Left/right follows each source line's arrows.", count)


def source_identity(path: Path) -> tuple[str, int, int] | None:
    """Identity for vector-file caching; folder imports keep their existing policy."""
    resolved = path.resolve()
    info = resolved.stat()
    if stat.S_ISDIR(info.st_mode):
        # Exporting into a JPG folder changes its mtime without changing input photos.
        return None
    return str(resolved).casefold(), info.st_size, info.st_mtime_ns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        result = classify_per_side_input(load_vector_input(args.input))
    except (ValueError, OSError) as exc:
        result = PolylineCompatibility(False, "read_error", str(exc))
    print(json.dumps(asdict(result)))
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
