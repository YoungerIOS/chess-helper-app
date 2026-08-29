"""训练并评估JJ 棋子分类 CNN。

训练依赖是可选的，运行主程序不需要安装 PyTorch。数据始终按完整对局
切分，避免同一局相邻帧同时落入训练集和验证集造成虚高。
"""

from __future__ import annotations

import json
import math
import os
import random
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageEnhance

INPUT_SIZE = 80
CLASS_ORDER = ["-", ".", "a", "b", "c", "k", "n", "p", "r", "A", "B", "C", "K", "N", "P", "R"]


def load_labels(dataset_dir: str) -> List[Dict]:
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
                    f"missing sample on labels line {line_number}: "
                    f"{record['absolute_path']}"
                )
            records.append(record)
    return records


def split_records_by_game(
    records: Sequence[Dict], holdout_games: Iterable[int]
) -> Tuple[List[Dict], List[Dict]]:
    holdouts = {int(game) for game in holdout_games}
    if not holdouts:
        raise ValueError("at least one holdout game is required")
    training = [r for r in records if int(r["game_index"]) not in holdouts]
    validation = [r for r in records if int(r["game_index"]) in holdouts]
    if not training or not validation:
        raise ValueError("training or validation split is empty")
    missing = sorted(set(CLASS_ORDER) - {r["label"] for r in training})
    if missing:
        raise ValueError(f"training split is missing classes: {missing}")
    return training, validation


def _torch_modules():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
    except ImportError as exc:
        raise RuntimeError(
            "CNN training requires the optional dependencies in requirements-train.txt"
        ) from exc
    return torch, nn, DataLoader, Dataset, WeightedRandomSampler


def create_model(num_classes: int = len(CLASS_ORDER)):
    torch, nn, _, _, _ = _torch_modules()

    class JJPiecesCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(3, 24, 3, padding=1, bias=False),
                nn.BatchNorm2d(24),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(24, 48, 3, padding=1, bias=False),
                nn.BatchNorm2d(48),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(48, 96, 3, padding=1, bias=False),
                nn.BatchNorm2d(96),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(96, 128, 3, padding=1, bias=False),
                nn.BatchNorm2d(128),
                nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d(1),
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Dropout(0.2),
                nn.Linear(128, num_classes),
            )

        def forward(self, inputs):
            return self.classifier(self.features(inputs))

    return JJPiecesCNN()


def _image_tensor(path: str, *, augment: bool, torch):
    with Image.open(path) as source:
        image = source.convert("RGB").resize(
            (INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR
        )
    if augment:
        image = image.rotate(random.uniform(-3.0, 3.0), resample=Image.Resampling.BILINEAR)
        image = ImageEnhance.Brightness(image).enhance(random.uniform(0.88, 1.12))
        image = ImageEnhance.Contrast(image).enhance(random.uniform(0.90, 1.10))
    array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(np.ascontiguousarray(array.transpose(2, 0, 1)))


def _accuracy(logits, targets, torch) -> Tuple[int, Counter, Counter]:
    predictions = torch.argmax(logits, dim=1)
    correct = predictions.eq(targets)
    class_correct = Counter()
    class_total = Counter()
    for target, is_correct in zip(targets.tolist(), correct.tolist()):
        class_total[int(target)] += 1
        if is_correct:
            class_correct[int(target)] += 1
    return int(correct.sum().item()), class_correct, class_total


def train_cnn(
    dataset_dir: str,
    output_dir: str,
    *,
    holdout_games: Iterable[int],
    epochs: int = 35,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    balance_power: float = 0.5,
    seed: int = 20260814,
) -> Dict:
    torch, nn, DataLoader, Dataset, WeightedRandomSampler = _torch_modules()
    dataset_dir = os.path.abspath(os.path.expanduser(dataset_dir))
    output_dir = os.path.abspath(os.path.expanduser(output_dir))
    os.makedirs(output_dir, exist_ok=True)
    holdout_games = sorted({int(game) for game in holdout_games})
    training, validation = split_records_by_game(
        load_labels(dataset_dir), holdout_games
    )

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    label_to_index = {label: index for index, label in enumerate(CLASS_ORDER)}

    class PieceDataset(Dataset):
        def __init__(self, records, augment=False):
            self.records = records
            self.augment = augment

        def __len__(self):
            return len(self.records)

        def __getitem__(self, index):
            record = self.records[index]
            return (
                _image_tensor(
                    record["absolute_path"], augment=self.augment, torch=torch
                ),
                label_to_index[record["label"]],
            )

    counts = Counter(record["label"] for record in training)
    balance_power = max(0.0, min(1.0, float(balance_power)))
    sample_weights = [
        1.0 / math.pow(counts[record["label"]], balance_power)
        for record in training
    ]
    generator = torch.Generator().manual_seed(seed)
    sampler = WeightedRandomSampler(
        sample_weights, len(training), replacement=True, generator=generator
    )
    train_loader = DataLoader(
        PieceDataset(training, augment=True),
        batch_size=max(1, int(batch_size)),
        sampler=sampler,
        num_workers=0,
    )
    validation_loader = DataLoader(
        PieceDataset(validation),
        batch_size=max(1, int(batch_size)),
        shuffle=False,
        num_workers=0,
    )

    model = create_model().to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=float(learning_rate), weight_decay=1e-4
    )
    criterion = nn.CrossEntropyLoss(label_smoothing=0.03)
    history = []
    best_board_accuracy = -1.0
    best_macro = -1.0
    best_path = os.path.join(output_dir, "best_model.pt")

    for epoch in range(1, max(1, int(epochs)) + 1):
        model.train()
        train_loss = 0.0
        for inputs, targets in train_loader:
            inputs, targets = inputs.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(inputs), targets)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(targets)

        model.eval()
        validation_loss = 0.0
        total_correct = 0
        class_correct = Counter()
        class_total = Counter()
        with torch.inference_mode():
            for inputs, targets in validation_loader:
                inputs, targets = inputs.to(device), targets.to(device)
                logits = model(inputs)
                validation_loss += float(criterion(logits, targets).item()) * len(targets)
                correct, per_correct, per_total = _accuracy(logits, targets, torch)
                total_correct += correct
                class_correct.update(per_correct)
                class_total.update(per_total)
        per_class = {
            CLASS_ORDER[index]: class_correct[index] / count
            for index, count in sorted(class_total.items()) if count
        }
        macro_accuracy = sum(per_class.values()) / len(per_class)
        marker_index = label_to_index["."]
        board_total = len(validation) - class_total[marker_index]
        board_correct = total_correct - class_correct[marker_index]
        board_accuracy = board_correct / board_total
        epoch_metrics = {
            "epoch": epoch,
            "train_loss": train_loss / len(training),
            "validation_loss": validation_loss / len(validation),
            "accuracy": total_correct / len(validation),
            "macro_accuracy": macro_accuracy,
            "board_accuracy": board_accuracy,
            "per_class_accuracy": per_class,
        }
        history.append(epoch_metrics)
        print(json.dumps(epoch_metrics, ensure_ascii=False))
        if (board_accuracy, macro_accuracy) > (best_board_accuracy, best_macro):
            best_board_accuracy = board_accuracy
            best_macro = macro_accuracy
            torch.save(model.state_dict(), best_path)

    model.load_state_dict(torch.load(best_path, map_location=device, weights_only=True))
    model.eval().cpu()
    onnx_path = os.path.join(output_dir, "jj_piece_model.onnx")
    torch.onnx.export(
        model,
        (torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE),),
        onnx_path,
        input_names=["images"],
        output_names=["logits"],
        dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    class_map = {str(index): label for index, label in enumerate(CLASS_ORDER)}
    with open(os.path.join(output_dir, "jj_piece_map.json"), "w", encoding="utf-8") as file:
        json.dump(class_map, file, ensure_ascii=False, indent=2)
    metrics = {
        "dataset_dir": dataset_dir,
        "holdout_games": holdout_games,
        "training_samples": len(training),
        "validation_samples": len(validation),
        "training_class_counts": dict(sorted(counts.items())),
        "balance_power": balance_power,
        "best_board_accuracy": best_board_accuracy,
        "best_macro_accuracy": best_macro,
        "best_epoch": max(
            history, key=lambda item: (item["board_accuracy"], item["macro_accuracy"])
        )["epoch"],
        "best_validation": max(
            history, key=lambda item: (item["board_accuracy"], item["macro_accuracy"])
        ),
        "history": history,
        "device": str(device),
        "onnx_path": onnx_path,
        "note": (
            "candidate model only; selection prioritizes board classes because a "
            "missing optional move marker is safer than a false marker"
        ),
    }
    with open(os.path.join(output_dir, "training_metrics.json"), "w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)
    return metrics
