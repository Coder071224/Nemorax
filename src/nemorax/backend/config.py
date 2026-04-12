"""Compatibility exports for backend settings and paths."""

from nemorax.backend.core.settings import ENV_FILE, PROJECT_ROOT, Settings, settings


DATA_DIR = settings.paths.data_dir
USERS_DIR = settings.paths.users_dir
HISTORY_DIR = settings.paths.history_dir
FEEDBACK_DIR = settings.paths.feedback_dir
SCHOOL_INFO_JSON_PATH = settings.paths.knowledge_base_json_path
SCHOOL_INFO_PATH = settings.paths.knowledge_base_markdown_path

__all__ = [
    "DATA_DIR",
    "ENV_FILE",
    "FEEDBACK_DIR",
    "HISTORY_DIR",
    "PROJECT_ROOT",
    "SCHOOL_INFO_JSON_PATH",
    "SCHOOL_INFO_PATH",
    "Settings",
    "USERS_DIR",
    "settings",
]
