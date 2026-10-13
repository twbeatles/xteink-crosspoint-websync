import os
import sys
from unittest.mock import patch

import websync.core.paths as paths_mod


def test_project_root_dev_mode_is_repo_parent():
    # 개발 모드: websync/ 패키지 상위가 프로젝트 루트
    root = paths_mod._detect_project_root()
    assert os.path.isdir(os.path.join(root, "websync"))
    assert os.path.isfile(os.path.join(root, "x3_websync.py"))


def test_detect_project_root_frozen_uses_executable_dir(tmp_path):
    fake_exe = tmp_path / "x3_websync.exe"
    fake_exe.write_bytes(b"")
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "executable", str(fake_exe)):
            root = paths_mod._detect_project_root()
    assert root == str(tmp_path)


def test_resolve_path_relative():
    p = paths_mod.resolve_path("./output")
    assert os.path.isabs(p)
    assert p.endswith("output") or p.endswith(f"output{os.sep}") or "output" in p
