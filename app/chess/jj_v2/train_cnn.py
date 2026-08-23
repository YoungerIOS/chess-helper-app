"""CLI: 按完整对局切分并训练 JJ v2 候选 CNN。"""

import argparse
import json

from .cnn import train_cnn


def main() -> None:
    parser = argparse.ArgumentParser(description="训练新版 JJ 棋子识别候选模型")
    parser.add_argument("dataset_dir")
    parser.add_argument("output_dir")
    parser.add_argument(
        "--holdout-games",
        type=int,
        nargs="+",
        required=True,
        help="完整留出的对局编号，例如 5 6",
    )
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument(
        "--balance-power",
        type=float,
        default=0.5,
        help="0=原始分布，0.5=平方根均衡，1=完全均衡",
    )
    args = parser.parse_args()
    metrics = train_cnn(
        args.dataset_dir,
        args.output_dir,
        holdout_games=args.holdout_games,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        balance_power=args.balance_power,
    )
    print(json.dumps(metrics["best_validation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
