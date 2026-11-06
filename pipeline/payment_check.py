"""Payment gate (client rule 2026-11-02): request must show willingness/capacity
to pay. Heuristic signals in M1 (config.yaml payment_signals); LLM verifies
budget-capability again in the M2 classifier (belt and braces).

No money signal → status 'unpaid', NO alert. Survivors fall through.
"""

import re

UPDATE_SQL = """UPDATE requests
                SET status = 'unpaid'
                WHERE id = ?"""


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns if p]

def has_payment_signal(text: str, regexes: list[re.Pattern]) -> bool:
    return any(rx.search(text) for rx in regexes)


def _first_match(text: str, regexes: list[re.Pattern]) -> str | None:
    for rx in regexes:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


def extract_amounts(text: str, amount_patterns: list[str]) -> list[str]:
    """Pull displayed budget figures out of text (dedup + max 3)."""
    regexes = [re.compile(p, re.IGNORECASE) for p in amount_patterns if p]
    found: list[str] = []
    for rx in regexes:
        for m in rx.findall(text):
            val = m.strip() if isinstance(m, str) else " ".join(m).strip()
            if val and val not in found:
                found.append(val)
            if len(found) >= 3:
                return found
    return found


def gate_payments(conn, items: list[dict], patterns: list[str],
                  amount_patterns: list[str] | None = None,
                  contact_patterns: list[str] | None = None,
                  gate_policy: dict | None = None) -> list[dict]:
    """Mark items without pass-signal as 'unpaid'; attach extracted
    amounts to survivors and write them to requests.budget; return
    survivors.

    M9 (client 2026-11-06): per-source gate policy.
    - default `payment` sources: survive on a payment-signal regex
      (unchanged M1/M8 behavior).
    - `contact_first` sources (facebook): tool-market norms — price is
      agreed in the inbox after first contact ("ib để báo giá"), so a
      CONTACT signal (contact_signals) also passes the gate. Survivors
      keep budget=None and carry `contact_channel` (col written too).
    Pipeline order (collector → dedup → spam → GATE → classifier) is
    untouched; only what counts as a "signal" is per-source.
    """
    if not items:
        return []
    regexes = compile_patterns(patterns)
    cregexes = compile_patterns(contact_patterns or [])
    policy = gate_policy or {}
    ids_by_url = {row["url"]: row["id"] for row in conn.execute(
        "SELECT id, url FROM requests WHERE status = 'lead' AND score IS NULL")}
    survivors = []
    for item in items:
        src = item.get("source", "")
        contact = None
        contact_first = policy.get(src) == "contact_first"
        passed = has_payment_signal(item.get("raw_text", ""), regexes)
        if contact_first:
            # M9: even when the payment rule passes, record the deal-entry
            # contact (ib/inbox/zalo/…) — TG alert shows 📞 and the owner
            # knows exactly where the conversation starts.
            contact = _first_match(item.get("raw_text", ""), cregexes)
        if not passed and contact_first:
            passed = contact is not None
        if passed:
            amounts = extract_amounts(item.get("raw_text", ""), amount_patterns or [])
            item["amounts"] = amounts
            item["budget"] = ", ".join(amounts)
            if contact:
                item["contact_channel"] = contact
            survivors.append(item)
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(
                    "UPDATE requests SET budget = ?, contact_channel = ? "
                    "WHERE id = ?",
                    (", ".join(amounts) or None,
                     contact or item.get("contact_channel") or None,
                     request_id),
                )
        else:
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(UPDATE_SQL, (request_id,))
    conn.commit()
    return survivors
