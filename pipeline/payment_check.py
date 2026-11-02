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
                  amount_patterns: list[str] | None = None) -> list[dict]:
    """Mark items without payment signal as 'unpaid'; attach extracted
    amounts to survivors and write them to requests.budget; return survivors."""
    if not items:
        return []
    regexes = compile_patterns(patterns)
    ids_by_url = {row["url"]: row["id"] for row in conn.execute(
        "SELECT id, url FROM requests WHERE status = 'lead' AND score IS NULL")}
    survivors = []
    for item in items:
        if has_payment_signal(item.get("raw_text", ""), regexes):
            amounts = extract_amounts(item.get("raw_text", ""), amount_patterns or [])
            item["amounts"] = amounts
            item["budget"] = ", ".join(amounts)
            survivors.append(item)
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(
                    "UPDATE requests SET budget = ? WHERE id = ?",
                    (", ".join(amounts) or None, request_id),
                )
        else:
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(UPDATE_SQL, (request_id,))
    conn.commit()
    return survivors
