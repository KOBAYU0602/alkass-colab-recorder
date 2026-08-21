#!/usr/bin/env python3
"""Create a shareable notebook copy with outputs and execution state removed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def sanitize(data: dict) -> dict:
    for cell in data.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        metadata = cell.setdefault("metadata", {})
        for key in ("execution", "collapsed", "scrolled"):
            metadata.pop(key, None)

    metadata = data.setdefault("metadata", {})
    metadata.pop("widgets", None)
    colab = metadata.get("colab")
    if isinstance(colab, dict):
        for key in ("authorship_tag", "include_colab_link", "mount_file_id"):
            colab.pop(key, None)
        colab["provenance"] = []
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("notebook", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = args.notebook.resolve()
    output = (args.output or source.with_name(source.stem + ".sanitized.ipynb")).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    output.write_text(json.dumps(sanitize(data), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
