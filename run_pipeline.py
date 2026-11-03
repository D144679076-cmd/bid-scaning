"""M2 pipeline runner. Order locked by AGENTS.md:
collector → dedup → spam filter → payment gate → CLASSIFIER → alert/digest.

M2 additions (client 2026-11-02):
- Real LLM classifier: score + request_type + fields persisted to DB.
- score >= 6 → instant alert with ✅/❌/🔗 buttons.
- score < 6 → status 'low' → daily digest (alerts/digest.py, sorted by score).
- Backlog drain keeps working when the current batch is empty.
"""

import argparse
import sys
from pathlib import Path

import config as Config
from alerts import telegram
from collectors import reddit
from db import connect
from pipeline import dedup, spam_filter, payment_check, classifier
from llm import client as llm_client_module

from collectors import make_forum, reddit, upwork_feed, x_search, linkedin_feed, fb_feed

_COLLECTORS = {
    "reddit": reddit.collect_reddit,
    "make": make_forum.collect_make,
    "facebook": fb_feed.collect_facebook,
    "upwork": upwork_feed.collect_upwork,
    "freelancer": upwork_feed.collect_freelancer,
    "x": x_search.collect_x,
    "linkedin": linkedin_feed.collect_linkedin,
}

UPDATE_FIELDS = """UPDATE requests
                   SET score=?, task_type=?, tools=?, budget=?, deadline=?,
                       language=?, draft_text=NULL
                   WHERE id=?"""


def _persist(conn, item: dict, status: str | None = None) -> None:
    sets = "score=?, task_type=?, tools=?, budget=?, deadline=?, language=?"
    params = [
        int(item.get("score", 0)),
        item.get("request_type") or "other software",
        __import__("json").dumps(item.get("tools", [])),
        item.get("budget") or None,
        item.get("deadline") or None,
        item.get("language") or None,
    ]
    sql = f"UPDATE requests SET {sets}"
    if status:
        sql += ", status=?"
        params.append(status)
    sql += " WHERE id=?"
    params.append(item["db_id"])
    conn.execute(sql, params)
    if status:
        item["status"] = status
    # sync budget string back for the alert message
    item["budget"] = item.get("budget") or ""
    conn.commit()


def run(cfg: dict, conn, limit_msgs=None, client=None, no_llm=False) -> dict:
    al = cfg.get("alerts", {})
    stats = {"collected": 0, "fresh": 0, "noise": 0, "unpaid": 0,
             "classified": 0, "instant": 0, "low": 0, "alerted": 0}

    # 1. collectors — every enabled source; one bad source never kills a cycle
    items: list[dict] = []
    for name in ("reddit", "make", "facebook", "upwork", "freelancer",
                 "x", "linkedin"):
        mod = _COLLECTORS.get(name)
        if mod is None:
            continue
        try:
            got = mod(cfg)
            items.extend(got)
            stats[f"src_{name}"] = len(got)
        except Exception as exc:  # defensive: browser/network issues isolate
            print(f"[warn] collector {name}: {exc}")
    stats["collected"] = len(items)

    # 2. dedup (fresh rows status 'lead')
    fresh = dedup.store(conn, items)
    ids_by_url = {r["url"]: r["id"] for r in conn.execute(
        "SELECT id, url FROM requests WHERE status='lead' AND score IS NULL")}
    for it in fresh:
        it["db_id"] = ids_by_url.get(it["url"])
    stats["fresh"] = len(fresh)

    # 3. spam filter
    survivors = spam_filter.filter_noise(conn, fresh, cfg.get("noise_keywords", []))
    survivors = [s for s in survivors if s.get("db_id")]
    stats["noise"] = len(fresh) - len(survivors)

    # 4. payment gate
    leads = payment_check.gate_payments(conn, survivors,
                                        cfg.get("payment_signals", []),
                                        cfg.get("amount_patterns", []))
    stats["unpaid"] = len(survivors) - len(leads)

    # 5. classifier slot — REAL in M2, capped per cycle (cron/n8n timeout)
    cap_cls = int(cfg.get("classifier", {}).get("max_per_cycle", 10))
    leads_pending = [l for l in leads if l.get("db_id")]
    queue_cls = leads_pending[:cap_cls]
    if not queue_cls and not no_llm:  # idle cycle → rescue unscored leads
        queue_cls = _unscored(conn, cap_cls)
    if queue_cls and not no_llm:
        client = client or llm_client_module.chat
        scored, low = classifier.run_classifier(cfg, client, queue_cls)
        stats["classified"] = len(queue_cls)
        stats["low"] = len(low)
        for item in scored:
            _persist(conn, item)          # stays 'lead' → instant queue
        for item in low:
            _persist(conn, item, status="low")  # digest backlog

    # M3: drafts for instant leads + regenerate for edited rows
    if no_llm:
        scored = []
    stats["drafts"] = draft_stage(conn, cfg, client, scored)

    # 6. alert (paced, capped) — instant queue first; idle drain of backlog
    queue = scored[:limit_msgs] if limit_msgs else scored
    cap = int(al.get("max_per_run", 15))
    min_int = int(al.get("min_interval_seconds", 8))
    if not queue:
        queue = _backlog(conn, cap)
    stats["alerted"] = telegram.alert(conn, queue, min_int, cap)

    return stats


def _unscored(conn, limit: int) -> list[dict]:
    """Rescue: lead rows that never got classified (crashed / capped cycles)."""
    rows = conn.execute(
        """SELECT id, raw_text, url, author, posted_at, source, budget, deadline
           FROM requests
           WHERE status = 'lead' AND score IS NULL
           ORDER BY id LIMIT ?""",
        (limit,),
    ).fetchall()
    paid = {"source": "reddit", }
    return [
        {"db_id": r["id"], "source": r["source"], "url": r["url"],
         "author": r["author"], "posted_at": r["posted_at"],
         "raw_text": r["raw_text"], "budget": r["budget"] or "",
         "deadline": r["deadline"] or ""}
        for r in rows
    ]


def draft_stage(conn, cfg, client, scored: list[dict]) -> int:
    """Draft writes for: score≥6 items + items the owner edited (✏️ note).

    The edited rows keep status='edited' → redraft with note → status
    'approved' (ready for manual send digest). Draft failures never take
    the whole run down. --no-llm runs (client=None) skip entirely.
    """
    if client is None:
        return 0
    import json as _json
    from pipeline import bid_writer
    from alerts import digest as _digest_mod  # noqa: F401 (import guard only)

    prof = bid_writer.load_profile(conn)
    if not prof.get("name"):
        print("[warn] profile empty — run profile_seed.py; skipping drafts")
        return 0
    import yaml as _yaml
    try:
        prof["contact_hint"] = (_yaml.safe_load(
            (Path(__file__).resolve().parent / "profile.yaml")
            .read_text(encoding="utf-8")) or {}).get("contact_hint", "")
        prof["hard_rules"] = (_yaml.safe_load(
            (Path(__file__).resolve().parent / "profile.yaml")
            .read_text(encoding="utf-8")) or {}).get("hard_rules", [])
    except OSError:
        pass
    written = 0
    cap = int(cfg.get("classifier", {}).get("drafts_per_cycle", 5))
    targets = list(scored)
    # backlog: high-score leads that predate M3 (or were capped) without drafts
    p = conn.execute(
        "PRAGMA table_info(requests)").fetchall()
    cols = {r[1] for r in p}
    if {"draft_text", "score"} <= cols:
        try:
            backlog = conn.execute(
                """SELECT id, raw_text, url, author, posted_at, source, budget,
                          score, task_type, deadline
                   FROM requests
                   WHERE score >= ? AND status = 'lead'
                     AND (draft_text IS NULL OR draft_text = '')
                   ORDER BY score DESC LIMIT ?""",
                (int(cfg.get("classifier", {}).get("instant_alert_min_score", 6)),
                 cap),).fetchall()
        except Exception:
            backlog = []
        for row in backlog:
            targets.append({
                "db_id": row["id"], "source": row["source"], "url": row["url"],
                "author": row["author"], "posted_at": row["posted_at"],
                "raw_text": row["raw_text"], "budget": row["budget"] or "",
                "score": row["score"], "request_type": row["task_type"],
                "deadline": row["deadline"] or "",
            })
    edited = conn.execute(
        """SELECT id, raw_text, url, author, posted_at, source, budget,
                  score, task_type, deadline, draft_text
           FROM requests WHERE status = 'edited'""").fetchall()
    for row in edited:
        targets.append({
            "db_id": row["id"], "source": row["source"], "url": row["url"],
            "author": row["author"], "posted_at": row["posted_at"],
            "raw_text": row["raw_text"], "budget": row["budget"] or "",
            "score": row["score"], "request_type": row["task_type"],
            "deadline": row["deadline"] or "",
            "client_note": row["draft_text"] or "",
        })
    for item in targets:
        if not item.get("db_id"):
            continue
        try:
            draft = bid_writer.write_bid(cfg, client, prof, item)
            bid_writer.persist_draft(conn, item, draft)
            item["draft_text"] = draft  # shows in the alert message
            if item.get("client_note") or item.get("status") == "edited":
                conn.execute(
                    "UPDATE requests SET status='approved' WHERE id=?",
                    (item["db_id"],))
                conn.commit()
            written += 1
        except Exception as exc:
            print(f"[warn] draft failed #{item.get('db_id')}: {exc}", flush=True)
    return written


def _backlog(conn, limit: int) -> list[dict]:
    """Unsent instant leads from previous runs."""
    rows = conn.execute(
        """SELECT id, raw_text, url, author, posted_at, source, budget,
                  score, task_type, deadline, draft_text
           FROM requests
           WHERE status = 'lead' AND sent_at IS NULL
           ORDER BY id LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {"db_id": r["id"], "source": r["source"], "url": r["url"],
         "author": r["author"], "posted_at": r["posted_at"],
         "raw_text": r["raw_text"], "budget": r["budget"] or "",
         "score": r["score"], "request_type": r["task_type"],
         "deadline": r["deadline"] or "", "draft_text": r["draft_text"] or ""}
        for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bid-scan M2 pipeline run")
    parser.add_argument("--limit-msgs", type=int, default=None,
                        help="cap Telegram alerts in this run")
    parser.add_argument("--no-llm", action="store_true",
                        help="skip classification (offline/dev run)")
    args = parser.parse_args()

    Config.load_env()

    # single-instance guard: LLM drafting is long — overlap = double alerts
    import fcntl
    lock = Path("data/runner.lock")
    lock.parent.mkdir(exist_ok=True)
    with open(lock, "w") as lockfh:
        try:
            fcntl.flock(lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another runner already active — skip cycle", flush=True)
            return 0
        cfg = Config.load_config()
        conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
        try:
            client = None
            stats = run(cfg, conn, args.limit_msgs, client,
                        no_llm=args.no_llm)
            print(stats)
            return 0
        except RuntimeError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
