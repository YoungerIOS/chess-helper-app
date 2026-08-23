import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from threading import Lock
from unittest.mock import patch

from app.chess.jj_v2.recorder import JJV2DatasetRecorder
from app.chess.jj_v2.replay import JJV2ReplayDataset
from app.chess.jj_v2.dataset_builder import JJV2DatasetBuilder
from app.chess.jj_v2.baseline import hog_feature
from app.chess.jj_v2.cnn import split_records_by_game
from app.chess.jj_v2.shadow import JJV2ShadowRunner
from app.chess.jj_v2.shadow_report import build_shadow_report
from app.chess.context import ChessContext
from app.chess.checker import PositionChecker
from app.chess.processor import ChessProcess


class FakeFrame:
    def __init__(self, width=2, height=2, color=(10, 20, 30, 255)):
        self.width = width
        self.height = height
        self.bgra = bytes(color) * (width * height)


@dataclass
class FakeStatus:
    is_same_board: bool = False
    is_opponent_step: bool = True
    step_info: dict = None


@dataclass
class FakeStartStatus:
    is_red_start: bool = True
    is_black_start: bool = False
    is_my_step: bool = False
    is_opponent_step: bool = False
    is_same_board: bool = False
    is_illegal_board: bool = False
    is_illegal_change: bool = False
    is_history_mismatch: bool = False
    is_multi_step: bool = False


class JJV2DatasetTests(unittest.TestCase):
    def test_record_and_replay_preserves_frames_and_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = JJV2DatasetRecorder(
                directory,
                session_id="test-session",
                include_unstable=True,
            )
            later_id = recorder.record_frame(
                FakeFrame(color=(1, 2, 3, 255)),
                captured_at=20.0,
                stable=False,
                board_region={"left": 10, "top": 20, "width": 2, "height": 2},
            )
            earlier_id = recorder.record_frame(
                FakeFrame(color=(4, 5, 6, 255)),
                captured_at=10.0,
                stable=True,
                board_region={"left": 10, "top": 20, "width": 2, "height": 2},
            )
            recorder.record_analysis(
                captured_at=10.0,
                board=[["R", "-"]],
                marker_coords=[(0, 1)],
                status=FakeStatus(step_info={"from_pos": (0, 0)}),
            )
            recorder.close()

            self.assertIsNotNone(later_id)
            self.assertIsNotNone(earlier_id)
            dataset = JJV2ReplayDataset(recorder.session_dir)
            frames = list(dataset.frames())
            self.assertEqual([earlier_id, later_id], [frame.frame_id for frame in frames])
            self.assertEqual([10.0, 20.0], [frame.captured_at for frame in frames])
            self.assertEqual(16, len(frames[0].bgra))
            self.assertEqual([earlier_id], [frame.frame_id for frame in dataset.frames(stable_only=True)])

            analyses = list(dataset.analysis_events())
            self.assertEqual(1, len(analyses))
            self.assertEqual([["R", "-"]], analyses[0]["board"])
            self.assertTrue(analyses[0]["status"]["is_opponent_step"])
            self.assertEqual([[0, 0]], [analyses[0]["status"]["step_info"]["from_pos"]])

    def test_unstable_frames_can_be_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = JJV2DatasetRecorder(
                directory,
                session_id="stable-only",
                include_unstable=False,
            )
            self.assertIsNone(recorder.record_frame(
                FakeFrame(), captured_at=1.0, stable=False
            ))
            stable_id = recorder.record_frame(
                FakeFrame(), captured_at=2.0, stable=True
            )
            recorder.close()

            dataset = JJV2ReplayDataset(recorder.session_dir)
            self.assertEqual([stable_id], [frame.frame_id for frame in dataset.frames()])

    def test_recorder_continues_after_one_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = JJV2DatasetRecorder(directory, session_id="write-recovery")
            original_write = recorder._write_event
            calls = 0

            def flaky_write(event):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("simulated disk error")
                original_write(event)

            recorder._write_event = flaky_write
            with patch("app.chess.jj_v2.recorder.logger.exception"):
                recorder.record_analysis(
                    captured_at=1.0, board=None, marker_coords=[]
                )
                recorder.record_analysis(
                    captured_at=2.0, board=[["-"]], marker_coords=[]
                )
                self.assertTrue(recorder.flush(timeout=1.0))
            self.assertEqual(1, recorder.failed_samples)
            self.assertIn("simulated disk error", recorder.last_write_error)
            recorder.close()

            with open(recorder.manifest_path, encoding="utf-8") as file:
                events = [json.loads(line) for line in file]
            self.assertEqual([2.0], [event["captured_at"] for event in events])

    def test_malformed_manifest_reports_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "manifest.jsonl")
            with open(manifest, "w", encoding="utf-8") as file:
                file.write('{"type": "capture"}\nnot-json\n')

            with self.assertRaisesRegex(ValueError, "line 2"):
                JJV2ReplayDataset(directory)

    def test_session_metadata_declares_version_and_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = JJV2DatasetRecorder(
                directory, session_id="metadata"
            )
            recorder.close()
            with open(
                os.path.join(recorder.session_dir, "session.json"),
                encoding="utf-8",
            ) as file:
                metadata = json.load(file)
            self.assertEqual(1, metadata["format_version"])
            self.assertEqual("JJ_V2", metadata["platform"])

    def test_builder_uses_start_template_and_creates_auditable_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = JJV2DatasetRecorder(
                directory,
                session_id="build-source",
                include_unstable=False,
            )
            recorder.record_frame(
                FakeFrame(width=800, height=900),
                captured_at=3.0,
                stable=True,
            )
            recorder.record_analysis(
                captured_at=3.0,
                board=[["-"] * 9 for _ in range(10)],
                marker_coords=[(4, 4)],
                status=FakeStartStatus(),
            )
            recorder.close()

            output_dir = os.path.join(directory, "output")
            summary = JJV2DatasetBuilder(
                output_dir,
                max_per_class=10,
            ).build([recorder.session_dir])

            self.assertEqual(1, summary.sessions)
            self.assertEqual(1, summary.games)
            self.assertEqual(1, summary.accepted_frames)
            self.assertGreaterEqual(summary.samples, 15)
            self.assertIn("R", summary.class_counts)
            self.assertIn("r", summary.class_counts)
            self.assertIn(".", summary.class_counts)
            self.assertTrue(os.path.isdir(os.path.join(output_dir, "samples", "red_R")))
            self.assertTrue(os.path.isdir(os.path.join(output_dir, "samples", "black_r")))
            self.assertNotEqual(
                os.path.realpath(os.path.join(output_dir, "samples", "red_R")),
                os.path.realpath(os.path.join(output_dir, "samples", "black_r")),
            )
            with open(os.path.join(output_dir, "labels.jsonl"), encoding="utf-8") as file:
                labels = [json.loads(line) for line in file]
            self.assertTrue(all(item["label_source"] == "start_template" for item in labels))

    def test_builder_assigns_unique_game_numbers_across_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = []
            for index in range(2):
                recorder = JJV2DatasetRecorder(
                    directory,
                    session_id=f"session-{index}",
                    include_unstable=False,
                )
                captured_at = float(index + 1)
                frame = FakeFrame(width=800, height=900)
                black = bytes((0, 0, 0, 255))
                white = bytes((255, 255, 255, 255))
                if index == 0:
                    frame.bgra = (black * 400 + white * 400) * 900
                else:
                    frame.bgra = black * (800 * 450) + white * (800 * 450)
                recorder.record_frame(
                    frame,
                    captured_at=captured_at,
                    stable=True,
                )
                recorder.record_analysis(
                    captured_at=captured_at,
                    board=[["-"] * 9 for _ in range(10)],
                    marker_coords=[],
                    status=FakeStartStatus(),
                )
                recorder.close()
                sessions.append(recorder.session_dir)

            output_dir = os.path.join(directory, "combined")
            summary = JJV2DatasetBuilder(
                output_dir,
                duplicate_distance=0,
            ).build(sessions)
            with open(os.path.join(output_dir, "labels.jsonl"), encoding="utf-8") as file:
                game_numbers = {json.loads(line)["game_index"] for line in file}

            self.assertEqual(2, summary.games)
            self.assertEqual({1, 2}, game_numbers)

    def test_builder_supersedes_orientation_correction_before_first_move(self):
        red_start = {"captured_at": 10.0, "status": {"is_red_start": True}}
        settlement = {"captured_at": 15.0, "status": {}}
        black_start = {"captured_at": 20.0, "status": {"is_black_start": True}}
        later_start = {"captured_at": 100.0, "status": {"is_red_start": True}}

        superseded = JJV2DatasetBuilder._superseded_start_ids(
            [red_start, settlement, black_start, later_start]
        )

        self.assertEqual({id(red_start)}, superseded)

    def test_manual_hog_feature_is_normalized_without_optional_opencv_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "gradient.jpg")
            from PIL import Image

            pixels = bytes(range(96)) * 96
            Image.frombytes("L", (96, 96), pixels).save(path)
            feature = hog_feature(path)

            self.assertEqual((1296,), feature.shape)
            self.assertAlmostEqual(1.0, float((feature ** 2).sum()), places=4)

    def test_cnn_split_keeps_complete_games_separate(self):
        records = [
            {"game_index": game, "label": label}
            for game in (1, 2, 3)
            for label in "-.abcknprABCKNPR"
        ]
        training, validation = split_records_by_game(records, [2, 3])

        self.assertEqual({1}, {record["game_index"] for record in training})
        self.assertEqual({2, 3}, {record["game_index"] for record in validation})

    def test_cnn_split_rejects_missing_training_classes(self):
        records = [
            {"game_index": 1, "label": "-"},
            {"game_index": 2, "label": "."},
        ]
        with self.assertRaisesRegex(ValueError, "missing classes"):
            split_records_by_game(records, [2])

    def test_shadow_diff_is_read_only_and_cell_precise(self):
        primary = [["-"] * 9 for _ in range(10)]
        shadow = [["-"] * 9 for _ in range(10)]
        shadow[3][4] = "P"
        confidences = [[0.9] * 9 for _ in range(10)]

        differences = JJV2ShadowRunner._compare(primary, shadow, confidences)

        self.assertEqual(1, len(differences))
        self.assertEqual(
            {"row": 3, "col": 4, "primary": "-", "shadow": "P", "shadow_confidence": 0.9},
            differences[0],
        )
        self.assertEqual("-", primary[3][4])

    def test_shadow_preserves_replayed_primary_status_dict(self):
        status = {"is_same_board": True, "message": "same"}
        copied = JJV2ShadowRunner._status_dict(status)

        self.assertEqual(status, copied)
        self.assertIsNot(status, copied)

    def test_shadow_gate_never_merges_unrelated_cells(self):
        primary = [["-"] * 9 for _ in range(10)]
        shadow = [["-"] * 9 for _ in range(10)]
        confidences = [[0.95] * 9 for _ in range(10)]
        primary[3][4] = "P"
        shadow[3][4] = "p"
        confidences[3][4] = 0.69
        shadow[5][6] = "r"

        gated = JJV2ShadowRunner._gated_board(primary, shadow, confidences, 0.70)

        self.assertEqual("P", gated[3][4])
        self.assertEqual("-", gated[5][6])
        self.assertEqual("P", primary[3][4])

    def test_shadow_gate_accepts_both_endpoints_of_one_legal_move(self):
        primary = [row[:] for row in PositionChecker.START_RED]
        shadow = [row[:] for row in primary]
        shadow[0][1] = "-"
        shadow[2][2] = "n"
        confidences = [[0.99] * 9 for _ in range(10)]
        confidences[0][1] = 0.687

        gated, decision = JJV2ShadowRunner._atomic_gate(
            primary, shadow, confidences, 0.70
        )

        self.assertEqual("-", gated[0][1])
        self.assertEqual("n", gated[2][2])
        self.assertEqual("atomic_legal_move", decision["mode"])

    def test_shadow_report_excludes_settlement_from_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shadow_results.jsonl")
            events = [
                {
                    "type": "shadow_analysis",
                    "latency_ms": 20.0,
                    "primary_board": [["-"] * 9 for _ in range(10)],
                    "difference_count": 0,
                    "differences": [],
                    "confidences": [[0.9] * 9 for _ in range(10)],
                    "primary_status": {"is_same_board": True},
                    "is_settlement_screen": False,
                },
                {
                    "type": "shadow_analysis",
                    "latency_ms": 30.0,
                    "primary_board": [["-"] * 9 for _ in range(10)],
                    "difference_count": 90,
                    "differences": [],
                    "confidences": [[0.9] * 9 for _ in range(10)],
                    "primary_status": {"is_same_board": True},
                    "is_settlement_screen": True,
                },
            ]
            with open(path, "w", encoding="utf-8") as file:
                for event in events:
                    file.write(json.dumps(event))
                    file.write("\n")

            report = build_shadow_report(directory)

            self.assertEqual(2, report["processed_frames"])
            self.assertEqual(1, report["comparable_frames"])
            self.assertEqual(1.0, report["exact_match_rate"])
            self.assertEqual(90, report["confidence_gate"]["high_confidence_cells"])
            self.assertEqual(1.0, report["confidence_gate"]["gated_exact_match_rate"])
            self.assertEqual(0, report["confidence_gate"]["fallback_to_primary_cells"])
            self.assertEqual(
                {"legacy_event": 1}, report["atomic_gate"]["decision_counts"]
            )

    def test_jj_auto_move_requires_complete_guarded_pipeline(self):
        context = ChessContext.__new__(ChessContext)
        context.platform = "JJ"
        context._jj_v2_shadow_enabled = True
        context._jj_v2_recommendation_enabled = False
        context._auto_move_enabled = False
        context.save_config = lambda: None

        ChessContext.auto_move_enabled.fset(context, True)

        self.assertFalse(context.auto_move_enabled)

    def test_jj_auto_move_allowed_with_complete_guarded_pipeline(self):
        context = ChessContext.__new__(ChessContext)
        context.platform = "JJ"
        context._jj_v2_shadow_enabled = True
        context._jj_v2_recommendation_enabled = True
        context._auto_move_enabled = False
        context.save_config = lambda: None

        ChessContext.auto_move_enabled.fset(context, True)

        self.assertTrue(context.auto_move_enabled)
        self.assertTrue(context.jj_v2_guarded_auto_ready)

    def test_disabling_recommendation_stops_auto_move(self):
        context = ChessContext.__new__(ChessContext)
        context.platform = "JJ"
        context._jj_v2_shadow_enabled = True
        context._jj_v2_recommendation_enabled = True
        context._auto_move_enabled = True
        context.save_config = lambda: None

        ChessContext.jj_v2_recommendation_enabled.fset(context, False)

        self.assertFalse(context.jj_v2_recommendation_enabled)
        self.assertFalse(context.auto_move_enabled)

    def test_platform_switch_revokes_auto_move_and_visual_state(self):
        context = ChessContext.__new__(ChessContext)
        context.platform = "TT"
        context._platforms = {"TT": object(), "JJ": object()}
        context._auto_move_enabled = True
        context._analysis_token_lock = Lock()
        context.analysis_token = 7
        context.history = type("History", (), {
            "cleared": False,
            "clear": lambda self: setattr(self, "cleared", True),
        })()
        context.base_fen = "some-fen"
        resets = []
        context.reset_checker = lambda: resets.append("checker")
        context.reset_recognizer = lambda: resets.append("recognizer")
        context.save_config = lambda: None

        safety_stopped = context.set_platform("JJ")

        self.assertTrue(safety_stopped)
        self.assertEqual("JJ", context.platform)
        self.assertFalse(context.auto_move_enabled)
        self.assertEqual(8, context.analysis_token)
        self.assertEqual(["checker", "recognizer"], resets)
        self.assertTrue(context.history.cleared)
        self.assertIsNone(context.base_fen)

    def test_recommendation_mode_requires_shadow_model(self):
        context = ChessContext.__new__(ChessContext)
        context._jj_v2_shadow_enabled = False
        context._jj_v2_recommendation_enabled = False
        context._auto_move_enabled = False
        context.save_config = lambda: None

        ChessContext.jj_v2_recommendation_enabled.fset(context, True)

        self.assertFalse(context.jj_v2_recommendation_enabled)

    def test_recommendation_mode_applies_only_atomic_candidate(self):
        primary = [row[:] for row in PositionChecker.START_RED]
        candidate = [row[:] for row in primary]
        candidate[0][1] = "-"
        candidate[2][2] = "n"

        class Runner:
            def analyze_candidate(self, *_args, **_kwargs):
                return {
                    "gated_board": candidate,
                    "gate_decision": {
                        "mode": "atomic_legal_move",
                        "piece": "n",
                        "from_pos": [0, 1],
                        "to_pos": [2, 2],
                    },
                }

        class Context:
            jj_v2_recommendation_enabled = True

            @staticmethod
            def get_jj_v2_shadow_runner():
                return Runner()

        process = ChessProcess.__new__(ChessProcess)
        process.context = Context()

        board, result = process._apply_jj_v2_recommendation(
            object(), primary, 1.0
        )

        self.assertEqual("-", board[0][1])
        self.assertEqual("n", board[2][2])
        self.assertEqual("atomic_legal_move", result["gate_decision"]["mode"])

    def test_recommendation_mode_keeps_primary_on_fallback(self):
        primary = [row[:] for row in PositionChecker.START_RED]

        class Runner:
            def analyze_candidate(self, *_args, **_kwargs):
                return {
                    "gated_board": [["-"] * 9 for _ in range(10)],
                    "gate_decision": {"mode": "primary_fallback"},
                }

        class Context:
            jj_v2_recommendation_enabled = True

            @staticmethod
            def get_jj_v2_shadow_runner():
                return Runner()

        process = ChessProcess.__new__(ChessProcess)
        process.context = Context()

        board, _result = process._apply_jj_v2_recommendation(
            object(), primary, 1.0
        )

        self.assertEqual(primary, board)


if __name__ == "__main__":
    unittest.main()
