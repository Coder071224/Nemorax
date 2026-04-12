from __future__ import annotations

import argparse

from _kb_common import ROOT, load_config
from nemorax.kb.validation import validate_kb


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the generated KB outputs.")
    parser.add_argument("--config", default=None, help="Path to the JSON crawl config.")
    args = parser.parse_args()

    config = load_config(args.config)
    summary = validate_kb(ROOT / config.output_directory)
    print(summary)


if __name__ == "__main__":
    main()
