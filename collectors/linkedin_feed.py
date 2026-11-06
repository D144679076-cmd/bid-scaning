"""LinkedIn feed collector (M5). Playwright, feed VIEW ONLY, storageState.

LinkedIn obfuscates DOM classes — extraction works on the rendered text:
main-feed entries are delimited by "Feed post" marker lines. Read-only:
never interact, comment, connect, or message. storageState from
collectors/session_linkedin.py (one-time manual login).
"""

import random
import sys
import time

from playwright.sync_api import (sync_playwright, Error as PWError,
                                 TimeoutError as PWTimeout)

import config as Config
from pipeline import safety

SEARCH_URL = ("https://www.linkedin.com/search/results/content/"
              "?keywords={q}&sortBy=%22date_posted%22")


def _parse_posts(main_text: str, base_url: str) -> list[dict]:
    """'Feed post' delimiters → post chunks; drop nav chrome lines."""
    import hashlib
    parts = [p for p in main_text.split("Feed post") if p.strip()]
    out = []
    for chunk in parts[1:]:  # chunk[0]: page nav header
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        junk = ("Skip to", "HomeNetworkJobs", "All filters", "Reset", "/ ")
        lines = [l for l in lines if not any(
            l.startswith(j) or l == j for j in junk)]  # basic cleanup
        body = "\n".join(lines)
        if len(body) < 60:
            continue
        # M9 dedup fix (same bug chain as FB): all posts previously shared
        # the search URL → url UNIQUE kept max 1 row/cycle. Per-post
        # pseudo-URL keyed by text hash keeps re-seen text deduped.
        post_url = (base_url + "?p="
                    + hashlib.sha1(body.encode("utf-8")).hexdigest()[:12])
        out.append({
            "source": "linkedin",
            "url": post_url,  # per-post dedup key; permalink needs DOM
            "author": lines[0][:60] if lines else "",
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "raw_text": body[:3000],
        })
    return out


def collect_linkedin(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("linkedin", {})
    if not src.get("enabled", False) or safety.branch_paused("linkedin"):
        return []
    state = safety.load_state_file(
        src.get("state_file", "data/session_linkedin.json"))
    if not state and src.get("require_session", True):
        return []  # login-only platform: must run manual login first
    q = src.get("search_query",
                '"looking for" ("automation" OR "scraper" OR "developer")')
    url = SEARCH_URL.format(q=q.replace('"', '%22').replace(' ', '%20'))
    out: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state, **safety.launch_headless())
        page = ctx.new_page()
        try:
            page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(random.uniform(5, 8))
            # LinkedIn SPA: content() races mid-navigation (seen live
            # 2026-11-06) → small retry until DOM settles
            html = ""
            for _ in range(4):
                try:
                    html = page.content()
                    break
                except (PWError, PWTimeout):
                    time.sleep(3)
            if not html:
                print("[warn] linkedin: page never settled for content()")
                return []
            if safety.is_loginwall(html):
                kb = safety.hit_loginwall("linkedin")
                print(f"[warn] li login-wall {kb['hits']}/2 paused={kb['paused']}")
                return []
            page.mouse.wheel(0, 2200)
            time.sleep(random.uniform(2, 4))
            text = page.locator("main").inner_text()
            out.extend(_parse_posts(text, url))
        except (PWTimeout, OSError, ValueError) as exc:
            print(f"[warn] linkedin: {exc}")
        finally:
            browser.close()
    return out


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    items = collect_linkedin(cfg)
    print(f"collected: {len(items)}")
    for it in items[:4]:
        print("-", it["author"], "|", it["raw_text"][:70].replace("\n", " / "))
