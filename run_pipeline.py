"""M1 pipeline runner. Order locked by AGENTS.md:
collector → dedup → spam filter → classifier (pass-through in M1) → alert.
"""

import argparse
import sys

import config as Config
from alerts import telegram
from collectors import reddit
from db import connect
from pipeline import dedup, spam_filter


def run(cfg: dict, conn, limit_msgs: int | None = None) -> dict:
    stats = {"collected": 0, "fresh": 0, "noise": 0, "alerted": 0}

    # 1. collector
    items = reddit.collect_reddit(cfg)
    stats["collected"] = len(items)

    # 2. dedup (stores fresh rows as status 'lead')
    fresh = dedup.store(conn, items)
    stats["fresh"] = len(fresh)

    # 3. spam filter (archives noise, returns survivors)
    noise_patterns = cfg.get("noise_keywords", [])
    survivors = spam_filter.filter_noise(conn, fresh, noise_patterns)
    stats["noise"] = len(fresh) - len(survivors)

    # 4. classifier — PASS-THROUGH in M1 (wired in M2)
    leads = survivors[:limit_msgs] if limit_msgs else survivors

    # 5. alert
    if leads:
        stats["alerted"] = telegram.alert(conn, leads)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Bid-scan M1 pipeline run")
    parser.add_argument(
        "--limit-msgs", type=int, default=None,
        help="cap Telegram alerts in this run (safety for first runs)",
    )
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
