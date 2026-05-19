from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.seed.local_dataset_mapper import ensure_local_dataset_files, export_bundle_to_local
from backend.app.seed.local_graph_exporter import export_graphs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_path")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--generate-graphs", action="store_true")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    result = {
        "bundle_path": args.bundle_path,
        "data_root": str(data_root),
        "ensured": ensure_local_dataset_files(data_root),
        "exported": export_bundle_to_local(Path(args.bundle_path), data_root),
    }
    if args.generate_graphs:
        result["graphs"] = export_graphs(data_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
