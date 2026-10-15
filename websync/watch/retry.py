"""Durable, serial Watch uploads with interruptible capped retry delays.

Only acknowledged targets are excluded on retry. A lost response remains uncertain:
this local queue cannot promise exactly-once delivery to a remote device.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field


def file_fingerprint(path: str) -> list[int]:
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = os.stat(path)
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("Watch source changed while fingerprinting")
    return [stat.st_size, stat.st_mtime_ns, int(digest.hexdigest(), 16)]


def valid_pending_job(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    fingerprint = value.get("fingerprint", [])
    return (
        isinstance(fingerprint, list)
        and (not fingerprint or len(fingerprint) == 3)
        and all(type(part) is int and part >= 0 for part in fingerprint)
        and all(isinstance(value.get(key, []), list)
                and all(isinstance(item, str) for item in value.get(key, []))
                for key in ("targets", "completed"))
    )


def target_key(target: dict, remote_dir: str) -> str:
    # Include destination: changing folder requests another copy on that device.
    return json.dumps([target.get("history_key") or target["ip"], remote_dir], ensure_ascii=False)


@dataclass
class _Job:
    state: dict = field(default_factory=dict)
    due: float = 0.0
    failures: int = 0
    generation: int = 0
    deferred: bool = False


class WatchRetryQueue:
    """One run() worker; callbacks must be thread-safe and must not access Tk.

    save(path, state|None) atomically updates only that pending record and its
    legacy pending_files entry. Success is removed only after durable saving.
    """

    def __init__(self, make_uploader, attempt, save, *, pending_files=(),
                 pending_jobs=None, on_error=None, retry_base=2.0, retry_cap=300.0,
                 stability_interval=0.5, stability_checks=2):
        self.make_uploader = make_uploader
        self.attempt = attempt
        self.save = save
        self.on_error = on_error or (lambda path, error: None)
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self.stability_interval = stability_interval
        self.stability_checks = stability_checks
        self.stop_event = threading.Event()
        self._condition = threading.Condition()
        self._jobs: dict[str, _Job] = {}
        self._finished: dict[str, dict] = {}
        states = pending_jobs or {}
        for path in dict.fromkeys([*pending_files, *states]):
            absolute = os.path.abspath(path)
            state = states.get(path, {})
            self._jobs[absolute] = _Job(copy.deepcopy(state) if valid_pending_job(state) else {})

    def _add(self, path: str, *, deferred: bool) -> bool:
        path = os.path.abspath(path)
        with self._condition:
            if self.stop_event.is_set() and not deferred:
                return False
            if path in self._jobs:
                job = self._jobs[path]
                job.generation += 1
                if not deferred and job.deferred:
                    job.deferred = False
                    job.due = 0.0
                if deferred:
                    try:
                        self.save(path, job.state)
                    except Exception as error:
                        self.on_error(path, error)
                self._condition.notify()
                return False
            # Retain the memory record even if a transient save fails. _process
            # must persist it before uploading, so an observer event cannot vanish.
            state = copy.deepcopy(self._finished.get(path, {}))
            self._jobs[path] = _Job(state, deferred=deferred)
            try:
                self.save(path, state)
            except Exception as error:
                self.on_error(path, error)
            self._condition.notify()
            return True

    def enqueue(self, path: str) -> bool:
        return self._add(path, deferred=False)

    def retain(self, path: str) -> bool:
        """Persist an unstabilized observer event for next startup only.

        The observer calls this during stop; it must never start another upload.
        Existing active/partial records retain their acknowledged device state.
        """
        return self._add(path, deferred=True)

    def stop(self) -> None:
        self.stop_event.set()
        with self._condition:
            self._condition.notify_all()

    def _process(self, path: str, job: _Job) -> bool:
        if not os.path.isfile(path):
            # Keep missing files pending: network/removable libraries may return.
            return False
        # Recovered jobs may have been handed off before watchdog debounce.
        # A file still being copied must stabilize before its first network write.
        fingerprint = file_fingerprint(path)
        for _ in range(self.stability_checks):
            if self.stop_event.wait(self.stability_interval):
                return False
            stat = os.stat(path)
            if [stat.st_size, stat.st_mtime_ns] != fingerprint[:2]:
                return False
        uploader = self.make_uploader()
        targets = uploader._build_target_list()
        keys = {target_key(target, uploader.remote_dir): target["ip"] for target in targets}
        previous = job.state
        completed = set(previous.get("completed", [])) if previous.get("fingerprint") == fingerprint else set()
        completed.intersection_update(keys)
        state = {"fingerprint": fingerprint, "targets": sorted(keys), "completed": sorted(completed)}
        self.save(path, state)
        job.state = state
        pending = [ip for key, ip in keys.items() if key not in completed]
        if self.stop_event.is_set():
            return False
        results = self.attempt(path, uploader, pending, self.stop_event) if pending else {}
        # Never acknowledge a mutable source under the old fingerprint.
        if file_fingerprint(path) != fingerprint:
            job.state = {}
            self.save(path, {})
            return False
        completed.update(key for key, ip in keys.items() if results.get(ip) is True)
        current = self.make_uploader()
        current_keys = {target_key(target, current.remote_dir) for target in current._build_target_list()}
        completed.intersection_update(current_keys)
        keys = current_keys
        state["targets"] = sorted(keys)
        state["completed"] = sorted(completed)
        self.save(path, state)
        job.state = state
        if keys and completed == set(keys):
            return True
        return False

    def run(self) -> None:
        while not self.stop_event.is_set():
            with self._condition:
                while not self.stop_event.is_set():
                    eligible = [(path, job) for path, job in self._jobs.items() if not job.deferred]
                    if not eligible:
                        self._condition.wait()
                        continue
                    path, job = min(eligible, key=lambda item: item[1].due)
                    delay = job.due - time.monotonic()
                    if delay > 0:
                        self._condition.wait(delay)
                        continue
                    break
                else:
                    return
            generation = job.generation
            try:
                complete = self._process(path, job)
            except Exception as error:
                complete = False
                self.on_error(path, error)
            with self._condition:
                if complete and generation == job.generation:
                    try:
                        self.save(path, None)
                    except Exception as error:
                        self.on_error(path, error)
                        job.due = time.monotonic() + self.retry_base
                        continue
                    self._finished[path] = copy.deepcopy(job.state)
                    del self._jobs[path]
                elif complete:
                    job.due = 0.0
                else:
                    # Avoid enormous exponent values during extended offline periods.
                    job.failures = min(job.failures + 1, 30)
                    job.due = time.monotonic() + min(self.retry_cap, self.retry_base * 2 ** (job.failures - 1))
