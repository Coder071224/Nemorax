from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("BACKEND_PORT") or os.environ.get("PORT") or "8000")
    print(f"[railway_backend] Starting backend on {host}:{port}", flush=True)
    uvicorn.run(
        "nemorax.backend.main:app",
        app_dir="src",
        host=host,
        port=port,
    )
