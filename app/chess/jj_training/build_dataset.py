"""CLI: 从一个或多个 JJ 会话构建棋子分类样本。"""

import argparse
import json

from .dataset_builder import JJDatasetBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="构建JJ 棋子训练样本")
    parser.add_argument("output_dir")
    parser.add_argument("session_dirs", nargs="+")
    parser.add_argument("--max-per-class", type=int, default=2000)
    parser.add_argument("--duplicate-distance", type=int, default=2)
    parser.add_argument("--corrections")
    parser.add_argument("--audit-model")
    parser.add_argument("--audit-confidence", type=float, default=0.70)
    args = parser.parse_args()
    builder = JJDatasetBuilder(
        args.output_dir,
        max_per_class=args.max_per_class,
        duplicate_distance=args.duplicate_distance,
        corrections_path=args.corrections,
        audit_model_path=args.audit_model,
        audit_confidence=args.audit_confidence,
    )
    summary = builder.build(args.session_dirs)
    print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
