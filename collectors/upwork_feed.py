"""Upwork / Freelancer jobs feed (M5). Playwright, FEED VIEW ONLY.

HARD RULE (AGENTS.md): never submit proposals via code — this collector
only scrolls public project search listings and extracts texts; the alert
message gives the link + draft, ALL sending is manual.

Works for both marketplaces (login-wall tolerated → items just stop when
wall appears; kill-switch after 2 wall hits per safety.py).
"""

import random
import re
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety

JOBS_RE = re.compile(
    r"(?i)(looking for|need|hire|build me|help with|develop|automate)[^.!?]{10,220}[.!?]")


def _extract(text: str, base_url: str, source: str) -> list[dict]:
    items = []
    # Job cards rendered as paragraphs/sentences; keep pos-shaped fragments
    for sent in JOBS_RE.findall(text):
        sent = sent.strip()
        if len(sent) < 40:
            continue
        items.append({
            "source": source,
            "url": base_url,
            "author": "",
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "raw_text": sent[:3000],
        })
    return items


def _collect_loginless(cfg, source: str, search_url: str) -> list[dict]:
    src = cfg.get("sources", {}).get(source, {})
    if not src.get("enabled", False) or safety.branch_paused(source):
        return []
    query = src.get("search_query", "")
    url = search_url.format(q=query.replace(" ", "+"))
    out: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for attempt, ua_vp in ([1], [2]):  # one retry
            try:
                ctx = browser.new_context(**safety.launch_headless())
                page = ctx.new_page()
                page.goto(url, timeout=60_000, wait_until="domcontentloaded")
                time.sleep(random.uniform(4, 8))
                html = page.content()
                if safety.is_loginwall(html):
                    kb = safety.hit_loginwall(source)
                    print(f"[warn] {source} login-wall {kb['hits']}/2 paused={kb['paused']}")
                    continue
                # scroll once for lazy-load, then read text
                page.mouse.wheel(0, 2000)
                time.sleep(random.uniform(2, 4))
                out = _extract(page.inner_text("body"), url, source)
                ctx.close()
            except (PWTimeout, OSError, KeyError) as exc:
                print(f"[warn] {source}: {exc}")
            else:
                break
        browser.close()
    return out


def collect_upwork(cfg: dict) -> list[dict]:
    return _collect_loginless(
        cfg, "upwork",
        "https://www.upwork.com/nx/search/jobs/?q={q}&sort=recency")


def collect_freelancer(cfg: dict) -> list[dict]:
    return _collect_loginless(
        cfg, "freelancer",
        "https://www.freelancer.com/search/users?keyword={q}")


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    for name, fn in (("upwork", collect_upwork), ("freelancer", collect_freelancer)):
        items = fn(cfg)
        print(f"{name}: collected {len(items)}")
        for it in items[:3]:
            print("-", it["raw_text"][:80].replace("\n", " / "))
