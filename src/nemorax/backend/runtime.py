"""Application service container and runtime factory."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from nemorax.backend.core.settings import Settings, settings
from nemorax.backend.llm import ChatProvider, build_provider
from nemorax.backend.repositories import FeedbackRepository, HistoryRepository, UserRepository
from nemorax.backend.services import (
    AuthService,
    ChatService,
    FeedbackService,
    HistoryService,
    KnowledgeBasePromptService,
)


@dataclass(slots=True)
class ApplicationServices:
    settings: Settings
    user_repository: UserRepository
    history_repository: HistoryRepository
    feedback_repository: FeedbackRepository
    auth_service: AuthService
    history_service: HistoryService
    feedback_service: FeedbackService
    prompt_service: KnowledgeBasePromptService
    llm_provider: ChatProvider
    chat_service: ChatService

    def ensure_ready(self) -> None:
        self.settings.ensure_directories()


def build_services(config: Settings | None = None) -> ApplicationServices:
    resolved_settings = config or settings
    user_repository = UserRepository(resolved_settings.paths)
    history_repository = HistoryRepository(resolved_settings.paths)
    feedback_repository = FeedbackRepository(resolved_settings.paths)
    auth_service = AuthService(user_repository)
    history_service = HistoryService(history_repository)
    feedback_service = FeedbackService(feedback_repository)
    prompt_service = KnowledgeBasePromptService(
        resolved_settings.paths.knowledge_base_markdown_path,
        max_knowledge_chars=resolved_settings.llm.prompt_knowledge_chars,
    )
    provider = build_provider(resolved_settings.llm)
    chat_service = ChatService(
        settings=resolved_settings,
        provider=provider,
        prompt_service=prompt_service,
        history_service=history_service,
    )
    return ApplicationServices(
        settings=resolved_settings,
        user_repository=user_repository,
        history_repository=history_repository,
        feedback_repository=feedback_repository,
        auth_service=auth_service,
        history_service=history_service,
        feedback_service=feedback_service,
        prompt_service=prompt_service,
        llm_provider=provider,
        chat_service=chat_service,
    )


@lru_cache(maxsize=1)
def get_runtime_services() -> ApplicationServices:
    return build_services()
