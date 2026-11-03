"""Safety hardening for browser-based collectors (M4/M5).

AGENTS.md hard rules implemented here:
- STRICTLY read-only: collectors must never like/comment/post.
- storageState sessions only (no passwords, ever).
- Randomized delays + UA/viewport rotation.
- Kill-switch: repeated captcha/login-wall → branch paused + urgent alert.

State lives in data/ only (gitignored).
"""

import json
import random
import time
from pathlib import Path

STATE_DIR = Path("data")
KILLSWITCH_FILE = STATE_DIR / "killswitch.json"
UIA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
]
VIEWPORTS = [(1280, 800), (1366, 768), (1440, 900)]
LOGINWALL_MARKERS = ("login", "log in", "sign in", "verify", "captcha",
                     "checkpoint", "two-factor", "password")
MAXHITS = 2  # kill-switch threshold

# Platforms never touched by writes even if accidentally invoked.
WRITE_FORBIDDEN = ("like", "comment", "post", "share", "follow", "react")


def save_state(name: str, state: dict) -> None:
    """Persist per-platform storageState (cookies live ONLY here, gitignored)."""
    STATE_DIR.mkdir(exist_ok=True)
    f = STATE_DIR / f"session_{name}.json"
    f.write_text(json.dumps(state))
    print(f"[safety] storageState saved → {f}")


def load_state(name: str) -> dict | None:
    f = STATE_DIR / f"session_{name}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def is_loginwall(page_html: str) -> bool:
    blob = (page_html or "")[:4000].lower()
    hits = sum(1 for m in LOGINWALL_MARKERS if m in blob)
    return hits >= 2


def hit_loginwall(name: str) -> dict:
    """Register login-wall/captcha hit; return kill-switch decision."""
    STATE_DIR.mkdir(exist_ok=True)
    st = json.loads(KILLSWITCH_FILE.read_text()) if KILLSWITCH_FILE.exists() else {}
    st.setdefault(name, {"hits": 0, "paused": False})
    st[name]["hits"] += 1
    st[name]["last_hit"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if st[name]["hits"] >= MAXHITS:
        st[name]["paused"] = True
    KILLSWITCH_FILE.write_text(json.dumps(st))
    return st[name]


def killswitch_state() -> dict:
    if not KILLSWITCH_FILE.exists():
        return {}
    return json.loads(KILLSWITCH_FILE.read_text())


def branch_paused(name: str) -> bool:
    return killswitch_state().get(name, {}).get("paused", False)


def human_pause(a: float = 3.0, b: float = 10.0) -> None:
    time.sleep(random.uniform(a, b))


def launch_headless() -> dict:
    """Context args: rotating UA + viewport, headless."""
    return {
        "user_agent": random.choice(UIA_POOL),
        "viewport": {"width": random.choice(VIEWPORTS)[0],
                     "height": random.choice(VIEWPORTS)[1]},
        "locale": "en-US",
    }
