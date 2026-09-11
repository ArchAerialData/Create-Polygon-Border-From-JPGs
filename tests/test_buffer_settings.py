import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from buffer_settings import BufferSettings, seed_side_fields


class BufferSettingsTests(TestCase):
    def test_copy_preserves_distance_and_precision(self):
        for text in ("350", "461", "0.005", " 12.34567 "):
            self.assertEqual(seed_side_fields(text), (text.strip(), text.strip()))
        for text in ("0", "0.0", "-0"):
            self.assertEqual(seed_side_fields(text), ("200", "200"))

    def test_invalid_values_and_zero_pair_are_rejected(self):
        for text in ("", "no", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=text), self.assertRaises(ValueError):
                seed_side_fields(text)
        with self.assertRaises(ValueError):
            BufferSettings.per_side(0, 0)
        self.assertEqual(BufferSettings.per_side(0, 200).right_ft, 200)

    def test_modes_and_distances_have_distinct_cache_keys(self):
        values = [BufferSettings(unified_ft=100), BufferSettings.per_side(100, 100),
                  BufferSettings.per_side(100, 50), BufferSettings.per_side(50, 100)]
        self.assertEqual(len({v.key for v in values}), 4)
