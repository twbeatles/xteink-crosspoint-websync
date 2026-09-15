import os
import sys
import shlex
import subprocess
from pathlib import PureWindowsPath

from websync.i18n import t


class SchedulerManager:
    """작업 스케줄러 등록 및 제어를 전담하는 클래스 (Windows/macOS/Linux 크로스플랫폼 지원)"""
    TASK_NAME = "XteinkX3WebSyncTask"

    def __init__(self, script_path: str = None):
        raw = sys.argv[0] if script_path is None else script_path
        self.script_path = self._resolve_script_path(raw)
        self.project_dir = self._dirname_for_script(self.script_path)

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

        cmd = [
            "schtasks", "/create",
            "/tn", self.TASK_NAME,
            "/tr", cmd_target,
            "/sc", "daily",
            "/st", f"{h_val:02d}:{m_val:02d}",
            "/f"
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="cp949", errors="ignore")
            return result.returncode == 0
        except Exception as e:
            print(t("scheduler.register_failed", error=e))
            return False

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
            with open(plist_path, "w", encoding="utf-8") as f:
                f.write(plist_content)
            if os.path.exists(plist_path):
                subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            result = subprocess.run(["launchctl", "load", plist_path], capture_output=True)
            return result.returncode == 0
        except Exception as e:
            print(t("scheduler.macos_register_failed", error=e))
            return False

    def _register_linux(self, h_val: int, m_val: int) -> bool:
        """Linux crontab 기반 등록"""
        project_q = shlex.quote(self.project_dir)
        log_path = shlex.quote(os.path.join(self.project_dir, "logs", "cron.log"))
        if getattr(sys, 'frozen', False):
            script_q = shlex.quote(self.script_path)
            run_part = f"cd {project_q} && {script_q} --sync"
        else:
            python_q = shlex.quote(sys.executable)
            script_q = shlex.quote(self.script_path)
            run_part = f"cd {project_q} && {python_q} {script_q} --sync"
        cron_cmd = f"{m_val} {h_val} * * * {run_part} >> {log_path} 2>&1"
        try:
            # 기존 크론탭 읽기
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            # 기존 등록 제거
            lines = [l for l in existing.splitlines() if self.TASK_NAME not in l and self.script_path not in l]
            lines.append(f"# {self.TASK_NAME}")
            lines.append(cron_cmd)
            new_crontab = "\n".join(lines) + "\n"
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
            return proc.returncode == 0
        except Exception as e:
            print(t("scheduler.linux_register_failed", error=e))
            return False


    def unregister_task(self) -> bool:
        if sys.platform == "win32":
            cmd = ["schtasks", "/delete", "/tn", self.TASK_NAME, "/f"]
            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="cp949", errors="ignore")
                return result.returncode == 0
            except Exception as e:
                print(t("scheduler.unregister_failed", error=e))
                return False
        elif sys.platform == "darwin":
            plist_path = os.path.expanduser(f"~/Library/LaunchAgents/com.x3websync.{self.TASK_NAME}.plist")
            try:
                subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
                if os.path.exists(plist_path):
                    os.remove(plist_path)
                return True
            except Exception as e:
                print(t("scheduler.macos_unregister_failed", error=e))
                return False
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                lines = [l for l in existing.splitlines() if self.TASK_NAME not in l and self.script_path not in l]
                new_crontab = "\n".join(lines) + "\n"
                proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
                return proc.returncode == 0
            except Exception as e:
                print(t("scheduler.linux_unregister_failed", error=e))
                return False

    def get_task_status(self) -> str:
        """스케줄 작업이 등록되어 있는지 상태 문자열 반환"""
        if sys.platform == "win32":
            cmd = ["schtasks", "/query", "/tn", self.TASK_NAME, "/fo", "csv"]
            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="cp949", errors="ignore")
                return t("scheduler.registered_waiting") if result.returncode == 0 else t("scheduler.not_registered")
            except Exception:
                return t("scheduler.status_unknown")
        elif sys.platform == "darwin":
            plist_path = os.path.expanduser(f"~/Library/LaunchAgents/com.x3websync.{self.TASK_NAME}.plist")
            return t("scheduler.registered_launchd") if os.path.exists(plist_path) else t("scheduler.not_registered")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                return t("scheduler.registered_crontab") if self.TASK_NAME in result.stdout else t("scheduler.not_registered")
            except Exception:
                return t("scheduler.status_unknown")
