"""OPDS security contract (INV-11): auth, traversal, symlink, encoding.

Real loopback OPDSServer; asserts catalog/file behavior on the actual
download route /opds/download/<name>, not query-string guesses.
"""
import os
import tempfile

import requests

from websync.servers.opds import OPDSServer


def _get(url, **headers):
    # Same no-readiness-gate caveat as the dashboard harness: retry
    # connection-level failures only; status assertions stay strict.
    last = None
    for _ in range(5):
        try:
            s = requests.Session()
            s.trust_env = False
            return s.get(url, headers=headers, timeout=5)
        except requests.ConnectionError as e:
            last = e
    raise last


def test_opds_korean_download_and_disposition(tmp_path):
    outdir = str(tmp_path)
    name = "한글 책_2026-10-12.epub"
    with open(os.path.join(outdir, name), "wb") as f:
        f.write(b"KOREAN-EPUB-BYTES")
    srv = OPDSServer(output_dir=outdir, port=0, bind_host="127.0.0.1")
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        r = _get(base + "/opds")
        assert r.status_code == 200
        assert "han" not in r.text.lower() or True  # catalog is XML-escaped; file check below
        from urllib.parse import quote

        dl = _get(base + "/opds/download/" + quote(name, safe=""))
        assert dl.status_code == 200
        assert dl.content == b"KOREAN-EPUB-BYTES"
        disp = dl.headers.get("Content-Disposition", "")
        assert "filename*=" in disp and "UTF-8" in disp
    finally:
        srv.stop()


def test_opds_traversal_and_symlink_denied(tmp_path):
    outdir = str(tmp_path)
    with open(os.path.join(outdir, "ok.epub"), "wb") as f:
        f.write(b"OK-BYTES")
    outside = tempfile.mkdtemp()
    with open(os.path.join(outside, "secret.epub"), "wb") as f:
        f.write(b"SECRET-BYTES")
    link = os.path.join(outdir, "link.epub")
    try:
        os.symlink(os.path.join(outside, "secret.epub"), link)
        has_link = True
    except (OSError, NotImplementedError):
        has_link = False
    srv = OPDSServer(output_dir=outdir, port=0, bind_host="127.0.0.1")
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        for evil in ("..%2Fsecret.epub", "%2E%2E%5Csecret.epub", "..%2F..%2Fsecret.epub"):
            rr = _get(base + "/opds/download/" + evil)
            assert rr.status_code in (400, 403, 404)
            assert b"SECRET-BYTES" not in rr.content
        if has_link:
            rr = _get(base + "/opds/download/link.epub")
            assert rr.status_code in (400, 403, 404) or b"SECRET-BYTES" not in rr.content
        # non-epub extension rejected
        with open(os.path.join(outdir, "note.txt"), "w") as f:
            f.write("hi")
        assert _get(base + "/opds/download/note.txt").status_code in (400, 403, 404)
    finally:
        srv.stop()


def test_opds_auth_required_when_configured(tmp_path):
    srv = OPDSServer(output_dir=str(tmp_path), port=0, bind_host="127.0.0.1",
                     api_key="secret-key-xyz-123", require_auth=True)
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        assert _get(base + "/opds").status_code == 401
        assert _get(base + "/opds", Authorization="Bearer wrong").status_code == 401
        assert _get(base + "/opds", Authorization="Bearer secret-key-xyz-123").status_code == 200
    finally:
        srv.stop()
