"""UpdateService 고수준 조율 서비스 단위 테스트."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from websync.core.update_manifest import ReleaseManifest, canonical_manifest_payload
from websync.core.update_service import UpdateService


@pytest.fixture
def test_keypair():
    private_key = Ed25519PrivateKey.generate()
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub_bytes).decode("ascii")
    return private_key, pub_b64


def test_update_service_check_for_update_found(tmp_path, test_keypair):
    private_key, pub_b64 = test_keypair
    service = UpdateService(
        current_version="1.0.0",
        public_key=pub_b64,
        storage_root=tmp_path,
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)
    payload = {
        "version": "1.2.0",
        "artifact_url": "https://example.invalid/app.exe",
        "sha256": "f" * 64,
        "size": 5000,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc_bytes = canonical_manifest_payload({"payload": payload, "signature": sig})

    with patch("websync.core.update_service.download_release_manifest", return_value=doc_bytes):
        manifest = service.check_for_update()
        assert manifest is not None
        assert manifest.version == "1.2.0"


def test_update_service_check_for_update_up_to_date(tmp_path, test_keypair):
    private_key, pub_b64 = test_keypair
    service = UpdateService(
        current_version="1.0.0",
        public_key=pub_b64,
        storage_root=tmp_path,
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)
    payload = {
        "version": "1.0.0",
        "artifact_url": "https://example.invalid/app.exe",
        "sha256": "f" * 64,
        "size": 5000,
        "expires_at": future_time.isoformat().replace("+00:00", "Z"),
    }
    sig = base64.b64encode(private_key.sign(canonical_manifest_payload(payload))).decode("ascii")
    doc_bytes = canonical_manifest_payload({"payload": payload, "signature": sig})

    with patch("websync.core.update_service.download_release_manifest", return_value=doc_bytes):
        manifest = service.check_for_update()
        assert manifest is None


def test_download_and_stage_streams_chunks_without_buffering(tmp_path):
    data = [b"first", b"second"]
    manifest = ReleaseManifest(
        version="1.1.0",
        artifact_url="https://example.invalid/app.exe",
        artifact_sha256=hashlib.sha256(b"".join(data)).hexdigest(),
        artifact_size=sum(map(len, data)),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        signature="dummy",
    )
    service = UpdateService(storage_root=tmp_path)
    progress = []
    consumed = []

    def source(*_args, **_kwargs):
        for chunk in data:
            consumed.append(chunk)
            yield chunk

    def staging(_manifest, *, chunks, staging_root, **_kwargs):
        iterator = iter(chunks)
        assert consumed == []
        assert next(iterator) == b"first"
        assert consumed == [b"first"]
        assert next(iterator) == b"second"
        path = Path(staging_root) / "staged.exe"
        path.write_bytes(b"".join(consumed))
        return path

    with patch("websync.core.update_service.stream_update_artifact", source), patch(
        "websync.core.update_service.prepare_staged_update", staging
    ):
        staged = service.download_and_stage(
            manifest, progress_callback=lambda current, total: progress.append((current, total))
        )

    assert staged.read_bytes() == b"firstsecond"
    assert progress == [(5, 11), (11, 11)]
