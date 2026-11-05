"""Facebook groups collector (M4). Playwright, READ-ONLY, allowlist only.

AGENTS.md/plan compliance:
- Own logged session via storageState only (collectors.fb_login).
- Never like/comment/post/DM — page interactions limited to scroll + read.
- Delays 3–10 s randomized, 1 poll per group per 2–4 h, UA/viewport rotation.
- Kill-switch: 2 captcha/login-wall hits → FB branch paused + urgent alert.
- Post items flow through the SAME pipeline (dedup → spam → payment → LLM).
"""

import hashlib
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
# M9 re-point (client 2026-11-05, docs/fb-scan-report.md §F): real tool-build
# demand is in VN tool-market groups ("thuê code tool", "gia công phần mềm")
# + the EN MMO side. Education-community terms retired.
DISCOVER_TERMS = ("thuê code tool", "nhận làm tool tự động",
                  "gia công phần mềm", "viết tool theo yêu cầu",
                  "web app theo yêu cầu", "make money online",
                  "freelance group")


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



def _visible_articles(page) -> tuple[list[str], int]:
    """Post bodies from the group feed DOM (role=article elements).

    Returns (filled_bodies, raw_article_count) — the raw count lets the
    caller detect the M9 'fb-skeleton' case (articles present but never
    hydrated → silent zero otherwise).
    """
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
    return out, len(nodes)


def _fb_relevance_ok(body: str, require: list[str], reject: list[str],
                     text_limit: int = 260) -> bool:
    """M9 (client 2026-11-05, docs/fb-scan-report.md §F): keep BUYER asks,
    drop seller self-promo in VN tool-market groups. Body probe = first
    `text_limit` chars; word-boundary matching like the freelancer filter
    (pipeline M8 uses the same probe shape)."""
    probe = body[:text_limit].lower()
    if any(re.search(rf"\b{re.escape(w.lower())}\b", probe) for w in reject):
        return False
    return any(re.search(rf"\b{re.escape(w.lower())}\b", probe)
               for w in require)


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
    require = src.get("require_keywords") or []
    reject = src.get("reject_keywords") or []
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
                bodies, raw_count = _visible_articles(page)
                if not bodies and raw_count:
                    # M9: distinct warn — articles in DOM but never hydrated
                    # (the 2026-11-04..05 silent-zero failure mode). Never
                    # quietly output 0 again.
                    print(f"[warn] fb-skeleton {url}: {raw_count} article "
                          "nodes, none hydrated — group fed nothing")
                used = 0
                for body in bodies[:15]:  # cap per group (poll courtesy)
                    blob = body[:200].lower()
                    if any(m in blob for m in SKIP_MARKERS):
                        continue
                    if _is_own_chat_echo(body):
                        continue
                    if require and not _fb_relevance_ok(body, require, reject):
                        continue  # seller promo / chatter — not a buyer ask
                    # M9 dedup fix: same group URL previously collapsed
                    # every post in a cycle to ONE row (url UNIQUE). Per-post
                    # pseudo-URL = text hash → same post dedups across runs.
                    post_url = (url + "?p="
                                + hashlib.sha1(body.encode("utf-8")).
                                hexdigest()[:12])
                    out.append({
                        "source": "facebook",
                        "url": post_url,
                        "author": "",
                        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "raw_text": body[:3000],
                    })
                    used += 1
                    if used >= 5:  # M9: marketplace feed floods sellers; the
                        break      # filter keeps asks, cap keeps the mix
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
