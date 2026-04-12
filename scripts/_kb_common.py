from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.kb.models import CrawlConfig  # noqa: E402


def load_config(path: str | None = None) -> CrawlConfig:
    config_path = Path(path) if path else ROOT / "config" / "nemsu_kb.json"
    return CrawlConfig.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
