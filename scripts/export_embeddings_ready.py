from __future__ import annotations

import argparse

from _kb_common import ROOT, load_config
from nemorax.kb.models import ChunkRecord
from nemorax.kb.utils import dump_json, iter_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Export KB chunks in a flat embeddings-ready JSON shape.")
    parser.add_argument("--config", default=None, help="Path to the JSON crawl config.")
    args = parser.parse_args()

    config = load_config(args.config)
    output_root = ROOT / config.output_directory
    chunks = [ChunkRecord.model_validate(row) for row in iter_jsonl(output_root / "chunks.jsonl")]
    rows = [
        {
            "id": chunk.chunk_id,
            "text": chunk.normalized_text,
            "metadata": {
                "page_id": chunk.page_id,
                "url": chunk.url,
                "title": chunk.title,
                "heading_path": chunk.heading_path,
                "page_type": chunk.page_type,
                "topic": chunk.topic,
                "publication_date": chunk.publication_date,
                "updated_date": chunk.updated_date,
                "freshness": chunk.freshness,
                "entities": chunk.entities,
            },
        }
        for chunk in chunks
    ]
    dump_json(output_root / "embeddings_ready.json", rows)
    print(f"Exported {len(rows)} chunks to {(output_root / 'embeddings_ready.json').resolve()}")


if __name__ == "__main__":
    main()
