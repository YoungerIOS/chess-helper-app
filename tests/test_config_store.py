import json
import os
import tempfile
import unittest

from app.tools.config_store import load_config, write_json_atomic


class ConfigStoreTests(unittest.TestCase):
    def test_first_run_copies_defaults_without_modifying_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            default_path = os.path.join(directory, "app", "game_config.json")
            user_path = os.path.join(directory, "user", "game_config.json")
            defaults = {"JJ": {"regions": {}}, "theme": "light"}
            write_json_atomic(default_path, defaults)

            loaded = load_config(default_path, user_path)
            loaded["JJ"]["regions"]["board"] = {"left": -1200}
            write_json_atomic(user_path, loaded)

            with open(default_path, encoding="utf-8") as file:
                self.assertEqual(defaults, json.load(file))
            with open(user_path, encoding="utf-8") as file:
                self.assertEqual(-1200, json.load(file)["JJ"]["regions"]["board"]["left"])

    def test_user_settings_override_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            default_path = os.path.join(directory, "default.json")
            user_path = os.path.join(directory, "user.json")
            write_json_atomic(default_path, {"theme": "light", "board_index": 0})
            write_json_atomic(user_path, {"theme": "dark"})

            self.assertEqual(
                {"theme": "dark", "board_index": 0},
                load_config(default_path, user_path),
            )


if __name__ == "__main__":
    unittest.main()
