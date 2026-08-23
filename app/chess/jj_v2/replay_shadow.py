"""将已采集的 JJ v2 会话确定性回放给影子模型。"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict

from PIL import Image

from .replay import JJV2ReplayDataset
from .shadow import JJV2ShadowRunner
from .shadow_report import build_shadow_report


@dataclass(frozen=True)
class _ImageFrame:
    width: int
    height: int
    bgra: bytes


def _load_frame(path: str) -> _ImageFrame:
    with Image.open(path) as source:
        image = source.convert("RGBA")
        return _ImageFrame(
            width=image.width,
            height=image.height,
            bgra=image.tobytes("raw", "BGRA"),
        )


def replay_shadow_session(
    session_dir: str,
    model_path: str,
    output_dir: str,
) -> Dict:
    dataset = JJV2ReplayDataset(session_dir)
    with open(os.path.join(dataset.session_dir, "session.json"), encoding="utf-8") as file:
        metadata = json.load(file)
    captures = {
        float(event["captured_at"]): event
        for event in dataset.events if event.get("type") == "capture"
    }
    runner = JJV2ShadowRunner(
        model_path,
        output_dir,
        grid_coords=metadata.get("grid_coords") or {},
    )
    missing_captures = 0
    try:
        for analysis in dataset.analysis_events():
            captured_at = float(analysis["captured_at"])
            capture = captures.get(captured_at)
            if capture is None:
                missing_captures += 1
                continue
            frame = _load_frame(os.path.join(dataset.session_dir, capture["path"]))
            runner.analyze_now(
                frame,
                captured_at=captured_at,
                primary_board=analysis.get("board"),
                primary_status=analysis.get("status"),
                is_settlement_screen=bool(analysis.get("is_settlement_screen")),
            )
    finally:
        runner.close()
    report = build_shadow_report(runner.session_dir)
    report["source_session_dir"] = dataset.session_dir
    report["missing_captures"] = missing_captures
    report_path = os.path.join(runner.session_dir, "shadow_report.json")
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="离线回放 JJ v2 影子识别")
    parser.add_argument("session_dir")
    parser.add_argument("model_path")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    report = replay_shadow_session(args.session_dir, args.model_path, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
