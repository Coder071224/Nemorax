from __future__ import annotations

from pathlib import Path

from .builder import KnowledgeBaseBuilder as _KnowledgeBaseBuilder


class KnowledgeBaseBuilder(_KnowledgeBaseBuilder):
    """Compatibility wrapper for older imports."""

    def __init__(self, config, output_root: Path | None = None):
        root = output_root or Path(config.output_directory)
        super().__init__(config, root)
