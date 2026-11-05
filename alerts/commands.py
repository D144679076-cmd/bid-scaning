"""Telegram slash commands (M9 2026-11-05). Handled inside the callbacks
poller (cold batch every 30 s — commands may take up to 30 s to react;
by design).

Commands (owner-only, from TG_OWNER_ID):
  /scan    → run one pipeline cycle now (flock-guarded, never overlaps timer run)
  /pause   → stop scheduled cycles (flag file; /scan still works)
  /resume  → re-enable scheduled cycles
  /status  → DB counts, pause state, last run + PER-SOURCE token/session health
  /digest  → send the daily digest now
  /db      → current contents of the DB (rows per source × status, last 24 h)
  /quota   → show/set per-source quotas: /quota <src> <n|0=mute> ·
             /quota <src> cap <n> (per-cycle collector cap)
  /filter  → show/add/remove freelancer require/reject words:
             /filter add reject "video editor" promo · /filter del require bot

Quotas and filter words land in data/source_overrides.json (runtime
override of config.yaml — nothing in config.yaml is edited). Send is always
to the chat the command came from (group "Agent Control").

Compliance per AGENTS.md: read-only collectors, no auto-send of bids —
unchanged; commands only tune thresholds and read state.
"""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alerts import telegram  # noqa: E402
from pipeline import source_state  # noqa: E402

PAUSE_FLAG = ROOT / "data" / "scan_paused.json"
LOGS = ROOT / "data" / "logs"
CMDS = ["scan", "pause", "resume", "status", "digest",
        "quota", "filter", "db"]


def _owner_ok(msg: dict) -> bool:
    owner = os.environ.get("TG_OWNER_ID", "")
    if not owner:  # no owner configured → commands disabled, fail safe
        return False
    return str((msg.get("from") or {}).get("id", "")) == owner


def _is_paused() -> bool:
    return PAUSE_FLAG.exists()


def _spawn(args: list[str]) -> None:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / "commands.log", "ab")
    subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)


def _pipeline_busy() -> bool:
    import fcntl
    lock = ROOT / "data" / "runner.lock"
    lock.parent.mkdir(exist_ok=True)
    fh = open(lock, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        fh.close()


def _db_counts(conn) -> dict:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM requests GROUP BY status ORDER BY 2 DESC")}


def _cmd_scan(token: str, chat_id: str) -> str:
    if _is_paused():
        return ("⏸️ Scanner is paused — /resume first "
                "(manual /scan is blocked while paused)")
    if _pipeline_busy():
        return "ℹ️ A scan is already running — wait for it to finish"
    _spawn([sys.executable, str(ROOT / "run_pipeline.py")])
    return "🔄 Scan started now (LLM classify takes a few minutes)."


def _cmd_pause(token: str, chat_id: str) -> str:
    if _is_paused():
        return "⏸️ Already paused."
    PAUSE_FLAG.write_text(json.dumps(
        {"paused_at": time.strftime("%Y-%m-%d %H:%M:%S")}))
    return ("⏸️ Scheduled scans paused. Buttons/digest keep working; "
            "/resume to re-enable (/scan stays blocked while paused).")


def _cmd_resume(token: str, chat_id: str) -> str:
    if not _is_paused():
        return "▶️ Not paused."
    PAUSE_FLAG.unlink()
    return ("▶️ Resumed. Next scheduled cycle at the 3 h timer "
            "(or /scan for one now).")


def _cmd_status(token: str, chat_id: str, conn) -> str:
    counts = _db_counts(conn)
    last = conn.execute(
        "SELECT MAX(sent_at) FROM requests WHERE sent_at IS NOT NULL").fetchone()[0]
    import config as Config
    cfg = Config.load_config()
    lines = ["📊 bid-scan status",
             f"paused: {'yes ⏸️' if _is_paused() else 'no'}",
             f"DB: {counts or 'empty'}",
             f"last alert sent: {last or 'never'}",
             f"scan cadence: every 3 h (timer)"]
    log = LOGS / "pipeline.log"
    if log.exists():
        age_min = int((time.time() - log.stat().st_mtime) / 60)
        lines.append(f"last pipeline log: {age_min} min ago")
    lines.extend(["── sources (last collect · quota alerts · token)"])
    lines.extend(source_state.token_report(conn, cfg))
    lines.append("(* = default quota 3 — set with /quota <src> <n>)")
    return "\n".join(lines)


def _cmd_quota(token: str, chat_id: str, args: list[str]) -> str:
    """/quota — show; /quota <src> <n> — alerts-per-cycle (0 = mute);
    /quota <src> cap <n> — collector items per cycle."""
    srcs = ("reddit", "make", "facebook", "upwork", "freelancer", "linkedin")
    if not args:
        ovr = source_state.load_overrides()
        lines = ["⚖️ per-source quotas (0 = muted)"]
        for s in srcs:
            a = ovr["alerts_per_cycle"].get(s, "default(3)")
            c = ovr["max_items"].get(s, "no cap")
            lines.append(f"{s}: {a} alerts · cap {c}")
        return "\n".join(lines)
    src = args[0].lower().rstrip(":")
    if src not in srcs:
        return f"⚠️ unknown source '{src}' — one of: {', '.join(srcs)}"
    if len(args) >= 3 and args[1].lower() in ("cap", "max"):
        try:
            n = max(0, int(args[2]))
        except ValueError:
            return "⚠️ usage: /quota <src> cap <n>"
        ovr = source_state.quota(src, max_n=n)
        return f"✅ {src} collector cap = {n} per cycle"
    try:
        n = max(0, int(args[1]))
    except (ValueError, IndexError):
        return ("⚠️ usage: /quota [<src> <n|0=mute>] or "
                "/quota [<src> cap <n>]")
    source_state.quota(src, alerts_n=n)
    return (f"✅ {src} alert quota = {n} per cycle"
            if n else f"🔇 {src} muted (0 alerts; collection continues)")


def _cmd_filter(token: str, chat_id: str, args: list[str]) -> str:
    """/filter — show freelancer effective word lists;
    /filter add|del require|reject <word...>  (quotes group phrases)."""
    def _show() -> str:
        import config as Config
        cfg = Config.load_config()
        fsrc = cfg.get("sources", {}).get("freelancer", {})
        add = source_state.load_overrides()["filter_add"]
        lines = ["🧹 freelancer filter words"]
        for side in ("require", "reject"):
            base = list(fsrc.get(f"{side}_keywords") or [])
            extra = [w for w in add[side]
                     if w.lower() not in [x.lower() for x in base]]
            mark = lambda w: (" (added)" if w in extra else "")
            words = " ".join(w + mark(w) for w in base + extra) or "∅"
            lines.append(f"{side}: {words}")
        lines.append('set: /filter add reject "video editor" · /filter del require bot')
        return "\n".join(lines)
    if not args:
        return _show()
    if len(args) < 3 or args[0] not in ("add", "del") \
            or args[1] not in ("require", "reject"):
        return ("⚠️ usage: /filter add|del require|reject <words...> "
                "(quotes group multi-word phrases)")
    action, side = args[0], args[1]
    words = [w for w in shlex.split(" ".join(args[2:])) if w]
    if not words:
        return "⚠️ no words given — nothing changed"
    ovr = source_state.filter_words(require=words if side == "require"
                                    else None,
                                    reject=words if side == "reject"
                                    else None,
                                    require_del=words if action == "del"
                                    and side == "require" else None,
                                    reject_del=words if action == "del"
                                    and side == "reject" else None)
    # del removes from overrides; a del of a base config word can't touch
    # config.yaml from runtime — report honestly
    if action == "del":
        note = ("\nℹ️ del only removes runtime-added words; "
                "config.yaml base words stay (edit config.yaml for those)")
    else:
        note = ""
    return (f"✅ {side} {action}: {', '.join(words)} (applies next "
            f"collector cycle){note}")


def _cmd_digest(token: str, chat_id: str) -> str:
    _spawn([sys.executable, "-m", "alerts.digest"])
    return "📨 Digest triggered (low-score backlog, sorted by score)."


def _cmd_db(token: str, chat_id: str, conn) -> str:
    return "\n".join(source_state.db_report(conn))


def handle_message(token: str, msg: dict, conn) -> bool:
    """Handle one /command message. Returns True if consumed."""
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return False
    parts = text[1:].split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]
    if cmd not in CMDS:
        return False
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    if not _owner_ok(msg):
        return True  # consume but ignore — owner-only commands
    if cmd == "status":
        reply = _cmd_status(token, chat_id, conn)
    elif cmd == "db":
        reply = _cmd_db(token, chat_id, conn)
    elif cmd == "quota":
        reply = _cmd_quota(token, chat_id, args)
    elif cmd == "filter":
        reply = _cmd_filter(token, chat_id, args)
    else:
        reply = {
            "scan": _cmd_scan,
            "pause": _cmd_pause,
            "resume": _cmd_resume,
            "digest": _cmd_digest,
        }[cmd](token, chat_id)
    try:
        telegram.send(token, chat_id, reply)
    except Exception as exc:
        print(f"[warn] commands reply: {exc}", flush=True)
    return True
