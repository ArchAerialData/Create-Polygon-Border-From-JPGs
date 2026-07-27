from __future__ import annotations

import ctypes
import re
import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import jpg_boundary_gui_window as windowing  # noqa: E402
from jpg_boundary_gui_window import (  # noqa: E402
    DEFAULT_FRAME_RESERVE_HEIGHT,
    DEFAULT_FRAME_RESERVE_WIDTH,
    MONITORINFO,
    OuterWindowBounds,
    WindowGeometry,
    WorkArea,
    apply_initial_geometry,
    calculate_adaptive_minimum,
    calculate_initial_geometry,
    clamp_child_geometry,
    fit_window_to_work_area,
    get_launch_work_area,
    get_toplevel_hwnd,
    get_window_work_area,
)


_GEOMETRY_RE = re.compile(
    r"^(?P<width>\d+)x(?P<height>\d+)"
    r"\+(?P<x>-?\d+)\+(?P<y>-?\d+)$"
)


class _FakeWindow:
    def __init__(
        self,
        *,
        width: int = 400,
        height: int = 300,
        x: int = 0,
        y: int = 0,
        screen_width: int = 1920,
        screen_height: int = 1080,
        hwnd: int = 100,
    ) -> None:
        self.current_geometry = WindowGeometry(width, height, x, y)
        self.requested_width = width
        self.requested_height = height
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.hwnd = hwnd
        self.geometry_calls: list[WindowGeometry] = []
        self.minimum: tuple[int, int] | None = None
        self.idle_updates = 0

    def geometry(self, value: str) -> None:
        match = _GEOMETRY_RE.fullmatch(value)
        if match is None:
            raise AssertionError(f"unexpected Tk geometry: {value!r}")
        values = {key: int(item) for key, item in match.groupdict().items()}
        self.current_geometry = WindowGeometry(
            values["width"], values["height"], values["x"], values["y"]
        )
        self.geometry_calls.append(self.current_geometry)

    def update_idletasks(self) -> None:
        self.idle_updates += 1

    def minsize(self, width: int, height: int) -> None:
        self.minimum = (width, height)

    def winfo_width(self) -> int:
        return self.current_geometry.width

    def winfo_height(self) -> int:
        return self.current_geometry.height

    def winfo_reqwidth(self) -> int:
        return self.requested_width

    def winfo_reqheight(self) -> int:
        return self.requested_height

    def winfo_rootx(self) -> int:
        return self.current_geometry.x

    def winfo_rooty(self) -> int:
        return self.current_geometry.y

    def winfo_screenwidth(self) -> int:
        return self.screen_width

    def winfo_screenheight(self) -> int:
        return self.screen_height

    def winfo_id(self) -> int:
        return self.hwnd


class _FailIfVirtualRootQueried(_FakeWindow):
    def winfo_vrootx(self) -> int:
        raise AssertionError("virtual-root origin must not be queried")

    def winfo_vrooty(self) -> int:
        raise AssertionError("virtual-root origin must not be queried")

    def winfo_vrootwidth(self) -> int:
        raise AssertionError("virtual-root width must not be queried")

    def winfo_vrootheight(self) -> int:
        raise AssertionError("virtual-root height must not be queried")


class _FakeFunction:
    def __init__(self, implementation) -> None:
        self.implementation = implementation
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.implementation(*args)


def _set_work_area(pointer, rectangle: tuple[int, int, int, int]) -> None:
    info = ctypes.cast(pointer, ctypes.POINTER(MONITORINFO)).contents
    info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = (
        rectangle
    )


def _measured_frame(
    fake_window: _FakeWindow,
    frame_width: int = 16,
    frame_height: int = 39,
) -> OuterWindowBounds:
    geometry = fake_window.current_geometry
    return OuterWindowBounds(
        geometry.x,
        geometry.y,
        geometry.x + geometry.width + frame_width,
        geometry.y + geometry.height + frame_height,
    )


class WindowGeometryTests(TestCase):
    def test_fit_window_to_work_area_uses_measured_fractional_fallback(
        self,
    ) -> None:
        fake = _FakeWindow(width=640, height=420)
        work_area = WorkArea(0, 0, 2048, 824)

        with patch.object(
            windowing,
            "_get_windows_outer_bounds",
            side_effect=lambda _window: _measured_frame(fake),
        ):
            result = fit_window_to_work_area(
                fake,
                work_area,
                max_fraction=0.94,
            )

        self.assertTrue(result.contained)
        self.assertFalse(result.used_reserve_fallback)
        self.assertLessEqual(result.outer_bounds.right, work_area.right)
        self.assertLessEqual(result.outer_bounds.bottom, work_area.bottom)
        self.assertGreater(result.geometry.width, 1800)
        self.assertGreater(result.geometry.height, 700)

    def test_initial_geometry_fits_standard_work_area(self) -> None:
        work_area = WorkArea(0, 0, 2048, 824)

        geometry = calculate_initial_geometry(work_area)

        self.assertEqual(geometry, WindowGeometry(1440, 741, 304, 41))
        self.assertGreaterEqual(geometry.x, work_area.left)
        self.assertGreaterEqual(geometry.y, work_area.top)
        self.assertLessEqual(geometry.x + geometry.width, work_area.right)
        self.assertLessEqual(geometry.y + geometry.height, work_area.bottom)

    def test_initial_geometry_fits_short_work_area(self) -> None:
        work_area = WorkArea(0, 0, 2560, 680)

        geometry = calculate_initial_geometry(work_area)
        minimum = calculate_adaptive_minimum(work_area)

        self.assertEqual(geometry.width, 1440)
        self.assertEqual(geometry.height, 612)
        self.assertLessEqual(minimum[0], geometry.width)
        self.assertLessEqual(minimum[1], 600)
        self.assertLessEqual(minimum[1], geometry.height)

    def test_apply_geometry_clamps_mock_nonclient_frame_on_short_work_area(
        self,
    ) -> None:
        work_area = WorkArea(-1559, 1080, 1001, 1760)
        root = _FakeWindow()

        with patch.object(
            windowing,
            "_get_windows_outer_bounds",
            side_effect=lambda window: _measured_frame(window),
        ):
            result = apply_initial_geometry(root, work_area)

        self.assertFalse(result.used_reserve_fallback)
        self.assertTrue(result.contained)
        self.assertIsNotNone(result.outer_bounds)
        self.assertTrue(result.outer_bounds.is_within(work_area))
        self.assertGreaterEqual(len(root.geometry_calls), 2)
        self.assertEqual(result.geometry, WindowGeometry(1440, 612, -1007, 1094))
        self.assertEqual(root.minimum, (960, 600))

    def test_outer_measurement_failure_uses_conservative_frame_reserve(
        self,
    ) -> None:
        work_area = WorkArea(-1559, 1080, 1001, 1760)
        root = _FakeWindow()

        with patch.object(
            windowing, "_get_windows_outer_bounds", return_value=None
        ):
            result = apply_initial_geometry(root, work_area)

        geometry = result.geometry
        self.assertTrue(result.used_reserve_fallback)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.warning)
        self.assertGreaterEqual(geometry.x, work_area.left)
        self.assertGreaterEqual(geometry.y, work_area.top)
        self.assertLessEqual(
            geometry.x + geometry.width + DEFAULT_FRAME_RESERVE_WIDTH,
            work_area.right,
        )
        self.assertLessEqual(
            geometry.y + geometry.height + DEFAULT_FRAME_RESERVE_HEIGHT,
            work_area.bottom,
        )
        self.assertEqual(root.geometry_calls[-1], geometry)

    def test_nonconverging_outer_measurement_returns_fallback_without_exception(
        self,
    ) -> None:
        work_area = WorkArea(0, 0, 1200, 700)
        root = _FakeWindow()
        measurements = 0

        def inconsistent(window: _FakeWindow) -> OuterWindowBounds | None:
            nonlocal measurements
            measurements += 1
            if measurements > 3:
                return None
            geometry = window.current_geometry
            offset = measurements * 7
            return OuterWindowBounds(
                geometry.x + offset,
                geometry.y + offset,
                geometry.x + offset + geometry.width + work_area.width,
                geometry.y + offset + geometry.height + work_area.height,
            )

        with patch.object(
            windowing,
            "_get_windows_outer_bounds",
            side_effect=inconsistent,
        ):
            result = apply_initial_geometry(root, work_area)

        self.assertTrue(result.used_reserve_fallback)
        self.assertIsNotNone(result.warning)
        self.assertLessEqual(
            result.geometry.width + DEFAULT_FRAME_RESERVE_WIDTH,
            work_area.width,
        )
        self.assertLessEqual(
            result.geometry.height + DEFAULT_FRAME_RESERVE_HEIGHT,
            work_area.height,
        )
        self.assertEqual(root.geometry_calls[-1], result.geometry)

    def test_geometry_preserves_negative_monitor_origin(self) -> None:
        work_area = WorkArea(-2560, -1080, -512, -256)

        geometry = calculate_initial_geometry(work_area)

        self.assertLess(geometry.x, 0)
        self.assertLess(geometry.y, 0)
        self.assertGreaterEqual(geometry.x, work_area.left)
        self.assertGreaterEqual(geometry.y, work_area.top)
        self.assertLessEqual(geometry.x + geometry.width, work_area.right)
        self.assertLessEqual(geometry.y + geometry.height, work_area.bottom)

    def test_geometry_respects_offset_work_area(self) -> None:
        work_area = WorkArea(2560, 13, 4608, 837)

        geometry = calculate_initial_geometry(work_area)

        self.assertEqual(geometry, WindowGeometry(1440, 741, 2864, 54))

    def test_geometry_string_formats_absolute_coordinates(self) -> None:
        expected = {
            (120, 80): "400x300+120+80",
            (-1000, 80): "400x300+-1000+80",
            (120, -500): "400x300+120+-500",
            (-1000, -500): "400x300+-1000+-500",
        }

        for (x, y), geometry_string in expected.items():
            with self.subTest(x=x, y=y):
                self.assertEqual(
                    WindowGeometry(400, 300, x, y).to_tk_geometry(),
                    geometry_string,
                )

    def test_adaptive_minimum_never_exceeds_initial_geometry(self) -> None:
        for work_area in (
            WorkArea(0, 0, 600, 400),
            WorkArea(-800, 100, -300, 450),
            WorkArea(25, 50, 425, 300),
        ):
            with self.subTest(work_area=work_area):
                geometry = calculate_initial_geometry(work_area)
                minimum = calculate_adaptive_minimum(work_area)
                self.assertLessEqual(minimum[0], geometry.width)
                self.assertLessEqual(minimum[1], geometry.height)

    def test_work_area_rejects_nonpositive_dimensions(self) -> None:
        invalid_rectangles = (
            (0, 0, 0, 100),
            (10, 0, 5, 100),
            (0, 0, 100, 0),
            (0, 10, 100, 5),
        )

        for rectangle in invalid_rectangles:
            with self.subTest(rectangle=rectangle):
                with self.assertRaises(ValueError):
                    WorkArea(*rectangle)


class WindowProviderTests(TestCase):
    def test_invalid_provider_rectangle_uses_next_fallback(self) -> None:
        invalid_user32 = SimpleNamespace()

        def invalid_info(_monitor, pointer) -> int:
            _set_work_area(pointer, (100, 100, 100, 500))
            return 1

        invalid_user32.GetMonitorInfoW = _FakeFunction(invalid_info)
        self.assertIsNone(windowing._monitor_work_area(invalid_user32, 55))

        expected = WorkArea(300, 20, 2300, 820)
        root = _FakeWindow()
        with (
            patch.object(windowing.sys, "platform", "win32"),
            patch.object(
                windowing, "_get_windows_cursor_work_area", return_value=None
            ),
            patch.object(
                windowing,
                "_get_windows_window_work_area",
                return_value=expected,
            ),
            patch.object(
                windowing,
                "_get_windows_primary_work_area",
                side_effect=AssertionError("primary fallback should not run"),
            ),
        ):
            self.assertEqual(get_launch_work_area(root), expected)

    def test_provider_failure_uses_tk_fallback(self) -> None:
        root = _FailIfVirtualRootQueried(
            screen_width=2048, screen_height=864
        )
        with (
            patch.object(windowing.sys, "platform", "win32"),
            patch.object(
                windowing,
                "_get_windows_cursor_work_area",
                side_effect=OSError("cursor unavailable"),
            ),
            patch.object(
                windowing,
                "_get_windows_window_work_area",
                return_value=None,
            ),
            patch.object(
                windowing,
                "_get_windows_primary_work_area",
                return_value=None,
            ),
        ):
            work_area = get_launch_work_area(root)

        self.assertEqual(work_area, WorkArea(0, 0, 2048, 864))

    def test_tk_primary_fallback_never_queries_virtual_root(self) -> None:
        root = _FailIfVirtualRootQueried(
            screen_width=1920, screen_height=1080
        )

        work_area = windowing._get_tk_primary_fallback(root)

        self.assertEqual(work_area, WorkArea(0, 0, 1920, 1080))

    def test_cursor_monitor_lookup_uses_nearest_fallback(self) -> None:
        calls: dict[str, object] = {}
        expected = (500, -800, 2500, 0)

        def get_cursor(pointer) -> int:
            point = ctypes.cast(
                pointer, ctypes.POINTER(windowing.POINT)
            ).contents
            point.x = 900
            point.y = -200
            return 1

        def monitor_from_point(point, flag):
            calls["point"] = (point.x, point.y)
            calls["flag"] = flag
            return 0x1_0000_0011

        def get_monitor_info(monitor, pointer) -> int:
            calls["monitor"] = windowing._handle_value(monitor)
            _set_work_area(pointer, expected)
            return 1

        user32 = SimpleNamespace(
            GetCursorPos=_FakeFunction(get_cursor),
            MonitorFromPoint=_FakeFunction(monitor_from_point),
            GetMonitorInfoW=_FakeFunction(get_monitor_info),
        )
        with patch.object(windowing, "_get_user32", return_value=user32):
            work_area = windowing._get_windows_cursor_work_area()

        self.assertEqual(work_area, WorkArea(*expected))
        self.assertEqual(calls["point"], (900, -200))
        self.assertEqual(calls["flag"], windowing.MONITOR_DEFAULTTONEAREST)

    def test_windows_monitor_provider_preserves_pointer_width_handle(
        self,
    ) -> None:
        large_handle = 0x1_0000_1234
        received: list[int] = []

        def get_cursor(pointer) -> int:
            point = ctypes.cast(
                pointer, ctypes.POINTER(windowing.POINT)
            ).contents
            point.x = 25
            point.y = 50
            return 1

        def get_monitor_info(monitor, pointer) -> int:
            received.append(windowing._handle_value(monitor))
            _set_work_area(pointer, (-1000, 50, 1000, 850))
            return 1

        user32 = SimpleNamespace(
            GetCursorPos=_FakeFunction(get_cursor),
            MonitorFromPoint=_FakeFunction(
                lambda _point, _flag: large_handle
            ),
            GetMonitorInfoW=_FakeFunction(get_monitor_info),
        )
        with patch.object(windowing, "_get_user32", return_value=user32):
            work_area = windowing._get_windows_cursor_work_area()

        self.assertEqual(received, [large_handle])
        self.assertEqual(work_area, WorkArea(-1000, 50, 1000, 850))

    def test_root_monitor_lookup_follows_cursor_failure(self) -> None:
        expected = WorkArea(-2000, 0, 0, 900)
        root = _FakeWindow()
        with (
            patch.object(windowing.sys, "platform", "win32"),
            patch.object(
                windowing, "_get_windows_cursor_work_area", return_value=None
            ),
            patch.object(
                windowing,
                "_get_windows_window_work_area",
                return_value=expected,
            ) as root_provider,
            patch.object(
                windowing,
                "_get_windows_primary_work_area",
                side_effect=AssertionError("primary fallback should not run"),
            ),
        ):
            selected = get_launch_work_area(root)

        self.assertEqual(selected, expected)
        root_provider.assert_called_once_with(root)

    def test_child_work_area_uses_parent_monitor_not_pointer_monitor(
        self,
    ) -> None:
        parent_area = WorkArea(-1920, 0, 0, 1040)
        parent = _FakeWindow()
        with (
            patch.object(windowing.sys, "platform", "win32"),
            patch.object(
                windowing,
                "_get_windows_window_work_area",
                return_value=parent_area,
            ) as window_provider,
            patch.object(
                windowing,
                "_get_windows_cursor_work_area",
                side_effect=AssertionError("pointer monitor must not run"),
            ),
            patch.object(
                windowing,
                "_get_windows_primary_work_area",
                side_effect=AssertionError("primary fallback should not run"),
            ),
        ):
            selected = get_window_work_area(parent)

        self.assertEqual(selected, parent_area)
        window_provider.assert_called_once_with(parent)

    def test_get_toplevel_hwnd_uses_pointer_width_frame_handle(self) -> None:
        large_handle = 0x1_0000_4321
        window = _FakeWindow()
        window.frame = lambda: hex(large_handle)

        self.assertEqual(get_toplevel_hwnd(window), large_handle)

    def test_get_toplevel_hwnd_falls_back_to_pointer_width_parent(self) -> None:
        content_handle = 0x1_0000_0020
        wrapper_handle = 0x1_0000_0040
        window = _FakeWindow(hwnd=content_handle)
        user32 = SimpleNamespace(
            GetParent=_FakeFunction(lambda hwnd: wrapper_handle)
        )

        with patch.object(windowing, "_get_user32", return_value=user32):
            self.assertEqual(get_toplevel_hwnd(window), wrapper_handle)


class ChildWindowTests(TestCase):
    def test_child_geometry_is_clamped_inside_parent_monitor(self) -> None:
        work_area = WorkArea(0, 0, 1000, 800)
        parent = _FakeWindow(width=400, height=300, x=850, y=650)
        child = _FakeWindow(width=1200, height=900)
        child.requested_width = 1200
        child.requested_height = 900

        def measure(window: _FakeWindow) -> OuterWindowBounds:
            if window is parent:
                return OuterWindowBounds(850, 650, 1250, 950)
            return _measured_frame(window)

        with (
            patch.object(
                windowing,
                "get_window_work_area",
                return_value=work_area,
            ) as area_provider,
            patch.object(
                windowing,
                "_get_windows_outer_bounds",
                side_effect=measure,
            ),
        ):
            result = clamp_child_geometry(parent, child)

        area_provider.assert_called_once_with(parent)
        self.assertTrue(result.contained)
        self.assertFalse(result.used_reserve_fallback)
        self.assertIsNotNone(result.outer_bounds)
        self.assertTrue(result.outer_bounds.is_within(work_area))
        self.assertLessEqual(result.geometry.width, work_area.width)
        self.assertLessEqual(result.geometry.height, work_area.height)


class LiveTkWindowTests(TestCase):
    @skipUnless(
        sys.platform == "win32",
        "live GetWindowRect containment is Windows-specific",
    )
    def test_hidden_root_outer_bounds_fit_current_work_area_on_windows(
        self,
    ) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        root.withdraw()
        try:
            work_area = get_launch_work_area(root)
            result = apply_initial_geometry(root, work_area)
            root.update_idletasks()
            outer = windowing._get_windows_outer_bounds(root)
            if outer is None:
                self.skipTest("Win32 outer-window measurement unavailable")
            self.assertTrue(
                outer.is_within(work_area),
                f"outer={outer!r}, work_area={work_area!r}, result={result!r}",
            )
        finally:
            root.destroy()


if __name__ == "__main__":
    import unittest

    unittest.main()
