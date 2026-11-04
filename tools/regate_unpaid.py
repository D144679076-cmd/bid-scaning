"""One-off rescue (2026-11-04): browser-source 'unpaid' rows re-gated.

Why: collectors extracted nav/own-chat noise instead of job cards, so the
payment gate (correctly) marked real listings as unpaid — text shape was
broken, gated on garbage. Collectors since fixed (upwork_feed.py rewrite,
fb own-echo filter); run this once to give stored rows with REAL payment
signals a second pass: unpaid → lead (score stays NULL → classifier picks
them up next cycle via _unscored rescue).

Run: python3 tools/regate_unpaid.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from db import connect  # noqa: E402
from pipeline.payment_check import compile_patterns, extract_amounts  # noqa: E402


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    regexes = compile_patterns(cfg.get("payment_signals", []))
    amounts = cfg.get("amount_patterns", [])
    conn = connect(str(ROOT / "data" / "bidscan.db"))
    rows = conn.execute(
        "SELECT id, url, raw_text FROM requests WHERE status = 'unpaid'"
    ).fetchall()
    flipped = 0
    for r in rows:
        text = r["raw_text"] or ""
        if not any(rx.search(text) for rx in regexes):
            continue
        # junk guard: rows extracted from nav garbage (fixed collectors make
        # these impossible for new rows) still LOOK paid ("$...") — require a
        # verb-shaped ask too, else they'd become garbage leads
        if not re.search(r"(?i)(need|hire|looking|build|develop|automate|"
                         r"hourly range|est\. time|help with)", text):
            continue
        conn.execute(
            "UPDATE requests SET status='lead', budget=? WHERE id=?",
            (", ".join(extract_amounts(text, amounts)) or None, r["id"]))
        flipped += 1
        print(f"[regate] #{r['id']} {text[:60].replace(chr(10), ' / ')}")
    conn.commit()
    print(f"regated {flipped}/{len(rows)} unpaid rows → lead "
          "(classifier queue, next cycle)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
