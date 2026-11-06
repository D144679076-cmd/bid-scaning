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
from alerts import stats as Stats


QUERY = """SELECT id, score, task_type, topic, budget, url,
                  substr(replace(raw_text, char(10), ' '), 1, 80) AS snippet
           FROM requests
           WHERE status = 'low'
           ORDER BY score DESC, id DESC
           LIMIT ?"""


def build_digest(conn: sqlite3.Connection, max_low: int) -> str:
    rows = conn.execute(QUERY, (max_low,)).fetchall()
    t = Stats.totals(conn)
    stat_line = " · ".join(f"{s}: {n}" for s, n in t["by_status"].items())
    lines = [f"<b>📊 Daily digest</b> ({stat_line})"]
    groups = Stats.by_group(conn)
    tg, wg = groups[Stats.TOOL_GROUP], groups[Stats.WEB_GROUP]
    if tg + wg:
        lines.append(f"<b>Build mix</b>: tool-build {tg}"
                     f" · web-build {wg} ({100*wg//(tg+wg)}% web)")
    src_line = " · ".join(
        f"{s} {n}" for s, n, _ in Stats.by_source(conn, days=1))
    if src_line:
        lines.append(f"<b>collected 24h</b>: {src_line}")
    if not rows:
        lines.append("Low-score backlog: empty.")
    else:
        lines.append(f"<b>Low-score backlog ({len(rows)}, sorted by score)</b>:")
        for row in rows:
            topic = f"· {html.escape(row['topic'])}" if row["topic"] else ""
            lines.append(
                f"• <b>{row['score']}</b> — {html.escape(row['task_type'] or '')}"
                f"{topic} {html.escape(row['snippet'])}\n"
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
