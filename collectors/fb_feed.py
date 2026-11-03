"""Facebook groups collector (M4). Playwright, READ-ONLY, allowlist only.

AGENTS.md/plan compliance:
- Own logged session via storageState only (collectors.fb_login).
- Never like/comment/post/DM — page interactions limited to scroll + read.
- Delays 3–10 s randomized, 1 poll per group per 2–4 h, UA/viewport rotation.
- Kill-switch: 2 captcha/login-wall hits → FB branch paused + urgent alert.
- Post items flow through the SAME pipeline (dedup → spam → payment → LLM).
"""

import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety
from collectors.make_forum import SKIP_MARKERS  # same de-noiser (M5 shared)


def _visible_articles(page) -> list[str]:
    """Post bodies from the group feed DOM (role=article elements)."""
    try:
        nodes = page.query_selector_all("div[role='article']")
    except PWTimeout:
        nodes = []
    out = []
    for n in nodes:
        try:
            txt = (n.inner_text() or "").strip()
        except (OSError, KeyError):
            continue
        # strip page-chrome lines ("Facebook" repeats, nav labels)
        lines = [l.strip() for l in txt.splitlines()
                 if l.strip() and l.strip().lower() != "facebook"]
        body = "\n".join(lines)
        if len(body) >= 40:
            out.append(body)
    return out


def _parse_feed(text: str, group_url: str) -> list[dict]:
    """Cheap text-wall parse: split posts, keep request-shaped quickies.

    Facebook post DOM is noisy; we cut on repeated divider markers and keep
    post texts that look like asks (the LLM classifier makes the final call).
    """
    items = []
    chunks = [c.strip() for c in text.split("\n\n\n") if c.strip()]
    for chunk in chunks:
        if len(chunk) < 40:
            continue
        blob = chunk[:200].lower()
        if any(m in blob for m in SKIP_MARKERS):
            continue
        href = ""
        for link in chunk.split("http"):
            link = link.strip().split()[0] if " " in link else link
            if "facebook.com/groups" in link:
                href = "http" + link
                break
        url = href or group_url  # fallback: group URL (dedup strips dup)
        items.append({
            "source": "facebook",
            "url": url,
            "author": "",  # no reliable name from text wall; classifier sees text
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "raw_text": chunk[:3000],
        })
    return items


def collect_facebook(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("facebook", {})
    if not src.get("enabled", False) or safety.branch_paused("facebook"):
        return []
    groups = src.get("groups", [])
    state = safety.load_state("facebook")
    if not state or not groups:
        return []
    poll_hours = float(src.get("poll_hours", 2))
    out: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state, **safety.launch_headless())
        page = ctx.new_page()
        for i, g in enumerate(groups):
            if i > 0:
                time.sleep(random.uniform(3, 10))  # randomized human pause
            url = g if str(g).startswith("http") else f"https://www.facebook.com/groups/{g}"
            try:
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                time.sleep(random.uniform(3, 6))
                html = page.content()
                if safety.is_loginwall(html):
                    kb = safety.hit_loginwall("facebook")
                    print(f"[warn] fb login-wall hit {kb['hits']}/2, paused={kb['paused']}")
                    continue
                page.mouse.wheel(0, 1500)  # lazy-load feed
                time.sleep(random.uniform(2, 4))
                bodies = _visible_articles(page)
                for body in bodies[:15]:  # cap per group (poll courtesy)
                    blob = body[:200].lower()
                    if any(m in blob for m in SKIP_MARKERS):
                        continue
                    out.append({
                        "source": "facebook",
                        "url": url,
                        "author": "",
                        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "raw_text": body[:3000],
                    })
            except (PWTimeout, OSError, KeyError) as exc:
                print(f"[warn] fb group {url}: {exc}")
        browser.close()
    if safety.branch_paused("facebook"):
        print("[kill-switch] FB paused — urgent alert path in alerts/telegram.py")
    return out


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    items = collect_facebook(cfg)
    print(f"collected: {len(items)}")
    for it in items[:3]:
        print("-", it["url"], "|", it["raw_text"][:70].replace("\n", " / "))
    sys.exit(0)
