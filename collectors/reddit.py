"""Reddit collector (M1). Public JSON endpoints, no auth, low poll rate.

Per AGENTS.md compliance: read-only, 10–15 min polling, no authentication.
Tested against one sample post before n8n wiring (tests/).
"""

import json
import urllib.error
import urllib.request

USER_AGENT = "bid-scan-m1/0.1 (personal lead scanner; contact via project owner)"


def fetch_listings(list_url: str) -> list[dict]:
    """Fetch one subreddit listing; returns list of post dicts."""
    request = urllib.request.Request(list_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data", {}).get("children", [])


def normalize(posts: list[dict], source: str = "reddit") -> list[dict]:
    """Children dicts → request dicts shaped for the pipeline."""
    out = []
    for child in posts:
        data = child.get("data", {})
        title = (data.get("title") or "").strip()
        selftext = (data.get("selftext") or "").strip()
        if not title and not selftext:
            continue  # link-only/no text posts: skip
        out.append(
            {
                "source": source,
                "url": "https://www.reddit.com" + (data.get("permalink") or ""),
                "author": data.get("author") or "",
                "posted_at": data.get("created_utc"),  # epoch seconds; stored ISO in dedup
                "raw_text": (title + "\n\n" + selftext).strip(),
            }
        )
    return out


def collect_reddit(cfg: dict) -> list[dict]:
    src = cfg.get("sources", {}).get("reddit", {})
    if not src.get("enabled", False):
        return []
    items: list[dict] = []
    for sub in src.get("subreddits", []):
        url = (src.get("list_url") or "").format(sub=sub)
        try:
            items.extend(normalize(fetch_listings(url)))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            # One bad subreddit must not kill the whole cycle; error workflow alerts.
            print(f"[warn] reddit r/{sub}: {exc}")
    return items
