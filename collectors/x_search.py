"""X (Twitter) search collector (M5). Playwright, read-only search scrape.

Buying-intent phrase search per plan ("looking for someone to automate…"
etc.). Without a logged session nitter-less X shows limited results; a
storageState session (same pattern as FB) lifts the wall — run
collectors/session_x.py once. Read-only: no likes/posts/DMs, ever.
"""

import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety

INTENT_QUERY = ('("looking for a developer" OR "need help building" OR '
                '"someone to automate" OR "need a bot" OR "hire a developer") '
                '-filter:replies -filter:links')


def collect_x(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("x", {})
    if not src.get("enabled", False) or safety.branch_paused("x"):
        return []
    url = ("https://x.com/search?q=" + INTENT_QUERY.replace(" ", "%20")
           + "&f=live")
    state = safety.load_state_file(cfg.get("sources", {}).get("x", {}).get(
        "state_file", "data/session_x.json"))
    use_state = bool(src.get("use_session", True)) and state is not None
    out: list[dict] = []
    with sync_playwright() as pw:
        # headful: X 403-blocks the bare headless fingerprint (2026-11-03)
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=state, **safety.launch_headless()) \
            if use_state else None
        ctx = ctx or browser.new_context(**safety.launch_headless())
        page = ctx.new_page()
        try:
            page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(random.uniform(4, 8))
            if safety.is_loginwall(page.content()):
                kb = safety.hit_loginwall("x")
                print(f"[warn] x login-wall {kb['hits']}/2 paused={kb['paused']}")
                return []
            page.mouse.wheel(0, 2500)
            time.sleep(random.uniform(2, 4))
            articles = page.query_selector_all("article")
            for art in articles[:40]:
                try:
                    txt = (art.inner_text() or "").strip()
                    if "·" not in txt or len(txt) < 30:
                        continue
                    # tweet body: first multiline block after the handle line
                    lines = [l for l in txt.splitlines()
                             if l and "·" not in l and not l.startswith("@")]
                    body = lines[1] if len(lines) > 1 else lines[0]
                    items_href = art.query_selector("a[href*='/status/']")
                    href = items_href.get_attribute("href") if items_href else None
                    out.append({
                        "source": "x",
                        "url": "https://x.com" + href if href else url,
                        "author": (lines[0].lstrip("@") if lines else ""),
                        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "raw_text": body[:3000],
                    })
                except (OSError, KeyError, AttributeError) as exc:
                    print(f"[warn] x article: {exc}")
        except (PWTimeout, OSError) as exc:
            print(f"[warn] x search: {exc}")
        finally:
            browser.close()
    return out


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    items = collect_x(cfg)
    print(f"collected: {len(items)}")
    for it in items[:3]:
        print("-", it["url"], "|", it["raw_text"][:70].replace("\n", " / "))
