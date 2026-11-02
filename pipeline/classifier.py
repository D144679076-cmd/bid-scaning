"""Classifier step (M2). LLM scores + extracts; module replaces the M1
pass-through in the locked pipeline slot:

collector → dedup → spam filter → [payment gate] → CLASSIFIER → alert / digest

Rules per AGENTS.md + client 2026-11-02:
- score >= 6  → status 'lead', instant alert (fields + buttons)
- score < 6   → status 'low', NO instant alert → daily digest sorted by score
- unpaid posts (no pay signal) already gated before this step.
Scope: ANY custom software request (not only automation).
"""

PROMPT = """You triage posts where people ask for software help or tools.
Score the BUYING INTENT plus ability to pay for a custom solution.

Return STRICT JSON only, no markdown:
{
  "score": 0-10,
  "request_type": "automation|script/bot|scraper|web/app dev|integration/SaaS|other software|not a request",
  "tools": ["zapier", "n8n"],
  "budget": "short amount text or empty string",
  "deadline": "short text or empty string",
  "language": "ISO 639-1 code of post language",
  "pay_capability": "clear|implied|none",
  "reason": "one short sentence"
}

Scoring guide:
9-10 explicit budget + clear custom build ask
7-8  clear paid project language ("paid project", "willing to pay")
5-6  strong pain described but pay unclear
2-4  tool question / discussion, weak intent
0-1  not a request, rant, or news
If the author "just asks for a free tool" with no pay path → score <= 4.
JSON only."""


def classify_one(cfg, client, item: dict) -> dict:
    """item → enriched copy with score + extracted fields."""
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user",
         "content": f"SOURCE: {item['source']}\nAUTHOR: {item.get('author','')}\n"
                    f"POST:\n{item.get('raw_text','')[:4000]}"},
    ]
    out = client(cfg, messages) if client else {"score": 0, "request_type": "not a request"}
    item["score"] = int(out.get("score", 0) or 0)
    item["request_type"] = out.get("request_type", "other software")
    item["tools"] = out.get("tools", []) or []
    item["budget"] = item.get("budget") or out.get("budget", "") or ""
    item["deadline"] = out.get("deadline", "") or ""
    item["language"] = out.get("language", "") or ""
    item["pay_capability"] = out.get("pay_capability", "") or ""
    item["reason"] = out.get("reason", "") or ""
    return item


def run_classifier(cfg, client, items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Requires DB ids already stored for dedup tracking.

    Returns (instant_alerts, digested). Items must carry db_id."""
    threshold = cfg.get("classifier", {}).get("instant_alert_min_score", 6)
    instant, digested = [], []
    for item in items:
        classify_one(cfg, client, item)
        score = item.get("score", 0)
        pay_clear = item.get("pay_capability") != "none"
        if score >= threshold and pay_clear:
            instant.append(item)
        else:
            item["_digest_reason"] = "score<6" if score < threshold else "pay=none"
            digested.append(item)
    return instant, digested
