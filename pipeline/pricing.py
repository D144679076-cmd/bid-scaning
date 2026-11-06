"""Suggested price per request (M10a, docs/phase-m10-auto-send.md §3).

Derived from profile.yaml pricing_tiers matched against the classifier
output via config.yaml pricing_match keyword rules. Displayed on the
pre-✅ card and consumed by senders (Freelancer fills its price field
from the stored value — no LLM re-invention at send time).

Config shape (first tier with a keyword hit wins — order = priority):
  pricing_match:
    - tier: "Retainer"
      keywords: ["ongoing", "monthly", ...]
    - tier: "Workflow build"
      keywords: ["automation", "workflow", ...]
Return: "<range> — <tier> tier" or None (card shows "not priced yet",
Freelancer auto-send blocked to protect connects).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _profile_tiers() -> dict:
    """tier name → range from profile.yaml pricing_tiers."""
    try:
        prof = __import__("yaml").safe_load(
            (Path(__file__).resolve().parent.parent / "profile.yaml")
            .read_text(encoding="utf-8")) or {}
    except (OSError, __import__("yaml").YAMLError):
        return {}
    return {t["name"]: t.get("range", "") for t in prof.get("pricing_tiers", [])
            if isinstance(t, dict) and t.get("name")}


def _price_blob(item: dict) -> str:
    """Text the rules run against. Budget signal from the poster is EXCLUDED
    (their number must never leak into our quote)."""
    tools = " ".join(item.get("tools") or []) if item.get("tools") else ""
    parts = [str(item.get("request_type") or ""),
             str(item.get("task_type") or ""),
             str(item.get("topic") or ""),
             tools,
             str(item.get("raw_text") or "")[:800]]
    return " ".join(parts).lower()


def _amount(range_str: str) -> str:
    """Normalize a tier range for form fields: "$200–600" → "$200-600"
    (en-dashes out, ASCII only)."""
    rng = (range_str or "").replace("–", "-").replace("—", "-")
    return "".join(c for c in rng if c in "+-.$01234567890")


def match_price(cfg: dict, item: dict) -> dict | None:
    """→ {"range": "$200-600", "tier": "Workflow build",
           "display": "$200-600 — Workflow build tier",
           "amount": "$200-600"} or None."""
    rules = cfg.get("pricing_match") or []
    if not rules:
        return None
    blob = _price_blob(item)
    tiers = _profile_tiers()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kws = [k.lower() for k in rule.get("keywords", [])]
        if any(k in blob for k in kws):
            tier = rule["tier"]
            rng = tiers.get(tier, "")
            if not rng:
                continue  # tier unknown in profile.yaml — try the next rule
            return {"range": rng, "tier": tier,
                    "display": f"{rng} — {tier} tier", "amount": _amount(rng)}
    return None


def price_amount(item_suggested: str) -> str:
    """ASCII-clean amount extracted from the stored suggested_price display
    string ("$200-600 — Workflow build tier" → "$200-600"); senders use it
    for Freelancer's budget field. Sent to "" when no number exists."""
    if not item_suggested:
        return ""
    return _amount(item_suggested.split(" — ")[0])
