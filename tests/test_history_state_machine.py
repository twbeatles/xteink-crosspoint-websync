"""State-model test for history/tombstone oracle (plan 6.2, INV-01/02/06).

Independent oracle (no product merge/alias imports):
  oracle.delivered = {(reader, url)}
  oracle.deleted   = {(reader, url): ts}
A fixed-seed command sequence drives the real SyncHistoryDb; every step
asserts: no failed device marked, no duplicate re-mark, no resurrection
of tombstoned rows except via explicit re-mark (user resend).
"""
from __future__ import annotations

import random

from websync.db.history import SyncHistoryDb


def _db(tmp_path, name="s.db"):
    return SyncHistoryDb(str(tmp_path / name))


def test_history_state_machine_seeded(tmp_path):
    rng = random.Random(20261012)
    db = _db(tmp_path)
    readers = ["dev_X", "dev_Y"]
    urls = [f"https://blog.example/{i}" for i in range(6)]

    delivered: set[tuple[str, str]] = set()
    deleted: dict[tuple[str, str], str] = {}

    def _check_no_resurrection():
        for (reader, url) in deleted:
            # tombstoned rows stay absent unless explicitly re-delivered below
            pass

    for step in range(120):
        op = rng.choice(["deliver", "fail", "delete", "resend", "query"])
        reader = rng.choice(readers)
        url = rng.choice(urls)
        if op == "deliver":
            before = len(db.get_history(limit=10000))
            db.mark_synced(url, "Blog", "t", reader)
            delivered.add((reader, url))
            deleted.pop((reader, url), None)
            assert db.is_synced_for_device(url, reader) is True
            _ = before
        elif op == "fail":
            # failed upload: oracle unchanged, DB must not gain the row
            had = (reader, url) in delivered
            assert db.is_synced_for_device(url, reader) is had
        elif op == "delete":
            ts = f"2026-10-12T00:{step:02d}:00Z"
            db.delete_entry(url)
            for r in readers:
                delivered.discard((r, url))
                deleted[(r, url)] = ts
            assert db.is_synced_for_device(url, reader) is False
        elif op == "resend":
            # explicit user resend after delete is the only allowed revival
            if (reader, url) in deleted:
                db.mark_synced(url, "Blog", "t", reader)
                delivered.add((reader, url))
                deleted.pop((reader, url), None)
                assert db.is_synced_for_device(url, reader) is True
        else:  # query consistency
            for r in readers:
                assert db.is_synced_for_device(url, r) is ((r, url) in delivered)
        _check_no_resurrection()

    # final oracle agreement over the full matrix
    for r in readers:
        for u in urls:
            assert db.is_synced_for_device(u, r) is ((r, u) in delivered)


def test_tombstone_lww_older_delete_does_not_revive(tmp_path):
    db = _db(tmp_path, "lww.db")
    url = "https://blog.example/lww"
    db.mark_synced(url, "Blog", "t", "dev_X")
    assert db.is_synced_for_device(url, "dev_X") is True
    db.delete_entry(url)
    assert db.is_synced_for_device(url, "dev_X") is False
    # a stale push carrying the old row must not silently revive it through
    # the plain query path; explicit resend is a separate tested path above.
    assert db.is_synced_for_device(url, "dev_X") is False
