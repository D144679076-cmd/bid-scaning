"""Upwork / Freelancer jobs feed (M5, fixed 2026-11-04). Playwright, FEED ONLY.

HARD RULE (AGENTS.md): never submit proposals via code — this collector
only scrolls public project search listings and extracts texts; the alert
message gives the link + draft, ALL sending is manual.

Fixes (2026-11-04, browser-source gate diagnosis):
- Upwork: extract per `article` job tile (real shape: "Posted 17 minutes ago |
  Title | Hourly: $9.00 - $15.00 | ...") instead of whole-body text that
  leaked nav tokens (HireRoles_153, jsn_SortBy_191) and dropped budgets.
- Freelancer: previous URL `/search/users` listed USERS, not jobs, and
  `/job-search/projects/` does not render login-less. `/jobs/{category}/`
  renders real project cards; smallest-element "Avg Bid" extraction.
"""

import random
import re
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config as Config
from pipeline import safety, source_state

JOBS_RE = re.compile(
    r"(?i)(looking for|need|hire|build me|help with|develop|automate)[^.!?]{10,220}[.!?]")

# React/accessibility token litter that used to leak into raw_text
JUNK_TOKEN_RE = re.compile(r"(?i)\b(?:hires?roles|jsn|usnuxt|aria_)[_a-z]*_?\d*\b")

# nav markers that mean a chunk is page chrome, not a job card (freelancer)
NAV_MARKERS = ("how it works browse jobs", "registered trademark",
               "hire a freelancer earn money freelancing",
               "search keyword", "filter by:")


def _relevance_ok(text: str, require: list[str], reject: list[str]) -> bool:
    """M8 (client): freelancer = web/app/automation/bot/CS/dev jobs ONLY.
    Title + first 200 chars of body decide; word-boundary matching."""
    probe = text[:260].lower()
    if any(re.search(rf"\b{re.escape(w.lower())}\b", probe) for w in reject):
        return False
    return any(re.search(rf"\b{re.escape(w.lower())}\b", probe)
               for w in require)


def _clean(text: str) -> str:
    return "\n".join(
        line for line in (l.strip() for l in text.splitlines())
        if line and not JUNK_TOKEN_RE.fullmatch(line)
    ).strip()


def _freelancer_cards(page) -> list[tuple[str, str]]:
    """Smallest DOM elements containing 'Avg Bid' whose parent is NOT one —
    real project cards; return (text, project href) pairs."""
    cards = page.evaluate("""() => {
      const hits = [];
      document.querySelectorAll('*').forEach(el => {
        const t = el.innerText || '';
        if (t.length > 400 && t.length < 6000 &&
            t.includes('Avg Bid') && el.children.length < 60) hits.push(el);
      });
      const all = new Set(hits);
      return hits.filter(e => !all.has(e.parentElement))
                 .map(e => {
                   const a = e.querySelector("a[href*='/projects/']");
                   return [e.innerText, a ? a.getAttribute('href') : ''];
                 });
    }""") or []
    out = []
    for text, href in cards:
        text = _clean(text)
        if any(m in text.lower() for m in NAV_MARKERS) or not href:
            continue
        out.append((text, href))
    return out


def _collect_loginless(cfg, source: str, search_url: str) -> list[dict]:
    src = cfg.get("sources", {}).get(source, {})
    if not src.get("enabled", False) or safety.branch_paused(source):
        return []
    query = (src.get("search_query", "") or "automation").strip()
    if source == "freelancer":
        url = search_url.format(q=query.lower().replace(" ", "-"))
    else:
        url = search_url.format(q=query.replace(" ", "+"))
    out: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for attempt in (1, 2):  # one retry
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
                # scroll once for lazy-load
                page.mouse.wheel(0, 2000)
                time.sleep(random.uniform(2, 4))

                if source == "upwork":
                    tiles = page.query_selector_all("article")
                    bodies = [(t.inner_text() or "") for t in tiles]
                    links = []
                    for t in tiles:
                        a = t.query_selector("a[href*='/jobs/']")
                        links.append(a and a.get_attribute("href") or "")
                    bodies = [(bd, ln) for bd, ln in zip(bodies, links)]
                    if not bodies:
                        bodies = [(_clean(page.inner_text("body")), "")] \
                            if JOBS_RE.search(page.inner_text("body") or "") else []
                    else:
                        bodies = [(bd, ln) for bd, ln in bodies
                                  if bd and "posted" in bd.lower()]
                else:  # freelancer
                    bodies = [(bd, href)
                              for bd, href in _freelancer_cards(page)]
                    if not bodies:  # fallback: old sentence parse stays available
                        body_txt = _clean(page.inner_text("body"))
                        bodies = [(m.group(0).strip(), "")
                                  for m in JOBS_RE.finditer(body_txt)]

                for bd, link in bodies:
                    bd = bd.strip()
                    if len(bd) < 40:
                        continue
                    if source == "freelancer":
                        fsrc = cfg.get("sources", {}).get("freelancer", {})
                        require = list(fsrc.get("require_keywords") or [])
                        reject = list(fsrc.get("reject_keywords") or [])
                        # M9 /filter: runtime word adds from the owner merge
                        # on top of config.yaml (both sides, case-insensitive)
                        add = source_state.load_overrides()["filter_add"]
                        low = lambda ws: [w.lower() for w in ws]
                        require = require + [w for w in add["require"]
                                             if w.lower() not in low(require)]
                        reject = reject + [w for w in add["reject"]
                                           if w.lower() not in low(reject)]
                        if require and not _relevance_ok(bd, require, reject):
                            continue
                    if not link and source == "freelancer":
                        continue  # no project link = unusable alert button
                    hosts = {"upwork": "https://www.upwork.com",
                             "freelancer": "https://www.freelancer.com"}
                    url_ = link if link.startswith("http") \
                        else (hosts[source] + link if link else url)
                    out.append({
                        "source": source,
                        "url": url_,
                        "author": "",
                        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "raw_text": bd[:3000],
                    })
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
        cfg, "freelancer", "https://www.freelancer.com/jobs/{q}/")


if __name__ == "__main__":
    Config.load_env()
    cfg = Config.load_config()
    for name, fn in (("upwork", collect_upwork), ("freelancer", collect_freelancer)):
        items = fn(cfg)
        print(f"{name}: collected {len(items)}")
        for it in items[:3]:
            print("-", it["url"])
            print(" ", it["raw_text"][:120].replace("\n", " / "))
