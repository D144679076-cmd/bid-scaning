# Phase M1 — Foundation & Reddit pipeline

Status: IMPLEMENTED (code + tests done) — pending: client TG creds in `.env`,
n8n install/import, first live run with client.

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`.

## Files / deliverables

```
config.yaml              subreddits[], poll_rate, noise keywords[], TG settings
.env.example             TG_TOKEN, TG_CHAT_ID placeholders (real .env uncommitted)
db.py                    SQLite init, WAL mode, schema from PLAN.md §4
collectors/reddit.py     fetch https://www.reddit.com/r/<sub>/new.json (no auth),
                         normalize → request dicts
pipeline/dedup.py        normalized URL unique + text fingerprint hash,
                         INSERT OR IGNORE
pipeline/spam_filter.py  keyword/regex noise filter (early hard filter)
alerts/telegram.py       plain TG alert: source, link, text excerpt (no LLM yet)
n8n/                     1 schedule workflow (cron 10–15 min) + 1 error workflow
tests/                   sample-post fixture, one recorded post validated
```

## Tasks

1. Scaffold repo structure above; `config.yaml` + `.env.example`.
2. `db.py` init with WAL; create tables (PLAN.md §4).
3. `collectors/reddit.py` — validate against one recorded sample post first
   (per AGENTS.md style rule).
4. `pipeline/dedup.py` — same post twice = 1 row, `INSERT OR IGNORE`.
5. `pipeline/spam_filter.py` — early keyword filter before anything stored.
6. `alerts/telegram.py` — plain alert: source, link, excerpt. No LLM in M1.
7. n8n schedule workflow (cron 10–15 min) + error workflow that alerts TG.
8. Wire pipeline order: collector → dedup → spam filter → classifier slot
   (pass-through in M1) → alert. Do not reorder (AGENTS.md).

## DoD

- New matching Reddit posts land in Telegram within 15 min.
- Duplicate posts never double-alert; runs are idempotent.

## Gate check with client

Reddit leads look correct → proceed M2.

## Client input needed for M1

- Telegram bot token + chat ID (goes in `.env` only, never committed).
- Confirm subreddit list (default: r/automation, r/nocode, r/AI_Agents,
  r/AiAutomations, r/smallbusiness, r/Entrepreneur, r/n8n) or add more.
