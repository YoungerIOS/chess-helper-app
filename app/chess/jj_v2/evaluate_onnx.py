"""CLI: 用 ONNX Runtime 评估 JJ v2 候选模型。"""

import argparse
import json

from .onnx_eval import evaluate_onnx


def main() -> None:
    parser = argparse.ArgumentParser(description="独立评估新版 JJ ONNX 模型")
    parser.add_argument("dataset_dir")
    parser.add_argument("model_path")
    parser.add_argument("--games", type=int, nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    metrics = evaluate_onnx(
        args.dataset_dir,
        args.model_path,
        games=args.games,
        output_path=args.output,
    )
    summary = {key: metrics[key] for key in (
        "games", "samples", "accuracy", "macro_accuracy",
        "per_class_accuracy", "confusion",
    )}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
