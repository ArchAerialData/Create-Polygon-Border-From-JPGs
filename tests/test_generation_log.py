import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests.test_gui_input import _sample_boundary_result
import generation_log
from jpg_boundary_kmz_core import format_summary


class GenerationLogTests(TestCase):
    def test_diagnostics_survive_log_close_outside_export(self):
        logger = logging.Logger("test-generation")
        with TemporaryDirectory() as tmp, patch.object(generation_log, "generation_logger", logger):
            path = generation_log.configure_generation_log(Path(tmp))
            self.assertIsNotNone(path)
            summary = format_summary(_sample_boundary_result().metadata)
            logger.info(summary + "\nSaved KMZ: Example – north.kmz")
            for handler in logger.handlers:
                handler.close()
            text = path.read_text(encoding="utf-8")
            self.assertIn(summary, text)
            self.assertIn("Saved KMZ: Example – north.kmz", text)

    def test_unavailable_log_directory_does_not_block_startup(self):
        with TemporaryDirectory() as tmp:
            unavailable = Path(tmp) / "file"
            unavailable.write_text("not a directory", encoding="utf-8")
            self.assertIsNone(generation_log.configure_generation_log(unavailable))

    def test_path_resolution_failure_does_not_block_startup(self):
        with patch.object(Path, "resolve", side_effect=OSError("unavailable volume")):
            self.assertIsNone(generation_log.configure_generation_log(Path("unavailable")))

    def test_initialization_is_idempotent_and_messages_are_not_duplicated(self):
        logger = logging.Logger("test-generation")
        with TemporaryDirectory() as tmp, patch.object(generation_log, "generation_logger", logger):
            try:
                first = generation_log.configure_generation_log(Path(tmp))
                second = generation_log.configure_generation_log(Path(tmp) / ".")
                self.assertEqual(first, second)
                self.assertEqual(len(logger.handlers), 1)
                logger.info("Unique generation summary")
                self.assertEqual(first.read_text(encoding="utf-8").count("Unique generation summary"), 1)
            finally:
                for handler in logger.handlers:
                    handler.close()

    def test_rotation_retains_bounded_history_and_unicode(self):
        logger = logging.Logger("test-generation")
        with TemporaryDirectory() as tmp, patch.object(generation_log, "generation_logger", logger):
            try:
                path = generation_log.configure_generation_log(Path(tmp))
                handler = logger.handlers[0]
                self.assertEqual(handler.maxBytes, 2_000_000)
                self.assertEqual(handler.backupCount, 3)
                handler.maxBytes = 100
                for index in range(7):
                    logger.info("Generation %s – café – %s", index, "x" * 40)
                files = sorted(Path(tmp).glob("generation.log*"))
                self.assertEqual(len(files), 4)
                retained = "".join(file.read_text(encoding="utf-8") for file in files)
                self.assertNotIn("Generation 0", retained)
                self.assertIn("Generation 6 – café", path.read_text(encoding="utf-8"))
                self.assertTrue(all(f"Generation {index}" in retained for index in range(3, 7)))
            finally:
                for handler in logger.handlers:
                    handler.close()
