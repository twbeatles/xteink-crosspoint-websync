import shlex
import sys
from unittest.mock import patch, MagicMock

from websync.scheduler.manager import SchedulerManager

# Windows 스타일 경로 — GitHub Actions(ubuntu)에서도 호스트 OS와 무관하게 동일하게 동작해야 함
_WIN_SCRIPT = r"C:\Users\First Last\x3\x3_websync.py"
_WIN_PROJECT = r"C:\Users\First Last\x3"
_WIN_PYTHON = r"C:\Program Files\Python\python.exe"
_WIN_PYTHONW = r"C:\Program Files\Python\pythonw.exe"


def test_resolve_script_path_preserves_windows_abs_on_any_host():
    """POSIX abspath가 C:\\… 를 CWD 상대경로로 붙이지 않도록 한다 (CI 재발 방지)."""
    resolved = SchedulerManager._resolve_script_path(_WIN_SCRIPT)
    assert resolved == _WIN_SCRIPT
    assert not resolved.startswith("/")  # Linux CWD 접두 금지
    assert SchedulerManager._dirname_for_script(resolved) == _WIN_PROJECT


def test_linux_cron_quotes_paths_with_spaces():
    mgr = SchedulerManager(script_path="/tmp/my project/x3_websync.py")
    mgr.project_dir = "/tmp/my project"

    with patch.object(mgr, "_register_windows"):
        with patch("sys.platform", "linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                mgr.register_daily_task("07", "30")

    cron_input = mock_run.call_args_list[-1].kwargs.get("input", "")
    assert shlex.quote(mgr.project_dir) in cron_input
    assert shlex.quote(mgr.script_path) in cron_input


def test_windows_tr_command_quotes_paths_with_spaces():
    """공백 포함 Windows 경로를 schtasks /tr 문자열에서 따옴표로 감싼다 (Linux CI 포함)."""
    mgr = SchedulerManager(script_path=_WIN_SCRIPT)
    assert mgr.script_path == _WIN_SCRIPT
    assert mgr.project_dir == _WIN_PROJECT
    with patch.object(sys, "executable", _WIN_PYTHON):
        with patch("os.path.exists", return_value=True):
            tr = mgr.build_windows_tr_command()
    assert f'cd /d "{_WIN_PROJECT}"' in tr
    assert f'"{_WIN_SCRIPT}"' in tr
    assert f'"{_WIN_PYTHONW}"' in tr
    assert "--sync" in tr
    # POSIX abspath가 CWD를 Windows 경로 앞에 붙인 회귀 차단
    assert tr.count(_WIN_SCRIPT) == 1


def test_macos_unloads_before_load():
    mgr = SchedulerManager(script_path="/tmp/x3_websync.py")

    with patch("sys.platform", "darwin"):
        with patch("os.path.expanduser", return_value="/tmp/LaunchAgents"):
            with patch("os.makedirs"):
                with patch("os.path.exists", return_value=True):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        with patch("builtins.open", MagicMock()):
                            mgr.register_daily_task("08", "00")

    calls = [c.args[0] for c in mock_run.call_args_list if c.args]
    assert ["launchctl", "unload"] in [c[:2] for c in calls]
    assert ["launchctl", "load"] in [c[:2] for c in calls]


def test_xml_escape_for_macos_plist():
    assert SchedulerManager._xml_escape('a&b<c>"d"') == "a&amp;b&lt;c&gt;&quot;d&quot;"


def test_macos_plist_escapes_special_chars_in_path():
    """경로에 & 등이 있어도 plist XML이 깨지지 않도록 이스케이프한다."""
    script = "/tmp/my & project/x3_websync.py"
    mgr = SchedulerManager(script_path=script)
    written = {}

    def fake_open(path, mode="r", *a, **k):
        from io import StringIO
        if "w" in mode:
            buf = StringIO()
            written["path"] = path
            written["buf"] = buf
            # close 시 내용 보존
            orig_close = buf.close

            def close():
                written["content"] = buf.getvalue()
                orig_close()

            buf.close = close  # type: ignore[method-assign]
            return buf
        raise FileNotFoundError(path)

    with patch("sys.platform", "darwin"):
        with patch("os.path.expanduser", return_value="/tmp/LaunchAgents"):
            with patch("os.makedirs"):
                with patch("os.path.exists", return_value=False):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        with patch("builtins.open", side_effect=fake_open):
                            mgr.register_daily_task("08", "00")

    content = written.get("content", "")
    assert "my &amp; project" in content
    assert "my & project" not in content


def test_crontab_merge_preserves_user_lines_and_idempotent():
    """ISSUE-004: 사용자 크론 줄을 보존하고 중복 등록하지 않는다."""
    mgr = SchedulerManager(script_path="/tmp/x3_websync.py")
    mgr.project_dir = "/tmp"
    custom = "*/30 * * * * /tmp/x3_websync.py --sync --custom"
    line = mgr._build_cron_line(7, 30)
    merged = mgr._merge_crontab(custom + "\n", line)
    assert custom in merged
    assert SchedulerManager.CRON_BLOCK_BEGIN in merged
    assert merged.count(line) == 1
    assert mgr._merge_crontab(merged, line) == merged


def test_crontab_unregister_removes_only_managed_block():
    """ISSUE-004: 해제 시 관리 블록만 제거하고 사용자 줄은 남긴다."""
    mgr = SchedulerManager(script_path="/tmp/x3_websync.py")
    mgr.project_dir = "/tmp"
    custom = "*/30 * * * * /usr/bin/uptime"
    existing = (
        custom + "\n"
        + SchedulerManager.CRON_BLOCK_BEGIN + "\n"
        + mgr._build_cron_line(7, 30) + "\n"
        + SchedulerManager.CRON_BLOCK_END + "\n"
    )
    cleaned = mgr._merge_crontab(existing, None)
    assert custom in cleaned
    assert SchedulerManager.CRON_BLOCK_BEGIN not in cleaned
    assert "--sync" not in cleaned


def test_crontab_register_migrates_legacy_marker():
    """ISSUE-004: 구 형식 마커(`# TASK_NAME` + 다음 줄)도 정리된다."""
    mgr = SchedulerManager(script_path="/tmp/x3_websync.py")
    mgr.project_dir = "/tmp"
    legacy = (
        "# " + SchedulerManager.TASK_NAME + "\n"
        "30 7 * * * cd /tmp && python3 /tmp/x3_websync.py --sync\n"
    )
    merged = mgr._merge_crontab(legacy, mgr._build_cron_line(7, 30))
    assert "# " + SchedulerManager.TASK_NAME + "\n" not in merged.splitlines()
    assert "python3 /tmp/x3_websync.py --sync" not in merged
    assert SchedulerManager.CRON_BLOCK_BEGIN in merged


def test_crontab_write_backs_up_existing(tmp_path):
    """ISSUE-004: 덮어쓰기 전 기존 크론탭을 logs/cron.bak에 보존한다."""
    mgr = SchedulerManager(script_path=str(tmp_path / "x3_websync.py"))
    mgr.project_dir = str(tmp_path)
    existing = "*/15 * * * * /usr/bin/uptime\n"
    captured = {}

    def fake_run(cmd, **kwargs):
        if list(cmd[:2]) == ["crontab", "-l"]:
            m = MagicMock()
            m.returncode = 0
            m.stdout = existing
            return m
        captured["input"] = kwargs.get("input")
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("sys.platform", "linux"):
        with patch("subprocess.run", side_effect=fake_run):
            assert mgr.register_daily_task("07", "30") is True
    assert "/usr/bin/uptime" in captured["input"]
    bak = tmp_path / "logs" / "cron.bak"
    assert bak.read_text(encoding="utf-8") == existing

