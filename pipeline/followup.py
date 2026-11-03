"""Follow-up tracker (M5). Cron: approved drafts with no follow-up in
24–48 h → Telegram reminder. Never auto-messages anyone on the platform —
reminds the OWNER (human) in the private chat only (AGENTS.md).

DB: existing `followups` table (db.py schema) — (request_id, due_at, done).
Reminder fires once per request (row inserted → marker).
"""

import datetime
import os
import sys
import time

import config as Config
from alerts import telegram
from db import connect

REMINDER_TEXT = """⏰ Follow-up nudge:
Request #{rid} ({source}) — approved draft is ready but no reply marked
after {hours} h. Check the thread and close the loop manually:
🔗 {url}

(button '❌' archives if it's dead)"""


def run(cfg: dict, conn) -> dict:
    f = cfg.get("followup", {})
    if not f.get("enabled", True):
        return {"reminded": 0}
    hours = float(f.get("after_hours", 24))
    cap = int(f.get("max_per_run", 5))
    cutoff = time.time() - hours * 3600
    # approved + alert-sent before cutoff, not already reminded
    rows = conn.execute(
        """SELECT r.id, r.source, r.url, r.sent_at
           FROM requests r
           LEFT JOIN followups fu ON fu.request_id = r.id
           WHERE r.status = 'approved' AND r.sent_at IS NOT NULL
             AND fu.request_id IS NULL
           ORDER BY r.sent_at ASC LIMIT ?""",
        (cap,),
    ).fetchall()
    sent = 0
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    for r in rows:
        ts = _ts(r["sent_at"])
        if ts is None or ts > cutoff:
            continue
        hours_waited = (time.time() - ts) / 3600
        text = REMINDER_TEXT.format(rid=r["id"], source=r["source"],
                                    hours=int(hours_waited), url=r["url"])
        try:
            telegram.call_api(token, "sendMessage",
                              {"chat_id": chat, "text": text})
        except Exception as exc:
            print(f"[warn] followup TG #{r['id']}: {exc}")
            continue
        conn.execute(
            "INSERT INTO followups (request_id, due_at, done) VALUES (?, ?, 0)",
            (r["id"], time.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        sent += 1
    return {"reminded": sent}


def _ts(value) -> float | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.datetime.strptime(str(value), fmt).timestamp()
        except ValueError:
            continue
    return None


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
    print(run(cfg, conn))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
