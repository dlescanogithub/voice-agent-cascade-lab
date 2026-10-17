"""Lightweight secret scan used by CI. It does not call a network service."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("vendor_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
)

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "var",
        "reports",
        "htmlcov",
        "dist",
        "build",
        ".eggs",
    }
)
SKIP_SUFFIXES = frozenset({".wav", ".png", ".pyc", ".egg", ".whl", ".so", ".dylib"})


def scan_path(root: Path) -> list[str]:
    findings: list[str] = []
    target = root.resolve()
    files = (
        [target]
        if target.is_file()
        else sorted(path for path in target.rglob("*") if path.is_file())
    )
    for path in files:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name == ".env":
            findings.append(f"env_file:{path}")
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS:
            if pattern.search(text):
                findings.append(f"{name}:{path}")
                break
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0] if args else ".")
    findings = scan_path(root)
    if findings:
        for finding in findings:
            print(f"secret-scan: {finding}")
        return 1
    print(f"secret-scan: clean ({root})")
    return 0
