"""LinkedIn feed collector (M5). Playwright, feed VIEW ONLY, storageState.

Plan: 'Postings view' — search results page for postings without wall in
many regions when logged out fails, so a storageState session is required
(collectors/session_linkedin.py — same one-time manual login pattern as
FB). Read-only: never interact, comment, connect, or message.
"""

import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety

SEARCH_URL = ("https://www.linkedin.com/search/results/content/"
              "?keywords={q}&sortBy=%22date_posted%22")


def collect_linkedin(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("linkedin", {})
    if not src.get("enabled", False) or safety.branch_paused("linkedin"):
        return []
    state = safety.load_state_file(cfg.get("sources", {}).get("linkedin", {}).get(
        "state_file", "data/session_linkedin.json"))
    if not state and src.get("require_session", True):
        return []  # login-only platform: must run manual login first
    q = src.get("search_query",
                '("looking for" AND ("automation" OR "scraper" OR "deeveloper"))')
    url = SEARCH_URL.format(q=q.replace('"', '%22'))
    out: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state, **safety.launch_headless())
        page = ctx.new_page()
        try:
            page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(random.uniform(4, 8))
            if safety.is_loginwall(page.content()):
                kb = safety.hit_loginwall("linkedin")
                print(f"[warn] li login-wall {kb['hits']}/2 paused={kb['paused']}")
                return []
            page.mouse.wheel(0, 2200)
            time.sleep(random.uniform(2, 4))
            posts = page.query_selector_all(
                "div.feed-shared-update-v2, div.entity-result")
            for post in posts[:30]:
                try:
                    txt = (post.inner_text() or "").strip()
                    if len(txt) < 80:
                        continue
                    link_el = post.query_selector("a[href*='/feed/'], a[href*='/posts/']")
                    href = link_el.get_attribute("href") if link_el else None
                    out.append({
                        "source": "linkedin",
                        "url": "https://www.linkedin.com" + href if href else url,
                        "author": "",
                        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "raw_text": txt[:3000],
                    })
                except (OSError, KeyError, AttributeError, ValueError) as exc:
                    print(f"[warn] li post: {exc}")
        except (PWTimeout, OSError) as exc:
            print(f"[warn] linkedin: {exc}")
        finally:
            browser.close()
    return out


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    items = collect_linkedin(cfg)
    print(f"collected: {len(items)}")
    for it in items[:3]:
        print("-", it["url"], "|", it["raw_text"][:70].replace("\n", " / "))
