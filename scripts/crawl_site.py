from __future__ import annotations

import argparse
import asyncio

from _kb_common import ROOT, load_config
from nemorax.kb.crawler import SiteCrawler


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl the public NEMSU site into raw HTML crawl data.")
    parser.add_argument("--config", default=None, help="Path to the JSON crawl config.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing crawl manifest and start fresh.")
    args = parser.parse_args()

    config = load_config(args.config)
    crawler = SiteCrawler(config, ROOT / config.output_directory)
    records = asyncio.run(crawler.crawl(resume=not args.no_resume))
    print(f"Crawled {len(records)} HTML pages into {(ROOT / config.output_directory / 'raw').resolve()}")


if __name__ == "__main__":
    main()
