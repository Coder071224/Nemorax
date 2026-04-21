from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def _start_backend() -> None:
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = os.getenv("PORT", os.getenv("BACKEND_PORT", "8000"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "nemorax.backend.main:app",
            "--app-dir",
            str(SRC_DIR),
            "--host",
            host,
            "--port",
            port,
        ],
        check=False,
        cwd=str(PROJECT_ROOT),
    )


def _wait_for_backend(host: str, port: int, *, timeout_seconds: float = 10.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_port_in_use(host, port):
            return True
        time.sleep(0.2)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Nemorax")
    parser.add_argument("--web", action="store_true", help="Open as web app")
    parser.add_argument(
        "--no-backend",
        action="store_true",
        help="Skip starting the backend (assumes it is already running)",
    )
    args = parser.parse_args()

    port = int(os.getenv("PORT", os.getenv("BACKEND_PORT", "8000")))
    os.environ.setdefault("NEMORAX_API_URL", f"http://127.0.0.1:{port}")

    if not args.no_backend:
        if _is_port_in_use("127.0.0.1", port):
            print(f"[run.py] Backend already running on http://127.0.0.1:{port}, skipping new backend start.")
        else:
            backend_thread = threading.Thread(target=_start_backend, daemon=True)
            backend_thread.start()
            print(f"[run.py] Backend starting on http://127.0.0.1:{port} ...")
            if not _wait_for_backend("127.0.0.1", port):
                print(f"[run.py] Backend did not become reachable within 10 seconds on port {port}.")

    import flet as ft
    from nemorax.frontend.main import main as flet_main

    if args.web:
        ft.run(flet_main, assets_dir="assets", view=ft.AppView.WEB_BROWSER)
    else:
        ft.run(flet_main, assets_dir="assets")


if __name__ == "__main__":
    main()
