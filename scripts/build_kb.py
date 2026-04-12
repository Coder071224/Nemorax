from __future__ import annotations

import argparse

from _kb_common import ROOT, load_config
from nemorax.kb.builder import KnowledgeBaseBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Build retrieval-ready KB artifacts from raw crawl outputs.")
    parser.add_argument("--config", default=None, help="Path to the JSON crawl config.")
    args = parser.parse_args()

    config = load_config(args.config)
    builder = KnowledgeBaseBuilder(config, ROOT / config.output_directory)
    summary = builder.build()
    print(summary)


if __name__ == "__main__":
    main()
