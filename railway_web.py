from __future__ import annotations

import os
import sys
from pathlib import Path


print("[railway_web] Process started", flush=True)


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


import flet as ft

from nemorax.frontend.main import main


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(
        os.environ.get("WEB_PORT")
        or os.environ.get("FLET_SERVER_PORT")
        or os.environ.get("PORT")
        or "8000"
    )
    print(f"[railway_web] Starting Flet on {host}:{port}", flush=True)
    ft.run(
        main,
        assets_dir="assets",
        view=ft.AppView.WEB_BROWSER,
        host=host,
        port=port,
    )
