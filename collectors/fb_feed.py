"""Facebook groups collector (M4). Playwright, READ-ONLY, allowlist only.

AGENTS.md/plan compliance:
- Own logged session via storageState only (collectors.fb_login).
- Never like/comment/post/DM — page interactions limited to scroll + read.
- Delays 3–10 s randomized, 1 poll per group per 2–4 h, UA/viewport rotation.
- Kill-switch: 2 captcha/login-wall hits → FB branch paused + urgent alert.
- Post items flow through the SAME pipeline (dedup → spam → payment → LLM).
"""

import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety
from collectors.make_forum import SKIP_MARKERS  # same de-noiser (M5 shared)

# Own-chat echoes extracted as "articles" (diagnosis 2026-11-04): FB renders
# the member's own sent messages ("Tin nhắn do Bạn gửi", "Bạn đã gửi") as
# role=article nodes — these are NOT group posts. Skip them.
OWN_CHAT_MARKERS = (
    "tin nhắn do",          # "message sent by You" (VI UI)
    "tin nhắn mà",
    "bạn đã gửi",           # "You sent"
    "đã gửi",
    "message you sent",
    "you sent",
    "typing a message",
)


def _is_own_chat_echo(body: str) -> bool:
    low = body[:300].lower()
    return any(m in low for m in OWN_CHAT_MARKERS)


# ---- M8 P2A: group auto-discovery + sharded polling ---------------------

DISCOVER_TERMS = ("make money online", "freelance group", "automation jobs",
                  "online earning", "work from home jobs")


def _discovery_path() -> Path:
    return Path("data/fb_groups.json")


def discover_groups(cfg: dict) -> list[str]:
    """Read-only sweep of FB group search results → group ids (M8 P2A).
    Merges into data/fb_groups.json (config.yaml stays the primary
    allowlist; discovered ids are additive state, capped)."""
    cap = int(cfg.get("sources", {}).get("facebook", {}).get(
        "discovery_cap", 25))
    known = set(cfg.get("sources", {}).get("facebook", {}).get("groups", []))
    try:
        known |= set((_discovery_path().read_text(
            encoding="utf-8") and __import__("json").loads(
            _discovery_path().read_text(encoding="utf-8"))) or [])
    except (OSError, ValueError):
        pass
    found: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=safety.load_state("facebook"),
                                  **safety.launch_headless())
        page = ctx.new_page()
        for term in DISCOVER_TERMS:
            try:
                page.goto(
                    "https://www.facebook.com/search/groups/?q="
                    + urllib.parse.quote(term),
                    timeout=45_000, wait_until="domcontentloaded")
                time.sleep(random.uniform(3, 6))
                hrefs = page.eval_on_selector_all(
                    "a[href*='/groups/']",
                    "els => els.map(e => e.getAttribute('href'))")
                for h in hrefs or []:
                    m = re.search(r"/groups/([^/?]+)", h or "")
                    if m and m.group(1) not in ("feed", "discover", "joins"):
                        found.append(m.group(1))
            except (PWTimeout, OSError):
                continue
        browser.close()
    new = [g for g in dict.fromkeys(found) if g not in known][:cap - len(known)]
    if new:
        merged = sorted(known | set(new))
        _discovery_path().write_text(
            __import__("json").dumps(merged), encoding="utf-8")
        print(f"[fb-discovery] +{len(new)} groups (total {len(merged)})")
    return new


def _shard(groups: list[str], cfg: dict) -> list[str]:
    """Oldest-polled-first, at most poll_groups_per_cycle (M8 politeness)."""
    import json as _json
    state_p = Path("data/fb_poll_state.json")
    try:
        state = _json.loads(state_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    per_cycle = int(cfg.get("sources", {}).get("facebook", {}).get(
        "poll_groups_per_cycle", 10))
    due_h = float(cfg.get("sources", {}).get("facebook", {}).get(
        "poll_hours", 2)) * 3600
    now = time.time()
    ordered = sorted(groups, key=lambda g: state.get(g, 0))
    due = [g for g in ordered if now - state.get(g, 0) >= due_h][:per_cycle]
    for g in due:
        state[g] = now
    try:
        state_p.write_text(_json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return due



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
    groups = list(src.get("groups", []))
    if src.get("discovery") and groups:
        try:  # M8 P2A: best-effort discovery, never blocks the poll
            import json as _json
            known = set(groups)
            try:
                known |= set(json.loads(_discovery_path().read_text(
                    encoding="utf-8")))
            except (OSError, ValueError):
                pass
            groups = list(known)[:int(src.get("discovery_cap", 25))]
        except Exception:
            pass
    state = safety.load_state("facebook")
    if not state or not groups:
        return []
    groups = _shard(groups, cfg)  # M8: oldest-polled 10 only per cycle
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
                    if _is_own_chat_echo(body):
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
