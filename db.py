"""SQLite access for the bid-scan pipeline. M1.

Schema per docs/PLAN.md §4 (M1 migration note: `fingerprint` column added,
see PLAN.md §4 note). WAL mode per AGENTS.md.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  fingerprint TEXT NOT NULL UNIQUE,
  author TEXT,
  posted_at TEXT,
  raw_text TEXT NOT NULL,
  score INTEGER,
  task_type TEXT,
  tools TEXT,
  topic TEXT,                      -- M9 stats (2026-11-06): short purpose label,
                                   -- e.g. "crm", "booking site" (see PLAN.md §4)
  suggested_price TEXT,            -- M10a (phase-m10-auto-send.md §4): pricing_tiers
                                   -- match, shown pre-✅, consumed by senders
  send_mode TEXT,                  -- M10a: 'auto' | 'assist'; NULL = manual copy
  budget TEXT,
  deadline TEXT,
  contact_channel TEXT,
  language TEXT,
  status TEXT DEFAULT 'lead',
  draft_text TEXT,
  comment_text TEXT,
  sent_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS followups (
  request_id INTEGER REFERENCES requests(id),
  due_at TEXT,
  done INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT,
  portfolio_url TEXT,
  past_work TEXT,
  pricing_tiers TEXT,
  tone TEXT,
  contact_hint TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # M8 migration (noted in docs/phase-m8.md + docs/PLAN.md §M8):
    # assisted comment drafts (B1) — existing DBs get the column added
    cols = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
    if "comment_text" not in cols:
        conn.execute("ALTER TABLE requests ADD COLUMN comment_text TEXT")
        conn.commit()
    # M9 migration (noted in docs/PLAN.md §4): short purpose/topic label
    # ("crm", "booking site", "auto-reply bot") for /stats command
    if "topic" not in cols:
        conn.execute("ALTER TABLE requests ADD COLUMN topic TEXT")
        conn.commit()
    # M10 migration (noted in docs/phase-m10-auto-send.md §4, client-approved
    # 2026-11-06): approval-gated auto-send — suggested_price shown pre-✅
    # (pricing_tiers match) and consumed by senders; send_mode 'auto'|'assist'
    # (NULL = legacy manual copy); send_log = audit trail, one row per attempt
    cols = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
    for col in ("suggested_price", "send_mode"):
        if col not in cols:
            conn.execute(f"ALTER TABLE requests ADD COLUMN {col} TEXT")
            conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS send_log (
        id INTEGER PRIMARY KEY,
        request_id INTEGER REFERENCES requests(id),
        platform TEXT NOT NULL,
        mode TEXT NOT NULL,
        outcome TEXT NOT NULL,
        screenshot_path TEXT,
        error TEXT,
        attempted_at TEXT DEFAULT (datetime('now')))""")
    conn.commit()
    return conn
