"""One-time manual LinkedIn login → storageState. Auto-saves on li_at poll.

    python3 -m collectors.session_linkedin
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config as Config
from pipeline import safety


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    storage = cfg.get("sources", {}).get("linkedin", {}).get(
        "state_file", "data/session_linkedin.json")
    print("Browser opening — log in LinkedIn inside the window…", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/login")
        deadline = time.time() + 30 * 60
        while time.time() < deadline:
            time.sleep(2)
            if any(c["name"] == "li_at" for c in ctx.cookies()):
                break
        else:
            print("No LinkedIn login in 30 min — closing.", flush=True)
            browser.close()
            return 1
        try:
            page.goto("https://www.linkedin.com/feed/", timeout=45_000)
            time.sleep(3)
        except OSError:
            pass
        ctx.storage_state(path=storage)
        browser.close()
    print(f"OK — storageState written → {storage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
