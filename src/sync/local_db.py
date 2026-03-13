"""
Local SQLite database for sync state tracking.

Replaces the ag_credentials table that the lenel-onguard-service adds inside
the Lenel SQL Server database.  Because we have no write access to Plasec's
database, sync state is stored in a local SQLite file in the user's config dir.

Schema (ag_sync_state):
  (plasec_identity_id, plasec_token_id)  — composite PK
  accessgrid_card_id                      — AG card ID after provisioning
  card_number                             — plasecInternalnumber (used as card #)
  full_name, last_synced_email, last_synced_phone, last_synced_title
  last_synced_token_status               — last Plasec token status seen (for change detection)
  created_at, last_synced_at
  status                                  — 'active' | 'suspended' | 'deleted' | 'error'
  sync_error                              — last error message
  retry_count
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from ..constants import DB_FILE, ensure_config_dir, MAX_RETRY_COUNT

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ag_sync_state (
    plasec_identity_id      TEXT NOT NULL,
    plasec_token_id         TEXT NOT NULL,
    accessgrid_card_id      TEXT,
    card_number             TEXT,
    full_name               TEXT,
    last_synced_email       TEXT,
    last_synced_phone       TEXT,
    last_synced_title       TEXT,
    last_synced_photo_hash  TEXT,
    last_synced_token_status TEXT,
    created_at              TEXT,
    last_synced_at          TEXT,
    status                  TEXT DEFAULT 'pending',
    sync_error              TEXT,
    retry_count             INTEGER DEFAULT 0,
    PRIMARY KEY (plasec_identity_id, plasec_token_id)
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalDB:
    """Thread-safe SQLite wrapper for sync state."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        ensure_config_dir()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"Opened local sync DB: {self.db_path}")

    def ensure_table(self) -> bool:
        try:
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
            # Migrate: add last_synced_title if missing (added after initial release)
            try:
                self._conn.execute(
                    "ALTER TABLE ag_sync_state ADD COLUMN last_synced_title TEXT"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
            logger.debug("ag_sync_state table ready")
            return True
        except Exception as e:
            logger.error(f"Failed to create ag_sync_state table: {e}")
            return False

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_synced_identity_token_pairs(self) -> Set[Tuple[str, str]]:
        """Return set of (plasec_identity_id, plasec_token_id) already tracked."""
        rows = self._conn.execute(
            "SELECT plasec_identity_id, plasec_token_id FROM ag_sync_state "
            "WHERE accessgrid_card_id IS NOT NULL AND status != 'deleted'"
        ).fetchall()
        return {(r['plasec_identity_id'], r['plasec_token_id']) for r in rows}

    def get_all_synced(self) -> List[Dict]:
        """Return all tracked records (any status)."""
        rows = self._conn.execute("SELECT * FROM ag_sync_state").fetchall()
        return [dict(r) for r in rows]

    def get_by_ag_card_id(self, ag_card_id: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT * FROM ag_sync_state WHERE accessgrid_card_id = ?",
            (ag_card_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_identity_token(self, identity_id: str, token_id: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT * FROM ag_sync_state "
            "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
            (identity_id, token_id)
        ).fetchone()
        return dict(row) if row else None

    def get_active_synced(self) -> List[Dict]:
        """Records that are currently synced and not deleted."""
        rows = self._conn.execute(
            "SELECT * FROM ag_sync_state "
            "WHERE status NOT IN ('deleted', 'error') "
            "AND accessgrid_card_id IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_failed_syncs(self) -> List[Dict]:
        """Records in error state that haven't hit the retry cap."""
        rows = self._conn.execute(
            "SELECT * FROM ag_sync_state "
            "WHERE status = 'error' AND retry_count < ? "
            "ORDER BY last_synced_at ASC",
            (MAX_RETRY_COUNT,)
        ).fetchall()
        return [dict(r) for r in rows]

    def is_empty(self) -> bool:
        count = self._conn.execute(
            "SELECT COUNT(*) FROM ag_sync_state"
        ).fetchone()[0]
        return count == 0

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def record_sync(
        self,
        identity_id: str,
        token_id: str,
        ag_card_id: str,
        card_number: str,
        full_name: str,
        email: str = '',
        phone: str = '',
        title: str = '',
        token_status: str = '1',
        photo_hash: str = '',
    ) -> bool:
        """
        Upsert a sync record.  Handles both new syncs and resurrections
        (identity was deleted then re-created).
        """
        try:
            now = _now()
            self._conn.execute(
                """
                INSERT INTO ag_sync_state
                    (plasec_identity_id, plasec_token_id, accessgrid_card_id,
                     card_number, full_name, last_synced_email, last_synced_phone,
                     last_synced_title, last_synced_photo_hash, last_synced_token_status,
                     created_at, last_synced_at, status, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0)
                ON CONFLICT(plasec_identity_id, plasec_token_id) DO UPDATE SET
                    accessgrid_card_id      = excluded.accessgrid_card_id,
                    card_number             = excluded.card_number,
                    full_name               = excluded.full_name,
                    last_synced_email       = excluded.last_synced_email,
                    last_synced_phone       = excluded.last_synced_phone,
                    last_synced_title       = excluded.last_synced_title,
                    last_synced_photo_hash  = excluded.last_synced_photo_hash,
                    last_synced_token_status = excluded.last_synced_token_status,
                    last_synced_at          = excluded.last_synced_at,
                    status                  = 'active',
                    retry_count             = 0,
                    sync_error              = NULL
                """,
                (identity_id, token_id, ag_card_id, card_number, full_name,
                 email, phone, title, photo_hash, token_status, now, now)
            )
            self._conn.commit()
            logger.debug(f"Recorded sync: identity={identity_id} token={token_id} ag={ag_card_id}")
            return True
        except Exception as e:
            logger.error(f"record_sync failed: {e}")
            return False

    def update_status(self, identity_id: str, token_id: str, status: str) -> bool:
        """Update sync status (e.g. 'active' → 'suspended' → 'deleted')."""
        try:
            self._conn.execute(
                "UPDATE ag_sync_state SET status = ?, last_synced_at = ? "
                "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                (status, _now(), identity_id, token_id)
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_status failed: {e}")
            return False

    def update_token_status_seen(
        self, identity_id: str, token_id: str, token_status: str
    ) -> bool:
        """Record the last Plasec token status we observed (for change detection)."""
        try:
            self._conn.execute(
                "UPDATE ag_sync_state "
                "SET last_synced_token_status = ?, last_synced_at = ? "
                "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                (token_status, _now(), identity_id, token_id)
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_token_status_seen failed: {e}")
            return False

    def update_field_snapshot(
        self,
        identity_id: str,
        token_id: str,
        full_name: str,
        email: str,
        phone: str,
        title: str = '',
    ) -> bool:
        """Update the last-seen values of fields used for change detection."""
        try:
            self._conn.execute(
                "UPDATE ag_sync_state "
                "SET full_name = ?, last_synced_email = ?, last_synced_phone = ?, "
                "    last_synced_title = ?, last_synced_at = ? "
                "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                (full_name, email, phone, title, _now(), identity_id, token_id)
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_field_snapshot failed: {e}")
            return False

    def record_error(self, identity_id: str, token_id: str, error: str) -> bool:
        """Record a sync error; cap at MAX_RETRY_COUNT."""
        try:
            row = self._conn.execute(
                "SELECT retry_count FROM ag_sync_state "
                "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                (identity_id, token_id)
            ).fetchone()

            if not row:
                # Insert a placeholder error record
                now = _now()
                self._conn.execute(
                    "INSERT OR IGNORE INTO ag_sync_state "
                    "(plasec_identity_id, plasec_token_id, status, sync_error, "
                    " retry_count, created_at, last_synced_at) "
                    "VALUES (?, ?, 'error', ?, 1, ?, ?)",
                    (identity_id, token_id, error[:500], now, now)
                )
                self._conn.commit()
                return True

            current = row['retry_count'] if row['retry_count'] is not None else 0
            if current >= MAX_RETRY_COUNT:
                logger.error(
                    f"Retry limit reached for identity={identity_id} token={token_id}"
                )
                self._conn.execute(
                    "UPDATE ag_sync_state SET sync_error = ?, last_synced_at = ? "
                    "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                    (error[:500], _now(), identity_id, token_id)
                )
            else:
                self._conn.execute(
                    "UPDATE ag_sync_state "
                    "SET sync_error = ?, retry_count = retry_count + 1, "
                    "    status = 'error', last_synced_at = ? "
                    "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
                    (error[:500], _now(), identity_id, token_id)
                )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"record_error failed: {e}")
            return False

    def mark_deleted(self, identity_id: str, token_id: str) -> bool:
        return self.update_status(identity_id, token_id, 'deleted')
