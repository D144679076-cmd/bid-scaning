"""M6 watchdog (*/10 min). Health of the self-running app → Telegram.

Checks (fail = fix attempt + TG alert to the owner):
1. ollama /api/version reachable — restart attempt once, alert if still down
   (2026-11-04: inside the app container ollama lives on the HOST — probe
   OLLAMA_BASE like llm/client.py does; restarting a localhost binary only
   makes sense when the URL actually is localhost)
2. session files parse + expected cookie names (fb: c_user/xs, li: li_at,
   x: auth_token) — expired/missing session → TG "log in again" nudge
   (only platform sources enabled in config)
3. cron.log freshness — mtime older than 20 min means the pipeline timer
   has not run (systemd user timer stuck) → TG alert
4. disk ≥ 500 MB free + memory ≥ 300 MB available

Idempotent: alerts deduped per check per 6 h (data/watchdog_state.json).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as Config  # noqa: E402
from alerts import telegram  # noqa: E402

STATE = ROOT / "data" / "watchdog_state.json"
LOG = ROOT / "data" / "cron.log"
ZERO_CYCLES_ALERT = 6  # M9 B4: 6 consecutive 0-fresh cycles → alert once
_ollama_base = os.environ.get("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
OLLAMA_URL = f"{_ollama_base}/api/version"
SESSION_COOKIE = {"facebook": ("c_user",), "linkedin": ("li_at",),
                  "x": ("auth_token",)}
ALERT_COOLDOWN = 6 * 3600


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st))


def _alert(cfg, text: str) -> None:
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    try:
        telegram.call_api(token, "sendMessage",
                          {"chat_id": chat, "text": text})
    except Exception as exc:
        print(f"[warn] watchdog TG: {exc}")


def _dedup_ok(st: dict, key: str) -> bool:
    """True if this alert is allowed now (cooldown 6 h per check)."""
    now = time.time()
    if now - float(st.get(key, 0)) < ALERT_COOLDOWN:
        return False
    st[key] = now
    return True


def check_ollama(cfg, st) -> str:
    llm = cfg.get("llm", {})
    if llm.get("active") == "cloud" and not llm.get("failover_enabled", True):
        return "llm cloud ok"  # cloud-only (2026-11-04): no local ollama to check/restart
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=5) as r:
            json.loads(r.read().decode())
        return "ollama ok"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        # one restart attempt — only possible when ollama is local; in the
        # container it lives on the host (OLLAMA_BASE) so just alert
        if "localhost" in OLLAMA_URL:
            env = dict(os.environ)
            env["OLLAMA_MODELS"] = os.path.expanduser("~/.local/opt/models")
            try:
                import subprocess
                subprocess.Popen(
                    [os.path.expanduser("~/.local/opt/bin/ollama"), "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            except OSError:
                pass
            time.sleep(5)
        try:
            with urllib.request.urlopen(OLLAMA_URL, timeout=5) as r:
                json.loads(r.read().decode())
            if _dedup_ok(st, "ollama_restart"):
                return "ollama was DOWN → restarted automatically"
        except Exception:
            if _dedup_ok(st, "ollama_down"):
                return ("🚨 ollama DOWN and restart failed — "
                        "classification falls back to local only")
        return "ollama recovering"
    return "ollama ok"


def check_sessions(cfg, st) -> list[str]:
    srcs = cfg.get("sources", {})
    out = []
    for plat, cookies in SESSION_COOKIE.items():
        src = srcs.get(plat, {})
        if not src.get("enabled"):
            continue
        f = ROOT / src.get("state_file", f"data/session_{plat}.json")
        if not f.exists():
            out.append(f"🚨 {plat}: NO session file — run: bidscan login "
                       f"{'fb' if plat == 'facebook' else plat}")
            continue
        missing = [c for c in cookies if c not in f.read_text()]
        if missing:
            out.append(f"🚨 {plat}: session expired ({missing[0]} gone) — "
                       "run: bidscan login "
                       f"{'fb' if plat == 'facebook' else plat}")
    return out


def check_log_freshness(st) -> str | None:
    if not LOG.exists():
        return None  # first boot, log not yet written
    age = time.time() - LOG.stat().st_mtime
    if age > 20 * 60 and _dedup_ok(st, "log_stale"):
        return (f"🚨 pipeline log stale ({int(age / 60)} min) — "
                "systemd timer may be stuck: bidscan status")
    return None


def check_disk_mem(st) -> list[str]:
    import shutil
    out = []
    free = shutil.disk_usage(ROOT).free
    if free < 500 * 1024 * 1024 and _dedup_ok(st, "disk_low"):
        out.append(f"🚨 disk low: {free // 1024 // 1024} MB free")
    mem = _mem_available_mb()
    if mem is not None and mem < 300 and _dedup_ok(st, "mem_low"):
        out.append(f"🚨 memory low: {mem} MB available")
    return out


def _mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def check_source_freshness(st) -> list[str]:
    """M9 B4 (client): a source collecting 0 fresh items for 6+ cycles in
    a row means a dead session / broken extraction — alert once at the
    threshold (dedup of repeats happens on the notifier side), never
    silent again (the 2026-11-04..05 FB silent-zero lesson)."""
    out = []
    try:
        state = json.loads((ROOT / "data" / "source_state.json")
                           .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    zeros = st.setdefault("zero_cycles", {})
    for src, info in state.items():
        if src.startswith("_") or not isinstance(info, dict):
            continue
        if int(info.get("count") or 0) == 0:
            zeros[src] = int(zeros.get(src, 0)) + 1
            if zeros[src] == ZERO_CYCLES_ALERT:
                out.append(
                    f"🚨 {src}: 0 fresh items for {zeros[src]} cycles — "
                    f"session or extraction looks dead: bidscan status")
        else:
            zeros.pop(src, None)
    return out


def run() -> int:
    Config.load_env()
    cfg = Config.load_config()
    st_path = STATE
    st = _load_state()
    msgs = []
    o = check_ollama(cfg, st)
    if "ok" not in o:
        msgs.append(o)
    msgs.extend(check_sessions(cfg, st))
    stale = check_log_freshness(st)
    if stale:
        msgs.append(stale)
    msgs.extend(check_disk_mem(st))
    msgs.extend(check_source_freshness(st))
    _save_state(st)
    for m in msgs:
        _alert(cfg, f"[bid-scan watchdog] {m}")
        print("ALERT:", m)
    print(msgs or ["all healthy"])
    return 0 if not msgs else 1


if __name__ == "__main__":
    sys.exit(run())
