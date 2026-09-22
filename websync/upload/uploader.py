"""X3 기기 HTTP 업로드."""
from __future__ import annotations

import hashlib
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import quote

import requests

from websync.upload.host import normalize_device_host
from websync.upload.remote_path import normalize_upload_remote_dir
from websync.upload.device_ids import build_targets_with_keys
from websync.i18n import t

__all__ = ["X3Uploader", "normalize_device_host", "normalize_upload_remote_dir"]


class X3Uploader:
    """Xteink X3 기기와의 HTTP 업로드 통신을 전담하는 클래스 (단일/다중 기기 지원)"""

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

    def _sanitize_filename(self, file_path: str) -> str:
        """CrossPoint 오작동(공백/특수문자 크래시) 우회 및 고유 식별용 파일명 클렌징"""
        base, ext = os.path.splitext(os.path.basename(file_path))
        # hashlib.md5 기반 6자리 short hash 생성하여 파일명 중복 덮어쓰기 방지
        h = hashlib.md5(base.encode("utf-8", errors="replace")).hexdigest()[:6]
        safe_base = "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in base])
        while "__" in safe_base:
            safe_base = safe_base.replace("__", "_")
        safe_base = safe_base.strip("_")
        if not safe_base:
            safe_base = f"sync_book_{h}"
        else:
            safe_base = f"{safe_base}_{h}"
        return safe_base + ext.lower()

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

    def _upload_to_ip(
        self,
        file_path: str,
        ip: str,
        safe_filename: str,
        timeout: int,
        remote_dir: str | None = None,
    ) -> bool:
        """지정 IP의 기기로 파일 1건 전송"""
        host = normalize_device_host(ip)
        if not host:
            msg = t("upload.empty_host")
            self.last_errors[str(ip)] = msg
            print(f"❌ [{ip}] {msg}")
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
            self.last_errors[host] = msg
            print(t("upload.http_error", host=host, msg=msg, url=url))
            return False
        except requests.Timeout as e:
            msg = t("upload.timeout", timeout=timeout, error=e)
            self.last_errors[host] = msg
            print(t("upload.failed", host=host, msg=msg))
            return False
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.last_errors[host] = msg
            print(t("upload.failed_exc", host=host, msg=msg))
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

    def upload_to_all_devices(self, file_path: str, remote_dir: str | None = None) -> dict:
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
            allow = {normalize_device_host(ip) for ip in only_ips if normalize_device_host(ip)}
            all_devices = [d for d in all_devices if d["ip"] in allow]

        if not all_devices:
            print(t("upload.no_devices") if only_ips is None else t("upload.no_targets"))
            return {}

        safe_filename = self._sanitize_filename(file_path)
        timeout = self._calc_timeout(file_path)
        results: dict[str, bool] = {}
        dest = remote_dir

        with ThreadPoolExecutor(max_workers=min(len(all_devices), 4)) as executor:
            future_to_device = {
                executor.submit(
                    self._upload_to_ip, file_path, d["ip"], safe_filename, timeout, dest
                ): d
                for d in all_devices
            }
            for future in as_completed(future_to_device):
                device = future_to_device[future]
                ip = device["ip"]
                try:
                    results[ip] = future.result()
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    self.last_errors[ip] = msg
                    print(t("upload.upload_exc", name=device.get("name", ip), error=e))
                    results[ip] = False
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
