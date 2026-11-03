"""One-time manual X login → storageState. Auto-saves on c_user/exists poll.

    python3 -m collectors.session_x
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config as Config
from pipeline import safety


def _wait_login(ctx, deadline) -> bool:
    while time.time() < deadline:
        time.sleep(2)
        for c in ctx.cookies():
            if c["name"] == "auth_token":
                return True
    return False


def main(username: str | None = None) -> int:
    Config.load_env()
    cfg = Config.load_config()
    storage = cfg.get("sources", {}).get("x", {}).get(
        "state_file", "data/session_x.json")
    print("Browser opening — log in X (twitter.com) inside the window…", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        page.goto("https://x.com/i/flow/login")
        if not _wait_login(ctx, time.time() + 30 * 60):
            print("No X login in 30 min — closing.", flush=True)
            browser.close()
            return 1
        try:
            page.goto("https://x.com/home", timeout=45_000)
            time.sleep(3)
        except OSError:
            pass
        ctx.storage_state(path=storage)
        browser.close()
    print(f"OK — storageState written → {storage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
