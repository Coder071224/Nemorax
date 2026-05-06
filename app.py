from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft

LOCAL_API_URL = "http://127.0.0.1:8000"
PUBLIC_API_URL = "https://nemorax-backend-c1ma.onrender.com"


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _running_on_android() -> bool:
    return sys.platform == "android" or bool(os.getenv("ANDROID_ROOT") or os.getenv("ANDROID_ARGUMENT"))


_bootstrap_src_path()
os.environ.setdefault("NEMORAX_API_URL", PUBLIC_API_URL if _running_on_android() else LOCAL_API_URL)


if __name__ == "__main__":
    from nemorax.frontend.main import main

    ft.run(main, assets_dir="assets")
