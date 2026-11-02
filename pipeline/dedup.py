"""Dedup step (M1). Unique key: normalized URL + text fingerprint hash.

INSERT OR IGNORE; new posts recorded with source + timestamp (AGENTS.md).
"""

import datetime as _dt
import hashlib
import re

INSERT_SQL = """
INSERT OR IGNORE INTO requests
  (source, url, fingerprint, author, posted_at, raw_text, status, created_at)
VALUES
  (?, ?, ?, ?, ?, ?, 'lead', ?)
"""


def _fingerprint(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def _iso(epoch_seconds) -> str:
    try:
        return _dt.datetime.fromtimestamp(
            float(epoch_seconds), tz=_dt.timezone.utc
        ).isoformat()
    except (TypeError, ValueError):
        return None


def store(conn, items: list[dict]) -> list[dict]:
    """Insert items; returns only the NOT-previously-seen items."""
    now = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    fresh = []
    for item in items:
        cur = conn.execute(
            INSERT_SQL,
            (
                item["source"],
                item["url"],
                _fingerprint(item["raw_text"]),
                item.get("author") or "",
                _iso(item.get("posted_at")),
                item["raw_text"],
                now,
            ),
        )
        if cur.rowcount == 1:
            fresh.append(item)
    conn.commit()
    return fresh
