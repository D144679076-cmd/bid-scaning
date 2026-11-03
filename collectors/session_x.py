"""One-time manual X login with ANTI-STALL LOGIN DRIVE.

2026-11-03 finding: X's 'knowledge_check' anti-fraud step silently drops
typed input when the session UA doesn't match the browser binary (our UA
rotation flagged it; the Continue button stays grey/disabled).

This helper:
- NO custom User-Agent (consistent Chrome fingerprint)
- drives the username step itself (fill + click), then hands the window to
  the human for password / captcha / verification
- auto-saves storageState the moment auth_token cookie appears

    python3 -m collectors.session_x            # plain
    python3 -m collectors.session_x DuyNqqa    # drive username step
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config as Config
from pipeline import safety


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    storage = cfg.get("sources", {}).get("x", {}).get(
        "state_file", "data/session_x.json")
    username = sys.argv[1] if len(sys.argv) > 1 else None
    print("Browser opening — log in X inside the window…", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        # NO UA override — keep fingerprint consistent with the binary
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  locale="en-US")
        page = ctx.new_page()
        page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
        time.sleep(4)
        if username:
            try:
                # X flow may sit on a "Confirm your account" pre-step
                field = page.locator("input[name='text'], input[autocomplete*='username']").first
                field.wait_for(timeout=30_000)
                field.fill(username)
                time.sleep(1)
                for label in ("Next", "Continue"):
                    btn = page.get_by_role("button", name=label).first
                    if btn.count() and btn.is_enabled():
                        btn.click()
                        break
                print(f"[drive] username '{username}' submitted — "
                      "TYPE YOUR PASSWORD IN THE WINDOW NOW", flush=True)
            except OSError as exc:
                print(f"[drive] no username field to drive: {exc}", flush=True)
        # phone-verification driver: X shows signup_phone for unknown IPs;
        # human fills number, script presses Continue (real DOM click)
        phone_deadline = time.time() + 15 * 60
        while time.time() < phone_deadline:
            time.sleep(3)
            try:
                p_url = page.url
                p_title = page.title()
            except OSError:
                break
            if "signup_phone" in p_url or "account_phone" in p_url:
                try:
                    btn = page.get_by_role("button", name="Continue").first
                    if btn.count() and btn.is_enabled():
                        # wait until the user typed a number (field non-empty)
                        val = page.locator(
                            "input[type='tel'], input[name='phone_number']") \
                            .first.input_value()
                        if val and len(val) >= 8:
                            btn.click()
                            print("[drive] phone Continue pressed — "
                                  "wait for SMS and type the code",
                                  flush=True)
                            break
                except (OSError, KeyError):
                    continue
            else:
                break
        deadline = time.time() + 30 * 60
        while time.time() < deadline:
            time.sleep(2)
            try:
                cookies = ctx.cookies()
            except OSError:
                break
            if any(c["name"] == "auth_token" for c in cookies):
                break
            url = ""
            try:
                url = page.url
            except OSError:
                pass
            if "knowledge_check" in url and sys.stdin.isatty() is False:
                pass
        else:
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
