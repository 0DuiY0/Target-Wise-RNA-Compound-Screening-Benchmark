"""Audit public-release candidate files for local machine paths.

The audit is intentionally conservative: it scans text-like files for
drive-qualified paths, the current user's home directory, the current worktree
root, and conda ``prefix:`` entries. Binary files are skipped.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}

SKIP_SUFFIXES = {
    ".7z",
    ".bin",
    ".bz2",
    ".dll",
    ".exe",
    ".feather",
    ".gif",
    ".gz",
    ".jpg",
    ".jpeg",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".pkl",
    ".png",
    ".pt",
    ".pth",
    ".pyc",
    ".svgz",
    ".tar",
    ".tif",
    ".tiff",
    ".zip",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        nargs="+",
        type=Path,
        required=True,
        help="Files or directories to audit.",
    )
    parser.add_argument(
        "--output_csv",
        type=Path,
        default=None,
        help="Optional CSV path for audit findings.",
    )
    parser.add_argument(
        "--fail-on-local-paths",
        action="store_true",
        help="Exit non-zero if any finding is detected.",
    )
    parser.add_argument(
        "--include-binary",
        action="store_true",
        help="Attempt to scan files normally skipped by suffix.",
    )
    return parser.parse_args()


def iter_files(roots: list[Path], include_binary: bool) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if include_binary or root.suffix.lower() not in SKIP_SUFFIXES:
                files.append(root)
            continue
        for path in root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if not include_binary and path.suffix.lower() in SKIP_SUFFIXES:
                continue
            files.append(path)
    return sorted(set(files))


def normalized_variants(path: Path) -> list[str]:
    resolved = str(path.resolve())
    variants = {resolved, resolved.replace("\\", "/")}
    return sorted(variants, key=len, reverse=True)


def build_patterns() -> list[tuple[str, re.Pattern[str]]]:
    repo_root = Path(__file__).resolve().parents[1]
    home = Path.home()
    patterns: list[tuple[str, re.Pattern[str]]] = []

    # Build the regex string without embedding an actual local drive path in the
    # source file, so this script can audit itself.
    drive_prefix = r"(?<![A-Za-z0-9_])[A-Za-z]" + re.escape(":") + r"[\\/]"
    patterns.append(("drive_qualified_path", re.compile(drive_prefix + r"[^\s<>'\"`]+")))
    patterns.append(("conda_prefix_entry", re.compile(r"^\s*prefix\s*:\s*\S+", re.IGNORECASE)))

    for label, base_path in [("repo_root_path", repo_root), ("home_path", home)]:
        for variant in normalized_variants(base_path):
            if len(variant) >= 4:
                patterns.append((label, re.compile(re.escape(variant), re.IGNORECASE)))
    return patterns


def read_text(path: Path) -> str | None:
    for encoding in ["utf-8", "utf-8-sig", "latin-1"]:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def audit_file(path: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, object]]:
    text = read_text(path)
    if text is None or "\x00" in text[:2048]:
        return []
    findings: list[dict[str, object]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            for match in pattern.finditer(line):
                excerpt = match.group(0)
                findings.append(
                    {
                        "path": path.as_posix(),
                        "line": lineno,
                        "kind": kind,
                        "match": excerpt[:240],
                    }
                )
    return findings


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "line", "kind", "match"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    files = iter_files(args.root, args.include_binary)
    patterns = build_patterns()
    findings: list[dict[str, object]] = []
    for path in files:
        findings.extend(audit_file(path, patterns))

    if args.output_csv:
        write_csv(args.output_csv, findings)

    if findings:
        print(f"local path audit found {len(findings)} finding(s)")
        for row in findings[:20]:
            print(f"{row['path']}:{row['line']}: {row['kind']}: {row['match']}")
        if len(findings) > 20:
            print(f"... {len(findings) - 20} more finding(s)")
        if args.fail_on_local_paths:
            sys.exit(1)
    else:
        print(f"local path audit passed for {len(files)} text-like file(s)")


if __name__ == "__main__":
    main()
