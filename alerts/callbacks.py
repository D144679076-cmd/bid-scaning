"""Telegram callback poller (M2). Cron-friendly: one cold batch per run,
stateless via offset file + flock guard (no overlap between runs).

Button data: approve:<id> / reject:<id> / open:<id> (open = url button, no callback).
Actions per AGENTS.md: approve → status 'approved' (send is always manual);
reject → status 'archived'. Edit flow arrives in M3.
"""

import fcntl
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as Config
from db import connect
from alerts import telegram


def poll_once(conn, token: str) -> int:
    state_file = Path("data/tg_offset.json")
    state_file.parent.mkdir(exist_ok=True)
    offset = 0
    if state_file.exists():
        try:
            offset = json.loads(state_file.read_text()).get("offset", 0)
        except json.JSONDecodeError:
            offset = 0

    resp = telegram.call_api(token, "getUpdates",
                             {"offset": offset, "timeout": 25,
                              "allowed_updates": ["callback_query"]})
    if not resp.get("ok"):
        return 0
    updates = resp.get("result", [])
    handled = 0
    new_offset = offset
    for upd in updates:
        new_offset = upd["update_id"] + 1
        cb = upd.get("callback_query")
        if not cb or not cb.get("data"):
            continue
        data = cb["data"].split(":")
        if len(data) != 2 or data[0] not in ("approve", "reject"):
            continue
        request_id = int(data[1])
        status = "approved" if data[0] == "approve" else "archived"
        cur = conn.execute(
            """UPDATE requests SET status = ?
               WHERE id = ? AND status = 'lead'""",
            (status, request_id))
        conn.commit()
        label = "✅ Approved — next: draft & manual send" if status == "approved" \
            else "❌ Rejected — archived"
        try:
            telegram.call_api(token, "answerCallbackQuery", {
                "callback_query_id": cb.get("id"), "text": label,
                "show_alert": False})
        except Exception:
            pass
        handled += 1
    if new_offset != offset:
        state_file.write_text(json.dumps({"offset": new_offset}))
    return handled


def main() -> int:
    Config.load_env()
    token = os.environ.get("TG_TOKEN", "")
    if not token:
        print("no TG_TOKEN", file=sys.stderr)
        return 1
    cfg = Config.load_config()
    conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
    lock = Path("data/callbacks.lock")
    lock.parent.mkdir(exist_ok=True)
    with open(lock, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another poller running")
            return 0
        try:
            done = poll_once(conn, token)
            print({"handled": done})
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
