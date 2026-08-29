import os
import unittest

from app.chess.windows import enumerate_windows


class WindowsEnumerationTests(unittest.TestCase):
    def test_non_windows_returns_empty_list(self):
        if os.name == "nt":
            self.skipTest("non-Windows behavior")
        self.assertEqual([], enumerate_windows())

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_enumerated_windows_have_physical_bounds(self):
        windows = enumerate_windows()
        self.assertTrue(windows)
        for window in windows:
            self.assertTrue(window["title"])
            self.assertGreater(window["bounds"][2], 1)
            self.assertGreater(window["bounds"][3], 1)
            self.assertGreater(window["window_id"], 0)


if __name__ == "__main__":
    unittest.main()
