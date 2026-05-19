from __future__ import annotations

import argparse
import json

from backend.app.search.index_schema import build_search_index
from backend.app.search.search_client import search_index_client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    index = build_search_index()
    if args.dry_run:
        print(json.dumps({"dry_run": True, "index_name": index.name, "fields": [field.name for field in index.fields]}, indent=2))
        return
    client = search_index_client()
    client.create_or_update_index(index)
    print(json.dumps({"dry_run": False, "index_name": index.name}, indent=2))


if __name__ == "__main__":
    main()
