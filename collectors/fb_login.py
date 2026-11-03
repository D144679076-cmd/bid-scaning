"""One-time manual Facebook login → storageState. AUTO-SAVES when login
detected (no manual Enter needed, no timeout kill): polls c_user cookie
every 2 s; saves + closes browser the moment the session exists.

    python3 -m collectors.fb_login

NO passwords stored — only cookies in data/session_facebook.json.
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config as Config
from pipeline import safety


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    src = cfg.get("sources", {}).get("facebook", {})
    storage = src.get("state_file", "data/session_facebook.json")
    print("Browser opening — log in Facebook inside the window…", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        page.goto("https://www.facebook.com/login")
        deadline = time.time() + 30 * 60  # up to 30 min for the human
        while time.time() < deadline:
            time.sleep(2)
            try:
                cookies = ctx.cookies()
            except OSError:
                break
            if any(c["name"] in ("c_user", "xs") for c in cookies):
                break
        else:
            print("No login in 30 min — closing.", flush=True)
            browser.close()
            return 1
        try:
            page.goto(src.get("base_url", "https://www.facebook.com"), timeout=45_000)
            time.sleep(3)
            if safety.is_loginwall(page.content()):
                print("[warn] login-wall still shown — saving anyway "
                      "(kill-switch will guard the collector)", flush=True)
        except OSError as exc:
            print(f"[warn] feed check skipped: {exc}", flush=True)
        ctx.storage_state(path=storage)
        browser.close()
    print(f"OK — storageState written → {storage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
