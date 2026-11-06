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
from alerts import commands, telegram


def poll_once(conn, token: str) -> int:
    state_file = Path("data/tg_offset.json")
    state_file.parent.mkdir(exist_ok=True)
    offset = 0
    if state_file.exists():
        try:
            offset = json.loads(state_file.read_text()).get("offset", 0)
        except json.JSONDecodeError:
            offset = 0

    # Telegram long-poll: a temporary network error must not kill the run
    # (offset file stays untouched → same updates fetched next run)
    try:
        resp = telegram.call_api(token, "getUpdates",
                                 {"offset": offset, "timeout": 25,
                                  "allowed_updates": ["callback_query", "message"]})
    except Exception as exc:
        print(f"[warn] getUpdates failed: {exc}", flush=True)
        return 0
    if not resp.get("ok"):
        return 0
    updates = resp.get("result", [])
    handled = 0
    new_offset = offset
    state_file2 = Path("data/editing.json")
    editing = json.loads(state_file2.read_text()) if state_file2.exists() else {}
    for upd in updates:
        new_offset = upd["update_id"] + 1
        # capture user's typed correction for an "edit" in progress (M2 store;
        # full re-draft flow lands in M3)
        msg = upd.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        # slash commands (/scan /pause /resume /status /digest) — before the
        # edit flow so a command is never stored as a draft correction
        if msg.get("text", "").startswith("/") and commands.handle_message(token, msg, conn):
            continue
        eid = editing.get(chat_id)
        if eid and msg.get("text"):
            conn.execute(
                "UPDATE requests SET draft_text = ?, status = 'edited' WHERE id = ?",
                (msg["text"], eid["request_id"]))
            conn.commit()
            state_file2.write_text(json.dumps({}))
            try:
                telegram.send(token, chat_id,
                              f"✏️ Note stored for request #{eid['request_id']} "
                              "(full re-draft lands in M3)")
            except Exception:
                pass
            editing.pop(chat_id, None)
            continue
        cb = upd.get("callback_query")
        if not cb or not cb.get("data"):
            continue
        data = cb["data"].split(":")
        if len(data) != 2 or data[0] not in ("approve", "reject", "edit"):
            continue
        request_id = int(data[1])
        status_map = {"approve": "approved", "reject": "archived", "edit": "editing"}
        status = status_map[data[0]]
        # M3+ rows arrive as 'drafted' (draft_stage runs before alerting) —
        # the old status='lead' gate silently swallowed every press
        cur = conn.execute(
            """UPDATE requests SET status = ?
               WHERE id = ? AND status IN ('lead', 'drafted')""",
            (status, request_id))
        conn.commit()
        if cur.rowcount == 0:  # honest toast: press matched no (editable) row
            row = conn.execute(
                "SELECT status FROM requests WHERE id = ?",
                (request_id,)).fetchone()
            real = row["status"] if row else "missing"
            label = (f"❌ {data[0]} skipped — request #{request_id} is "
                     f"{real}, not lead/drafted")
        else:
            if status == "editing":
                cbchat = str((cb.get("from") or {}).get("id", ""))
                editing[cbchat] = {"request_id": request_id}
                state_file2.write_text(json.dumps(editing))
            label = {"approve": "✅ Approved — copy the draft & send manually",
                     "reject": "❌ Rejected — archived",
                     "edit": "✏️ Send your corrected note as a reply in this chat"
                     }[data[0]]
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
