# Live source smoke (informational only, never a PR gate)

- Script: `scripts/validate_korean_scrapers.py` (public sample URLs only).
- Report only: `source`, HTTP status, selector hit, sample count, content length, timestamp.
- Never record logins, full article text, or API keys.
- A live-site failure (site redesign, 429/503, network) must not fail the deterministic CI suite.
- When a fixture starts failing after an upstream change: capture the new HTML sample first,
  write the failing test against it, then update selectors. Never auto-regenerate expectations.
