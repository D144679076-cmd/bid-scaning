"""Assisted comment drafts (M8, mode B1 — client-approved 2026-11-04).

A post that asks for automation/dev work but lacks budget/scope gets a
SHORT friendly question comment DRAFTED into Telegram, exactly like bid
drafts: ✅ approve → human pastes it manually. Zero auto-send (AGENTS.md
envelope unchanged — this module never posts anywhere).

Targets: facebook rows, score >= instant_alert_min_score, budget missing,
no comment yet. Cap: comments_per_cycle (default 3, LLM budget guard).
"""

import json

COMMENT_TMPL = """Write ONE short friendly comment to post under this Facebook \
job post. Goal: surface scope/budget details and position us as a helper — \
NOT a pitch.

Rules:
- in the author's language: {language}
- tone: {tone}
- max {max_chars} characters
- one concrete question about the missing detail (budget, scope, or timeline)
- mention ONE relevant capability briefly (no links, no contact info,
  no "hire me" spam — the human continues in DMs)
- strict JSON only: {{"comment": "..."}}

Post:
{post}"""


def build_comment_prompt(item: dict, tone: str = "casual-professional",
                         max_chars: int = 280) -> str:
    return COMMENT_TMPL.format(
        language=item.get("language") or "the author's",
        tone=tone,
        max_chars=max_chars,
        post=(item.get("raw_text") or "")[:2500])


def write_comment(cfg, client, item: dict) -> str:
    """LLM → comment text. Raises RuntimeError on empty output."""
    if client is None:
        from llm import client as _c
        client = _c.chat
    messages = [
        {"role": "system",
         "content": "You write one-line helpful comments. Strict JSON only."},
        {"role": "user",
         "content": build_comment_prompt(
             item, tone=(cfg.get("profile", {}) or {}).get("tone",
                                                           "casual-professional"))},
    ]
    out = client(cfg, messages) or {}
    comment = str((out.get("comment") or "")).strip()
    if not comment:
        raise RuntimeError("empty comment")
    return comment[:280]


def comment_stage(conn, cfg, client, scored: list[dict]) -> int:
    """Draft comments for FB leads missing budget info. Persists to
    requests.comment_text (shown in the TG alert message, B1: manual send)."""
    src = cfg.get("sources", {}).get("facebook", {})
    cap = int(src.get("comments_per_cycle", 3))
    if not src.get("enabled", False) or cap <= 0:
        return 0
    targets = [it for it in scored
               if it.get("source") == "facebook"
               and not (it.get("budget") or "").strip()
               and it.get("db_id")][:cap]
    if not targets:  # idle-cycle backlog: unscored-info FB rows from DB
        rows = conn.execute(
            """SELECT id, source, url, raw_text, score, budget FROM requests
               WHERE source='facebook' AND score >= ?
                 AND (budget IS NULL OR budget='') AND comment_text IS NULL
               ORDER BY id LIMIT ?""",
            (int(cfg.get("classifier", {}).get("instant_alert_min_score", 6)),
             cap)).fetchall()
        targets = [{"db_id": r["id"], "source": r["source"], "url": r["url"],
                    "raw_text": r["raw_text"], "score": r["score"],
                    "budget": r["budget"] or ""} for r in rows]
    written = 0
    for item in targets:
        try:
            item["comment_text"] = write_comment(cfg, client, item)
            conn.execute(
                "UPDATE requests SET comment_text=? WHERE id=?",
                (item["comment_text"], item["db_id"]))
            written += 1
        except Exception as exc:  # LLM hiccup: retry next cycle
            print(f"[warn] comment draft #{item.get('db_id')}: {exc}",
                  flush=True)
    conn.commit()
    return written


def attach_comments(conn, items: list[dict]) -> None:
    """Bulk-load existing comment drafts so alert messages show them."""
    if not items:
        return
    ids = [it["db_id"] for it in items if it.get("db_id")]
    if not ids:
        return
    q = ",".join("?" * len(ids))
    for row in conn.execute(
            f"SELECT id, comment_text FROM requests WHERE id IN ({q})", ids):
        for it in items:
            if it.get("db_id") == row["id"]:
                it.setdefault("comment_text", row["comment_text"] or "")
