"""汇总只读影子识别会话，定位新旧模型分歧。"""

from __future__ import annotations

import json
import os
from collections import Counter
from statistics import mean, median
from typing import Dict


def _primary_status_accepted(event: Dict) -> bool:
    status = event.get("primary_status") or {}
    rejected = any(status.get(flag) for flag in (
        "is_illegal_board",
        "is_illegal_change",
        "is_history_mismatch",
        "is_multi_step",
    ))
    accepted = any(status.get(flag) for flag in (
        "is_same_board",
        "is_my_step",
        "is_opponent_step",
        "is_red_start",
        "is_black_start",
        "is_new_game",
    ))
    return bool(event.get("primary_board")) and accepted and not rejected


def build_shadow_report(session_dir: str, *, confidence_threshold: float = 0.70) -> Dict:
    session_dir = os.path.abspath(os.path.expanduser(session_dir))
    results_path = os.path.join(session_dir, "shadow_results.jsonl")
    analyses = []
    errors = []
    with open(results_path, encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid shadow result line {line_number}: {exc}") from exc
            if event.get("type") == "shadow_analysis":
                analyses.append(event)
            elif event.get("type") == "shadow_error":
                errors.append(event)

    comparable = [
        event for event in analyses
        if event.get("primary_board") and not event.get("is_settlement_screen")
    ]
    latencies = [float(event["latency_ms"]) for event in analyses]
    disagreement_frames = sum(bool(event.get("difference_count")) for event in comparable)
    confusion = Counter()
    positions = Counter()
    for event in comparable:
        for difference in event.get("differences", []):
            confusion[(difference["primary"], difference["shadow"])] += 1
            positions[(int(difference["row"]), int(difference["col"]))] += 1

    trusted = [event for event in comparable if _primary_status_accepted(event)]
    gate_decisions = Counter(
        (event.get("gate_decision") or {}).get("mode", "legacy_event")
        for event in trusted
    )
    atomic_moves = [
        {
            "captured_at": event.get("captured_at"),
            **event["gate_decision"],
        }
        for event in trusted
        if (event.get("gate_decision") or {}).get("mode") == "atomic_legal_move"
    ]
    high_confidence_cells = 0
    high_confidence_agreements = 0
    high_confidence_differences = []
    low_confidence_differences = 0
    gated_disagreement_frames = 0
    trusted_cell_count = len(trusted) * 90
    threshold = float(confidence_threshold)
    for event in trusted:
        event_has_high_confidence_difference = False
        differences_by_position = {
            (int(item["row"]), int(item["col"])): item
            for item in event.get("differences", [])
        }
        for row in range(10):
            for col in range(9):
                confidence = float(event["confidences"][row][col])
                difference = differences_by_position.get((row, col))
                if confidence >= threshold:
                    high_confidence_cells += 1
                    if difference is None:
                        high_confidence_agreements += 1
                    else:
                        event_has_high_confidence_difference = True
                        high_confidence_differences.append({
                            "captured_at": event["captured_at"],
                            **difference,
                        })
                elif difference is not None:
                    low_confidence_differences += 1
        if event_has_high_confidence_difference:
            gated_disagreement_frames += 1

    return {
        "session_dir": session_dir,
        "processed_frames": len(analyses),
        "error_frames": len(errors),
        "comparable_frames": len(comparable),
        "exact_match_frames": len(comparable) - disagreement_frames,
        "exact_match_rate": (
            (len(comparable) - disagreement_frames) / len(comparable)
            if comparable else None
        ),
        "total_cell_differences": sum(confusion.values()),
        "trusted_primary_frames": len(trusted),
        "confidence_gate": {
            "threshold": threshold,
            "total_cells": trusted_cell_count,
            "high_confidence_cells": high_confidence_cells,
            "coverage": (
                high_confidence_cells / trusted_cell_count
                if trusted_cell_count else None
            ),
            "agreements_with_primary": high_confidence_agreements,
            "differences_from_primary": len(high_confidence_differences),
            "agreement_rate": (
                high_confidence_agreements / high_confidence_cells
                if high_confidence_cells else None
            ),
            "high_confidence_differences": high_confidence_differences,
            "low_confidence_differences": low_confidence_differences,
            "fallback_to_primary_cells": trusted_cell_count - high_confidence_cells,
            "gated_exact_match_frames": len(trusted) - gated_disagreement_frames,
            "gated_exact_match_rate": (
                (len(trusted) - gated_disagreement_frames) / len(trusted)
                if trusted else None
            ),
        },
        "atomic_gate": {
            "decision_counts": dict(gate_decisions),
            "accepted_legal_moves": atomic_moves,
        },
        "latency_ms": {
            "mean": mean(latencies) if latencies else None,
            "median": median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "confusion": {
            f"{primary}->{shadow}": count
            for (primary, shadow), count in confusion.most_common()
        },
        "most_disputed_positions": [
            {"row": row, "col": col, "count": count}
            for (row, col), count in positions.most_common(20)
        ],
        "errors": errors,
    }
