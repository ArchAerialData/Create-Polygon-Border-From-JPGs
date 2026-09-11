"""Immutable buffer requests shared by geometry and the GUI."""
from __future__ import annotations

import math
from dataclasses import dataclass


def distance_ft(value: str | float | None, label: str = "Buffer") -> float:
    try:
        distance = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number in feet.") from exc
    if not math.isfinite(distance) or distance < 0:
        raise ValueError(f"{label} must be finite and 0 or greater.")
    return distance


def seed_side_fields(unified_text: str) -> tuple[str, str]:
    value = distance_ft(unified_text)
    text = unified_text.strip() if value > 0 else "200"
    return text, text


@dataclass(frozen=True)
class BufferSettings:
    mode: str = "unified"
    unified_ft: float | None = 0.0
    left_ft: float | None = None
    right_ft: float | None = None

    def __post_init__(self) -> None:
        if self.mode == "unified":
            object.__setattr__(self, "unified_ft", distance_ft(self.unified_ft))
            if self.left_ft is not None or self.right_ft is not None:
                raise ValueError("Unified buffer cannot contain side distances.")
        elif self.mode == "per_side":
            if self.unified_ft is not None:
                raise ValueError("Per-side buffer cannot contain a unified distance.")
            left = distance_ft(self.left_ft, "Left buffer")
            right = distance_ft(self.right_ft, "Right buffer")
            if left == 0 and right == 0:
                raise ValueError("At least one side buffer must be greater than 0 ft.")
            object.__setattr__(self, "left_ft", left)
            object.__setattr__(self, "right_ft", right)
        else:
            raise ValueError("Unknown buffer mode.")

    @classmethod
    def per_side(cls, left_ft: str | float, right_ft: str | float) -> BufferSettings:
        return cls("per_side", None, left_ft, right_ft)

    @property
    def key(self) -> tuple[str, float | None, float | None]:
        if self.mode == "unified":
            return self.mode, self.unified_ft, None
        return self.mode, self.left_ft, self.right_ft

    @property
    def description(self) -> str:
        if self.mode == "per_side":
            return f"Left {self.left_ft:g} ft / Right {self.right_ft:g} ft"
        return f"{self.unified_ft:g} ft"
