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
YOUR FIRST JOB — IS_REQUEST: is this post an ACTUAL REQUEST/offer for paid work
(a JD-like ask: "need someone to build X, budget $Y", "looking to hire",
"who can automate this for me?"), or is it a BLOG/DISCUSSION/SHOWCASE post
where the author shares something, asks a general question, or describes a
personal workflow with no intent to pay someone?

Return STRICT JSON only, no markdown:
{
  "is_request": true|false,
  "score": 0-10,
  "request_type": "automation|script/bot|scraper|web/app dev|integration/SaaS|other software|not a request",
  "tools": ["zapier", "n8n"],
  "budget": "short amount text or empty string",
  "deadline": "short text or empty string",
  "language": "ISO 639-1 code of post language",
  "pay_capability": "clear|implied|none",
  "reason": "one short sentence"
}

HARD RULES:
- if is_request=false → score MUST be <= 2 (blog/discussion/tip = never a lead)
- is_request=true requires an implied or stated person to be HIRED/PAYING
  for a build ("need someone to...", "who can build...", "$ budget offered")
- general "how do I build X myself?" questions → is_request=false
- PAID EXCHANGE FOR NON-LABOR is NOT a request: buying/selling/renting
  API credits, accounts, data, courses, tools, software licenses, trading,
  barter offers, "I pay you in exchange for [raw goods]" → is_request=false
  Example: "who has unused Azure credits, I can use them and pay you" →
  is_request=false (the author offers payment for RAW GOODS, not labor for
  building something on their behalf).
- A true paid request is always for someone's BUILD/AUTOMATION/INTEGRATION
  LABOR on the author's own process. If the offered payment is not tied to
  building/automating for the author, is_request=false.

Scoring guide (only when is_request=true):
9-10 explicit budget + clear custom build ask (JD-like)
7-8  clear paid project language ("paid project", "willing to pay")
5-6  strong pain described, hiring intent implied but pay unclear
2-4  tool recommendation wanted, pay path unknown
0-1  freebie ask or no hiring intent
If the author "just wants a free tool" with no pay path → score <= 4.
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
    is_request = bool(out.get("is_request", False))
    item["is_request"] = is_request
    score = int(out.get("score", 0) or 0)
    if not is_request:
        score = min(score, 2)  # hard rule: blog/discussion can never be a lead
    item["score"] = score
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
    item["request_type"] = out.get("request_type", "other software")
    item["tools"] = out.get("tools", []) or []
    item["budget"] = item.get("budget") or out.get("budget", "") or ""
    item["deadline"] = out.get("deadline", "") or ""
    item["language"] = out.get("language", "") or ""
    item["pay_capability"] = out.get("pay_capability", "") or ""
    item["reason"] = out.get("reason", "") or ""
    return item
