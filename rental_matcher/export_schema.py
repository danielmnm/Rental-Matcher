"""
Export the canonical Listing model as JSON Schema.

Writes two files:
  schema/listing.schema.json              the current contract
  schema/history/listing.schema.v<N>.json  a frozen copy for version N

The history copies are what let a non-Python consumer (and
tests/test_migrations.py) check that a record stamped with an OLD version
really conforms to that version's contract. Earlier snapshots were
recovered from git history; this script only ever writes the CURRENT
version's snapshot, never an older one.

tests/test_schema.py fails if either file is stale, so forgetting to
re-run this after editing schema.py can't go unnoticed.

Usage:
    python -m rental_matcher.export_schema
"""

import json
from pathlib import Path

from .schema import SCHEMA_VERSION, Listing

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
OUTPUT_PATH = SCHEMA_DIR / "listing.schema.json"
HISTORY_DIR = SCHEMA_DIR / "history"


def history_path(version: str) -> Path:
    return HISTORY_DIR / f"listing.schema.v{version}.json"


def render() -> str:
    return json.dumps(Listing.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    text = render()
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    history_path(SCHEMA_VERSION).write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} and {history_path(SCHEMA_VERSION)}")


if __name__ == "__main__":
    main()
