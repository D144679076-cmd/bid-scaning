"""One-time manual Facebook login → Playwright storageState (M4).

Human logs in interactively (own session, non-main account per plan).
NO passwords stored, ever — the session cookies land only in
data/session_facebook.json (gitignored). Run manually:

    python3 -m collectors.fb_login

After success the collector uses the session read-only for 2–4 h/group polls.
"""

import sys

from playwright.sync_api import sync_playwright

from db import connect  # config wiring parity
import config as Config
from pipeline import safety


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    storage = cfg.get("sources", {}).get("facebook", {}).get(
        "state_file", "data/session_facebook.json")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        page.goto("https://www.facebook.com/login")
        print("Log in manually in the opened browser window…")
        page.wait_for_url("**/facebook.com/**", timeout=300_000)
        # confirm session: check a feed page renders without login-wall
        page.goto(cfg.get("sources", {}).get("facebook", {}).get(
            "base_url", "https://www.facebook.com"))
        if safety.is_loginwall(page.content()):
            print("login-wall detected — session may be restricted; "
                  "stored anyway, kill-switch will guard")
        ctx.storage_state(path=storage)
        browser.close()
    print(f"storageState written → {storage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
