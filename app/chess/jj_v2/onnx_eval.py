"""用应用实际采用的 ONNX Runtime 独立评估候选 JJ v2 模型。"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Dict, Iterable, Optional

import numpy as np
import onnxruntime as ort
from PIL import Image

from .cnn import CLASS_ORDER, INPUT_SIZE, load_labels


def _preprocess(path: str) -> np.ndarray:
    with Image.open(path) as source:
        image = source.convert("RGB").resize(
            (INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR
        )
    array = np.asarray(image, dtype=np.float32) / 255.0
    return np.ascontiguousarray(array.transpose(2, 0, 1))


def evaluate_onnx(
    dataset_dir: str,
    model_path: str,
    *,
    games: Optional[Iterable[int]] = None,
    output_path: Optional[str] = None,
    batch_size: int = 128,
) -> Dict:
    dataset_dir = os.path.abspath(os.path.expanduser(dataset_dir))
    model_path = os.path.abspath(os.path.expanduser(model_path))
    selected_games = None if games is None else {int(game) for game in games}
    records = load_labels(dataset_dir)
    if selected_games is not None:
        records = [
            record for record in records
            if int(record["game_index"]) in selected_games
        ]
    if not records:
        raise ValueError("ONNX evaluation selection is empty")

    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    predictions = []
    confidences = []
    size = max(1, int(batch_size))
    for start in range(0, len(records), size):
        batch_records = records[start:start + size]
        inputs = np.stack([_preprocess(record["absolute_path"]) for record in batch_records])
        logits = session.run(None, {input_name: inputs})[0]
        logits -= np.max(logits, axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= np.sum(probabilities, axis=1, keepdims=True)
        indices = np.argmax(probabilities, axis=1)
        predictions.extend(CLASS_ORDER[int(index)] for index in indices)
        confidences.extend(float(probabilities[row, index]) for row, index in enumerate(indices))

    totals = Counter()
    correct = Counter()
    confusion = Counter()
    errors = []
    for record, predicted, confidence in zip(records, predictions, confidences):
        expected = record["label"]
        totals[expected] += 1
        if expected == predicted:
            correct[expected] += 1
        else:
            confusion[(expected, predicted)] += 1
            errors.append({
                "path": record["path"],
                "game_index": int(record["game_index"]),
                "frame_id": record["frame_id"],
                "row": record["row"],
                "col": record["col"],
                "expected": expected,
                "predicted": predicted,
                "confidence": confidence,
            })
    per_class = {
        label: correct[label] / totals[label]
        for label in CLASS_ORDER if totals[label]
    }
    metrics = {
        "model_path": model_path,
        "games": sorted(selected_games) if selected_games is not None else "all",
        "samples": len(records),
        "accuracy": sum(correct.values()) / len(records),
        "macro_accuracy": sum(per_class.values()) / len(per_class),
        "per_class_accuracy": per_class,
        "class_counts": dict(totals),
        "confusion": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
        },
        "errors": errors,
    }
    if output_path:
        output_path = os.path.abspath(os.path.expanduser(output_path))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(metrics, file, ensure_ascii=False, indent=2)
    return metrics
