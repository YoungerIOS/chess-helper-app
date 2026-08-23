"""打印 JJ v2 采集会话摘要：python -m app.chess.jj_v2 SESSION_DIR。"""

import argparse

from .replay import JJV2ReplayDataset


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 JJ v2 离线回放数据集")
    parser.add_argument("session_dir", help="包含 session.json/manifest.jsonl 的会话目录")
    args = parser.parse_args()
    dataset = JJV2ReplayDataset(args.session_dir)
    frames = list(dataset.frames())
    stable = sum(frame.stable for frame in frames)
    analyses = sum(1 for _ in dataset.analysis_events())
    print(f"frames={len(frames)} stable={stable} analyses={analyses}")


if __name__ == "__main__":
    main()
