import subprocess
import sys

from websync.i18n import t


class ToastNotifier:
    """플랫폼별 데스크톱 알림 (Windows PowerShell / macOS osascript / Linux notify-send)"""

    @staticmethod
    def show_toast(title: str, text: str, is_error: bool = False):
        if sys.platform == "win32":
            ToastNotifier._show_windows(title, text, is_error)
        elif sys.platform == "darwin":
            ToastNotifier._show_macos(title, text)
        else:
            ToastNotifier._show_linux(title, text)

    @staticmethod
    def _show_windows(title: str, text: str, is_error: bool):
        icon = "Error" if is_error else "Info"
        ps_script = (
            '[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms"); '
            '$obj = New-Object System.Windows.Forms.NotifyIcon; '
            '$obj.Icon = [System.Drawing.SystemIcons]::Information; '
            '$obj.BalloonTipIcon = $args[2]; '
            '$obj.BalloonTipTitle = $args[0]; '
            '$obj.BalloonTipText = $args[1]; '
            '$obj.Visible = $True; '
            '$obj.ShowBalloonTip(5000); '
            'Start-Sleep -Seconds 5; '
            '$obj.Dispose();'
        )
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_script, title, text, icon],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            print(t("notify.show_fail", error=e))
            print(t("notify.fallback", title=title, text=text))

    @staticmethod
    def _show_macos(title: str, text: str):
        safe_title = title.replace('"', '\\"')
        safe_text = text.replace('"', '\\"')
        script = f'display notification "{safe_text}" with title "{safe_title}"'
        try:
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            print(t("notify.fallback", title=title, text=text))

    @staticmethod
    def _show_linux(title: str, text: str):
        try:
            subprocess.Popen(
                ["notify-send", title, text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print(t("notify.fallback", title=title, text=text))
        except Exception as e:
            print(t("notify.show_fail", error=e))
            print(t("notify.fallback", title=title, text=text))