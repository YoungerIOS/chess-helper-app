"""CLI: 按完整对局留出验证 HOG+kNN 数据基线。"""

import argparse
import json

from .baseline import evaluate_baseline


def main() -> None:
    parser = argparse.ArgumentParser(description="评估新版 JJ 样本可学习性")
    parser.add_argument("dataset_dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--holdout-game", type=int)
    args = parser.parse_args()
    metrics = evaluate_baseline(
        args.dataset_dir,
        output_dir=args.output_dir,
        holdout_game=args.holdout_game,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
