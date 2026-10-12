# Test Strategy (hermetic / contract / integration / device)

- hermetic (default `pytest tests/`): no real network, no real user files. Uses `tmp_path`,
  monkeypatched scrapers/uploaders, in-memory or temp SQLite. Must pass on Linux+Windows.
- contract (`test_crosspoint_*`, `test_opds_*`, `test_*_contract`): real loopback HTTP
  via stdlib `ThreadingHTTPServer` on 127.0.0.1, OS-assigned port, `threading.Event`
  readiness + `shutdown()`. Asserts request path/method/multipart bytes (SHA-256),
  response codes, and DB side effects. No `requests` monkeypatch for the happy path.
- integration (`test_pipeline_http_*`, `test_backup_*`, `test_history_*`):
  real `SyncService`/`EpubBuilder`/`SyncHistoryDb` wiring; only remote sites and
  device web servers are faked. Each test uses isolated `tmp_path` for
  `config.json`, `sync_history.db`, `output/`, shared-folder JSON.
- gui (`test_gui_*`): headless Fake Service + event callbacks; no real Tk mainloop,
  no real display. Frozen-EXE/agent click flows stay manual.
- physical-device (never in CI): `--real-device` + `XTEINK_TEST_DEVICE_URL` +
  `XTEINK_TEST_WRITE=1` all required; read-only `/api/status`, `/api/files` first;
  writes only under `/WebSyncTest/<run-id>/`. Left as NOT RUN unless approved.
- live-scraper (informational only): `scripts/validate_korean_scrapers.py`, never a PR gate.
- Rules: never touch real `config.json`/`sync_history.db`/`sites.json`/Calibre/reader
  files; never auto-regenerate golden expectations to force green; every new
  regression must show a failing-before signal (failure injection or mutation).
