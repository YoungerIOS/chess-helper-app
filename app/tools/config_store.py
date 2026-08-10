"""Persistence helpers for the split default/user configuration."""

from __future__ import annotations

import copy
import json
import os
from typing import Dict


def write_json_atomic(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
    os.replace(tmp_path, path)


def load_config(default_path: str, user_path: str) -> Dict:
    """Load defaults plus user overrides and seed the user file on first run."""
    with open(default_path, "r", encoding="utf-8") as file:
        defaults = json.load(file)

    config = copy.deepcopy(defaults)
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as file:
            config.update(json.load(file))
    else:
        write_json_atomic(user_path, config)
    return config

