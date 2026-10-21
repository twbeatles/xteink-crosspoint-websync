"""End-to-end check that the update helper can replace an executable that is still running.

Windows only. Pass a built one-file executable (for example from
``python scripts/verify_isolated_build.py --output <new path>``)::

    python scripts/verify_update_swap.py --exe <path to x3_websync.exe>

Everything happens in a temporary folder: the executable is copied there as the
"installed" app and started (a window may flash), then the real ``--apply-update``
helper replaces it while it is still running. No user data or install is touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from websync.core.update.installer import clean_frozen_environment  # noqa: E402


def _kill_everything_under(root: Path) -> None:
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
        f"$_.ExecutablePath.StartsWith('{root}', 'OrdinalIgnoreCase') }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--hold-seconds", type=float, default=8.0,
                        help="time to let the installed app start before swapping")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("Windows only: running executables are only locked on Windows", file=sys.stderr)
        return 2
    source = args.exe.resolve()
    if not source.is_file():
        parser.error(f"Executable not found: {source}")

    with tempfile.TemporaryDirectory(prefix="websync-update-swap-") as temporary:
        root = Path(temporary).resolve()
        install = root / "install"
        staging = install / ".updates"
        staging.mkdir(parents=True)
        target = install / "x3_websync.exe"
        staged = staging / f"update-9.9.9-{uuid.uuid4().hex}.exe"
        helper = staging / f"update-helper-{uuid.uuid4().hex}.exe"
        backup = install / "x3_websync.exe.v0.0.1.bak"
        result_file = staging / "last-update-result.json"
        for destination in (target, staged, helper):
            shutil.copy2(source, destination)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        original = target.read_bytes()

        env = dict(clean_frozen_environment(), X3_WEBSYNC_STORAGE_ROOT=str(root / "state"))
        app = subprocess.Popen([str(target)], cwd=install, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(args.hold_seconds)
            if app.poll() is not None:
                print(f"FAIL: installed app exited early ({app.returncode}); cannot hold the image", file=sys.stderr)
                return 1
            # Leftover from an earlier failed attempt must not block this one.
            backup.write_bytes(b"stale backup from a failed attempt")
            started = time.monotonic()
            subprocess.Popen(
                [str(helper), "--apply-update", "--update-target", str(target),
                 "--update-staged", str(staged), "--update-backup", str(backup),
                 "--update-parent-pid", "0", "--update-expected-sha256", digest,
                 "--update-expected-size", str(staged.stat().st_size),
                 "--update-result-file", str(result_file)],
                cwd=staging, env=clean_frozen_environment(), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            while not result_file.exists() and time.monotonic() - started < 120:
                time.sleep(0.5)
            if not result_file.exists():
                print("FAIL: helper wrote no result within 120s", file=sys.stderr)
                return 1
            result = json.loads(result_file.read_text(encoding="utf-8"))
            still_running = app.poll() is None
            problems = []
            if result.get("status") != "applied":
                problems.append(f"helper status={result!r}")
            if not still_running:
                problems.append("old app was not running during the swap (test did not exercise the lock)")
            if staged.exists():
                problems.append("staged file was not consumed")
            if not backup.exists() or backup.read_bytes() != original:
                problems.append("backup missing or not the previous executable")
            if not target.exists():
                problems.append("target missing")
            if problems:
                print("FAIL: " + "; ".join(problems), file=sys.stderr)
                return 1
            print(f"Update swap verified in {time.monotonic() - started:.1f}s "
                  "(old app still running during replacement)")
            return 0
        finally:
            _kill_everything_under(root)
            time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
