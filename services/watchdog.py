"""M6 watchdog (*/10 min). Health of the self-running app → Telegram.

Checks (fail = fix attempt + TG alert to the owner):
1. ollama /api/version reachable — restart attempt once, alert if still down
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
OLLAMA_URL = "http://localhost:11434/api/version"
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


def check_ollama(st) -> str:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=5) as r:
            json.loads(r.read().decode())
        return "ollama ok"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        # one restart attempt (local binary, same env as dev usage)
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


def run() -> int:
    Config.load_env()
    cfg = Config.load_config()
    st_path = STATE
    st = _load_state()
    msgs = []
    o = check_ollama(st)
    if "ok" not in o:
        msgs.append(o)
    msgs.extend(check_sessions(cfg, st))
    stale = check_log_freshness(st)
    if stale:
        msgs.append(stale)
    msgs.extend(check_disk_mem(st))
    _save_state(st)
    for m in msgs:
        _alert(cfg, f"[bid-scan watchdog] {m}")
        print("ALERT:", m)
    print(msgs or ["all healthy"])
    return 0 if not msgs else 1


if __name__ == "__main__":
    sys.exit(run())
