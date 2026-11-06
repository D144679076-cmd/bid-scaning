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


# M9 dedup fix (2026-11-06): FB bodies embed FB's relative-time chrome
# ("·", "3 giờ", "48 phút", "2 hours ago") that re-renders every poll —
# hashing raw text made the same post dedup twice (DB rows 1265/1284).
# Chrome-only lines are dropped before hashing; content lines untouched.
_CHROME_LINE = re.compile(
    r"^\s*(?:[·•]\s*)?(?:\d+\s*)?"
    r"(?:giây|giờ|phút|ngày|tuần|tháng|năm|"
    r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|"
    r"[hdwy])\s*(?:ago)?\s*$",
    re.IGNORECASE,
)


def normalize_for_fingerprint(text: str) -> str:
    """Drop chrome-only lines (relative time stamps, bare separators),
    then collapse whitespace + lowercase."""
    lines = [l for l in text.splitlines() if l.strip()
             and not _CHROME_LINE.match(l.strip())]
    return re.sub(r"\s+", " ", "\n".join(lines).strip().lower())


def _fingerprint(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", normalize_for_fingerprint(text))
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """sha1 of the fingerprint-normalized text — used for per-post pseudo-URLs
    (fb_feed): keeps the URL stable across FB's re-rendered time chrome, so
    URL uniqueness IS the dedup for group posts."""
    return hashlib.sha1(normalize_for_fingerprint(text)
                        .encode("utf-8")).hexdigest()[:12]


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
