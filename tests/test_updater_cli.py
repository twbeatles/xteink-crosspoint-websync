"""CLI --smoke, --version 플래그 단위 테스트."""
from __future__ import annotations

import subprocess
import sys

from websync import __version__


def test_cli_smoke():
    completed = subprocess.run(
        [sys.executable, "x3_websync.py", "--smoke"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "smoke check OK" in completed.stdout


def test_run_smoke_check_loads_core_modules():
    from x3_websync import SMOKE_MODULES, run_smoke_check

    assert "websync.pipeline.service" in SMOKE_MODULES
    assert "websync.scrapers.factory" in SMOKE_MODULES
    assert "websync.epub.builder" in SMOKE_MODULES
    assert "websync.i18n" in SMOKE_MODULES
    assert run_smoke_check() == 0


def test_cli_version():
    completed = subprocess.run(
        [sys.executable, "x3_websync.py", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert f"v{__version__}" in completed.stdout


def test_handle_apply_update_parent_timeout(tmp_path):
    import argparse
    from unittest.mock import patch
    from x3_websync import _handle_apply_update
    from websync.core.update_installer import consume_update_result

    res_file = tmp_path / "result.json"
    args = argparse.Namespace(
        update_target=str(tmp_path / "target.exe"),
        update_staged=str(tmp_path / "staged.exe"),
        update_backup=str(tmp_path / "backup.exe"),
        update_parent_pid=999999,
        update_expected_sha256="0" * 64,
        update_expected_size=100,
        update_result_file=str(res_file),
    )

    # 부모 프로세스가 계속 살아있다고 모킹하고 time.sleep을 즉시 리턴하게 모킹
    with patch("websync.cli.update_apply._is_process_running", return_value=True), \
         patch("time.sleep", return_value=None):
        ret = _handle_apply_update(args)
        assert ret == 1
        res = consume_update_result(res_file)
        assert res is not None
        assert res["status"] == "failed"
        assert "초과" in res["error"]


def test_staging_block_allows_dev_and_helper():
    import argparse
    from x3_websync import _staging_block_target

    assert _staging_block_target(argparse.Namespace(apply_update=False)) is None
    assert _staging_block_target(argparse.Namespace(apply_update=True)) is None


def test_staging_block_detects_helper_copy(tmp_path, monkeypatch):
    import argparse
    import sys
    from x3_websync import _staging_block_target

    base = tmp_path / "app"
    staging = base / ".updates"
    staging.mkdir(parents=True)
    target = base / "x3_websync.exe"
    target.write_bytes(b"app")
    helper = staging / "update-helper-abc123.exe"
    helper.write_bytes(b"helper")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(helper), raising=False)
    assert _staging_block_target(
        argparse.Namespace(apply_update=False)
    ) == str(target.resolve())
    assert (
        _staging_block_target(argparse.Namespace(apply_update=True)) is None
    )


def test_staging_block_allows_normal_frozen_exe(tmp_path, monkeypatch):
    import argparse
    import sys
    from x3_websync import _staging_block_target

    base = tmp_path / "app"
    base.mkdir()
    target = base / "x3_websync.exe"
    target.write_bytes(b"app")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(target), raising=False)
    assert _staging_block_target(argparse.Namespace(apply_update=False)) is None
