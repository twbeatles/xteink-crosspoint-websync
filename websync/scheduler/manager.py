import os
import shlex
import subprocess
import sys
from pathlib import PureWindowsPath

from websync.i18n import t


def _windows_console_encoding() -> str:
    """schtasks 같은 콘솔 도구의 출력 코드 페이지 (예: 한국어 cp949, 영어 cp437)."""
    try:
        import codecs
        import ctypes

        name = f"cp{ctypes.windll.kernel32.GetOEMCP()}"  # type: ignore[attr-defined]
        codecs.lookup(name)
        return name
    except Exception:
        return "mbcs" if sys.platform == "win32" else "utf-8"


def _process_output(result) -> str:
    """실패한 하위 프로세스의 stderr(없으면 stdout) 요약."""
    for attr in ("stderr", "stdout"):
        value = getattr(result, attr, None)
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            return text[:300] + ("…" if len(text) > 300 else "")
    return ""


class SchedulerManager:
    """작업 스케줄러 등록 및 제어를 전담하는 클래스 (Windows/macOS/Linux 크로스플랫폼 지원)"""
    TASK_NAME = "XteinkX3WebSyncTask"
    # schtasks /TR 인자의 최대 길이. 초과 시 schtasks가 등록을 거부한다.
    WINDOWS_TR_MAX_LENGTH = 261

    def __init__(self, script_path: str = None):
        raw = sys.argv[0] if script_path is None else script_path
        self.script_path = self._resolve_script_path(raw)
        self.project_dir = self._dirname_for_script(self.script_path)
        # 마지막 등록 실패의 구체적 사유 (GUI 표시용). 원인을 모르면 빈 문자열.
        self.last_error = ""

    @staticmethod
    def _is_windows_abs_path(path: str) -> bool:
        """드라이브 문자 절대 경로(C:\\… / C:/…)인지 여부. POSIX abspath가 망가뜨리지 않게 한다."""
        if not path or len(path) < 3:
            return False
        return path[0].isalpha() and path[1] == ":" and path[2] in "\\/"

    @classmethod
    def _resolve_script_path(cls, path: str) -> str:
        """호스트 OS와 무관하게 Windows 절대 경로는 그대로 유지 (CI·단위 테스트 안전)."""
        if cls._is_windows_abs_path(path):
            return path
        return os.path.abspath(path)

    @classmethod
    def _dirname_for_script(cls, path: str) -> str:
        """Windows 절대 경로는 PureWindowsPath로 부모를 구한다 (Linux에서 \\ 분리 실패 방지)."""
        if cls._is_windows_abs_path(path):
            parent = PureWindowsPath(path).parent
            return str(parent)
        return os.path.dirname(path)

    def register_daily_task(self, hour: str, minute: str) -> bool:
        """플랫폼에 맞는 일간 스케줄 등록"""
        self.last_error = ""
        # 쉘 인젝션 방어용 입력 화이트리스트 정수 검증
        if not hour.isdigit() or not minute.isdigit():
            print(t("scheduler.hour_not_int"))
            return False
        h_val, m_val = int(hour), int(minute)
        if not (0 <= h_val <= 23) or not (0 <= m_val <= 59):
            print(t("scheduler.hour_range"))
            return False

        if sys.platform == "win32":
            return self._register_windows(h_val, m_val)
        elif sys.platform == "darwin":
            return self._register_macos(h_val, m_val)
        else:
            return self._register_linux(h_val, m_val)

    @staticmethod
    def _win_quote(path: str) -> str:
        """cmd.exe 내부에서 쓸 경로를 큰따옴표로 감쌉니다."""
        p = (path or "").replace('"', "")
        return f'"{p}"'

    def build_windows_tr_command(self) -> str:
        """schtasks /tr 에 넣을 cmd 문자열 (테스트·등록 공용)."""
        proj = self._win_quote(self.project_dir)
        if getattr(sys, "frozen", False):
            script = self._win_quote(self.script_path)
            return f"cmd.exe /c cd /d {proj} && {script} --sync"
        python_exe = sys.executable
        pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw_exe):
            pythonw_exe = python_exe
        py = self._win_quote(pythonw_exe)
        script = self._win_quote(self.script_path)
        return f"cmd.exe /c cd /d {proj} && {py} {script} --sync"

    def _register_windows(self, h_val: int, m_val: int) -> bool:
        """Windows schtasks 기반 등록 (경로 공백 안전)."""
        cmd_target = self.build_windows_tr_command()
        if len(cmd_target) > self.WINDOWS_TR_MAX_LENGTH:
            self.last_error = t(
                "scheduler.tr_too_long", length=len(cmd_target), limit=self.WINDOWS_TR_MAX_LENGTH
            )
            print(self.last_error)
            return False

        cmd = [
            "schtasks", "/create",
            "/tn", self.TASK_NAME,
            "/tr", cmd_target,
            "/sc", "daily",
            "/st", f"{h_val:02d}:{m_val:02d}",
            "/f"
        ]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding=_windows_console_encoding(), errors="replace",
            )
            if result.returncode == 0:
                return True
            return self._fail("schtasks", result)
        except Exception as e:
            print(t("scheduler.register_failed", error=e))
            return self._fail("schtasks", error=e)

    @staticmethod
    def _xml_escape(value: str) -> str:
        """plist XML 텍스트 노드용 이스케이프."""
        return (
            (value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _register_macos(self, h_val: int, m_val: int) -> bool:
        """macOS launchd plist 기반 등록"""
        plist_dir = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(plist_dir, exist_ok=True)
        plist_path = os.path.join(plist_dir, f"com.x3websync.{self.TASK_NAME}.plist")
        python_exe = sys.executable
        script_x = self._xml_escape(self.script_path)
        proj_x = self._xml_escape(self.project_dir)
        py_x = self._xml_escape(python_exe)

        if getattr(sys, 'frozen', False):
            args_xml = f"""        <string>{script_x}</string>
        <string>--sync</string>"""
        else:
            args_xml = f"""        <string>{py_x}</string>
        <string>{script_x}</string>
        <string>--sync</string>"""

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.x3websync.{self.TASK_NAME}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{h_val}</integer>
        <key>Minute</key>
        <integer>{m_val}</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>{proj_x}</string>
    <key>StandardOutPath</key>
    <string>{proj_x}/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{proj_x}/logs/launchd_stderr.log</string>
</dict>
</plist>"""
        try:
            # Do not destroy the existing schedule when unloading it failed.
            if os.path.exists(plist_path):
                result = subprocess.run(["launchctl", "unload", plist_path], capture_output=True, timeout=15)
                if result.returncode != 0 and self._macos_job_loaded() is not False:
                    return self._fail("launchctl unload", result)
            with open(plist_path, "w", encoding="utf-8") as f:
                f.write(plist_content)
            result = subprocess.run(["launchctl", "load", plist_path], capture_output=True, timeout=15)
            if result.returncode == 0:
                return True
            return self._fail("launchctl", result)
        except Exception as e:
            print(t("scheduler.macos_register_failed", error=e))
            return self._fail("launchctl", error=e)

    # Linux crontab 관리 블록 마커 — 이 블록 안의 줄만 도구가 관리한다.
    CRON_BLOCK_BEGIN = "# XteinkX3WebSyncTask BEGIN"
    CRON_BLOCK_END = "# XteinkX3WebSyncTask END"
    _LEGACY_CRON_MARKER = "# XteinkX3WebSyncTask"

    @staticmethod
    def _cron_quote(value: str) -> str:
        """Quote one shell word while protecting cron's earlier percent parsing.

        Separate quoted percent segments also handle literal backslashes before %.
        Cronie removes the escape before %, leaving a quoted shell literal.
        """
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Scheduler paths must not contain control characters")
        return "'\\%'".join(shlex.quote(part) for part in value.split("%"))

    def _build_cron_line(self, h_val: int, m_val: int) -> str:
        """crontab에 기록할 실행 줄 (등록·테스트 공용)."""
        project_q = self._cron_quote(self.project_dir)
        log_path = self._cron_quote(os.path.join(self.project_dir, "logs", "cron.log"))
        if getattr(sys, "frozen", False):
            script_q = self._cron_quote(self.script_path)
            run_part = f"cd {project_q} && {script_q} --sync"
        else:
            python_q = self._cron_quote(sys.executable)
            script_q = self._cron_quote(self.script_path)
            run_part = f"cd {project_q} && {python_q} {script_q} --sync"
        return f"{m_val} {h_val} * * * {run_part} >> {log_path} 2>&1"

    @classmethod
    def _strip_managed_cron_lines(cls, lines: list) -> list:
        """관리 블록(BEGIN/END)과 레거시 마커(`# TASK_NAME` + 다음 줄)만 제거한다."""
        kept = []
        in_block = False
        skip_next = False
        for line in lines:
            stripped = line.strip()
            if stripped == cls.CRON_BLOCK_BEGIN:
                in_block = True
                continue
            if stripped == cls.CRON_BLOCK_END:
                in_block = False
                continue
            if in_block:
                continue
            if stripped == cls._LEGACY_CRON_MARKER:
                # 다음 줄은 도구가 예전에 기록한 실행 줄이므로 함께 제거한다.
                skip_next = True
                continue
            if skip_next:
                skip_next = False
                if "--sync" in line:
                    continue
            kept.append(line)
        return kept

    def _merge_crontab(self, existing: str, cron_cmd) -> str:
        """기존 크론탭에서 관리 줄을 정리하고 필요시 새 블록을 추가한다."""
        lines = existing.splitlines() if isinstance(existing, str) and existing else []
        kept = self._strip_managed_cron_lines(lines)
        if cron_cmd:
            kept.append(self.CRON_BLOCK_BEGIN)
            kept.append(cron_cmd)
            kept.append(self.CRON_BLOCK_END)
        text = "\n".join(kept)
        return text + "\n" if text else "\n"

    def _backup_crontab(self, existing: str) -> None:
        """덮어쓰기 전 기존 크론탭을 logs/cron.bak에 보존한다 (실패해도 무시)."""
        try:
            log_dir = os.path.join(self.project_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "cron.bak"), "w", encoding="utf-8") as f:
                f.write(existing if isinstance(existing, str) else "")
        except OSError:
            pass

    def _register_linux(self, h_val: int, m_val: int) -> bool:
        """Linux crontab 기반 등록 (마커 블록만 관리 — 사용자 크론 줄 보존)."""
        try:
            cron_cmd = self._build_cron_line(h_val, m_val)
            existing = self._read_crontab()
            if existing is None:
                return False
            self._backup_crontab(existing)
            new_crontab = self._merge_crontab(existing, cron_cmd)
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
            if proc.returncode == 0:
                return True
            return self._fail("crontab", proc)
        except Exception as e:
            print(t("scheduler.linux_register_failed", error=e))
            return self._fail("crontab", error=e)

    def _read_crontab(self):
        """현재 crontab 내용. 아직 없으면 "", 읽기 자체가 실패하면 None (덮어쓰기 금지)."""
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        err = getattr(result, "stderr", "")
        if isinstance(err, str) and "no crontab" in err.lower():
            return ""
        # 권한·데몬 문제로 못 읽은 것을 "빈 crontab"으로 보면 사용자 줄이 지워진다.
        self._fail("crontab -l", result)
        return None

    def _fail(self, tool: str, result=None, *, error: Exception | None = None) -> bool:
        """실패 사유를 last_error와 로그에 남기고 False를 반환한다."""
        detail = str(error) if error is not None else _process_output(result)
        code = getattr(result, "returncode", None)
        self.last_error = t(
            "scheduler.tool_failed",
            tool=tool,
            code="-" if code is None else code,
            detail=detail or t("scheduler.no_detail"),
        )
        try:
            from websync.core.logger import get_logger

            get_logger().warning(self.last_error)
        except Exception:
            pass
        return False


    def _macos_job_loaded(self) -> bool | None:
        """True/False for a known job state; command/permission errors stay unknown."""
        result = subprocess.run(
            ["launchctl", "list", f"com.x3websync.{self.TASK_NAME}"],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0:
            return True
        detail = _process_output(result).lower()
        if "could not find service" in detail or "could not find specified service" in detail:
            return False
        return None

    def unregister_task(self) -> bool:
        self.last_error = ""
        if sys.platform == "win32":
            cmd = ["schtasks", "/delete", "/tn", self.TASK_NAME, "/f"]
            try:
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding=_windows_console_encoding(), errors="replace",
                )
                if result.returncode == 0:
                    return True
                return self._fail("schtasks", result)
            except Exception as e:
                print(t("scheduler.unregister_failed", error=e))
                return self._fail("schtasks", error=e)
        elif sys.platform == "darwin":
            plist_path = os.path.expanduser(f"~/Library/LaunchAgents/com.x3websync.{self.TASK_NAME}.plist")
            try:
                result = subprocess.run(["launchctl", "unload", plist_path], capture_output=True, timeout=15)
                if result.returncode != 0 and self._macos_job_loaded() is not False:
                    return self._fail("launchctl unload", result)
                if os.path.exists(plist_path):
                    os.remove(plist_path)
                return True
            except Exception as e:
                print(t("scheduler.macos_unregister_failed", error=e))
                return self._fail("launchctl", error=e)
        else:
            try:
                existing = self._read_crontab()
                if existing is None:
                    return False
                self._backup_crontab(existing)
                new_crontab = self._merge_crontab(existing, None)
                proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
                if proc.returncode == 0:
                    return True
                return self._fail("crontab", proc)
            except Exception as e:
                print(t("scheduler.linux_unregister_failed", error=e))
                return self._fail("crontab", error=e)

    def get_task_status(self) -> str:
        """스케줄 작업이 등록되어 있는지 상태 문자열 반환"""
        if sys.platform == "win32":
            cmd = ["schtasks", "/query", "/tn", self.TASK_NAME, "/fo", "csv"]
            try:
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding=_windows_console_encoding(), errors="replace",
                )
                return t("scheduler.registered_waiting") if result.returncode == 0 else t("scheduler.not_registered")
            except Exception:
                return t("scheduler.status_unknown")
        elif sys.platform == "darwin":
            try:
                loaded = self._macos_job_loaded()
                if loaded is None:
                    return t("scheduler.status_unknown")
                return t("scheduler.registered_launchd") if loaded else t("scheduler.not_registered")
            except Exception:
                return t("scheduler.status_unknown")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                return t("scheduler.registered_crontab") if self.TASK_NAME in result.stdout else t("scheduler.not_registered")
            except Exception:
                return t("scheduler.status_unknown")
