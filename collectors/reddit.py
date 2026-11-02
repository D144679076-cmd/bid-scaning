"""Reddit collector (M1). Public Atom RSS feeds, no auth, low poll rate.

2026 update per AGENTS.md sync: unauthenticated JSON endpoints now return
403/login-wall; /new.rss remains publicly readable — same compliance
envelope (no auth, read-only, 10–15 min polling). Tested against recorded
sample fixture in tests/.

Per AGENTS.md compliance: read-only, low poll, no authentication.
"""

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
NS = {"a": "http://www.w3.org/2005/Atom"}


def fetch_listings(list_url: str) -> bytes:
    request = urllib.request.Request(
        list_url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"}
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.read()


def _to_text(html: str) -> str:
    html = re.sub(r"<[^>]+>", " ", html or "")
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&#39;", "'").replace("&quot;", '"').replace("&gt;", ">")
    return re.sub(r"\s+", " ", html).strip()


def normalize(xml_bytes: bytes, source: str = "reddit") -> list[dict]:
    """Atom feed → request dicts shaped for the pipeline.

    Client rule 2026-11-03: only *request-shaped* posts pass — skip
    blogs/discussions/resources. Classifier (LLM) makes the FINAL call;
    this is a cheap early de-noiser.
    """
    skip_markers = ("[discussion]", "[blog]", "[resource]", "[guide]",
                    "[tutorial]", "[showcase]", "[event]", "[tips]",
                    "i built", "i made", "introducing", "case study",
                    "lessons learned", "show r/", "new release")
    root = ET.fromstring(xml_bytes)
    out = []
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", "", NS) or "").strip()
        content_html = entry.findtext("a:content", "", NS) or ""
        body = _to_text(content_html)
        if not title and not body:
            continue
        blob = (title + "\n" + body)[:300].lower()
        if any(marker in blob for marker in skip_markers):
            continue  # announcement/blog shape → not a JD-like request
        link = ""
        for el in entry.findall("a:link", NS):
            href = el.get("href")
            rel = el.get("rel")
            if href and (rel is None or rel == "alternate"):
                link = href
                if rel is None:
                    break
        if not link:
            continue
        author = (entry.findtext("a:author/a:name", "", NS) or "").strip()
        posted = (entry.findtext("a:updated", "", NS) or "").strip() or None
        out.append(
            {
                "source": source,
                "url": link,
                "author": author,
                "posted_at": posted,  # ISO timestamp from feed
                "raw_text": (title + "\n\n" + body).strip(),
            }
        )
    return out


def collect_reddit(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("reddit", {})
    if not src.get("enabled", False):
        return []
    items: list[dict] = []
    subs = src.get("subreddits", [])
    for i, sub in enumerate(subs):
        # Rate-limit courtesy: wait between subreddit fetches (200+ subs throttled).
        if i > 0:
            import time as _t
            _t.sleep(3 + (i % 3))  # 3–5 s rotating pause
        url = (src.get("list_url") or "").format(sub=sub)
        try:
            items.extend(normalize(fetch_listings(url)))
        except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError, ValueError) as exc:
            # One bad subreddit must not kill the whole cycle; error workflow alerts.
            print(f"[warn] reddit r/{sub}: {exc}")
    return items
