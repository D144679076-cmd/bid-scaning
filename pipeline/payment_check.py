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


def gate_payments(conn, items: list[dict], patterns: list[str]) -> list[dict]:
    """Mark items without payment signal as 'unpaid'; return survivors."""
    if not items:
        return []
    regexes = compile_patterns(patterns)
    ids_by_url = {row["url"]: row["id"] for row in conn.execute(
        "SELECT id, url FROM requests WHERE status = 'lead' AND score IS NULL")}
    survivors = []
    for item in items:
        if has_payment_signal(item.get("raw_text", ""), regexes):
            survivors.append(item)
        else:
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(UPDATE_SQL, (request_id,))
    conn.commit()
    return survivors
