from __future__ import annotations

import argparse
import asyncio

from _kb_common import ROOT, load_config
from nemorax.kb.documents import LinkedDocumentIngestor
from nemorax.kb.models import CrawlRecord
from nemorax.kb.utils import iter_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest linked NEMSU documents from the crawl manifest.")
    parser.add_argument("--config", default=None, help="Path to the JSON crawl config.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing document manifest and re-fetch.")
    args = parser.parse_args()

    config = load_config(args.config)
    output_root = ROOT / config.output_directory
    crawl_records = [CrawlRecord.model_validate(row) for row in iter_jsonl(output_root / "raw" / "crawl_manifest.jsonl")]
    ingestor = LinkedDocumentIngestor(config, output_root)
    records = asyncio.run(ingestor.ingest(crawl_records, resume=not args.no_resume))
    print(f"Processed {len(records)} linked documents into {(output_root / 'raw').resolve()}")


if __name__ == "__main__":
    main()
