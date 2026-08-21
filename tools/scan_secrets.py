#!/usr/bin/env python3
"""Fail when files contain credential-shaped values or signed stream URLs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PATTERNS = {
    "netscape-alkass-cookie": re.compile(
        r"(?mi)^(?:#HttpOnly_)?(?:\.?shoof\.alkass\.net|\.?alkass\.net)\s+"
        r"(?:TRUE|FALSE)\s+/\s+(?:TRUE|FALSE)\s+\d+\s+"
        r"(?:PHPSESSID|Token|cookiesession1)\s+\S+"
    ),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    "literal-bearer": re.compile(r"(?i)Authorization\s*[:=]\s*[\"']?Bearer\s+[A-Za-z0-9._~-]{16,}"),
    "literal-session-value": re.compile(
        r"(?i)[\"'](?:PHPSESSID|Token|cookiesession1)[\"']\s*[:=]\s*[\"'][^\"']{16,}[\"']"
    ),
    "signed-stream-query": re.compile(
        r"(?i)https?://[^\s\"']+(?:token|signature|policy|key-pair-id)=[^\s\"'&]{12,}"
    ),
}

SKIP_PARTS = {".git", "__pycache__", ".venv", "venv"}
TEXT_SUFFIXES = {".py", ".ipynb", ".md", ".json", ".txt", ".yaml", ".yml", ".toml", ".ini"}


def iter_files(paths: list[Path]):
    for path in paths:
        if path.is_file():
            yield path
            continue
        for candidate in path.rglob("*"):
            if candidate.is_file() and not any(part in SKIP_PARTS for part in candidate.parts):
                yield candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    findings = []

    for path in iter_files(args.paths):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append((path, line, name))

    if findings:
        for path, line, name in findings:
            print(f"{path}:{line}: possible secret ({name})", file=sys.stderr)
        return 1

    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
