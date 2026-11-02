"""Daily digest (pulled forward from M5 per client decision 2026-11-02).

One TG message at send_hour: low-score backlog (status 'low') sorted by
score descending (AGENTS.md rule) + simple stats.
"""

import html
import os
import sys
from pathlib import Path
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as Config
from db import connect
from alerts import telegram


QUERY = """SELECT id, score, task_type, budget, url,
                  substr(replace(raw_text, char(10), ' '), 1, 80) AS snippet
           FROM requests
           WHERE status = 'low'
           ORDER BY score DESC, id DESC
           LIMIT ?"""


def build_digest(conn: sqlite3.Connection, max_low: int) -> str:
    rows = conn.execute(QUERY, (max_low,)).fetchall()
    counts = conn.execute(
        "SELECT status, COUNT(*) FROM requests GROUP BY status").fetchall()
    stat_line = " · ".join(f"{s}: {n}" for s, n in counts)
    lines = [f"<b>📊 Daily digest</b> ({stat_line})"]
    if not rows:
        lines.append("Low-score backlog: empty.")
    else:
        lines.append(f"<b>Low-score backlog ({len(rows)}, sorted by score)</b>:")
        for row in rows:
            lines.append(
                f"• <b>{row['score']}</b> — {html.escape(row['task_type'] or '')} "
                f"{html.escape(row['snippet'])}\n"
                + (f"💰 {html.escape(str(row['budget']))}\n" if row["budget"] else '')
                + f"🔗 {html.escape(row['url'])}"
            )
    return "\n".join(lines)


def main() -> int:
    Config.load_env()
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat:
        print("TG creds missing", file=sys.stderr)
        return 1
    cfg = Config.load_config()
    dcfg = cfg.get("digest", {})
    if not dcfg.get("enabled", True):
        return 0
    conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
    message = build_digest(conn, int(dcfg.get("max_low_items", 30)))
    # Repeated alerts become visible only once per day thanks to cron send_hour.
    telegram.send(token, chat, message)
    print({"digest": "sent", "len": len(message)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
