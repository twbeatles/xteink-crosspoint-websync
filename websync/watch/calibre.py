"""Calibre 서재 폴더 변경 감시 모듈 (watchdog 사용)"""
import os
import time
import threading
from typing import Callable, Optional

from websync.i18n import t

DEBOUNCE_SECONDS = 2.0
STABLE_SIZE_CHECKS = 2
STABLE_CHECK_INTERVAL = 0.5
MAX_STABILITY_RETRIES = 60
WATCH_BOOK_EXTS = (".epub", ".pdf", ".mobi", ".txt", ".azw3")


def _is_watch_book_file(path: str) -> bool:
    if not path or path.endswith(("/", "\\")):
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in WATCH_BOOK_EXTS


class CalibreWatcher:
    """Calibre 라이브러리 폴더에 새 파일이 추가되면 콜백을 호출하는 감시자"""

    def __init__(self, watch_dir: str, on_new_file: Callable[[str], None], debounce_sec: float = DEBOUNCE_SECONDS):
        self.watch_dir = watch_dir
        self.on_new_file = on_new_file
        self.debounce_sec = debounce_sec
        self._observer: Optional[object] = None
        self._running = False
        self._pending: dict[str, float] = {}
        self._stability_retries: dict[str, int] = {}
        self._pending_lock = threading.Lock()
        self._debounce_timer: Optional[threading.Timer] = None

    def _schedule_debounced(self, fpath: str):
        with self._pending_lock:
            self._pending[fpath] = time.time()
            self._stability_retries[fpath] = 0
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.debounce_sec, self._flush_pending)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    @staticmethod
    def _is_file_stable(path: str) -> bool:
        """파일 크기가 연속으로 동일할 때만 전송 대상으로 간주합니다."""
        if not os.path.isfile(path):
            return False
        try:
            last_size = os.path.getsize(path)
        except OSError:
            return False
        for _ in range(STABLE_SIZE_CHECKS):
            time.sleep(STABLE_CHECK_INTERVAL)
            if not os.path.isfile(path):
                return False
            try:
                size = os.path.getsize(path)
            except OSError:
                return False
            if size != last_size:
                return False
            last_size = size
        return True

    def _flush_pending(self):
        with self._pending_lock:
            now = time.time()
            candidates = [
                path for path, ts in self._pending.items()
                if now - ts >= self.debounce_sec
            ]
            for path in candidates:
                del self._pending[path]
        ready = []
        retry = []
        for path in candidates:
            if self._is_file_stable(path):
                ready.append(path)
            elif os.path.isfile(path):
                retry.append(path)

        if retry:
            with self._pending_lock:
                now = time.time()
                for path in retry:
                    attempts = self._stability_retries.get(path, 0) + 1
                    if attempts <= MAX_STABILITY_RETRIES:
                        self._stability_retries[path] = attempts
                        self._pending[path] = now
                    else:
                        self._stability_retries.pop(path, None)
                if self._pending:
                    self._debounce_timer = threading.Timer(
                        self.debounce_sec, self._flush_pending
                    )
                    self._debounce_timer.daemon = True
                    self._debounce_timer.start()
        for path in ready:
            self._stability_retries.pop(path, None)
            try:
                self.on_new_file(path)
            except Exception as e:
                print(t("watch.callback_error", path=path, error=e))

    def start(self) -> bool:
        if self._running:
            return True
        if not os.path.isdir(self.watch_dir):
            print(t("watch.no_folder", path=self.watch_dir))
            return False
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            watcher_self = self

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if event.is_directory:
                        return
                    if _is_watch_book_file(event.src_path):
                        watcher_self._schedule_debounced(event.src_path)

                def on_moved(self, event):
                    if event.is_directory:
                        return
                    dest = getattr(event, "dest_path", "") or ""
                    if _is_watch_book_file(dest):
                        watcher_self._schedule_debounced(dest)

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    if _is_watch_book_file(event.src_path):
                        watcher_self._schedule_debounced(event.src_path)

            self._observer = Observer()
            self._observer.schedule(_Handler(), self.watch_dir, recursive=True)
            self._observer.start()
            self._running = True
            return True
        except ImportError:
            print(t("watch.no_watchdog"))
            return False
        except Exception as e:
            print(t("watch.start_failed", error=e))
            return False

    def stop(self):
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        with self._pending_lock:
            self._pending.clear()
            self._stability_retries.clear()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
