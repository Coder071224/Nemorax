from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _configure_web_server_env() -> None:
    os.environ.setdefault("FLET_FORCE_WEB_SERVER", "true")
    os.environ.setdefault("FLET_SERVER_IP", "0.0.0.0")

    port = os.getenv("PORT", "").strip()
    if port:
        os.environ["FLET_SERVER_PORT"] = port
    else:
        os.environ.setdefault("FLET_SERVER_PORT", "8550")


_bootstrap_src_path()
_configure_web_server_env()


if __name__ == "__main__":
    from nemorax.frontend.main import main

    ft.run(main, assets_dir="assets", view=ft.AppView.WEB_BROWSER)
