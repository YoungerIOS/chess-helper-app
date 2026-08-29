import os
import tempfile
import unittest
from unittest.mock import patch

from app.chess.engine import ChessEngine


class WindowsEngineDiscoveryTests(unittest.TestCase):
    def test_prefers_bmi2_over_incompatible_vnni512(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_dir = os.path.join(directory, "Pikafish")
            os.makedirs(engine_dir)
            open(os.path.join(engine_dir, "pikafish-vnni512.exe"), "wb").close()
            expected = os.path.join(engine_dir, "pikafish-bmi2.exe")
            open(expected, "wb").close()

            def app_path(relative):
                return os.path.join(directory, *relative.split("/"))

            with (
                patch("app.chess.engine.sys.platform", "win32"),
                patch("app.tools.utils.engine_path", side_effect=app_path),
                patch("app.tools.utils.app_data_path", side_effect=app_path),
                patch("app.chess.engine.resource_path", return_value=os.path.join(directory, "missing")),
            ):
                engine = ChessEngine()

            self.assertEqual(expected, engine.engine_path)


if __name__ == "__main__":
    unittest.main()
