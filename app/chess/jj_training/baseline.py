"""用轻量 HOG+kNN 快速评估 JJ 数据是否具备可学习性。"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Optional

import cv2
import numpy as np

CLASS_ORDER = [
    "-",
    ".",
    "a",
    "b",
    "c",
    "k",
    "n",
    "p",
    "r",
    "A",
    "B",
    "C",
    "K",
    "N",
    "P",
    "R",
]


def load_labels(dataset_dir: str) -> list[dict]:
    labels_path = os.path.join(dataset_dir, "labels.jsonl")
    records = []
    with open(labels_path, encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            record["absolute_path"] = os.path.join(dataset_dir, record["path"])
            if not os.path.isfile(record["absolute_path"]):
                raise FileNotFoundError(
                    f"missing sample on labels line {line_number}: {record['absolute_path']}"
                )
            records.append(record)
    return records


def hog_feature(path: str) -> np.ndarray:
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"cannot read sample: {path}")
    image = cv2.resize(image, (96, 96), interpolation=cv2.INTER_AREA)
    image = cv2.equalizeHist(image)
    normalized = image.astype(np.float32) / 255.0
    gradient_y, gradient_x = np.gradient(normalized)
    magnitude = np.hypot(gradient_x, gradient_y)
    angle = (np.degrees(np.arctan2(gradient_y, gradient_x)) + 180.0) % 180.0
    bins = np.minimum((angle / 20.0).astype(np.int32), 8)
    cells = []
    for top in range(0, 96, 8):
        for left in range(0, 96, 8):
            cell_bins = bins[top : top + 8, left : left + 8].reshape(-1)
            cell_magnitude = magnitude[top : top + 8, left : left + 8].reshape(-1)
            histogram = np.bincount(
                cell_bins,
                weights=cell_magnitude,
                minlength=9,
            ).astype(np.float32)
            histogram /= np.linalg.norm(histogram) + 1e-6
            cells.append(histogram)
    feature = np.concatenate(cells)
    feature /= np.linalg.norm(feature) + 1e-6
    return feature.astype(np.float32)


def _balanced_training(records: list[dict], max_per_class: int) -> list[dict]:
    grouped = defaultdict(list)
    for record in records:
        grouped[record["label"]].append(record)
    selected = []
    for label in CLASS_ORDER:
        selected.extend(grouped[label][:max_per_class])
    return selected


def evaluate_baseline(
    dataset_dir: str,
    *,
    output_dir: Optional[str] = None,
    holdout_game: Optional[int] = None,
    max_train_per_class: int = 200,
) -> dict:
    dataset_dir = os.path.abspath(os.path.expanduser(dataset_dir))
    output_dir = os.path.abspath(os.path.expanduser(output_dir or dataset_dir))
    os.makedirs(output_dir, exist_ok=True)
    records = load_labels(dataset_dir)
    games = sorted({int(record["game_index"]) for record in records})
    if len(games) < 2:
        raise ValueError("baseline evaluation requires at least two recorded games")
    holdout_game = int(holdout_game if holdout_game is not None else games[-1])
    training = _balanced_training(
        [record for record in records if int(record["game_index"]) != holdout_game],
        max(1, int(max_train_per_class)),
    )
    validation = [
        record for record in records if int(record["game_index"]) == holdout_game
    ]
    if not training or not validation:
        raise ValueError("training or validation split is empty")

    present_labels = {record["label"] for record in training}
    validation = [record for record in validation if record["label"] in present_labels]
    label_to_index = {
        label: index
        for index, label in enumerate(CLASS_ORDER)
        if label in present_labels
    }
    index_to_label = {index: label for label, index in label_to_index.items()}

    train_x = np.stack([hog_feature(record["absolute_path"]) for record in training])
    train_y = np.array(
        [label_to_index[record["label"]] for record in training], dtype=np.int32
    )
    validation_x = np.stack(
        [hog_feature(record["absolute_path"]) for record in validation]
    )
    validation_y = [record["label"] for record in validation]

    similarities = validation_x @ train_x.T
    neighbor_count = min(3, len(training))
    neighbor_indices = np.argpartition(
        similarities,
        -neighbor_count,
        axis=1,
    )[:, -neighbor_count:]
    predictions = []
    for row, indices in enumerate(neighbor_indices):
        votes: dict[int, float] = defaultdict(float)
        for index in indices:
            votes[int(train_y[index])] += max(0.0, float(similarities[row, index]))
        predicted_index = max(votes, key=lambda index: votes[index])
        predictions.append(index_to_label[predicted_index])

    correct = Counter()
    totals = Counter(validation_y)
    confusion = Counter()
    errors = []
    for row, (record, expected, predicted) in enumerate(
        zip(validation, validation_y, predictions)
    ):
        confusion[(expected, predicted)] += 1
        if expected == predicted:
            correct[expected] += 1
        else:
            errors.append(
                {
                    "path": record["path"],
                    "game_index": record["game_index"],
                    "frame_id": record["frame_id"],
                    "row": record["row"],
                    "col": record["col"],
                    "label_source": record["label_source"],
                    "expected": expected,
                    "predicted": predicted,
                    "nearest_similarity": float(np.max(similarities[row])),
                }
            )

    metrics = {
        "holdout_game": holdout_game,
        "training_samples": len(training),
        "validation_samples": len(validation),
        "accuracy": sum(
            expected == predicted
            for expected, predicted in zip(validation_y, predictions)
        )
        / len(validation),
        "training_class_counts": dict(Counter(record["label"] for record in training)),
        "validation_class_counts": dict(totals),
        "per_class_accuracy": {
            label: correct[label] / totals[label]
            for label in CLASS_ORDER
            if totals[label]
        },
        "confusion": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
            if expected != predicted
        },
        "note": "diagnostic HOG+kNN baseline only; do not deploy as the production recognizer",
    }
    np.savez_compressed(
        os.path.join(output_dir, "baseline_knn.npz"),
        features=train_x,
        labels=train_y,
    )
    with open(
        os.path.join(output_dir, "baseline_metrics.json"), "w", encoding="utf-8"
    ) as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)
    with open(
        os.path.join(output_dir, "baseline_errors.jsonl"), "w", encoding="utf-8"
    ) as file:
        for error in errors:
            file.write(json.dumps(error, ensure_ascii=False))
            file.write("\n")
    return metrics
