import unittest

from app.chess.engine import ChessEngine


class EngineInfoTests(unittest.TestCase):
    def test_parses_live_depth_score_and_speed(self):
        info = ChessEngine.parse_engine_info(
            "info depth 22 seldepth 35 multipv 1 score cp 83 "
            "nodes 1234567 nps 2345678 time 526 pv a0a1"
        )

        self.assertEqual(22, info["depth"])
        self.assertEqual("cp", info["score_type"])
        self.assertEqual(83, info["score"])
        self.assertEqual(2345678, info["nps"])
        self.assertEqual(526, info["time"])

    def test_parses_mate_score(self):
        info = ChessEngine.parse_engine_info(
            "info depth 31 score mate -4 nodes 99 nps 1000 time 20 pv a0a1"
        )

        self.assertEqual("mate", info["score_type"])
        self.assertEqual(-4, info["score"])


if __name__ == "__main__":
    unittest.main()
