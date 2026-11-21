"""X3 기기 HTTP 업로드."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import time
from concurrent.futures import (
    CancelledError as FuturesCancelledError,
)
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import Callable, Optional
from urllib.parse import quote

import requests

from websync.i18n import t
from websync.upload.device_ids import build_targets_with_keys
from websync.upload.host import normalize_device_host
from websync.upload.remote_path import normalize_upload_remote_dir

__all__ = ["X3Uploader", "normalize_device_host", "normalize_upload_remote_dir"]


class X3Uploader:
    """Xteink X3 기기와의 HTTP 업로드 통신을 전담하는 클래스 (단일/다중 기기 지원)"""

    # 일시 오류 재시도 정책 (ISSUE-001): Timeout/연결 끊김/429·5xx만 재시도한다.
    DEFAULT_MAX_RETRIES = 1
    DEFAULT_RETRY_BACKOFF = 1.0

    def __init__(
        self,
        x3_ip: str,
        devices: Optional[list] = None,
        remote_dir: str | None = None,
        *,
        primary_device_id: str = "",
        primary_alias_ids: list | None = None,
    ):
        self.x3_ip = normalize_device_host(x3_ip)
        self.devices = devices or []
        self.primary_device_id = (primary_device_id or "").strip()
        self.primary_alias_ids = primary_alias_ids or []
        self.remote_dir = normalize_upload_remote_dir(remote_dir)
        # 최근 전송 실패 사유 {ip: message} — GUI/파이프라인 로그용
        self.last_errors: dict[str, str] = {}
        # 협력 취소 콜백 (Translator.cancel_requested와 같은 형태).
        # 진행 중 POST를 강제 종료하지는 않으며, 재시도·대기 중 전송을 막는다.
        self.cancel_requested: Callable[[], bool] = lambda: False
        self.max_retries = self.DEFAULT_MAX_RETRIES
        self.retry_backoff = self.DEFAULT_RETRY_BACKOFF

    def _sanitize_filename(self, file_path: str) -> str:
        """기기 전송용 파일명 정리 — 앱에서 지정한 원본 블로그명(한글 포함)을 그대로 유지하고 파일시스템 금지 문자만 치환"""
        base, ext = os.path.splitext(os.path.basename(file_path))
        # 원본 basename의 결정적 짧은 해시: 정리 후 같아지는 서로 다른 원본(가/ga)을 구분한다.
        # basename 자체가 같으면 결과도 같다. 실행 간 고유성은 EpubBuilder 파일명이 맡는다.
        h = hashlib.md5(base.encode("utf-8", errors="replace")).hexdigest()[:6]
        safe_base = "".join(
            [c if c.isalnum() or c in ("-", "_") else "_" for c in base]
        )
        while "__" in safe_base:
            safe_base = safe_base.replace("__", "_")
        safe_base = safe_base.strip("_")
        if not safe_base:
            safe_base = f"sync_book_{h}"
        else:
            safe_base = f"{safe_base}_{h}"
        return safe_base + ext.lower()

    def check_batch_filenames(self, paths) -> None:
        """Reject ambiguous remote names before the first network write."""
        seen: dict[str, str] = {}
        for path in paths:
            name = self._sanitize_filename(path).casefold()
            if name in seen:
                raise ValueError(
                    t(
                        "upload.batch_collision",
                        first=seen[name],
                        second=str(path),
                        name=name,
                    )
                )
            seen[name] = str(path)

    def _guess_mime(self, file_path: str) -> str:
        mime, _ = mimetypes.guess_type(file_path)
        return mime or "application/octet-stream"

    def _calc_timeout(self, file_path: str) -> int:
        """파일 크기 기반 가변 타임아웃 계산"""
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except Exception:
            file_size_mb = 1.0
        return int(25 + (file_size_mb * 5))

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        """재시도 가치가 있는 HTTP 상태 (429·5xx, 일시 오류)."""
        return status_code == 429 or 500 <= status_code < 600

    def _upload_to_ip(
        self,
        file_path: str,
        ip: str,
        safe_filename: str,
        timeout: int,
        remote_dir: str | None = None,
        *,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
    ) -> bool:
        """지정 IP의 기기로 파일 1건 전송.

        일시 오류(Timeout/연결 끊김/429·5xx)는 제한 재시도한다. 그 외
        오류(4xx·파일 열기 실패 등)는 즉시 실패한다. 재시도 전 취소가
        요청되면 재시도하지 않는다. 진행 중 POST는 강제 종료하지 않는다.
        """
        host = normalize_device_host(ip)
        if not host:
            msg = t("upload.empty_host")
            self.last_errors[str(ip)] = msg
            print(f"❌ [{ip}] {msg}")
            return False
        if self.cancel_requested():
            msg = t("upload.cancelled")
            self.last_errors[host] = msg
            print(f"🚫 [{host}] {msg}")
            return False

        dest = normalize_upload_remote_dir(
            remote_dir if remote_dir is not None else self.remote_dir
        )
        # path 쿼리: 루트면 생략 (구 펌웨어 호환)
        if dest and dest != "/":
            url = f"http://{host}/upload?path={quote(dest, safe='/')}"
        else:
            url = f"http://{host}/upload"
        mime = self._guess_mime(file_path)
        attempts = 1 + (
            self.max_retries if max_retries is None else max_retries
        )
        backoff = self.retry_backoff if retry_backoff is None else retry_backoff
        last_msg = ""
        for attempt in range(attempts):
            if attempt > 0:
                if self.cancel_requested():
                    msg = t("upload.cancelled")
                    self.last_errors[host] = msg
                    print(f"🚫 [{host}] {msg}")
                    return False
                if backoff > 0:
                    time.sleep(backoff * attempt)
            try:
                with open(file_path, "rb") as f:
                    files = {"file": (safe_filename, f, mime)}
                    response = requests.post(url, files=files, timeout=timeout)
                if response.status_code == 200:
                    self.last_errors.pop(host, None)
                    return True
                body = (response.text or "").strip().replace("\n", " ")
                if len(body) > 160:
                    body = body[:160] + "…"
                msg = f"HTTP {response.status_code}"
                if body:
                    msg += f" — {body}"
                if response.status_code == 404 and "//" in url:
                    msg += t("upload.trailing_slash")
                if self._is_retryable_status(
                    response.status_code
                ) and attempt < attempts - 1:
                    last_msg = msg
                    print(
                        t(
                            "upload.retrying",
                            host=host,
                            attempt=attempt + 1,
                            total=attempts,
                            msg=msg,
                        )
                    )
                    continue
                self.last_errors[host] = msg
                print(t("upload.http_error", host=host, msg=msg, url=url))
                return False
            except requests.Timeout as e:
                last_msg = t("upload.timeout", timeout=timeout, error=e)
                if attempt >= attempts - 1:
                    break
                print(
                    t(
                        "upload.retrying",
                        host=host,
                        attempt=attempt + 1,
                        total=attempts,
                        msg=last_msg,
                    )
                )
            except requests.ConnectionError as e:
                last_msg = f"{type(e).__name__}: {e}"
                if attempt >= attempts - 1:
                    break
                print(
                    t(
                        "upload.retrying",
                        host=host,
                        attempt=attempt + 1,
                        total=attempts,
                        msg=last_msg,
                    )
                )
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.last_errors[host] = msg
                print(t("upload.failed_exc", host=host, msg=msg))
                return False
        self.last_errors[host] = last_msg
        print(t("upload.failed", host=host, msg=last_msg))
        return False

    def _build_target_list(self) -> list[dict]:
        """전송 대상 기기 목록 (기본 기기 + x3_devices, 중복 IP 제거).

        각 항목: name, ip, id, history_key (이력 DB 키 — 안정 id 또는 IP).
        """
        return build_targets_with_keys(
            self.x3_ip,
            self.devices,
            primary_id=self.primary_device_id,
            primary_alias_ids=self.primary_alias_ids,
        )

    def upload(self, file_path: str, remote_dir: str | None = None) -> bool:
        """메인 기기(x3_ip)로 파일 전송"""
        host = normalize_device_host(self.x3_ip)
        if not host:
            return False
        safe_filename = self._sanitize_filename(file_path)
        timeout = self._calc_timeout(file_path)
        result = self._upload_to_ip(
            file_path, host, safe_filename, timeout, remote_dir=remote_dir
        )
        if not result:
            print(t("upload.tip_wifi"))
            print(t("upload.tip_address"))
        return result

    def upload_to_all_devices(
        self, file_path: str, remote_dir: str | None = None
    ) -> dict:
        """등록된 모든 기기에 병렬로 파일 전송. 결과를 {ip: bool} 로 반환."""
        return self.upload_to_targets(file_path, remote_dir=remote_dir)

    def upload_to_targets(
        self,
        file_path: str,
        only_ips: Optional[list[str]] = None,
        remote_dir: str | None = None,
    ) -> dict[str, bool]:
        """
        기본 기기 및 x3_devices에 전송합니다.
        반환: {ip: 성공여부} — 키는 항상 기기 IP/호스트입니다.

        only_ips: 지정 시 해당 IP만 전송 (부분 재시도용).
        remote_dir: 기기 내 대상 폴더 (None이면 self.remote_dir).
        """
        self.last_errors = {}
        all_devices = self._build_target_list()
        if only_ips is not None:
            allow = {
                normalize_device_host(ip)
                for ip in only_ips
                if normalize_device_host(ip)
            }
            all_devices = [d for d in all_devices if d["ip"] in allow]

        if not all_devices:
            print(
                t("upload.no_devices") if only_ips is None else t("upload.no_targets")
            )
            return {}

        safe_filename = self._sanitize_filename(file_path)
        timeout = self._calc_timeout(file_path)
        results: dict[str, bool] = {}
        dest = remote_dir

        def _mark_cancelled(ip: str) -> None:
            msg = t("upload.cancelled")
            results[ip] = False
            self.last_errors[ip] = msg
            print(f"🚫 [{ip}] {msg}")

        with ThreadPoolExecutor(max_workers=min(len(all_devices), 4)) as executor:
            future_to_device = {}
            for d in all_devices:
                # 대기 중 전송은 시작하지 않는다. 진행 중 POST는 강제
                # 종료하지 않고 끝까지 기다린다 (협력 취소).
                if self.cancel_requested():
                    _mark_cancelled(d["ip"])
                    continue
                future_to_device[
                    executor.submit(
                        self._upload_to_ip,
                        file_path,
                        d["ip"],
                        safe_filename,
                        timeout,
                        dest,
                    )
                ] = d
            for future in as_completed(future_to_device):
                device = future_to_device[future]
                ip = device["ip"]
                try:
                    results[ip] = future.result()
                except FuturesCancelledError:
                    _mark_cancelled(ip)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    self.last_errors[ip] = msg
                    print(t("upload.upload_exc", name=device.get("name", ip), error=e))
                    results[ip] = False
                # 아직 시작하지 않은 대기 작업은 취소한다. 실행 중인
                # 작업은 끝까지 기다린다.
                if self.cancel_requested():
                    for pending in future_to_device:
                        pending.cancel()
        return results

    def test_connection(self, ip: str = None) -> bool:
        """기기가 켜져 있고 지정한 IP/호스트의 웹서버에 접속 가능한지 검사"""
        target_ip = normalize_device_host(ip or self.x3_ip)
        if not target_ip:
            return False
        url = f"http://{target_ip}/"
        try:
            response = requests.get(url, timeout=3)
            # 상태코드를 보지 않으면 무관한 웹서버의 404/500도 연결 성공이 된다.
            status = getattr(response, "status_code", 0) or 0
            return 200 <= status < 300
        except Exception:
            return False
