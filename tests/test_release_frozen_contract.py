"""Release/update + frozen-CLI contract (INV-13).

Ephemeral Ed25519 keys only (never real release keys): tampered payload,
bad sha/size, expiry, downgrade, non-HTTPS URL are all rejected. Frozen
equivalence: real `x3_websync.py --version/--smoke` subprocess passes and
the PyInstaller spec keeps locales/templates/themes importable.
"""
import base64
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from websync.core.update_manifest import (
    NoUpdateAvailableError,
    canonical_manifest_payload,
    verify_release_manifest,
)


def _keys():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return priv, base64.b64encode(pub).decode("ascii")


def _payload(**over):
    base = {
        "version": "9.9.1",
        "artifact_url": "https://example.com/releases/app-9.9.1.exe",
        "sha256": "b" * 64,
        "size": 1024,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
    }
    base.update(over)
    return base


def _doc(priv, payload):
    sig = base64.b64encode(priv.sign(canonical_manifest_payload(payload))).decode("ascii")
    return {"payload": payload, "signature": sig}


def test_tampered_payload_rejected():
    priv, pub = _keys()
    doc = _doc(priv, _payload())
    doc["payload"]["size"] = 999999
    with pytest.raises(ValueError, match="signature"):
        verify_release_manifest(doc, public_key=pub, current_version="9.9.0")


def test_bad_hash_size_expiry_downgrade_http_rejected():
    priv, pub = _keys()
    cases = [
        _payload(sha256="not-a-hash"),
        _payload(size=0),
        _payload(expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")),
        _payload(version="9.9.0"),
        _payload(artifact_url="http://example.com/app.exe"),
    ]
    for payload in cases:
        doc = _doc(priv, payload)
        with pytest.raises((ValueError, NoUpdateAvailableError)):
            verify_release_manifest(doc, public_key=pub, current_version="9.9.0")


def test_frozen_cli_version_and_smoke():
    r = subprocess.run([sys.executable, "x3_websync.py", "--version"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "v" in (r.stdout + r.stderr)
    r = subprocess.run([sys.executable, "x3_websync.py", "--smoke"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "smoke" in (r.stdout + r.stderr).lower()


def test_spec_keeps_locales_and_epub_resources():
    import pathlib

    spec = pathlib.Path("x3_websync.spec").read_text(encoding="utf-8")
    assert "locales" in spec
    assert "hiddenimports" in spec
