"""CrossPoint 기기 HTTP 파일 관리 클라이언트.

File Transfer / Calibre Wireless 모드에서 동작하는 웹서버 API를 사용합니다.
문서: https://github.com/crosspoint-reader/crosspoint-reader/blob/develop/docs/webserver-endpoints.md
"""
from __future__ import annotations

import json
import mimetypes
import os
import uuid
from typing import Any, Optional

import requests

from websync.upload.errors import DeviceClientError
from websync.upload.host import normalize_device_host
from websync.upload.remote_path import format_file_size, normalize_remote_path

# 하위 호환 re-export
from websync.upload.remote_path import (  # noqa: F401
    join_remote_path,
    parent_remote_path,
)
from websync.upload.sync_epub import (  # noqa: F401
    filter_old_sync_epubs,
    parse_sync_epub_date,
)
from websync.i18n import t

class X3DeviceClient:
    """CrossPoint 기기 파일·상태 API 클라이언트 (단일/다중 기기)."""

    DEFAULT_TIMEOUT = 8
    LIST_TIMEOUT = 15
    DELETE_TIMEOUT = 30
    DOWNLOAD_TIMEOUT = 120
    UPLOAD_BASE_TIMEOUT = 25

    def __init__(self, x3_ip: str, devices: Optional[list] = None):
        self.x3_ip = normalize_device_host(x3_ip)
        self.devices = devices or []
        self.last_errors: dict[str, str] = {}

    def _resolve_host(self, ip: str | None = None) -> str:
        host = normalize_device_host(ip or self.x3_ip)
        if not host:
            raise DeviceClientError(t("device.empty_host"))
        return host

    def _record_error(self, host: str, msg: str) -> None:
        self.last_errors[host] = msg

    def _clear_error(self, host: str) -> None:
        self.last_errors.pop(host, None)

    def _request_error_message(self, response: requests.Response) -> str:
        body = (response.text or "").strip().replace("\n", " ")
        if len(body) > 160:
            body = body[:160] + "…"
        msg = f"HTTP {response.status_code}"
        if body:
            msg += f" — {body}"
        if response.status_code == 404:
            msg += t("device.http_404_hint")
        return msg

    def _build_target_list(self) -> list[dict]:
        """등록된 기기 목록 (기본 + x3_devices, 중복 IP 제거)."""
        targets: list[dict] = []
        seen_ips: set[str] = set()

        if self.x3_ip:
            ip = normalize_device_host(self.x3_ip)
            if ip:
                targets.append({"name": t("device.default_name"), "ip": ip})
                seen_ips.add(ip)

        for dev in self.devices:
            ip = normalize_device_host(dev.get("ip") or "")
            if not ip or ip in seen_ips:
                continue
            targets.append({"name": dev.get("name") or ip, "ip": ip})
            seen_ips.add(ip)

        return targets

    def get_status(self, ip: str | None = None) -> dict[str, Any]:
        """GET /api/status — 펌웨어·네트워크 상태."""
        host = self._resolve_host(ip)
        url = f"http://{host}/api/status"
        try:
            response = requests.get(url, timeout=self.DEFAULT_TIMEOUT)
        except requests.Timeout as e:
            msg = t("device.timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        try:
            data = response.json()
        except ValueError as e:
            msg = t("device.status_json")
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if not isinstance(data, dict):
            msg = t("device.status_format")
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host)

        self._clear_error(host)
        return data

    def list_files(self, path: str = "/", ip: str | None = None) -> list[dict[str, Any]]:
        """GET /api/files?path=... — 디렉터리 목록."""
        host = self._resolve_host(ip)
        remote = normalize_remote_path(path)
        url = f"http://{host}/api/files"
        try:
            response = requests.get(
                url,
                params={"path": remote},
                timeout=self.LIST_TIMEOUT,
            )
        except requests.Timeout as e:
            msg = t("device.list_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        try:
            data = response.json()
        except ValueError as e:
            msg = t("device.list_json")
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if not isinstance(data, list):
            msg = t("device.list_format")
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host)

        items: list[dict[str, Any]] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not name or not isinstance(name, str):
                continue
            # 경로 세그먼트로 부적합한 이름 건너뛰기
            if name in (".", "..") or "/" in name or "\\" in name:
                continue
            try:
                size = int(raw.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            if remote == "/":
                item_path = f"/{name}"
            else:
                item_path = f"{remote}/{name}"
            items.append(
                {
                    "name": name,
                    "size": size,
                    "isDirectory": bool(raw.get("isDirectory")),
                    "isEpub": bool(raw.get("isEpub")),
                    "path": item_path,
                }
            )

        # 폴더 우선, 이름 정렬
        items.sort(key=lambda x: (not x["isDirectory"], x["name"].lower()))
        self._clear_error(host)
        return items

    def delete_paths(self, paths: list[str], ip: str | None = None) -> bool:
        """POST /delete — 하나 이상 경로 삭제."""
        host = self._resolve_host(ip)
        cleaned = [normalize_remote_path(p) for p in paths if p]
        cleaned = [p for p in cleaned if p != "/"]
        if not cleaned:
            msg = t("device.no_delete_paths")
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host)

        url = f"http://{host}/delete"
        # 단건은 path, 다건은 paths JSON (펌웨어 문서)
        if len(cleaned) == 1:
            data: dict[str, str] = {"path": cleaned[0]}
        else:
            data = {"paths": json.dumps(cleaned, ensure_ascii=False)}

        try:
            response = requests.post(url, data=data, timeout=self.DELETE_TIMEOUT)
        except requests.Timeout as e:
            msg = t("device.delete_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        self._clear_error(host)
        return True

    def mkdir(self, name: str, path: str = "/", ip: str | None = None) -> bool:
        """POST /mkdir — 폴더 생성."""
        host = self._resolve_host(ip)
        parent = normalize_remote_path(path)
        folder_name = (name or "").strip()
        if not folder_name or "/" in folder_name or "\\" in folder_name:
            raise DeviceClientError(t("device.bad_folder_name"), host=host)

        url = f"http://{host}/mkdir"
        try:
            response = requests.post(
                url,
                data={"name": folder_name, "path": parent},
                timeout=self.DEFAULT_TIMEOUT,
            )
        except requests.Timeout as e:
            msg = t("device.mkdir_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        self._clear_error(host)
        return True

    def download(self, remote_path: str, local_path: str, ip: str | None = None) -> bool:
        """GET /download?path=... — 파일을 PC로 저장."""
        host = self._resolve_host(ip)
        remote = normalize_remote_path(remote_path)
        if remote == "/":
            raise DeviceClientError(t("device.no_download"), host=host)

        url = f"http://{host}/download"
        try:
            response = requests.get(
                url,
                params={"path": remote},
                timeout=self.DOWNLOAD_TIMEOUT,
                stream=True,
            )
        except requests.Timeout as e:
            msg = t("device.download_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        parent_dir = os.path.dirname(os.path.abspath(local_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        temp_path = os.path.join(
            parent_dir or ".",
            f".{os.path.basename(local_path)}.{uuid.uuid4().hex}.part",
        )
        try:
            with open(temp_path, "xb") as f:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, local_path)
        except (OSError, requests.RequestException) as e:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            msg = t("device.save_failed", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        self._clear_error(host)
        return True

    def rename(self, path: str, new_name: str, ip: str | None = None) -> bool:
        """POST /rename — 파일 이름 변경 (파일만, 폴더 불가)."""
        host = self._resolve_host(ip)
        remote = normalize_remote_path(path)
        name = (new_name or "").strip()
        if remote == "/":
            raise DeviceClientError(t("device.no_rename"), host=host)
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise DeviceClientError(t("device.bad_new_name"), host=host)

        url = f"http://{host}/rename"
        try:
            response = requests.post(
                url,
                data={"path": remote, "name": name},
                timeout=self.DEFAULT_TIMEOUT,
            )
        except requests.Timeout as e:
            msg = t("device.rename_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        self._clear_error(host)
        return True

    def move(self, path: str, dest_dir: str, ip: str | None = None) -> bool:
        """POST /move — 파일을 기존 폴더로 이동 (파일만)."""
        host = self._resolve_host(ip)
        remote = normalize_remote_path(path)
        dest = normalize_remote_path(dest_dir)
        if remote == "/":
            raise DeviceClientError(t("device.no_move"), host=host)

        url = f"http://{host}/move"
        try:
            response = requests.post(
                url,
                data={"path": remote, "dest": dest},
                timeout=self.DEFAULT_TIMEOUT,
            )
        except requests.Timeout as e:
            msg = t("device.move_timeout", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        self._clear_error(host)
        return True

    def remote_file_exists(
        self,
        remote_dir: str,
        filename: str,
        ip: str | None = None,
    ) -> bool:
        """디렉터리에 동일 이름 파일이 있는지 확인."""
        name = (filename or "").strip()
        if not name:
            return False
        items = self.list_files(remote_dir, ip=ip)
        return any(
            (i.get("name") == name) and not i.get("isDirectory") for i in items
        )

    def upload_to_path(
        self,
        file_path: str,
        remote_dir: str = "/",
        ip: str | None = None,
        *,
        safe_filename: str | None = None,
    ) -> bool:
        """POST /upload?path=... — 지정 폴더로 파일 업로드."""
        host = self._resolve_host(ip)
        if not file_path or not os.path.isfile(file_path):
            raise DeviceClientError(t("device.no_local_file", path=file_path), host=host)

        dest = normalize_remote_path(remote_dir)
        if safe_filename is None:
            # uploader와 동일한 세니타이징 규칙
            from websync.upload.uploader import X3Uploader

            safe_filename = X3Uploader(host)._sanitize_filename(file_path)

        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except OSError:
            file_size_mb = 1.0
        timeout = int(self.UPLOAD_BASE_TIMEOUT + (file_size_mb * 5))

        url = f"http://{host}/upload"
        params = {}
        if dest and dest != "/":
            params["path"] = dest

        import mimetypes

        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                files = {"file": (safe_filename, f, mime)}
                response = requests.post(
                    url, files=files, params=params or None, timeout=timeout
                )
        except requests.Timeout as e:
            msg = t("device.upload_timeout", timeout=timeout, error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except requests.RequestException as e:
            # requests 예외는 OSError 하위일 수 있으므로 OSError보다 먼저 처리
            msg = f"{type(e).__name__}: {e}"
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e
        except OSError as e:
            msg = t("device.read_failed", error=e)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host) from e

        if response.status_code != 200:
            msg = self._request_error_message(response)
            self._record_error(host, msg)
            raise DeviceClientError(msg, host=host, status_code=response.status_code)

        self._clear_error(host)
        return True

    def test_connection(self, ip: str | None = None) -> bool:
        """기기 웹서버 접속 가능 여부 (status 우선, 실패 시 GET /)."""
        host = normalize_device_host(ip or self.x3_ip)
        if not host:
            return False
        try:
            self.get_status(host)
            return True
        except DeviceClientError:
            pass
        try:
            requests.get(f"http://{host}/", timeout=3)
            return True
        except Exception:
            return False

    @staticmethod
    def format_status_summary(status: dict[str, Any]) -> str:
        """상태 dict를 한 줄 요약 문자열로."""
        device = status.get("device") or "?"
        version = status.get("version") or "?"
        mode = status.get("mode") or "?"
        parts = [str(device), f"v{version}", str(mode)]
        rssi = status.get("rssi")
        if mode == "STA" and rssi not in (None, 0):
            parts.append(f"RSSI {rssi}")
        free_heap = status.get("freeHeap")
        if isinstance(free_heap, (int, float)) and free_heap > 0:
            parts.append(f"heap {format_file_size(free_heap)}")
        return " · ".join(parts)
