"""Load profile.yaml into the `profile` DB row (id=1). Idempotent reseed."""

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as Config
from db import connect


def seed(cfg: dict, profile: dict) -> None:
    conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
    conn.execute(
        """INSERT INTO profile (id, name, portfolio_url, past_work,
                                pricing_tiers, tone, contact_hint)
           VALUES (1, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, portfolio_url=excluded.portfolio_url,
             past_work=excluded.past_work, pricing_tiers=excluded.pricing_tiers,
             tone=excluded.tone, contact_hint=excluded.contact_hint""",
        (
            profile.get("name", ""),
            profile.get("portfolio_url", ""),
            json.dumps(profile.get("past_work", []), ensure_ascii=False),
            json.dumps(profile.get("pricing_tiers", []), ensure_ascii=False),
            profile.get("tone", ""),
            profile.get("contact_hint", ""),
        ),
    )
    conn.commit()
    print("profile row seeded")

# hard_rules stay read from profile.yaml at draft time (pipeline/bid_writer.py
# loads it); they are rules, not row data.


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    prof_path = Path("profile.yaml")
    if not prof_path.exists():
        print("profile.yaml missing", file=sys.stderr)
        return 1
    prof = yaml.safe_load(prof_path.read_text(encoding="utf-8"))
    seed(cfg, prof)
    if "REPLACE-ME" in json.dumps(prof, ensure_ascii=False):
        print("[warn] profile.yaml still contains REPLACE-ME placeholders — "
              "fill it with your real data, then rerun `python3 profile_seed.py`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
