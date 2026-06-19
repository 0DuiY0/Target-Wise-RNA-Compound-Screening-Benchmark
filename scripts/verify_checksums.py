"""Write or verify SHA-256 checksums for public release artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import pandas as pd


DEFAULT_STATUSES = {"GREEN_PUBLIC"}
SKIP_SUFFIXES = {".png", ".pdf", ".csv", ".json", ".md", ".py", ".tex", ".bib", ".bst", ".cls", ".txt", ".yml"}


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Write checksums instead of verifying them.")
    parser.add_argument(
        "--include-status",
        nargs="+",
        default=sorted(DEFAULT_STATUSES),
        help="Manifest public_status values to include.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_manifest_paths(root: Path, manifest_path: Path, statuses: set[str]) -> list[Path]:
    manifest = pd.read_csv(manifest_path)
    required = {"relative_path", "public_status"}
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise KeyError(f"{manifest_path} is missing required columns: {missing}")

    paths: list[Path] = []
    for _, row in manifest.iterrows():
        if str(row["public_status"]) not in statuses:
            continue
        rel = str(row["relative_path"]).strip()
        if not rel or rel == "nan":
            continue
        path = (root / rel).resolve()
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    paths.append(child)
        elif path.is_file():
            paths.append(path)
    return sorted(set(paths))


def write_checksums(root: Path, paths: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in paths:
        rows.append(
            {
                "relative_path": path.resolve().relative_to(root.resolve()).as_posix(),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path", "sha256", "size_bytes"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {output_path} with {len(rows)} artifact checksum(s)")


def verify_checksums(root: Path, checksum_path: Path) -> int:
    checksums = pd.read_csv(checksum_path)
    required = {"relative_path", "sha256"}
    missing = sorted(required.difference(checksums.columns))
    if missing:
        raise KeyError(f"{checksum_path} is missing required columns: {missing}")

    failures = []
    for _, row in checksums.iterrows():
        path = (root / str(row["relative_path"])).resolve()
        expected = str(row["sha256"])
        if not path.exists():
            failures.append((str(row["relative_path"]), "missing"))
            continue
        actual = sha256(path)
        if actual != expected:
            failures.append((str(row["relative_path"]), "sha256 mismatch"))

    if failures:
        print(f"checksum verification failed for {len(failures)} artifact(s)")
        for rel, reason in failures[:20]:
            print(f"{rel}: {reason}")
        return 1
    print(f"checksum verification passed for {len(checksums)} artifact(s)")
    return 0


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    if args.write:
        if args.manifest is None:
            raise ValueError("--manifest is required when --write is used")
        paths = iter_manifest_paths(root, args.manifest, set(args.include_status))
        write_checksums(root, paths, args.checksums)
    else:
        sys.exit(verify_checksums(root, args.checksums))


if __name__ == "__main__":
    main()
