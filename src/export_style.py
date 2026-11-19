"""Validated appearance settings shared by the preview and KMZ serializer."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


BOUNDARY_COLORS = (
    "#d62728", "#2ca02c", "#1f77b4", "#9467bd", "#ff7f0e",
    "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
)
MAX_LINE_WIDTH = 100.0


class ExportStyleError(ValueError):
    """An appearance validation failure associated with one editable field."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class ExportStyle:
    line_color: str | None = None
    fill_color: str | None = None
    line_width: float = 5.0
    line_opacity: float = 100.0
    fill_opacity: float = 100.0
    mode: str = "outline"

    def __post_init__(self) -> None:
        if self.mode not in ("outline", "fill", "both"):
            raise ExportStyleError("Choose outline, fill, or both.", field="mode")
        for field, label in (("line_color", "Outline color"), ("fill_color", "Fill color")):
            value = getattr(self, field)
            if value is not None:
                if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None:
                    raise ExportStyleError(f"{label} must be a six-digit hex color such as #336699.", field=field)
                object.__setattr__(self, field, value.lower())
        for field, label in (("line_width", "Line width"), ("line_opacity", "Outline opacity"),
                             ("fill_opacity", "Fill opacity")):
            if isinstance(getattr(self, field), bool):
                raise ExportStyleError(f"{label} must be a number, not a Boolean.", field=field)
            try:
                value = float(getattr(self, field))
            except (ValueError, TypeError, OverflowError) as error:
                raise ExportStyleError(f"{label} must be a number.", field=field) from error
            if not math.isfinite(value):
                raise ExportStyleError(f"{label} must be finite.", field=field)
            if field == "line_width" and not 0 < value <= MAX_LINE_WIDTH:
                raise ExportStyleError(
                    f"Line width must be greater than zero and at most {MAX_LINE_WIDTH:g} pixels.", field=field)
            if field != "line_width" and not 0 <= value <= 100:
                raise ExportStyleError(f"{label} must be between 0 and 100 percent.", field=field)
            object.__setattr__(self, field, value)

    def color_for(self, index: int, *, fill: bool = False) -> str:
        selected = self.fill_color if fill else self.line_color
        return selected if selected is not None else BOUNDARY_COLORS[index % len(BOUNDARY_COLORS)]

    def kml_color_for(self, index: int, *, fill: bool = False) -> str:
        """Encode RGB and percent opacity as KML's AABBGGRR bytes."""
        color = self.color_for(index, fill=fill).lstrip("#")
        opacity = self.fill_opacity if fill else self.line_opacity
        alpha = int(opacity * 255.0 / 100.0 + 0.5)
        return f"{alpha:02x}{color[4:6]}{color[2:4]}{color[0:2]}"
