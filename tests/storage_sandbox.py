"""Python I/O safeguard for tests; never imported by production code.

Checks audited Python file/SQLite operations and descriptor-relative os.open.
This is not an OS sandbox: native libraries or non-Python child processes may
perform I/O without emitting Python audit events.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from functools import wraps
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs


def canonical_path(value) -> Path:
    """Windows extended paths and ordinary paths name the same boundary."""
    text = os.fsdecode(value)
    if text.lower().startswith("\\\\?\\unc\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return Path(text).resolve()


class StorageGuard:
    def __init__(self, repository: str | Path):
        self.repository = canonical_path(repository)
        self.allowed_root = canonical_path(tempfile.gettempdir())
        self.violations: list[str] = []
        self._descriptor_open = threading.local()

    def _inside(self, value) -> Path | None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return None
        try:
            path = canonical_path(value)
            return path.relative_to(self.repository)
        except (ValueError, OSError):
            return None

    @staticmethod
    def _mutable(relative: Path) -> bool:
        first = relative.parts[0].lower() if relative.parts else ""
        return (first in {"output", "logs", "dist", ".updates"}
                or first.startswith("config.json")
                or first.startswith("sync_history.db")
                or first in {"sites.json", "synced_posts.json", "manifest.json"}
                or first.endswith(".lock")
                or "설정백업" in first)

    def __call__(self, event: str, args: tuple) -> None:
        paths = []
        write = False
        if event == "open":
            paths = [args[0]]
            mode, flags = args[1:3]
            context = getattr(self._descriptor_open, "context", None)
            if (context is not None and not context["consumed"] and mode is None
                    and os.fsdecode(args[0]) == context["path"]):
                # os.open emits the raw relative path without its dir_fd.
                # Use the wrapper's actual path for this one matching event.
                context["consumed"] = True
                paths = [context["resolved"]]
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        elif event == "sqlite3.connect":
            name = os.fsdecode(args[0])
            if name == ":memory:":
                return
            if name.startswith("file:"):
                uri = urlsplit(name)
                if parse_qs(uri.query).get("mode") == ["memory"]:
                    return
                name = unquote(uri.path)
                if uri.netloc and uri.netloc != "localhost":
                    name = "//" + uri.netloc + name
                elif os.name == "nt" and len(name) > 2 and name[0] == "/" and name[2] == ":":
                    name = name[1:]
            paths, write = [name], True
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate"}:
            fd_index = 2 if event in {"os.mkdir", "os.chmod"} else 1
            dir_fd = args[fd_index] if event != "os.truncate" and len(args) > fd_index else None
            paths, write = [self._with_dir_fd(args[0], dir_fd)], True
        elif event in {"os.rename", "os.link", "os.symlink"}:
            if event == "os.symlink":
                paths = [args[0], self._with_dir_fd(args[1], args[2])]
            else:
                paths = [self._with_dir_fd(args[0], args[2]),
                         self._with_dir_fd(args[1], args[3])]
            write = True
        else:
            return
        for path in paths:
            if not isinstance(path, (str, bytes, os.PathLike)):
                continue
            resolved = canonical_path(path)
            relative = self._inside(path)
            # pytest's disabled file logger opens the OS null sink.
            null_sink = os.fsdecode(path).lower() in {os.devnull.lower(), "\\\\.\\nul"}
            # Python/pytest caches contain no application state.
            cache = relative is not None and (
                "__pycache__" in relative.parts or ".pytest_cache" in relative.parts)
            temporary = resolved.is_relative_to(self.allowed_root)
            protected = relative is not None and self._mutable(relative)
            if protected or (write and not temporary and not cache and not null_sink):
                message = f"Unsafe test storage access: {event} {path}"
                self.violations.append(message)
                raise AssertionError(message)

    def _with_dir_fd(self, path, dir_fd):
        if dir_fd in (None, -1) or not isinstance(path, (str, bytes, os.PathLike)):
            return path
        if os.path.isabs(path):
            return path
        for prefix in ("/proc/self/fd", "/dev/fd"):
            try:
                directory = os.readlink(f"{prefix}/{dir_fd}")
                if os.path.isabs(directory):
                    return os.path.join(directory, os.fsdecode(path))
            except OSError:
                pass
        # macOS exposes the directory path through F_GETPATH.
        if sys.platform == "darwin":
            try:
                import fcntl
                directory = os.fsdecode(fcntl.fcntl(dir_fd, 50, bytes(1024)).split(b"\0", 1)[0])
                if os.path.isabs(directory):
                    return os.path.join(directory, os.fsdecode(path))
            except OSError:
                pass
        message = f"Unsafe test storage access: unresolved dir_fd={dir_fd} path={path}"
        self.violations.append(message)
        raise AssertionError(message)


def install_storage_guard(repository: str | Path) -> StorageGuard:
    guard = StorageGuard(repository)
    sys.addaudithook(guard)
    # The 'open' audit event omits os.open's dir_fd. Check the resolved path
    # before delegating so that descriptor-relative opens cannot evade it.
    original_open = os.open

    @wraps(original_open)
    def guarded_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None:
            resolved = guard._with_dir_fd(path, dir_fd)
            guard("open", (resolved, None, flags))
            previous = getattr(guard._descriptor_open, "context", None)
            guard._descriptor_open.context = {
                "path": os.fsdecode(path), "resolved": resolved, "consumed": False,
            }
            try:
                return original_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                guard._descriptor_open.context = previous
        return original_open(path, flags, mode, dir_fd=dir_fd)

    os.open = guarded_open
    if original_open in os.supports_dir_fd:
        os.supports_dir_fd.add(guarded_open)
    return guard
