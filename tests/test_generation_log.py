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
