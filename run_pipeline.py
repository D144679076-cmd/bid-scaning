"""M1.1 pipeline runner. Order locked by AGENTS.md:
collector → dedup → spam filter → classifier slot (pass-through in M1;
includes payment gate) → alert (paced).

Client rules in effect:
- payment-ability gate (2026-11-02): no money signal → 'unpaid', no alert.
- Telegram send pacing: min_interval_seconds between sends, max_per_run cap;
  backlog beyond cap stays status=lead and goes out in later runs.
"""

import argparse
import sys

import config as Config
from alerts import telegram
from collectors import reddit
from db import connect
from pipeline import dedup, spam_filter
from pipeline import payment_check


def _backlog(conn, limit: int) -> list[dict]:
    """Unsent leads from previous runs; go out before nothing new is lost."""
    rows = conn.execute(
        """SELECT raw_text, url, author, posted_at, source, budget
           FROM requests
           WHERE status = 'lead' AND sent_at IS NULL
           ORDER BY id LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {"source": r["source"], "url": r["url"], "author": r["author"],
         "posted_at": r["posted_at"], "raw_text": r["raw_text"],
         "budget": r["budget"], }
        for r in rows
    ]


def run(cfg: dict, conn, limit_msgs=None) -> dict:
    al = cfg.get("alerts", {})
    min_int = int(al.get("min_interval_seconds", 8))
    cap = int(al.get("max_per_run", 15))
    stats = {"collected": 0, "fresh": 0, "noise": 0, "unpaid": 0,
             "alerted": 0, "backlog_left": 0}

    # 1. collector
    items = reddit.collect_reddit(cfg)
    stats["collected"] = len(items)

    # 2. dedup (stores fresh rows as status 'lead')
    fresh = dedup.store(conn, items)
    stats["fresh"] = len(fresh)

    # 3. spam filter (archives noise, returns survivors)
    survivors = spam_filter.filter_noise(conn, fresh, cfg.get("noise_keywords", []))
    stats["noise"] = len(fresh) - len(survivors)

    # 4. classifier slot in M1: payment gate only (real LLM classifier in M2)
    leads = payment_check.gate_payments(conn, survivors,
                                        cfg.get("payment_signals", []),
                                        cfg.get("amount_patterns", []))
    stats["unpaid"] = len(survivors) - len(leads)

    # 5. alert — paced, capped; backlog carries over, nothing dropped
    queue = leads[:limit_msgs] if limit_msgs else leads
    if not queue:  # idle cycle → clear the backlog instead
        queue = _backlog(conn, cap)
    stats["alerted"] = telegram.alert(conn, queue, min_int, cap)
    left = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status='lead' AND sent_at IS NULL"
    ).fetchone()[0]
    stats["backlog_left"] = max(0, left + max(0, len(queue) - stats["alerted"]))

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Bid-scan M1 pipeline run")
    parser.add_argument("--limit-msgs", type=int, default=None,
                        help="cap Telegram alerts in this run")
    args = parser.parse_args()

    Config.load_env()
    cfg = Config.load_config()
    conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))

    try:
        stats = run(cfg, conn, args.limit_msgs)
        print(stats)
        return 0
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
