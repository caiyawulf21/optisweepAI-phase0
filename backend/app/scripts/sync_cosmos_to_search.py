from __future__ import annotations

import argparse
import json

from backend.app.repositories.cosmos_client import cosmos_container
from backend.app.search.index_documents import INDEXED_CONTAINERS, search_documents_from_container_documents
from backend.app.search.search_client import search_client


def load_cosmos_documents() -> dict[str, list[dict]]:
    documents = {}
    for container_name in sorted(INDEXED_CONTAINERS):
        container = cosmos_container(container_name)
        documents[container_name] = list(container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))
    return documents


def upload_documents(documents: list[dict]) -> dict:
    client = search_client()
    result = client.upload_documents(documents)
    return {"submitted": len(documents), "succeeded": sum(1 for item in result if item.succeeded), "failed": sum(1 for item in result if not item.succeeded)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cosmos_documents = load_cosmos_documents()
    search_documents = search_documents_from_container_documents(cosmos_documents)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "search_document_count": len(search_documents), "documents": search_documents}, indent=2, ensure_ascii=False))
        return
    print(json.dumps({"dry_run": False, "upload": upload_documents(search_documents)}, indent=2))


if __name__ == "__main__":
    main()
