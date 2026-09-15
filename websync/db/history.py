import sqlite3
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from websync.core.paths import PROJECT_ROOT, resolve_path
from websync.i18n import t

LEGACY_DEVICE_IP = "*"
HISTORY_MODE_PER_DEVICE = "per_device"
HISTORY_MODE_GLOBAL_URL = "global_url"


def _normalize_history_mode(value: str | None) -> str:
    text = (str(value) if value is not None else "").strip().lower()
    if text in (HISTORY_MODE_PER_DEVICE, HISTORY_MODE_GLOBAL_URL):
        return text
    return HISTORY_MODE_PER_DEVICE


class SyncHistoryDbError(Exception):
    """동기화 이력 DB 접근 실패"""


class SyncHistoryDb:
    """기기별 동기화 이력을 관리하는 SQLite DB 클래스.

    로컬 작업용 캐시 DB입니다. OneDrive 등 공유 폴더에는 JSON 정본을 쓰며
    이 파일을 클라우드 경로에 직접 두지 마세요.
    """
    _db_lock = threading.Lock()

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            self.db_path = os.path.join(PROJECT_ROOT, "sync_history.db")
        else:
            self.db_path = resolve_path(db_path)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._db_lock:
            try:
                with self._connect() as conn:
                    if self.db_path != ":memory:":
                        try:
                            conn.execute("PRAGMA journal_mode=WAL")
                            conn.execute("PRAGMA synchronous=NORMAL")
                        except sqlite3.Error:
                            pass
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='synced_posts'"
                    )
                    if cursor.fetchone():
                        cursor.execute("PRAGMA table_info(synced_posts)")
                        columns = {row[1] for row in cursor.fetchall()}
                        if "device_ip" not in columns:
                            self._migrate_legacy_schema(conn)
                    else:
                        self._create_v2_table(conn)
                    self._create_deleted_posts_table(conn)
                    conn.commit()
            except SyncHistoryDbError:
                raise
            except Exception as e:
                raise SyncHistoryDbError(t("db.init_failed", error=e)) from e

    @staticmethod
    def _create_v2_table(conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS synced_posts (
                url TEXT NOT NULL,
                device_ip TEXT NOT NULL,
                site_name TEXT,
                title TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (url, device_ip)
            )
        """)

    @staticmethod
    def _create_deleted_posts_table(conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deleted_posts (
                url TEXT NOT NULL,
                device_ip TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                PRIMARY KEY (url, device_ip)
            )
        """)

    def _migrate_legacy_schema(self, conn: sqlite3.Connection):
        conn.execute("ALTER TABLE synced_posts RENAME TO synced_posts_legacy")
        self._create_v2_table(conn)
        conn.execute("""
            INSERT INTO synced_posts (url, device_ip, site_name, title, synced_at)
            SELECT url, ?, site_name, title, synced_at FROM synced_posts_legacy
        """, (LEGACY_DEVICE_IP,))
        conn.execute("DROP TABLE synced_posts_legacy")

    def is_synced_for_device(self, url: str, device_ip: str) -> bool:
        """특정 기기에 해당 URL이 이미 전송되었는지 확인합니다.

        레거시 device_ip='*' 행은 더 이상 모든 기기에 대한 완료로 취급하지 않습니다.
        (다중 기기 도입 후 재전송이 막히던 문제 수정)
        """
        if not url or not device_ip:
            return False
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT 1 FROM synced_posts
                        WHERE url = ? AND device_ip = ?
                        """,
                        (url, device_ip),
                    )
                    return cursor.fetchone() is not None
            except Exception as e:
                raise SyncHistoryDbError(t("db.query_failed", error=e)) from e

    def is_synced_for_any_key(self, url: str, keys: list[str]) -> bool:
        """여러 이력 키(안정 id / IP / 예전 호스트) 중 하나라도 있으면 True."""
        if not url:
            return False
        for key in keys:
            k = (key or "").strip()
            if k and self.is_synced_for_device(url, k):
                return True
        return False

    def needs_sync(
        self,
        url: str,
        target_ips: list[str],
        *,
        history_mode: str = HISTORY_MODE_PER_DEVICE,
        key_aliases: list[list[str]] | None = None,
    ) -> bool:
        """미전송이 있으면 True.

        history_mode:
          - per_device: 대상 기기 키 중 하나라도 미전송이면 True
          - global_url: URL 이력이 하나라도 있으면 False (전역 스킵)
        target_ips 는 실제로는 이력 키 목록(안정 device id 또는 IP)일 수 있습니다.
        key_aliases: 기기별 후보 키 목록 (id·현재 IP·과거 host). 있으면 target_ips 대신 사용.
        주소 변경 호환성은 key_aliases의 안정 ID·이전 주소로만 판정합니다.
        """
        if not url:
            return False
        mode = _normalize_history_mode(history_mode)
        if mode == HISTORY_MODE_GLOBAL_URL:
            return not self.is_synced(url)

        groups: list[list[str]]
        if key_aliases:
            groups = [list(g) for g in key_aliases if g]
        else:
            groups = [[ip] for ip in target_ips if ip]

        if not groups:
            return not self.is_synced(url)

        return any(not self.is_synced_for_any_key(url, g) for g in groups)

    def pending_device_ips(
        self,
        url: str,
        target_ips: list[str],
        *,
        history_mode: str = HISTORY_MODE_PER_DEVICE,
        key_aliases: list[list[str]] | None = None,
    ) -> list[str]:
        """아직 전송되지 않은 기기 키 목록.

        target_ips 가 비어 있으면 전송 대상이 없으므로 항상 빈 목록을 반환합니다.
        global_url 모드에서는 URL 이력이 있으면 빈 목록, 없으면 전체 대상.
        key_aliases 가 있으면 각 그룹의 대표 키(첫 항목)를 반환 목록에 사용하고,
        매칭은 그룹 전체로 합니다.
        """
        if not url:
            return []
        mode = _normalize_history_mode(history_mode)

        groups: list[list[str]]
        if key_aliases:
            groups = [list(g) for g in key_aliases if g]
        else:
            groups = [[ip] for ip in target_ips if ip]

        if not groups:
            return []

        if mode == HISTORY_MODE_GLOBAL_URL:
            if self.is_synced(url):
                return []
            return [(g[0] if g else "") for g in groups if g]

        pending: list[str] = []
        for g in groups:
            if not self.is_synced_for_any_key(url, g):
                pending.append(g[0])
        return pending

    def is_synced(self, url: str) -> bool:
        """URL에 동기화 이력이 존재하는지 (레거시·기기별 포함)."""
        if not url:
            return False
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM synced_posts WHERE url = ? LIMIT 1", (url,))
                    return cursor.fetchone() is not None
            except Exception as e:
                raise SyncHistoryDbError(t("db.query_failed", error=e)) from e

    def mark_synced(self, url: str, site_name: str, title: str, device_ip: str):
        """특정 기기에 대한 전송 완료 이력을 저장합니다."""
        self.mark_synced_many(
            [{"url": url, "site_name": site_name, "title": title, "device_ip": device_ip}]
        )

    def mark_synced_many(self, entries: list[dict]) -> int:
        """여러 전송 완료 이력을 한 트랜잭션으로 저장합니다.

        entries: [{url, site_name, title, device_ip}, ...]
        Returns: 저장된 행 수
        """
        if not entries:
            return 0
        rows = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            url = (e.get("url") or "").strip()
            device_ip = (e.get("device_ip") or "").strip()
            if not url or not device_ip:
                continue
            rows.append(
                (
                    url,
                    device_ip,
                    e.get("site_name") or "",
                    e.get("title") or "",
                )
            )
        if not rows:
            return 0
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.executemany(
                        """
                        INSERT OR REPLACE INTO synced_posts (url, device_ip, site_name, title)
                        VALUES (?, ?, ?, ?)
                        """,
                        rows,
                    )
                    cursor.executemany(
                        "DELETE FROM deleted_posts WHERE url = ? AND device_ip = ?",
                        [(url, device_ip) for url, device_ip, _site, _title in rows],
                    )
                    conn.commit()
                    return len(rows)
            except Exception as e:
                raise SyncHistoryDbError(t("db.write_failed", error=e)) from e

    def remap_legacy_star_to_device(self, device_ip: str) -> int:
        """레거시 device_ip='*' 행을 지정 기기 IP로 이관합니다. Returns: 갱신 건수."""
        if not device_ip or device_ip == LEGACY_DEVICE_IP:
            return 0
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    # 이미 동일 URL+device 가 있으면 * 행만 삭제, 없으면 IP 로 변경
                    cursor.execute(
                        "SELECT url, site_name, title, synced_at FROM synced_posts WHERE device_ip = ?",
                        (LEGACY_DEVICE_IP,),
                    )
                    legacy = cursor.fetchall()
                    changed = 0
                    for url, site_name, title, synced_at in legacy:
                        cursor.execute(
                            "SELECT 1 FROM synced_posts WHERE url = ? AND device_ip = ?",
                            (url, device_ip),
                        )
                        if cursor.fetchone():
                            cursor.execute(
                                "DELETE FROM synced_posts WHERE url = ? AND device_ip = ?",
                                (url, LEGACY_DEVICE_IP),
                            )
                        else:
                            cursor.execute(
                                """
                                UPDATE synced_posts SET device_ip = ?
                                WHERE url = ? AND device_ip = ?
                                """,
                                (device_ip, url, LEGACY_DEVICE_IP),
                            )
                        changed += 1
                    conn.commit()
                    return changed
            except Exception as e:
                raise SyncHistoryDbError(t("db.legacy_failed", error=e)) from e

    def get_history(self, limit: int = 200) -> list:
        """동기화 이력을 최신순으로 반환 (URL 기준 집계)."""
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT url, site_name, title, MAX(synced_at), GROUP_CONCAT(device_ip)
                        FROM synced_posts
                        GROUP BY url
                        ORDER BY MAX(synced_at) DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                    return cursor.fetchall()
            except Exception as e:
                raise SyncHistoryDbError(t("db.history_query_failed", error=e)) from e

    def delete_entry(self, url: str):
        """특정 URL의 모든 기기 동기화 이력 삭제 (재전송 허용)."""
        if not url:
            return
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    deleted_at = datetime.now().isoformat(timespec="microseconds")
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO deleted_posts (url, device_ip, deleted_at)
                        SELECT url, device_ip, ? FROM synced_posts WHERE url = ?
                        """,
                        (deleted_at, url),
                    )
                    cursor.execute("DELETE FROM synced_posts WHERE url = ?", (url,))
                    conn.commit()
            except Exception as e:
                raise SyncHistoryDbError(t("db.delete_failed", error=e)) from e

    def clear_all(self):
        """모든 동기화 이력 초기화"""
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    deleted_at = datetime.now().isoformat(timespec="microseconds")
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO deleted_posts (url, device_ip, deleted_at)
                        SELECT url, device_ip, ? FROM synced_posts
                        """,
                        (deleted_at,),
                    )
                    cursor.execute("DELETE FROM synced_posts")
                    conn.commit()
            except Exception as e:
                raise SyncHistoryDbError(t("db.clear_failed", error=e)) from e

    def get_count(self) -> int:
        """고유 URL 이력 건수 반환"""
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(DISTINCT url) FROM synced_posts")
                    row = cursor.fetchone()
                    return row[0] if row else 0
            except Exception as e:
                raise SyncHistoryDbError(t("db.count_failed", error=e)) from e

    def export_all_posts(self) -> list[dict]:
        """전체 전송 이력을 dict 목록으로 반환 (백업/클라우드 동기화용)."""
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT url, device_ip, site_name, title, synced_at
                        FROM synced_posts
                        ORDER BY synced_at ASC, url ASC, device_ip ASC
                        """
                    )
                    rows = cursor.fetchall()
                    return [
                        {
                            "url": row[0] or "",
                            "device_ip": row[1] or "",
                            "site_name": row[2] or "",
                            "title": row[3] or "",
                            "synced_at": row[4] or "",
                        }
                        for row in rows
                    ]
            except Exception as e:
                raise SyncHistoryDbError(t("db.export_failed", error=e)) from e

    def export_deleted_posts(self) -> list[dict]:
        """클라우드 동기화에서 삭제를 전파할 tombstone 목록을 반환합니다."""
        with self._db_lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT url, device_ip, deleted_at FROM deleted_posts
                        ORDER BY deleted_at ASC, url ASC, device_ip ASC
                        """
                    ).fetchall()
                    return [
                        {"url": row[0], "device_ip": row[1], "deleted_at": row[2]}
                        for row in rows
                    ]
            except Exception as e:
                raise SyncHistoryDbError(t("db.export_deleted_failed", error=e)) from e

    def import_deleted_posts(self, deleted_posts: list[dict]) -> int:
        """원격 tombstone을 병합하고 그보다 오래된 전송 이력을 제거합니다."""
        if not deleted_posts:
            return 0
        changed = 0
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    for item in deleted_posts:
                        if not isinstance(item, dict):
                            continue
                        url = (item.get("url") or "").strip()
                        device_ip = (item.get("device_ip") or "").strip()
                        deleted_at = (item.get("deleted_at") or "").strip()
                        if not url or not device_ip or not deleted_at:
                            continue
                        cursor.execute(
                            "SELECT deleted_at FROM deleted_posts WHERE url = ? AND device_ip = ?",
                            (url, device_ip),
                        )
                        row = cursor.fetchone()
                        old_deleted = (row[0] if row else "") or ""
                        if not row or self._time_key(deleted_at) > self._time_key(old_deleted):
                            cursor.execute(
                                "INSERT OR REPLACE INTO deleted_posts (url, device_ip, deleted_at) VALUES (?, ?, ?)",
                                (url, device_ip, deleted_at),
                            )
                            changed += 1
                        cursor.execute(
                            "SELECT synced_at FROM synced_posts WHERE url = ? AND device_ip = ?",
                            (url, device_ip),
                        )
                        synced = cursor.fetchone()
                        if synced and self._time_key(deleted_at) >= self._time_key(synced[0] or ""):
                            cursor.execute(
                                "DELETE FROM synced_posts WHERE url = ? AND device_ip = ?",
                                (url, device_ip),
                            )
                    return changed
            except Exception as e:
                raise SyncHistoryDbError(t("db.import_deleted_failed", error=e)) from e

    @staticmethod
    def _time_key(value: str) -> str:
        return (value or "").replace("T", " ", 1).replace("Z", "+00:00")

    def import_posts_union(self, posts: list[dict]) -> int:
        """원격 이력을 합집합 병합합니다. (url, device_ip) 기준.

        - 없으면 INSERT
        - 있으면 synced_at 이 더 최신인 쪽의 title/site_name/synced_at 유지
        Returns:
            신규 삽입 또는 갱신된 행 수
        """
        if not posts:
            return 0
        changed = 0
        with self._db_lock:
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    for post in posts:
                        if not isinstance(post, dict):
                            continue
                        url = (post.get("url") or "").strip()
                        device_ip = (post.get("device_ip") or "").strip()
                        if not url or not device_ip:
                            continue
                        site_name = post.get("site_name") or ""
                        title = post.get("title") or ""
                        synced_at = post.get("synced_at") or ""

                        cursor.execute(
                            "SELECT deleted_at FROM deleted_posts WHERE url = ? AND device_ip = ?",
                            (url, device_ip),
                        )
                        tombstone = cursor.fetchone()
                        if tombstone and self._time_key(tombstone[0] or "") >= self._time_key(synced_at):
                            continue
                        if tombstone:
                            cursor.execute(
                                "DELETE FROM deleted_posts WHERE url = ? AND device_ip = ?",
                                (url, device_ip),
                            )

                        cursor.execute(
                            """
                            SELECT site_name, title, synced_at FROM synced_posts
                            WHERE url = ? AND device_ip = ?
                            """,
                            (url, device_ip),
                        )
                        existing = cursor.fetchone()
                        if existing is None:
                            if synced_at:
                                cursor.execute(
                                    """
                                    INSERT INTO synced_posts
                                    (url, device_ip, site_name, title, synced_at)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (url, device_ip, site_name, title, synced_at),
                                )
                            else:
                                cursor.execute(
                                    """
                                    INSERT INTO synced_posts
                                    (url, device_ip, site_name, title)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (url, device_ip, site_name, title),
                                )
                            changed += 1
                            continue

                        old_site, old_title, old_at = existing
                        old_at_s = old_at or ""
                        new_at_s = synced_at or ""
                        # 원격이 더 최신이거나 로컬 시각이 비어 있으면 갱신
                        # ISO(T) / SQLite(공백) 혼용을 위해 비교용 정규화
                        old_cmp = old_at_s.replace("T", " ", 1)
                        new_cmp = new_at_s.replace("T", " ", 1)
                        if new_at_s and (not old_at_s or new_cmp > old_cmp):
                            cursor.execute(
                                """
                                UPDATE synced_posts
                                SET site_name = ?, title = ?, synced_at = ?
                                WHERE url = ? AND device_ip = ?
                                """,
                                (site_name or old_site, title or old_title, new_at_s, url, device_ip),
                            )
                            changed += 1
                        elif not old_at_s and not new_at_s:
                            # 둘 다 시각 없음: 메타만 보강
                            if (site_name and site_name != old_site) or (title and title != old_title):
                                cursor.execute(
                                    """
                                    UPDATE synced_posts
                                    SET site_name = COALESCE(NULLIF(?, ''), site_name),
                                        title = COALESCE(NULLIF(?, ''), title)
                                    WHERE url = ? AND device_ip = ?
                                    """,
                                    (site_name, title, url, device_ip),
                                )
                                if cursor.rowcount:
                                    changed += 1
                    conn.commit()
                    return changed
            except Exception as e:
                raise SyncHistoryDbError(t("db.import_failed", error=e)) from e
