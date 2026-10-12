# Test Baseline (Phase 0)

- HEAD: `75b2cc4ce06a724527e24068c93656a1b58b1d00` (2026-10-01 KST, app v1.3.0)
- Verified 2026-10-12: `git rev-parse HEAD` = same value above, clean tree except plan doc.
- OS/Python: Windows 10.0.26200 / Python 3.15.0 (local dev PC). CI reference: Ubuntu + Python 3.12.
- 2026-10-12 follow-up: CI/test/release fully switched to Python 3.15 (3.12 legacy removed);
  suite re-verified green on 3.15.0 after the switch (see `VALIDATION_REPORT_2026-10-12.md` addendum).
- Baseline commands (this session):
  - `python -m pytest --collect-only -q` → 358 collected, exit 0
  - `python -m pytest tests/ -q --tb=short -ra` → **358 passed in ~37s**, exit 0
  - `python x3_websync.py --smoke` → `Xteink X3 WebSync v1.3.0 smoke check OK`, exit 0
  - `python -m compileall -q websync x3_websync.py` → exit 0
- Failing/skipped/flaky at baseline: none (0 failed, 0 skipped).
- Not verified at baseline: real X3/X4 device, Windows frozen EXE, 1h soak, mutation score, branch coverage %.
