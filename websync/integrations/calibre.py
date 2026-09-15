import os
import json
import subprocess

from websync.i18n import t

class CalibreManager:
    """calibredb.exe 명령어를 래핑하여 Calibre 도서 정보를 조회하고 경로를 추적하는 클래스"""
    def __init__(
        self,
        calibre_path: str = "C:\\Program Files\\Calibre2\\calibredb.exe",
        library_path: str = "",
    ):
        self.calibre_path = calibre_path
        self.library_path = (library_path or "").strip()

    def _base_cmd(self) -> list[str]:
        cmd = [self.calibre_path]
        if self.library_path:
            cmd.extend(["--with-library", self.library_path])
        return cmd

    def test_connection(self) -> bool:
        """Calibre 실행 파일 경로가 유효한지 검증"""
        if not self.calibre_path or not os.path.exists(self.calibre_path):
            return False
        try:
            result = subprocess.run(self._base_cmd() + ["--version"], capture_output=True, text=True, timeout=3)
            return result.returncode == 0
        except Exception:
            return False

    def list_books(self) -> list:
        """Calibre 서재의 도서 정보 리스트를 조회하여 반환"""
        if not self.test_connection():
            return []
        try:
            cmd = self._base_cmd() + ["list", "--fields", "id,title,authors,formats", "--to-json"]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return []
        except Exception as e:
            print(t("calibre.list_failed", error=e))
            return []

    def get_book_file_path(self, book_id: int) -> str:
        """책 ID에 해당하는 도서의 실제 파일 경로를 조회"""
        if not self.test_connection():
            return ""
        try:
            cmd = self._base_cmd() + ["format-paths", str(book_id)]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10)
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                paths = {}
                for line in lines:
                    if ":" in line:
                        fmt, path = line.split(":", 1)
                        paths[fmt.strip().lower()] = path.strip()
                
                # EPUB 포맷 선호, 없으면 차선책 조회
                for fmt in ["epub", "pdf", "mobi", "txt"]:
                    if fmt in paths:
                        return paths[fmt]
                if paths:
                    return list(paths.values())[0]
            return ""
        except Exception as e:
            print(t("calibre.path_failed", error=e))
            return ""
