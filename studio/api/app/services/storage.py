from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[4]
API_DIR = ROOT_DIR / "studio" / "api"
DATA_DIR = API_DIR / "data"
MODULE_DIR = DATA_DIR / "modules"
BUILD_DIR = DATA_DIR / "builds"
JOB_DIR = DATA_DIR / "jobs"

FREQTRADE_DIR = ROOT_DIR / "freqtrade"
GENERATED_STRATEGY_DIR = FREQTRADE_DIR / "user_data" / "strategies" / "generated"
BACKTEST_RESULTS_DIR = FREQTRADE_DIR / "user_data" / "backtest_results"


def ensure_directories() -> None:
    for path in (
        DATA_DIR,
        MODULE_DIR,
        BUILD_DIR,
        JOB_DIR,
        GENERATED_STRATEGY_DIR,
        BACKTEST_RESULTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = uuid.uuid4().hex[:6]
    return f"{prefix}_{stamp}_{rand}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


ensure_directories()
