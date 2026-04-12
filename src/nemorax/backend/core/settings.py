"""Centralized runtime settings for the Nemorax backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[3]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def _read_str(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return default


def _read_int(*names: str, default: int) -> int:
    raw = _read_str(*names, default=str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _read_float(*names: str, default: float) -> float:
    raw = _read_str(*names, default=str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve_path(raw: str, *, base: Path) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _normalize_provider(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "groq": "groq",
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
    }
    return aliases.get(normalized, normalized or "groq")


@dataclass(frozen=True, slots=True)
class PathSettings:
    project_root: Path
    data_dir: Path
    users_dir: Path
    history_dir: Path
    feedback_dir: Path
    knowledge_base_markdown_path: Path
    knowledge_base_json_path: Path
    knowledge_base_chunks_path: Path

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.users_dir, self.history_dir, self.feedback_dir):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    app_name: str
    app_version: str
    environment: str
    log_level: str
    backend_host: str
    backend_port: int
    backend_url: str
    cors_origins_raw: str

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_origins_raw == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class LLMSettings:
    provider: str
    model: str
    fallback_model: str | None
    base_url: str
    api_key: str | None
    request_timeout_seconds: float
    health_timeout_seconds: float
    temperature: float
    top_p: float
    max_completion_tokens: int
    reasoning_effort: str
    include_reasoning: bool
    stream: bool
    seed: int | None
    max_context_tokens: int
    message_window: int
    prompt_knowledge_chars: int

    @property
    def provider_label(self) -> str:
        labels = {
            "groq": "Groq",
            "openai_compatible": "OpenAI-compatible",
        }
        return labels.get(self.provider, self.provider.title())


@dataclass(frozen=True, slots=True)
class Settings:
    api: ApiSettings
    llm: LLMSettings
    paths: PathSettings

    @property
    def app_name(self) -> str:
        return self.api.app_name

    @property
    def app_version(self) -> str:
        return self.api.app_version

    @property
    def environment(self) -> str:
        return self.api.environment

    @property
    def backend_host(self) -> str:
        return self.api.backend_host

    @property
    def backend_port(self) -> int:
        return self.api.backend_port

    @property
    def backend_url(self) -> str:
        return self.api.backend_url

    @property
    def cors_origins(self) -> list[str]:
        return self.api.cors_origins

    @property
    def log_level(self) -> str:
        return self.api.log_level

    def ensure_directories(self) -> None:
        self.paths.ensure_directories()


def load_settings() -> Settings:
    provider = _normalize_provider(_read_str("LLM_PROVIDER", default="groq"))

    data_dir = _resolve_path(
        _read_str("NEMORAX_DATA_DIR", default="data"),
        base=PROJECT_ROOT,
    )
    paths = PathSettings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        users_dir=data_dir / "USERS",
        history_dir=data_dir / "HISTORY",
        feedback_dir=data_dir / "FEEDBACK",
        knowledge_base_markdown_path=_resolve_path(
            _read_str("NEMORAX_KB_MARKDOWN_PATH", default="data/school_info.md"),
            base=PROJECT_ROOT,
        ),
        knowledge_base_json_path=_resolve_path(
            _read_str("NEMORAX_KB_JSON_PATH", default="data/school_info.json"),
            base=PROJECT_ROOT,
        ),
        knowledge_base_chunks_path=_resolve_path(
            _read_str("NEMORAX_KB_CHUNKS_PATH", default="kb/chunks.jsonl"),
            base=PROJECT_ROOT,
        ),
    )

    if provider == "groq":
        llm_base_url = _read_str("LLM_BASE_URL", "GROQ_BASE_URL", default="https://api.groq.com/openai/v1")
        llm_model = _read_str("LLM_MODEL", "GROQ_MODEL", default="")
        llm_api_key = _read_str("LLM_API_KEY", "GROQ_API_KEY", default="") or None
    else:
        llm_base_url = _read_str(
            "LLM_BASE_URL",
            "OPENAI_COMPAT_BASE_URL",
            default="https://api.openai.com/v1",
        )
        llm_model = _read_str("LLM_MODEL", "OPENAI_COMPAT_MODEL", default="")
        llm_api_key = _read_str("LLM_API_KEY", "OPENAI_API_KEY", default="") or None

    api = ApiSettings(
        app_name=_read_str("NEMORAX_APP_NAME", default="Nemorax API"),
        app_version=_read_str("NEMORAX_APP_VERSION", default="1.0.0"),
        environment=_read_str("NEMORAX_ENV", default="development"),
        log_level=_read_str("LOG_LEVEL", default="INFO"),
        backend_host=_read_str("BACKEND_HOST", default="0.0.0.0"),
        backend_port=_read_int("BACKEND_PORT", default=8000),
        backend_url=_read_str("BACKEND_URL", default="http://127.0.0.1:8000"),
        cors_origins_raw=_read_str("CORS_ORIGINS", default="*"),
    )
    llm = LLMSettings(
        provider=provider,
        model=llm_model or "openai/gpt-oss-20b",
        fallback_model=_read_str("LLM_FALLBACK_MODEL", "GROQ_FALLBACK_MODEL", default="") or None,
        base_url=llm_base_url,
        api_key=llm_api_key,
        request_timeout_seconds=_read_float("REQUEST_TIMEOUT_SECONDS", default=180.0),
        health_timeout_seconds=_read_float("HEALTH_TIMEOUT_SECONDS", default=4.0),
        temperature=_read_float("LLM_TEMPERATURE", default=0.25),
        top_p=_read_float("LLM_TOP_P", default=1.0),
        max_completion_tokens=_read_int("LLM_MAX_COMPLETION_TOKENS", default=900),
        reasoning_effort=_read_str("LLM_REASONING_EFFORT", default="medium").lower() or "medium",
        include_reasoning=_read_str("LLM_INCLUDE_REASONING", default="false").lower() in {"1", "true", "yes", "on"},
        stream=_read_str("LLM_STREAM", default="true").lower() in {"1", "true", "yes", "on"},
        seed=(
            None
            if _read_str("LLM_SEED", default="7").strip().lower() in {"", "none", "null"}
            else _read_int("LLM_SEED", default=7)
        ),
        max_context_tokens=_read_int("LLM_MAX_CONTEXT_TOKENS", default=16384),
        message_window=_read_int("LLM_MESSAGE_WINDOW", default=10),
        prompt_knowledge_chars=_read_int("LLM_PROMPT_KNOWLEDGE_CHARS", default=6000),
    )

    settings = Settings(api=api, llm=llm, paths=paths)
    settings.ensure_directories()
    return settings


settings = load_settings()

__all__ = [
    "ENV_FILE",
    "PROJECT_ROOT",
    "ApiSettings",
    "LLMSettings",
    "PathSettings",
    "Settings",
    "load_settings",
    "settings",
]
