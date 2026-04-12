from __future__ import annotations

from pathlib import Path

from .validation import validate_kb


class KnowledgeBaseValidator:
    """Compatibility wrapper around the current validation entrypoint."""

    def __init__(self, output_dir: str = "kb") -> None:
        self.output_dir = Path(output_dir)

    def validate(self) -> dict:
        return validate_kb(self.output_dir)


__all__ = ["KnowledgeBaseValidator", "validate_kb"]
