"""Per-source runtime state (M9). One module, three jobs:

1. Record — run_pipeline saves each collector's cycle result to
   data/source_state.json so /status and `bidscan status` can show how
   fresh every branch is.
2. Token/session report — per source: last collect + age, session
   storageState file health (facebook/linkedin/x), login-wall killswitch
   paused state, RSS-collector branches marked "n/a (public)".
3. Overrides — data/source_overrides.json holds runtime settings the owner
   edits from Telegram (/quota, /filter). config.yaml stays the
   authoritative default; overrides win when present.

No DB schema change: state lives in data/*.json (WAL schema untouched).
Secrets: never written here — token files are storageState only (M4 rule).
"""

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_FILE = DATA / "source_state.json"
OVERRIDES_FILE = DATA / "source_overrides.json"

# what the token column of the /status report means per source
SESSION_FILES = {
    "facebook": "session_facebook.json",
    "linkedin": "session_linkedin.json",
    "x": "session_x.json",
}

DEFAULTS = {
    "alerts_per_cycle": {},   # source → int; missing = config default (3)
    "max_items": {},          # source → int; per-cycle collector cap
    "filter_add": {"require": [], "reject": []},  # freelancer keyword adds
}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def record(counts: dict) -> None:
    """run_pipeline: {source: count} collected this cycle → fresh state."""
    state = _read(STATE_FILE, {})
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for src, n in counts.items():
        prev = state.get(src) or {}
        state[src] = {"ts": now, "count": int(n)} if n else {
            "ts": prev.get("ts", "?"), "count": 0}
    state["_updated"] = now
    DATA.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1))


# --- overrides ----------------------------------------------------------

def load_overrides() -> dict:
    ovr = _read(OVERRIDES_FILE, {})
    merged = json.loads(json.dumps(DEFAULTS))  # deep-enough copy
    if ovr:
        for k in ("alerts_per_cycle", "max_items"):
            if isinstance(ovr.get(k), dict):
                merged[k].update({s: int(v) for s, v in ovr[k].items()})
        fa = ovr.get("filter_add") or {}
        for side in ("require", "reject"):
            if isinstance(fa.get(side), list):
                merged["filter_add"][side] = [str(w) for w in fa[side]]
    return merged


def save_overrides(ovr: dict) -> None:
    DATA.mkdir(exist_ok=True)
    OVERRIDES_FILE.write_text(json.dumps(ovr, indent=1))


def quota(source: str, alerts_n: int | None = None,
          max_n: int | None = None) -> dict:
    """Set or read per-source quotas; returns the full override state."""
    ovr = load_overrides()
    if alerts_n is not None:
        ovr["alerts_per_cycle"][source] = alerts_n
    if max_n is not None:
        ovr["max_items"][source] = max_n
    if alerts_n is not None or max_n is not None:
        save_overrides(ovr)
    return ovr


def filter_words(require: list[str] | None = None,
                 reject: list[str] | None = None,
                 require_del: list[str] | None = None,
                 reject_del: list[str] | None = None) -> dict:
    """Apply freelancer require/reject word adds/dels to overrides."""
    ovr = load_overrides()
    fa = ovr["filter_add"]
    for words, bad in (((require or []), False), ((reject or []), True)):
        side = "reject" if bad else "require"
        for w in words:
            if w.lower() not in [x.lower() for x in fa[side]]:
                fa[side].append(w.lower())
    for side, words in (("require", require_del or []),
                        ("reject", reject_del or [])):
        fa[side] = [w for w in fa[side]
                    if w.lower() not in [x.lower() for x in words]]
    save_overrides(ovr)
    return ovr


# --- reports ------------------------------------------------------------

def _age(ts: str | None) -> str:
    """Humanized '3min / 5h / 2d ago' for a 'YYYY-MM-DD HH:MM:SS' stamp."""
    if not ts:
        return "?"
    try:
        delta = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S")) \
            - time.time()
    except (ValueError, OverflowError):
        return ts
    mins = abs(int(delta)) // 60
    if mins < 1:
        return "<1min"
    for div, unit in ((1440, "d"), (60, "h"), (1, "min")):
        if mins >= div:
            return f"{mins // div}{unit} ago"
    return "?"


def token_report(conn: sqlite3.Connection, cfg: dict) -> list[str]:
    """Per-source health for /status + `bidscan status`."""
    state = _read(STATE_FILE, {})
    ok_kill = _read(DATA / "killswitch.json", {})
    mutes = load_overrides().get("alerts_per_cycle", {})
    lines = []
    for src in ("reddit", "make", "facebook", "upwork", "freelancer",
                "linkedin", "x"):
        conf = (cfg.get("sources", {}).get(src) or {})
        if conf.get("enabled") is False:
            lines.append(f"{src}: disabled off")
            continue
        st = state.get(src) or {}
        last = f"{_age(st.get('ts'))} · {st.get('count', 0)} fresh"
        q = mutes.get(src)
        quota_s = "🔇" if q == 0 else f"{q} alerts ✓" if q else "*"
        parts = []
        session = SESSION_FILES.get(src)
        if session:
            p = DATA / session
            if not p.exists():
                parts.append("❌ no session file")
            else:
                mod_time = time.strftime(
                    "%y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
                parts.append(f"🔑 storageState {mod_time}")
        else:
            parts.append("📤 public/RSS no-token")
        if (ok_kill.get(src) or {}).get("paused"):
            parts.append("🚨 paused (login-wall killswitch)")
        if conf.get("require_session") and not session:
            parts.append("⚠️ session required")
        lines.append(f"{src}: {last} · {quota_s} · {' · '.join(parts)}")
    import os
    if os.environ.get("LLM_API_KEY"):
        lines.append("llm: 🔑 LLM_API_KEY set (cloud)")
    return lines


def db_report(conn: sqlite3.Connection) -> list[str]:
    """Current content of the requests table, compact for Telegram."""
    rows = conn.execute(
        """SELECT source, status, COUNT(*) AS n
           FROM requests GROUP BY source, status""").fetchall()
    by_src: dict[str, dict[str, int]] = {}
    for r in rows:
        by_src.setdefault(r["source"], {})[r["status"]] = r["n"]
    lines = ["🗄️ DB contents (requests)"]
    last24 = conn.execute(
        "SELECT COUNT(*) AS n FROM requests "
        "WHERE created_at >= datetime('now','-1 day')").fetchone()["n"]
    for src, st in sorted(by_src.items(),
                          key=lambda kv: -sum(kv[1].values())):
        total = sum(st.values())
        last_post = conn.execute(
            "SELECT MAX(date(created_at)) FROM requests WHERE source=?",
            (src,)).fetchone()[0]
        detail = " ".join(f"{k}:{v}" for k, v in
                          sorted(st.items(), key=lambda kv: -kv[1]))
        lines.append(f"{src}: {total} rows ({last_post}) — {detail}")
    lines.append(f"last 24h new: {last24}")
    return lines
