from __future__ import annotations

import argparse
import json

from backend.app.config.settings import get_settings
from backend.app.storage.blob_client import blob_service_client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    container_names = [settings.raw_artifacts_container, settings.processed_artifacts_container]
    if args.dry_run:
        print(json.dumps({"dry_run": True, "containers": container_names}, indent=2))
        return
    service = blob_service_client(settings)
    created = []
    for container_name in container_names:
        container = service.get_container_client(container_name)
        try:
            container.create_container()
        except Exception as exc:
            if exc.__class__.__name__ != "ResourceExistsError":
                raise
        created.append(container_name)
    print(json.dumps({"containers": created}, indent=2))


if __name__ == "__main__":
    main()
