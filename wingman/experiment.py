"""Append structured experiment records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import config


def _experiments_dir() -> Path:
    data = getattr(config, "DATA_DIR", config.BASE_DIR / "data")
    return data / "experiments"


def append_wingman_record(record: dict[str, Any]) -> Path:
    path = _experiments_dir() / "wingman.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if "timestamp" not in record:
        record["timestamp"] = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def new_profile_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
