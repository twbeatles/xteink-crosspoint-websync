"""Read-only storage inventory. An explicit application/shared root is required.

Only metadata is read. No config/DB contents, credentials or article text is read.
No retention policy is applied: replicas and tombstones must not be pruned blindly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def storage_report(root: Path) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Storage root must be a directory")
    groups = {name: {"files": 0, "bytes": 0} for name in ("epubs", "logs", "replicas", "history")}
    errors = 0
    for folder, group in ((root / "output", "epubs"), (root / "logs", "logs"),
                          (root / ".websync-replicas", "replicas")):
        if folder.is_symlink():
            continue
        try:
            for path in folder.rglob("*"):
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    if group == "epubs" and path.suffix.lower() != ".epub":
                        continue
                    groups[group]["bytes"] += path.stat().st_size
                    groups[group]["files"] += 1
                except OSError:
                    errors += 1
        except OSError:
            errors += 1
    for name in ("sync_history.db", "sync_history.db-wal", "sync_history.db-shm"):
        path = root / name
        try:
            if path.is_file() and not path.is_symlink():
                groups["history"]["bytes"] += path.stat().st_size
                groups["history"]["files"] += 1
        except OSError:
            errors += 1
    return {"groups": groups, "metadata_errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Application folder or shared folder to inspect")
    args = parser.parse_args()
    try:
        print(json.dumps(storage_report(args.root), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
