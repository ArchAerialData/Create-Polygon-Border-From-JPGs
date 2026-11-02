from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Any, Callable, Sequence

from matplotlib import patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
from pyproj import CRS, Transformer


SCALE_START_X_FRACTION = 0.03
SCALE_Y_FRACTION = 0.08
SCALE_MAX_WIDTH_FRACTION = 0.25
SCALE_MIN_MILES = 0.01
SCALE_RELATIVE_ERROR_TOLERANCE = 0.0025
SCALE_BISECTION_MAX_ITERATIONS = 48
METRES_PER_STATUTE_MILE = 1609.344

_SCALE_END_X_FRACTION = SCALE_START_X_FRACTION + SCALE_MAX_WIDTH_FRACTION
_MIN_VISIBLE_WIDTH_FRACTION = 0.10
_MONOTONIC_SAMPLE_COUNT = 8
_NO_SIGNATURE = object()
_ARTIST_GID_PREFIX = "jpg-boundary-scale-"


@dataclass(frozen=True)
class ScaleBarSpec:
    start_fraction: float
    end_fraction: float
    y_fraction: float
    miles: float
    label: str
    relative_error: float


def format_miles(miles: float) -> str:
    """Format a valid scale-bar distance with at most two decimal places."""

    try:
        value = float(miles)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Scale mileage must be a finite number.") from exc
    if not math.isfinite(value) or value < SCALE_MIN_MILES:
        raise ValueError("Scale mileage must be at least 0.01 statute miles.")
    label_value = f"{value:.2f}".rstrip("0").rstrip(".")
    if label_value in {"", "-0", "0"}:
        raise ValueError("Scale mileage is too small to display.")
    return f"{label_value} mi"


def select_nice_miles(
    available_miles: float,
    minimum_miles: float = SCALE_MIN_MILES,
) -> float | None:
    """Return the largest 1/2/5 step that fits the available distance."""

    try:
        available = float(available_miles)
        minimum = float(minimum_miles)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(available)
        or not math.isfinite(minimum)
        or available <= 0.0
        or minimum <= 0.0
        or available < minimum
    ):
        return None

    exponent = math.floor(math.log10(available))
    minimum_exponent = math.floor(math.log10(minimum)) - 1
    for candidate_exponent in range(exponent, minimum_exponent - 1, -1):
        magnitude = 10.0**candidate_exponent
        for multiplier in (5.0, 2.0, 1.0):
            candidate = multiplier * magnitude
            if minimum <= candidate <= available:
                return candidate
    return None


def calculate_scale_bar(
    axes: Any | None,
    display_crs: Any,
    *,
    axes_fraction_to_data: Callable[[float, float], Sequence[float]] | None = None,
    xlim: Sequence[float] | None = None,
    ylim: Sequence[float] | None = None,
    axes_pixel_bounds: Sequence[float] | None = None,
) -> ScaleBarSpec | None:
    """Calculate a locally geodesic scale bar for the current rendered view.

    ``None`` is returned for every invalid, unmeasurable, or misleading state.
    The optional transform and view arguments make the calculation testable
    without a GUI or a particular Matplotlib backend.
    """

    try:
        transform, geod = _resolve_geodesic_tools(display_crs)
        mapper, checked_xlim, checked_ylim, checked_bounds = _resolve_view(
            axes,
            axes_fraction_to_data,
            xlim,
            ylim,
            axes_pixel_bounds,
        )
        if not _valid_view(checked_xlim, checked_ylim, checked_bounds):
            return None

        start_data = _map_axes_fraction(
            mapper,
            SCALE_START_X_FRACTION,
            SCALE_Y_FRACTION,
        )
        start_geodetic = _to_geodetic(transform, start_data)

        def measure(end_fraction: float) -> float | None:
            end_data = _map_axes_fraction(
                mapper,
                end_fraction,
                SCALE_Y_FRACTION,
            )
            end_geodetic = _to_geodetic(transform, end_data)
            _forward_azimuth, _back_azimuth, distance_metres = geod.inv(
                start_geodetic[0],
                start_geodetic[1],
                end_geodetic[0],
                end_geodetic[1],
            )
            distance_miles = abs(float(distance_metres)) / METRES_PER_STATUTE_MILE
            if not math.isfinite(distance_miles):
                return None
            return distance_miles

        sampled_distances: list[float] = []
        previous_distance = 0.0
        for index in range(1, _MONOTONIC_SAMPLE_COUNT + 1):
            fraction = SCALE_START_X_FRACTION + (
                SCALE_MAX_WIDTH_FRACTION * index / _MONOTONIC_SAMPLE_COUNT
            )
            sampled_distance = measure(fraction)
            if sampled_distance is None:
                return None
            monotonic_slack = max(1.0e-12, previous_distance * 1.0e-10)
            if sampled_distance + monotonic_slack < previous_distance:
                return None
            sampled_distances.append(sampled_distance)
            previous_distance = sampled_distance

        available_miles = sampled_distances[-1]
        target_miles = select_nice_miles(available_miles)
        if target_miles is None:
            return None

        low_fraction = SCALE_START_X_FRACTION
        low_distance = 0.0
        high_fraction = _SCALE_END_X_FRACTION
        high_distance = available_miles
        best_fraction = high_fraction
        best_relative_error = _relative_error(high_distance, target_miles)

        for _iteration in range(SCALE_BISECTION_MAX_ITERATIONS):
            candidate_fraction = (low_fraction + high_fraction) / 2.0
            candidate_distance = measure(candidate_fraction)
            if candidate_distance is None:
                return None
            bracket_slack = max(1.0e-12, high_distance * 1.0e-10)
            if (
                candidate_distance + bracket_slack < low_distance
                or candidate_distance > high_distance + bracket_slack
            ):
                return None

            candidate_error = _relative_error(candidate_distance, target_miles)
            if candidate_error < best_relative_error:
                best_fraction = candidate_fraction
                best_relative_error = candidate_error
            if candidate_error <= SCALE_RELATIVE_ERROR_TOLERANCE:
                best_fraction = candidate_fraction
                break
            if candidate_distance < target_miles:
                low_fraction = candidate_fraction
                low_distance = candidate_distance
            else:
                high_fraction = candidate_fraction
                high_distance = candidate_distance

        final_distance = measure(best_fraction)
        if final_distance is None:
            return None
        final_relative_error = _relative_error(final_distance, target_miles)
        visual_width = best_fraction - SCALE_START_X_FRACTION
        if (
            final_relative_error > SCALE_RELATIVE_ERROR_TOLERANCE
            or visual_width < _MIN_VISIBLE_WIDTH_FRACTION - 1.0e-12
            or visual_width > SCALE_MAX_WIDTH_FRACTION + 1.0e-12
        ):
            return None

        return ScaleBarSpec(
            start_fraction=SCALE_START_X_FRACTION,
            end_fraction=best_fraction,
            y_fraction=SCALE_Y_FRACTION,
            miles=target_miles,
            label=format_miles(target_miles),
            relative_error=final_relative_error,
        )
    except Exception:
        return None


class ScaleBarController:
    """Own and refresh one passive scale-bar artist group for one axes."""

    def __init__(self, axes: Any, canvas: Any | None = None) -> None:
        self.axes = axes
        self.canvas = canvas if canvas is not None else axes.figure.canvas
        self._bound = False
        self._display_crs: Any = None
        self._result_generation: Any = None
        self._signature: object | tuple[Any, ...] = _NO_SIGNATURE
        self._spec: ScaleBarSpec | None = None
        self._background: FancyBboxPatch | None = None
        self._line: Line2D | None = None
        self._ticks: Line2D | None = None
        self._label: Any | None = None

    @property
    def spec(self) -> ScaleBarSpec | None:
        return self._spec

    def bind_result(self, display_crs: Any, result_generation: Any) -> bool:
        """Bind the controller to a displayed result and invalidate its view."""

        try:
            identity = _crs_identity(display_crs)
            current_identity = _crs_identity(self._display_crs)
            changed = (
                not self._bound
                or identity != current_identity
                or result_generation != self._result_generation
            )
        except Exception:
            changed = True
        self._bound = True
        self._display_crs = display_crs
        self._result_generation = result_generation
        if changed:
            self._signature = _NO_SIGNATURE
        return changed

    def refresh(self) -> bool:
        """Refresh artists for the current view without registering callbacks."""

        try:
            if not self._bound or self._display_crs is None:
                changed = self._remove_artists()
                self._spec = None
                return changed

            signature = self._view_signature()
            if (
                signature == self._signature
                and self._spec is not None
                and self._artists_attached()
            ):
                return False
            if signature == self._signature and self._spec is None:
                return self._remove_artists()
            if (
                signature == self._signature
                and self._spec is not None
                and not self._artists_attached()
            ):
                self._remove_artists()
                self._apply_spec(self._spec)
                return True

            spec = calculate_scale_bar(self.axes, self._display_crs)
            self._signature = signature
            self._spec = spec
            if spec is None:
                self._remove_artists()
                return True
            self._apply_spec(spec)
            return True
        except Exception:
            changed = self._remove_artists()
            self._spec = None
            self._signature = _NO_SIGNATURE
            return changed

    def clear(self) -> bool:
        """Remove all artists and forget the currently bound result."""

        was_bound = self._bound
        had_state = self._spec is not None or self._signature is not _NO_SIGNATURE
        changed = self._remove_artists()
        self._bound = False
        self._display_crs = None
        self._result_generation = None
        self._signature = _NO_SIGNATURE
        self._spec = None
        return changed or was_bound or had_state

    def _view_signature(self) -> tuple[Any, ...]:
        xlim = _finite_signature_pair(self.axes.get_xlim())
        ylim = _finite_signature_pair(self.axes.get_ylim())
        bounds = _finite_signature_values(self.axes.get_window_extent().bounds, 4)
        dpi = _signature_number(self.axes.figure.dpi)
        return (
            _crs_identity(self._display_crs),
            _safe_signature_value(self._result_generation),
            xlim,
            ylim,
            bounds,
            dpi,
        )

    def _artists_attached(self) -> bool:
        return (
            self._background is not None
            and any(item is self._background for item in self.axes.patches)
            and self._line is not None
            and any(item is self._line for item in self.axes.lines)
            and self._ticks is not None
            and any(item is self._ticks for item in self.axes.lines)
            and self._label is not None
            and any(item is self._label for item in self.axes.texts)
        )

    def _apply_spec(self, spec: ScaleBarSpec) -> None:
        if not self._artists_attached():
            self._remove_artists()
            self._create_artists()

        start = spec.start_fraction
        end = spec.end_fraction
        y = spec.y_fraction
        tick_half_height = 0.013
        background_x = start - 0.012
        background_y = y - 0.035
        background_width = end - start + 0.024
        background_height = 0.086

        assert self._background is not None
        assert self._line is not None
        assert self._ticks is not None
        assert self._label is not None
        self._background.set_bounds(
            background_x,
            background_y,
            background_width,
            background_height,
        )
        self._line.set_data((start, end), (y, y))
        self._ticks.set_data(
            (start, start, math.nan, end, end),
            (
                y - tick_half_height,
                y + tick_half_height,
                math.nan,
                y - tick_half_height,
                y + tick_half_height,
            ),
        )
        self._label.set_position(((start + end) / 2.0, y + 0.019))
        self._label.set_text(spec.label)

    def _create_artists(self) -> None:
        axes_transform = self.axes.transAxes
        self._background = FancyBboxPatch(
            (0.0, 0.0),
            0.1,
            0.08,
            boxstyle="round,pad=0.006,rounding_size=0.008",
            transform=axes_transform,
            facecolor="#0B1220",
            edgecolor="#CBD5E1",
            linewidth=0.8,
            alpha=0.84,
            clip_on=False,
            zorder=998,
        )
        self._background.set_gid(f"{_ARTIST_GID_PREFIX}background")
        self.axes.add_patch(self._background)

        self._line = Line2D(
            (),
            (),
            transform=axes_transform,
            color="#F8FAFC",
            linewidth=2.4,
            solid_capstyle="butt",
            clip_on=False,
            zorder=1000,
        )
        self._line.set_gid(f"{_ARTIST_GID_PREFIX}line")
        self._line.set_path_effects(
            [patheffects.Stroke(linewidth=4.2, foreground="#020617"), patheffects.Normal()]
        )
        self.axes.add_line(self._line)

        self._ticks = Line2D(
            (),
            (),
            transform=axes_transform,
            color="#F8FAFC",
            linewidth=2.0,
            solid_capstyle="butt",
            clip_on=False,
            zorder=1001,
        )
        self._ticks.set_gid(f"{_ARTIST_GID_PREFIX}ticks")
        self._ticks.set_path_effects(
            [patheffects.Stroke(linewidth=3.8, foreground="#020617"), patheffects.Normal()]
        )
        self.axes.add_line(self._ticks)

        self._label = self.axes.text(
            0.0,
            0.0,
            "",
            transform=axes_transform,
            color="#F8FAFC",
            fontsize=9,
            fontweight="semibold",
            horizontalalignment="center",
            verticalalignment="bottom",
            clip_on=False,
            zorder=1002,
            path_effects=[
                patheffects.Stroke(linewidth=2.4, foreground="#020617"),
                patheffects.Normal(),
            ],
        )
        self._label.set_gid(f"{_ARTIST_GID_PREFIX}label")

    def _remove_artists(self) -> bool:
        artists = (self._background, self._line, self._ticks, self._label)
        changed = any(artist is not None for artist in artists)
        for artist in artists:
            if artist is None:
                continue
            try:
                artist.remove()
            except Exception:
                pass
        self._background = None
        self._line = None
        self._ticks = None
        self._label = None
        return changed


@lru_cache(maxsize=32)
def _cached_geodesic_tools(crs_wkt: str) -> tuple[Transformer, Any]:
    crs = CRS.from_wkt(crs_wkt)
    geodetic_crs = crs.geodetic_crs
    if geodetic_crs is None:
        raise ValueError("Display CRS has no geodetic CRS.")
    transformer = Transformer.from_crs(crs, geodetic_crs, always_xy=True)
    return transformer, crs.get_geod()


def _resolve_geodesic_tools(display_crs: Any) -> tuple[Transformer, Any]:
    crs = CRS.from_user_input(display_crs)
    return _cached_geodesic_tools(crs.to_wkt())


def _resolve_view(
    axes: Any | None,
    axes_fraction_to_data: Callable[[float, float], Sequence[float]] | None,
    xlim: Sequence[float] | None,
    ylim: Sequence[float] | None,
    axes_pixel_bounds: Sequence[float] | None,
) -> tuple[
    Callable[[float, float], Sequence[float]],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float, float, float],
]:
    if xlim is None:
        if axes is None:
            raise ValueError("Explicit x limits are required without axes.")
        xlim = axes.get_xlim()
    if ylim is None:
        if axes is None:
            raise ValueError("Explicit y limits are required without axes.")
        ylim = axes.get_ylim()
    if axes_pixel_bounds is None:
        if axes is None:
            raise ValueError("Explicit axes bounds are required without axes.")
        axes_pixel_bounds = axes.get_window_extent().bounds

    checked_xlim = _finite_values(xlim, 2)
    checked_ylim = _finite_values(ylim, 2)
    checked_bounds = _finite_values(axes_pixel_bounds, 4)

    if axes_fraction_to_data is None:
        if axes is None:
            raise ValueError("Axes or an injected transform is required.")

        def mapper(x_fraction: float, y_fraction: float) -> Sequence[float]:
            display_point = axes.transAxes.transform((x_fraction, y_fraction))
            return axes.transData.inverted().transform(display_point)

    else:
        mapper = axes_fraction_to_data
    return mapper, checked_xlim, checked_ylim, checked_bounds


def _valid_view(
    xlim: tuple[float, float],
    ylim: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    return (
        xlim[0] != xlim[1]
        and ylim[0] != ylim[1]
        and bounds[2] > 0.0
        and bounds[3] > 0.0
    )


def _map_axes_fraction(
    mapper: Callable[[float, float], Sequence[float]],
    x_fraction: float,
    y_fraction: float,
) -> tuple[float, float]:
    return _finite_values(mapper(x_fraction, y_fraction), 2)


def _to_geodetic(
    transformer: Transformer,
    point: tuple[float, float],
) -> tuple[float, float]:
    longitude, latitude = transformer.transform(point[0], point[1], errcheck=True)
    return _finite_values((longitude, latitude), 2)


def _relative_error(measured: float, target: float) -> float:
    if target <= 0.0:
        return math.inf
    return abs(measured - target) / target


def _finite_values(values: Sequence[float], length: int) -> tuple[Any, ...]:
    if len(values) != length:
        raise ValueError("Unexpected coordinate length.")
    converted = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in converted):
        raise ValueError("Coordinates must be finite.")
    return converted


def _finite_signature_pair(values: Sequence[float]) -> tuple[Any, Any]:
    return _finite_signature_values(values, 2)


def _finite_signature_values(
    values: Sequence[float],
    length: int,
) -> tuple[Any, ...]:
    if len(values) != length:
        return ("invalid-length", len(values))
    return tuple(_signature_number(value) for value in values)


def _signature_number(value: Any) -> float | str:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return f"invalid:{type(value).__name__}"
    if math.isnan(converted):
        return "nan"
    if math.isinf(converted):
        return "inf" if converted > 0.0 else "-inf"
    return converted


def _crs_identity(display_crs: Any) -> str:
    try:
        return CRS.from_user_input(display_crs).to_wkt()
    except Exception:
        return f"invalid:{_safe_signature_value(display_crs)!r}"


def _safe_signature_value(value: Any) -> Any:
    try:
        hash(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<{type(value).__name__}>"
    return value


__all__ = [
    "SCALE_START_X_FRACTION",
    "SCALE_Y_FRACTION",
    "SCALE_MAX_WIDTH_FRACTION",
    "SCALE_MIN_MILES",
    "SCALE_RELATIVE_ERROR_TOLERANCE",
    "SCALE_BISECTION_MAX_ITERATIONS",
    "METRES_PER_STATUTE_MILE",
    "ScaleBarSpec",
    "format_miles",
    "select_nice_miles",
    "calculate_scale_bar",
    "ScaleBarController",
]
