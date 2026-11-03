"""Make forum collector (M5). Public Discourse RSS — no auth, low poll rate.

Boards scanned: full latest.rss + the "Hire a Pro" category (the job wall).
Same compliance envelope as Reddit: read-only, unauthenticated, 10–30 min
polling. Client rule: only request-shaped posts pass — same skip_markers
de-noiser as the Reddit collector; the LLM classifier makes the final call.
"""

import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from collectors.reddit import USER_AGENT, _to_text

RSS = ""
DC = "{http://purl.org/dc/elements/1.1/}"

SKIP_MARKERS = ("[discussion]", "[blog]", "[resource]", "[guide]",
                "[tutorial]", "[showcase]", "[event]", "[tips]",
                "i built", "i made", "introducing", "case study",
                "lessons learned", "new release")


def fetch_rss(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml"})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.read()


def normalize(xml_bytes: bytes) -> list[dict]:
    """RSS 2.0 (Discourse) → pipeline-shaped request dicts."""
    root = ET.fromstring(xml_bytes)
    out = []
    for item_el in root.iter("item"):
        title = (item_el.findtext(f"{RSS}title") or "").strip()
        desc = item_el.findtext(f"{RSS}description") or ""
        body = _to_text(desc)
        if not title and not body:
            continue
        blob = (title + "\n" + body)[:300].lower()
        if any(m in blob for m in SKIP_MARKERS):
            continue  # blog/showcase shape → not a request
        link = (item_el.findtext(f"{RSS}link") or "").strip()
        if not link:
            continue
        author = (item_el.findtext(f"{DC}creator") or "").strip()
        posted = (item_el.findtext(f"{RSS}pubDate") or "").strip() or None
        out.append({
            "source": "make",
            "url": link,
            "author": author,
            "posted_at": posted,
            "raw_text": (title + "\n\n" + body).strip(),
        })
    return out


def collect_make(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("make", {})
    if not src.get("enabled", False):
        return []
    items: list[dict] = []
    urls = [src.get("list_url", "https://community.make.com/latest.rss")]
    if src.get("include_hire_a_pro", True):
        urls.append(
            "https://community.make.com/c/hire-a-pro/" +
            str(src.get("hire_a_pro_category_id", 50)) + ".rss")
    for i, url in enumerate(urls):
        if i > 0:
            time.sleep(3 + i)  # fetch spacing (courtesy, same as reddit)
        try:
            items.extend(normalize(fetch_rss(url)))
        except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
            print(f"[warn] make {url}: {exc}")
    return items
