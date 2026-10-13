"""Build and smoke-check a frozen artifact without using local app data.

Run with the build dependencies installed: python scripts/verify_isolated_build.py
Optional --output copies the verified binary to a NEW path, never overwrites it.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new path")
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="websync-frozen-check-") as temporary:
        root = Path(temporary).resolve()
        source = root / "source"
        source.mkdir()
        shutil.copytree(repo / "websync", source / "websync",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("x3_websync.py", "x3_websync.spec"):
            shutil.copy2(repo / name, source / name)
        env = dict(os.environ, X3_WEBSYNC_STORAGE_ROOT=str(root / "state"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        log = root / "build.log"
        try:
            with log.open("w", encoding="utf-8") as handle:
                subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                                "--workpath", str(root / "work"), "--distpath", str(root / "dist"),
                                "x3_websync.spec"], cwd=source, env=env, stdout=handle,
                               stderr=subprocess.STDOUT, timeout=900, check=True)
            artifact = root / "dist" / ("x3_websync.exe" if sys.platform == "win32" else "x3_websync")
            completed = subprocess.run([str(artifact), "--smoke"], cwd=root, env=env,
                                       capture_output=True, text=True, timeout=90)
            if completed.returncode:
                raise RuntimeError(f"Frozen smoke failed: {completed.returncode}\n{completed.stdout}\n{completed.stderr}")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive create also prevents a concurrent output overwrite.
                with artifact.open("rb") as src, args.output.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"Verified artifact: {args.output.resolve()}")
            print("Isolated frozen build and --smoke passed")
        except Exception:
            if log.exists():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-35:]), file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
