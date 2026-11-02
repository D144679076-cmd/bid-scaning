# Bid Scanning — M1 quick start

Full plan: `docs/PLAN.md` + `docs/phase-m1.md`. Rules: `AGENTS.md`.

## Local run (without n8n)

```bash
cp .env.example .env      # fill TG_TOKEN + TG_CHAT_ID
python3 run_pipeline.py --limit-msgs 10
```

## Tests (offline, no network)

```bash
python3 -m tests.test_m1
```

## n8n

1. Install n8n (see below), import `n8n/bid-scan-m1.json`.
2. The JSON's `_second_workflow_on_import_create_separately` section describes
   a second workflow (Error Alert) — create it, then attach as Error workflow
   of the collector workflow.
3. `Execute Command` nodes run `python3` using the project path — update path
   there if the repo moves.

## n8n install (not done locally yet)

```bash
npm install -g n8n
n8n start   # web UI: http://localhost:5678
```

## M1 status — CLOSED 2026-11-02

- [x] Code: config, db (WAL), reddit collector (RSS), dedup, spam filter,
      payment gate, TG alerts (paced), runner
- [x] Tests 8/8 green (`tests/test_m1.py`, recorded real-feed fixture)
- [x] Schema migration noted in `docs/PLAN.md` §4 (`fingerprint` column)
- [x] Client `.env` live (token + chat id)
- [x] n8n installed + workflow imported/active (runtime toggle pending — cron fallback active)
- [x] First live runs: 98 requests, 73 alerts, payment gate live (18 unpaid filtered)
- [x] Client feedback M1.1 wired in: send pacing + payment-ability rule
- [x] Gate check passed → next: M2 (docs/phase-m2.md)
