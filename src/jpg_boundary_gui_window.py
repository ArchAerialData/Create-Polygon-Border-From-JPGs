"""Monitor-aware sizing for Tk application and child windows.

The process remains in its existing DPI-awareness mode. Win32 work areas,
Tk geometry requests, and measured outer bounds therefore stay in the same
virtualized coordinate space.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any


MONITOR_DEFAULTTOPRIMARY = 0x00000001
MONITOR_DEFAULTTONEAREST = 0x00000002
FRAME_RESERVE_WIDTH = 32
FRAME_RESERVE_HEIGHT = 64
# Descriptive aliases retained for callers that prefer an explicit default.
DEFAULT_FRAME_RESERVE_WIDTH = FRAME_RESERVE_WIDTH
DEFAULT_FRAME_RESERVE_HEIGHT = FRAME_RESERVE_HEIGHT
MAX_MEASURED_FIT_PASSES = 3

HWND = wintypes.HWND
HMONITOR = wintypes.HANDLE


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class MONITORINFO(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    )

    def __init__(self) -> None:
        super().__init__()
        self.cbSize = ctypes.sizeof(type(self))


@dataclass(frozen=True)
class WorkArea:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left:
            raise ValueError("Work-area width must be positive.")
        if self.bottom <= self.top:
            raise ValueError("Work-area height must be positive.")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class WindowGeometry:
    width: int
    height: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("Window width must be positive.")
        if self.height <= 0:
            raise ValueError("Window height must be positive.")

    def to_tk_geometry(self) -> str:
        # Tk interprets a bare negative position as an offset from the right or
        # bottom edge. Prefixing every coordinate with "+" keeps a negative
        # virtual-screen coordinate absolute (for example, "+-1000").
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


@dataclass(frozen=True)
class OuterWindowBounds:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left:
            raise ValueError("Outer window width must be positive.")
        if self.bottom <= self.top:
            raise ValueError("Outer window height must be positive.")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def is_within(self, work_area: WorkArea) -> bool:
        return (
            self.left >= work_area.left
            and self.top >= work_area.top
            and self.right <= work_area.right
            and self.bottom <= work_area.bottom
        )


@dataclass(frozen=True)
class WindowFitResult:
    geometry: WindowGeometry
    outer_bounds: OuterWindowBounds | None
    contained: bool
    used_reserve_fallback: bool
    warning: str | None = None


def _configure_user32(user32: Any) -> Any:
    """Attach pointer-width-safe signatures to the Win32 calls we use."""

    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = HMONITOR
    user32.MonitorFromWindow.argtypes = [HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = HMONITOR
    user32.GetMonitorInfoW.argtypes = [
        HMONITOR,
        ctypes.POINTER(MONITORINFO),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetParent.argtypes = [HWND]
    user32.GetParent.restype = HWND
    return user32


def _load_user32() -> Any | None:
    if sys.platform != "win32":
        return None
    try:
        return _configure_user32(ctypes.windll.user32)
    except (AttributeError, OSError):
        return None


def _get_user32() -> Any | None:
    """Compatibility indirection for callers/tests that patch either name."""

    return _load_user32()


def _handle_value(handle: Any) -> int | None:
    value = getattr(handle, "value", handle)
    if value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if numeric else None


def _monitor_work_area(user32: Any, monitor: Any) -> WorkArea | None:
    if _handle_value(monitor) is None:
        return None
    try:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        return WorkArea(
            int(info.rcWork.left),
            int(info.rcWork.top),
            int(info.rcWork.right),
            int(info.rcWork.bottom),
        )
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        TypeError,
        ValueError,
    ):
        return None


def _work_area_from_monitor(
    user32: Any,
    monitor: Any,
) -> WorkArea | None:
    """Compatibility alias with a descriptive provider-oriented name."""

    return _monitor_work_area(user32, monitor)


def _get_windows_cursor_work_area() -> WorkArea | None:
    user32 = _get_user32()
    if user32 is None:
        return None
    try:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        monitor = user32.MonitorFromPoint(
            point,
            MONITOR_DEFAULTTONEAREST,
        )
        return _monitor_work_area(user32, monitor)
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        TypeError,
        ValueError,
    ):
        return None


def get_toplevel_hwnd(window: tk.Misc) -> int | None:
    """Return Tk's decorated wrapper HWND, retaining full pointer width."""

    try:
        window.update_idletasks()
    except (AttributeError, tk.TclError):
        pass

    try:
        frame_value = window.frame()
        frame_handle = int(str(frame_value), 0)
        if frame_handle:
            return frame_handle
    except (AttributeError, TypeError, ValueError, tk.TclError):
        pass

    try:
        content_handle = int(window.winfo_id())
    except (AttributeError, TypeError, ValueError, tk.TclError):
        return None
    if not content_handle:
        return None

    user32 = _get_user32()
    if user32 is not None:
        try:
            parent_handle = _handle_value(user32.GetParent(content_handle))
            if parent_handle is not None:
                return parent_handle
        except (
            AttributeError,
            ctypes.ArgumentError,
            OSError,
            TypeError,
            ValueError,
        ):
            pass
    return content_handle


def _get_windows_window_work_area(window: tk.Misc) -> WorkArea | None:
    user32 = _get_user32()
    if user32 is None:
        return None
    try:
        hwnd = get_toplevel_hwnd(window)
        if hwnd is None:
            return None
        monitor = user32.MonitorFromWindow(
            hwnd,
            MONITOR_DEFAULTTONEAREST,
        )
        return _monitor_work_area(user32, monitor)
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        tk.TclError,
        TypeError,
        ValueError,
    ):
        return None


def _get_windows_primary_work_area() -> WorkArea | None:
    user32 = _get_user32()
    if user32 is None:
        return None
    try:
        monitor = user32.MonitorFromPoint(
            POINT(0, 0),
            MONITOR_DEFAULTTOPRIMARY,
        )
        return _monitor_work_area(user32, monitor)
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        TypeError,
        ValueError,
    ):
        return None


def _get_tk_primary_fallback(root: tk.Misc) -> WorkArea:
    # Do not use winfo_vroot*: its union can include gaps between monitors.
    return WorkArea(
        0,
        0,
        int(root.winfo_screenwidth()),
        int(root.winfo_screenheight()),
    )


def get_launch_work_area(root: tk.Misc) -> WorkArea:
    """Resolve the pointer monitor, then root, primary, and Tk fallbacks."""

    for provider in (
        _get_windows_cursor_work_area,
        lambda: _get_windows_window_work_area(root),
        _get_windows_primary_work_area,
    ):
        try:
            work_area = provider()
        except Exception:
            work_area = None
        if work_area is not None:
            return work_area
    return _get_tk_primary_fallback(root)


def get_window_work_area(window: tk.Misc) -> WorkArea:
    """Resolve the monitor containing a supplied root or child window."""

    for provider in (
        lambda: _get_windows_window_work_area(window),
        _get_windows_primary_work_area,
    ):
        try:
            work_area = provider()
        except Exception:
            work_area = None
        if work_area is not None:
            return work_area
    return _get_tk_primary_fallback(window)


def _get_windows_outer_bounds(
    window: tk.Misc,
) -> OuterWindowBounds | None:
    user32 = _get_user32()
    if user32 is None:
        return None
    try:
        hwnd = get_toplevel_hwnd(window)
        if hwnd is None:
            return None
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return OuterWindowBounds(
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        tk.TclError,
        TypeError,
        ValueError,
    ):
        return None


def calculate_initial_geometry(
    work_area: WorkArea,
    ideal_width: int = 1440,
    ideal_height: int = 900,
    max_fraction: float = 0.90,
) -> WindowGeometry:
    if ideal_width <= 0 or ideal_height <= 0:
        raise ValueError("Ideal window dimensions must be positive.")
    if not 0 < max_fraction <= 1:
        raise ValueError("Maximum work-area fraction must be in (0, 1].")

    width = max(1, min(ideal_width, int(work_area.width * max_fraction)))
    height = max(1, min(ideal_height, int(work_area.height * max_fraction)))
    x = work_area.left + (work_area.width - width) // 2
    y = work_area.top + (work_area.height - height) // 2
    return WindowGeometry(width, height, x, y)


def calculate_adaptive_minimum(
    work_area: WorkArea,
    base_width: int = 960,
    base_height: int = 600,
) -> tuple[int, int]:
    if base_width <= 0 or base_height <= 0:
        raise ValueError("Base minimum dimensions must be positive.")
    initial = calculate_initial_geometry(work_area)
    return (
        min(base_width, initial.width),
        min(base_height, initial.height),
    )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    if maximum < minimum:
        return minimum
    return max(minimum, min(value, maximum))


def _centered_outer_origin(
    desired: WindowGeometry,
    outer_width: int,
    outer_height: int,
    work_area: WorkArea,
) -> tuple[int, int]:
    target_center_x = desired.x + desired.width // 2
    target_center_y = desired.y + desired.height // 2
    left = (2 * target_center_x - outer_width) // 2
    top = (2 * target_center_y - outer_height) // 2
    return (
        _clamp(left, work_area.left, work_area.right - outer_width),
        _clamp(top, work_area.top, work_area.bottom - outer_height),
    )


def _reserved_geometry(
    desired: WindowGeometry,
    work_area: WorkArea,
) -> WindowGeometry:
    width = min(
        desired.width,
        max(1, work_area.width - DEFAULT_FRAME_RESERVE_WIDTH),
    )
    height = min(
        desired.height,
        max(1, work_area.height - DEFAULT_FRAME_RESERVE_HEIGHT),
    )
    reserved_outer_width = min(
        work_area.width,
        width + DEFAULT_FRAME_RESERVE_WIDTH,
    )
    reserved_outer_height = min(
        work_area.height,
        height + DEFAULT_FRAME_RESERVE_HEIGHT,
    )
    x, y = _centered_outer_origin(
        desired,
        reserved_outer_width,
        reserved_outer_height,
        work_area,
    )
    return WindowGeometry(width, height, x, y)


def _apply_geometry(window: tk.Misc, geometry: WindowGeometry) -> None:
    window.geometry(geometry.to_tk_geometry())
    window.update_idletasks()


def _safe_outer_bounds(window: tk.Misc) -> OuterWindowBounds | None:
    try:
        return _get_windows_outer_bounds(window)
    except Exception:
        # Provider/compositor failures are diagnostic, not launcher-fatal.
        return None


def get_outer_window_bounds(window: tk.Misc) -> OuterWindowBounds | None:
    """Return best-effort decorated bounds without exposing provider failures."""

    return _safe_outer_bounds(window)


def _fit_realized_window_to_work_area(
    window: tk.Misc,
    work_area: WorkArea,
    desired_client_geometry: WindowGeometry,
) -> WindowFitResult:
    """Fit a realized decorated window without making startup fatal."""

    current = desired_client_geometry
    last_bounds: OuterWindowBounds | None = None

    for _pass_number in range(MAX_MEASURED_FIT_PASSES):
        _apply_geometry(window, current)
        last_bounds = _safe_outer_bounds(window)
        if last_bounds is None:
            break

        frame_width = max(0, last_bounds.width - current.width)
        frame_height = max(0, last_bounds.height - current.height)
        left_offset = last_bounds.left - current.x
        top_offset = last_bounds.top - current.y

        next_width = max(
            1,
            min(current.width, work_area.width - frame_width),
        )
        next_height = max(
            1,
            min(current.height, work_area.height - frame_height),
        )
        estimated_outer_width = min(
            work_area.width,
            next_width + frame_width,
        )
        estimated_outer_height = min(
            work_area.height,
            next_height + frame_height,
        )
        target_outer_x, target_outer_y = _centered_outer_origin(
            desired_client_geometry,
            estimated_outer_width,
            estimated_outer_height,
            work_area,
        )
        next_geometry = WindowGeometry(
            next_width,
            next_height,
            target_outer_x - left_offset,
            target_outer_y - top_offset,
        )

        if next_geometry == current and last_bounds.is_within(work_area):
            return WindowFitResult(
                geometry=current,
                outer_bounds=last_bounds,
                contained=True,
                used_reserve_fallback=False,
            )
        current = next_geometry

    fallback = _reserved_geometry(desired_client_geometry, work_area)
    _apply_geometry(window, fallback)
    fallback_bounds = _safe_outer_bounds(window)
    contained = (
        fallback_bounds is not None
        and fallback_bounds.is_within(work_area)
    )
    return WindowFitResult(
        geometry=fallback,
        outer_bounds=fallback_bounds,
        contained=contained,
        used_reserve_fallback=True,
        warning=(
            "Window-frame measurement was unavailable or did not converge; "
            "a conservative monitor-safe size was applied."
        ),
    )


def fit_window_to_work_area(
    window: tk.Misc,
    work_area: WorkArea | None = None,
    *,
    max_fraction: float = 0.94,
) -> WindowFitResult:
    """Fit a realized window to a centered fraction of its current work area."""

    selected_work_area = work_area or get_window_work_area(window)
    desired = calculate_initial_geometry(
        selected_work_area,
        ideal_width=selected_work_area.width,
        ideal_height=selected_work_area.height,
        max_fraction=max_fraction,
    )
    return _fit_realized_window_to_work_area(
        window,
        selected_work_area,
        desired,
    )


def apply_initial_geometry(
    root: tk.Misc,
    work_area: WorkArea | None = None,
) -> WindowFitResult:
    selected_work_area = work_area or get_launch_work_area(root)
    desired = calculate_initial_geometry(selected_work_area)
    result = _fit_realized_window_to_work_area(
        root,
        selected_work_area,
        desired,
    )
    minimum_width, minimum_height = calculate_adaptive_minimum(
        selected_work_area,
    )
    root.minsize(
        min(minimum_width, result.geometry.width),
        min(minimum_height, result.geometry.height),
    )
    return result


def _window_outer_or_tk_bounds(window: tk.Misc) -> OuterWindowBounds:
    outer = _safe_outer_bounds(window)
    if outer is not None:
        return outer
    try:
        window.update_idletasks()
    except (AttributeError, tk.TclError):
        pass
    width = max(1, int(window.winfo_width()))
    height = max(1, int(window.winfo_height()))
    left = int(window.winfo_rootx())
    top = int(window.winfo_rooty())
    return OuterWindowBounds(left, top, left + width, top + height)


def _requested_window_size(window: tk.Misc) -> tuple[int, int]:
    try:
        window.update_idletasks()
    except (AttributeError, tk.TclError):
        pass
    try:
        width = int(window.winfo_width())
        height = int(window.winfo_height())
        if width > 1 and height > 1:
            return width, height
    except (AttributeError, TypeError, ValueError, tk.TclError):
        pass
    return (
        max(1, int(window.winfo_reqwidth())),
        max(1, int(window.winfo_reqheight())),
    )


def clamp_child_geometry(
    parent: tk.Misc,
    child: tk.Misc,
    work_area: WorkArea | None = None,
) -> WindowFitResult:
    selected_work_area = work_area or get_window_work_area(parent)
    parent_bounds = _window_outer_or_tk_bounds(parent)
    child_width, child_height = _requested_window_size(child)
    child_width = min(child_width, selected_work_area.width)
    child_height = min(child_height, selected_work_area.height)

    x = parent_bounds.left + (parent_bounds.width - child_width) // 2
    y = parent_bounds.top + (parent_bounds.height - child_height) // 2
    x = _clamp(
        x,
        selected_work_area.left,
        selected_work_area.right - child_width,
    )
    y = _clamp(
        y,
        selected_work_area.top,
        selected_work_area.bottom - child_height,
    )
    desired = WindowGeometry(child_width, child_height, x, y)
    return _fit_realized_window_to_work_area(
        child,
        selected_work_area,
        desired,
    )
