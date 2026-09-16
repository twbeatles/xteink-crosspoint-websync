"""릴리즈 매니페스트 파싱, 서명 검증 및 버전 비교 단위 테스트."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from websync.core.update_manifest import (
    NoUpdateAvailableError,
    ReleaseManifest,
    canonical_manifest_payload,
    is_newer_version,
    verify_release_manifest,
)


@pytest.fixture
def keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub_bytes).decode("ascii")
    return private_key, pub_b64


def test_is_newer_version():
    assert is_newer_version("1.0.1", "1.0.0") is True
    assert is_newer_version("1.1.0", "1.0.9") is True
    assert is_newer_version("2.0.0", "1.99.99") is True
    assert is_newer_version("1.0.0.1", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False


def test_canonical_manifest_payload():
    data = {"b": 2, "a": 1}
    payload = canonical_manifest_payload(data)
    assert payload == b'{"a":1,"b":2}'


def test_verify_release_manifest_success(keypair):
    private_key, pub_b64 = keypair
    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)
    
    payload = {
        "version": "1.1.0",
        "artifact_url": "https://github.com/twbeatles/xteink-x3-websync/releases/download/v1.1.0/xteink-x3-websync-v1.1.0.exe",
        "sha256": "a" * 64,
        "size": 1024 * 1024 * 10,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc = {"payload": payload, "signature": sig}

    manifest = verify_release_manifest(
        doc,
        public_key=pub_b64,
        current_version="1.0.0",
    )
    assert isinstance(manifest, ReleaseManifest)
    assert manifest.version == "1.1.0"
    assert manifest.artifact_sha256 == "a" * 64
    assert manifest.artifact_size == 1024 * 1024 * 10


def test_verify_release_manifest_invalid_signature(keypair):
    private_key, pub_b64 = keypair
    other_key = Ed25519PrivateKey.generate()
    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)

    payload = {
        "version": "1.1.0",
        "artifact_url": "https://github.com/twbeatles/xteink-x3-websync/releases/download/v1.1.0/app.exe",
        "sha256": "a" * 64,
        "size": 1000,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    # 다른 키로 서명
    sig = base64.b64encode(other_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc = {"payload": payload, "signature": sig}

    with pytest.raises(ValueError, match="signature verification failed"):
        verify_release_manifest(doc, public_key=pub_b64, current_version="1.0.0")


def test_verify_release_manifest_not_newer_version(keypair):
    private_key, pub_b64 = keypair
    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)

    payload = {
        "version": "1.0.0",
        "artifact_url": "https://github.com/twbeatles/xteink-x3-websync/releases/download/v1.0.0/app.exe",
        "sha256": "a" * 64,
        "size": 1000,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc = {"payload": payload, "signature": sig}

    with pytest.raises(NoUpdateAvailableError):
        verify_release_manifest(doc, public_key=pub_b64, current_version="1.0.0")


def test_verify_release_manifest_expired(keypair):
    private_key, pub_b64 = keypair
    past_time = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)

    payload = {
        "version": "1.1.0",
        "artifact_url": "https://github.com/twbeatles/xteink-x3-websync/releases/download/v1.1.0/app.exe",
        "sha256": "a" * 64,
        "size": 1000,
        "expires_at": past_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc = {"payload": payload, "signature": sig}

    with pytest.raises(ValueError, match="expired"):
        verify_release_manifest(doc, public_key=pub_b64, current_version="1.0.0")


def test_verify_release_manifest_non_https_rejected(keypair):
    private_key, pub_b64 = keypair
    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)

    payload = {
        "version": "1.1.0",
        "artifact_url": "http://insecure.example.com/app.exe",
        "sha256": "a" * 64,
        "size": 1000,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc = {"payload": payload, "signature": sig}

    with pytest.raises(ValueError, match="must be HTTPS"):
        verify_release_manifest(doc, public_key=pub_b64, current_version="1.0.0")


def test_download_release_manifest_cache_busting():
    from unittest.mock import patch, MagicMock
    from websync.core.update_manifest import download_release_manifest

    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def geturl(self):
            return "https://example.com/latest.json"
        def read(self, limit):
            return b'{"payload": {}}'

    def fake_urlopen(req, timeout):
        captured_requests.append(req)
        return FakeResponse()

    with patch("websync.core.update.manifest.urlopen", side_effect=fake_urlopen):
        result = download_release_manifest("https://example.com/latest.json")
        assert result == b'{"payload": {}}'
        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert "_t=" in req.full_url
        assert req.headers.get("Cache-control") == "no-cache" or req.headers.get("Cache-Control") == "no-cache"
        assert req.headers.get("Pragma") == "no-cache"
