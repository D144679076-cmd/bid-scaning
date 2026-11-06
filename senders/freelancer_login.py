"""One-time manual Freelancer login → storageState (M10a sender prep).

Manual browser window; auto-saves the moment logged-in cookies are
detected. NO password ever stored — data/session_freelancer.json only.

    python3 senders/freelancer_login.py
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config as Config
from pipeline import safety

# Freelancer logged-in cookie markers (checked like fb_login c_user/xs)
LOGIN_COOKIES = ("autologin[hidden]",)

DETECT_URL = "https://www.freelancer.com/"


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    src = cfg.get("senders", {}).get("freelancer", {}) or {}
    storage = src.get("state_file", "data/session_freelancer.json")
    print("Browser opening — log in Freelancer inside the window…", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        page.goto("https://www.freelancer.com/log-in", timeout=45_000)
        deadline = time.time() + 30 * 60
        logged = False
        while time.time() < deadline:
            time.sleep(2)
            try:
                cookies = ctx.cookies(DETECT_URL)
            except OSError:
                break
            # 'autologin[hidden]' = freelancer.com persistent session marker;
            # fallback: any 'uas' cookie family
            if any(c["name"].startswith("autologin") for c in cookies) \
                    or any(c["name"] == "uas" for c in cookies):
                logged = True
                break
        if not logged:
            print("No login in 30 min — closing without saving.", flush=True)
            browser.close()
            return 1
        try:
            page.goto(DETECT_URL, timeout=45_000)
            time.sleep(3)
            if safety.is_loginwall(page.content()):
                print("[warn] login-wall still shown — saving anyway "
                      "(sender killswitch will guard the flow)", flush=True)
        except OSError as exc:
            print(f"[warn] feed check skipped: {exc}", flush=True)
        ctx.storage_state(path=storage)
        browser.close()
    print(f"OK — storageState written → {storage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
