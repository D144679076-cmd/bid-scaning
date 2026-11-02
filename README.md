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

## M1 status

- [x] Code: config, db (WAL), reddit collector, dedup, spam filter, TG alerts, runner
- [x] Tests 7/7 green (`tests/test_m1.py`, sample-post fixture offline)
- [x] Schema migration noted in `docs/PLAN.md` §4 (`fingerprint` column)
- [ ] Client: `.env` with real TG_TOKEN + TG_CHAT_ID (file exists; placeholder values now)
- [x] n8n installed + workflow imported/activated + server running
- [ ] First live run + gate check with client
