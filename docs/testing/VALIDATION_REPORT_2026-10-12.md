# Test Hardening Validation Report

## Scope

- repository / branch / base HEAD / result HEAD: `twbeatles/xteink-crosspoint-websync`, `main`,
  base `75b2cc4` (2026-10-01, app v1.3.0), result HEAD `75b2cc4` (no product-code commit; work is uncommitted test/tools/CI additions on top).
- OS / architecture / Python / PyInstaller / CrossPoint firmware: Windows 10.0.26200 AMD64,
  Python 3.15.0 (local dev PC); CI reference Ubuntu + Python 3.12 (existing) plus new `compat-315` job (3.15).
  PyInstaller / CrossPoint firmware: not exercised.
- production code changed? **No.** `git status` shows only `M .github/workflows/test.yml` plus new files under
  `tests/` and `docs/testing/`. A temporary mutant in `websync/pipeline/upload_results.py` was applied,
  observed, and fully reverted via `git checkout` (verified: `git diff` shows no `websync/` changes).

## Baseline vs After

| Metric | Before | After | Command / evidence |
|---|---:|---:|---|
| pytest collected / passed / failed / skipped | 358 / 358 / 0 / 0 | 457 / 457 / 0 / 0 | `python -m pytest tests/ -q --tb=short -ra` (~53s), exit 0 |
| new hardening tests | 0 | 99 collected, 99 passed | 17 new files + `tests/support/fake_crosspoint_server.py`, 2 contract fixtures |
| coverage line / branch (core: pipeline+db+upload+backup+epub) | not measured | ~80% line, 209 partial branches (TOTAL 3178 stmts, 633 missed) | `pytest --cov=websync/pipeline --cov=websync/db --cov=websync/upload --cov=websync/backup --cov=websync/epub --cov-branch` |
| coverage overall | not measured | 53% TOTAL | `pytest --cov=websync --cov-branch` |
| P0 invariant tests passed | n/a (new) | INV-01/02/03/04/05/06/07/08/09/10/11/13/14 covered; see mapping | new suite |
| mutation killed/survived/timeout/equivalent | n/a | 1 targeted mutant KILLED / 0 survived (no mutmut run) | PIPE-04 vs guard-removal mutant, details below |
| HTTP contract scenarios | 0 real-HTTP | 44 passed (contract + failure matrix + path properties) | `test_crosspoint_*`, `test_device_path_properties.py` |
| two-PC oracle scenarios | mocked only | real-HTTP A→B→A→B + concurrent push + corrupt-shared, 12 passed | `test_backup_interleavings.py` + Phase 3 files |
| frozen EXE smoke | not run | NOT RUN (source `--smoke` OK, spec check OK) | `python x3_websync.py --smoke` → OK; no PyInstaller build here |
| real X3/X4 test | NOT RUN | NOT RUN | no device, no firmware version to record |
| soak duration | NOT RUN | NOT RUN | 1h soak not performed; must not be claimed |

Key module branch coverages (core): `sync_pipeline` 90%, `upload_results` 87%, `backup/service` 86%,
`epub/builder` 84%, `db/history` 81%, `upload/uploader` 78%, `upload/device_ids` 71%,
`upload/device_client` 70%, `pipeline/service` 70%. Plan target of 85% core-branch is **not yet met**
(device_client/delete-mkdir-rename-move and translator/summarizer branches dominate the gap).

## New Regression Proof

| case | independent expected | observed | failure injection | test path |
|---|---|---|---|---|
| PIPE-01 | 1 upload; EPUB has A,B; DB keys={dev_primary} | same | none | `tests/test_pipeline_http_integration.py` |
| PIPE-02 | rerun: 0 uploads, 0 new rows | same | rerun-same | same |
| PIPE-03 | only C uploaded; A absent from new EPUB | same | incremental | same |
| PIPE-04 | X history={A,B}, Y absent; uploads good=1 bad=0; overall False | same | peer HTTP 500 | same |
| PIPE-05 | good resends 0, flaky sends 1; flaky rows appear | same | recover 500→200 | same |
| PIPE-10 | EPUB has A,C not B; B absent from DB | same | selection | same |
| PIPE-11 | 1 valid EPUB file; 0 uploads; 0 DB rows; uploader spy silent | same | epub-only | same |
| PIPE-12 | 1 digest upload; A+B inside; 1 row per URL | same | digest mode | same |
| PIPE-06..09,13..16 | per-oracle (other-site intact; empty→`empty_fetch`; pull-fail blocks upload + keeps shared bytes; push-fail verdict≠success with local rows kept; digest partial; cancel commits 1 batch; no-device clean; db-error verdict) | all same | per-case | `tests/test_pipeline_failure_recovery.py` |
| HTTP-200-without-commit | listing empty despite 200 | pinned as observable gap (policy unchanged) | `store_upload=False` | `tests/test_crosspoint_upload_failure_matrix.py` |
| download interrupt | original bytes kept, zero `.part` leftovers | same | mid-stream disconnect | `tests/test_crosspoint_http_contract.py` |
| corrupt shared (0B/truncated/bad-UTF8) | pull fails, shared bytes identical, sync_now refuses push | same | shared-byte comparison | `tests/test_backup_interleavings.py` |
| concurrent push | union {url1, url2} intact | same | barrier rendezvous | same |
| identity | primaries merge across addresses; secondaries split; distinct locals never share keys | same | reconcile fixtures | `tests/test_device_identity_properties.py` |
| state model | 120 seeded ops agree with oracle sets; tombstone LWW holds | same | seed 20261012 | `tests/test_history_state_machine.py` |
| EPUB structure | mimetype first+stored, container/OPF/spine/nav, 2 ordered chapters, XML-wellformed | same | structural oracle | `tests/test_epub_structural_contract.py` |
| sanitization | no script/iframe/form/handlers/`javascript:`; URL-scheme guard contract | same (2 expectations corrected to real product contract — see defects) | malicious HTML | `tests/test_scraper_sanitization.py` |
| scraper metamorphic | limit monotonicity, dup-GUID stability, empty/429/503 surfacing, encoding robustness | same | local fixtures only | `tests/test_scraper_metamorphic.py` |
| GUI journey | save-fail→0 work; worker-exc→busy/progress recover; epub-only→no uploader/DB calls | same | Fake service, no Tk loop | `tests/test_gui_user_journey.py` |
| locks | class lock serializes instances; held lock refuses second run; lock paths agree | same | threads | `tests/test_pipeline_multiprocess_lock.py` |
| dashboard/OPDS | unauth sync→401 + 0 callbacks; busy→409; accept→202; traversal/symlink denied; no secret leak; 20-thread burst clean | same (after harness readiness fix — see defects) | real loopback | `tests/test_http_server_lifecycle.py`, `tests/test_opds_security_contract.py` |
| release | tamper/bad-hash/size/expiry/downgrade/http-URL rejected; `--version`/`--smoke` green; spec keeps locales+hiddenimports | same | ephemeral Ed25519 keys | `tests/test_release_frozen_contract.py` |

## Defects Found

- Test-expectation bugs found and fixed against real product behavior (no product change):
  1. `is_allowed_fetch_url("http://127.0.0.1/...")` returns True — private-URL allowance is by design
     (explicitly configured private sources allowed; redirect-into-private blocked; detection lives in
     `selector_assistant.url_safety.is_private_or_local_url`). Test corrected to assert the real contract.
  2. EPUB chapter XHTML uses `<!DOCTYPE html>` (no DTD); strict `ElementTree` parse needs DOCTYPE stripping first.
     Test corrected; validity assertion preserved.
  3. `ProcessFileLock` attribute is `lock_path`, not `path`. Test corrected.
  4. OPDS download route is `/opds/download/<name>` (query-string `/download?path=` is not a route).
     Traversal tests rewritten against the real routes.
  5. New-test helper used single-attempt HTTP against servers with no readiness gate
     (`WebDashboard.start()`/`OPDSServer.start()` return right after `thread.start()`).
     One intermittent failure observed: `test_dashboard_busy_maps_to_409_and_cancel_needs_auth`
     failed once in 4 combined runs (assertion, detail not captured), then 4/4 green.
     Fix (harness-only, statuses stay strict): `_wait_ready()` poll + connection-error-only retry
     (max 5) in `tests/test_http_server_lifecycle.py`; same connection-only retry in
     `tests/test_opds_security_contract.py`. After fix: 6/6 green + full suite green twice.
     Root cause of the single event is undetermined — recorded here, not hidden.
- Product-code findings (no change made, per plan constraint):
  1. HTTP 200 is treated as success without post-store verification (upload path). Pinned by test
     (`store_upload=False` case) as an observable gap; policy change requires real-firmware evidence.
  2. Two PCs whose primaries are physically different readers are still merged by current
     `reconcile_config_devices` policy. Pinned as documented limit in
     `test_two_physical_primaries_documented_limit`; policy change needs approval + migration plan.
- Mutation proof: guard `if not ok: continue` removed from `collect_mark_entries`
  → `test_PIPE_04_partial_failure_only_success_recorded` FAILED with
  `assert 'dev_bad' not in {'dev_bad': {...}, 'dev_primary': {...}}` (mutant KILLED).
  Mutant reverted; test green again. Full mutmut/cosmic-ray run not performed (tool/Python-3.15
  compatibility unverified) — kill-rate claim is limited to this targeted mutant.

## Python 3.15 Upgrade Assessment (additional request)

- CodeGraph used for impact scoping: `X3Uploader` blast radius, `SyncService` pipeline paths,
  `SyncHistoryDb` history API, `BackupSyncService` pull/push, OPDS/dashboard auth, manifest verify.
- Result: **no product-code change required.** Full suite (457 tests) is green on Python 3.15.0.
  Installed pins all import and pass: beautifulsoup4 4.15.0, EbookLib 0.20, requests 2.34.2,
  lxml 6.1.3, pytest 9.1.1, customtkinter 6.0.0, cryptography 50.0.2, Pillow 12.3.0,
  youtube-transcript-api 0.6.2, watchdog 6.0.0, googletrans 4.0.2 (lazy import with graceful fallback).
- The single 3.15 incompatibility found was in new test support: stdlib `cgi` was removed in
  Python 3.13+, so `tests/support/fake_crosspoint_server.py` ships a dependency-free manual
  multipart parser (no `cgi` import anywhere in the repo now; product code never used it).
- `requirements.txt` lower-bound pins need no change: pip resolves 3.15-compatible releases for all
  of them (verified by the green 3.15.0 run, not by editing pins without evidence).
- Watch item (unverified, unchanged): `requirements-optional.txt` pins `googletrans==4.0.0-rc1`,
  while this machine carries 4.0.2 and the translator degrades gracefully on import failure.
  Whether rc1 installs/imports on 3.15 was not tested here (no system-interpreter installs per
  project env policy); recommend verifying in the new `compat-315` CI job before relaxing the pin.
- CI: `test.yml`/`release.yml` fully switched to Python 3.15 (3.12 legacy removed, §A).
  Frozen-3.15 EXE proven by local PyInstaller build + frozen `--smoke` (§A).

## Addendum A — 2026-10-12 follow-up: full 3.15 upgrade + branch-test backfill

- `tests/test_device_client_branches.py` (15 tests): bad-name/root guards, multi-delete,
  malformed-listing skips, non-200 on mkdir/rename/move/delete/upload, missing local file,
  `remote_file_exists`, `test_connection` fallback shapes — all against real loopback HTTP.
  `device_client.py` line coverage rises accordingly (remaining misses are mostly timeout
  branches, which need delay injection rather than more cases).
- `requirements-optional.txt`: `googletrans==4.0.0-rc1` → `googletrans>=4.0.0`.
  Evidence: rc1 sdist inspected (2020-era, httpx 0.13 lineage, no 3.15-era metadata);
  installed 4.0.2 verified working on 3.15.0 in this env; translator degrades gracefully
  on import failure, so the relaxed floor cannot break the suite.
- Python 3.12 legacy removed: `test.yml` (4 jobs) and `release.yml` now pin 3.15;
  the interim `compat-315` job was folded away (everything is 3.15).
- Full suite after all changes: **472 passed, 0 failed** on Python 3.15.0
  (`python -m pytest tests/ -q --tb=short -ra`), `python x3_websync.py --smoke` OK.
- Local frozen build: `pyinstaller --clean x3_websync.spec` on Python 3.15.0, frozen EXE
  `--smoke` exit 0, `--version` exit 0. `dist/`/`build/` are gitignored, not committed.
- Frozen-build defect found and fixed (product packaging, not app logic): first 3.15-frozen EXE
  died with `ImportError: DLL load failed while importing _rust`. Root cause, verified step by step:
  `PKG-00.toc` lacked `_rust.pyd` because `hazmat/bindings/_rust/` ships `.pyi` stubs that shadow
  the native module from modulegraph (fixed via explicit `binaries`+`hiddenimports` in
  `x3_websync.spec`); then still failing because `_rust.pyd` links 3.15's
  `<prefix>/abi3t-compat/python3t.dll`, which dependency analysis misses and which exists
  nowhere else on disk (proven via pefile import table + runtime module enumeration).
  A repo-wide `.pyd` scan showed `_rust.pyd` is the sole `python3t.dll` consumer, so the spec
  helper bundles that one stub DLL at the bundle root. Rebuilt EXE: `--smoke` OK, `--version` OK.
  Regression pinned by `test_spec_collects_cryptography_rust_extension`.

## CI & Release Decision

- mandatory gates status: new `test.yml` jobs (`unit-linux`, `contract-linux`, `integration-windows`,
  `coverage`, all Python 3.15) are defined but not executed here (no GitHub Actions in this environment) —
  local equivalents all green: full suite 472 passed (after §A addendum), `--smoke` OK.
- RED / YELLOW / GREEN: **YELLOW** — ship-blockers absent (no data-loss/mis-mark regression, no product
  change, no hidden failures), but GREEN is withheld: no real X3/X4 firmware verification, no frozen-EXE
  build, no 1h soak, no full mutation score, core-branch 85% target unmet (~80%), one undetermined
  single-event flake (mitigated, 6/6 + full-suite green after).
- commands, exit codes, run links, logs/artifacts: all commands above, exit 0 except the intentional
  mutant-kill run (exit 1, expected) and the single flake (exit 1, recorded). No external run links.
- current environment not verified: real X3/X4 devices + firmware versions, Windows frozen EXE +
  first-run portable flow, macOS/Linux schedulers, 1h soak, `mutmut`/`cosmic-ray` on 3.15,
  `googletrans==4.0.0-rc1` on 3.15, GitHub-hosted CI runs of the new jobs.
- human steps before shipping:
  - [ ] Approve real-device opt-in (`--real-device` + `XTEINK_TEST_DEVICE_URL` + `XTEINK_TEST_WRITE=1`) and record firmware versions; run §12.4 scenarios.
  - [ ] Build + smoke the Windows frozen EXE on a clean machine (`pyinstaller --clean x3_websync.spec`, then `--version`/`--smoke`/`--check-update`).
  - [ ] Review the HTTP-200-without-commit gap and the two-primaries-merge limit; file follow-ups (no silent policy change).
  - [ ] Run the new CI jobs on GitHub (including `compat-315`) and attach links here.
  - [ ] Decide on full mutation gate + 85% core-branch target hardernings (device_client delete/mkdir/rename/move branches first).
