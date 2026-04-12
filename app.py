from __future__ import annotations

import sys
from pathlib import Path

import flet as ft


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_src_path()


if __name__ == "__main__":
    from nemorax.frontend.main import main

    ft.run(main, assets_dir="assets")
