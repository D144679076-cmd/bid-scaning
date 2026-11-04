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
    return conn
