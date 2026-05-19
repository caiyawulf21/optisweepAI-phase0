from __future__ import annotations

import argparse
import json

from backend.app.repositories.container_config import CONTAINERS
from backend.app.repositories.cosmos_client import create_containers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        containers = [{"container": definition.name, "partition_key": definition.partition_key} for definition in CONTAINERS.values()]
        print(json.dumps({"dry_run": True, "containers": containers}, indent=2))
        return
    print(json.dumps({"created": create_containers()}, indent=2))


if __name__ == "__main__":
    main()
