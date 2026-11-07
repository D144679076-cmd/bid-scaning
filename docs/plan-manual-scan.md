# Plan — manual-only scanning + 3 jobs per `/scan`

Date: 2026-11-06 · Status: ✅ DONE 2026-11-07 (scheduler flag code, host
pipeline.timer stopped, config cap 3, container rebuilt + flag verified)

Client request 2026-11-06: no scheduled scan runs; scanning happens only on
demand (`/scan` in Telegram), and each `/scan` should surface found jobs
one by one — capped at 3 leads per scan cycle (chosen over 1 and "up to 15").

Current automation being switched off: container scheduler (`services/
scheduler.py`) fires `pipeline` every 30 min + a boot cycle; host timer
`bidscan-pipeline.timer` fires every ~3 h.

## 1. Stop the 30-min schedule (container side)

- `services/scheduler.py`: before firing any `pipeline` job, check
  `data/scheduler.json` → `{"pipeline_disabled": true}` → skip the fire.
  Also on the boot cycle (a container restart must not auto-scan).
- The flag is re-read every loop → re-enabling later is
  `{"pipeline_disabled": false}` (or delete the file), no code change.
- Callbacks / digest / followup / watchdog / sender loops untouched.
- Rebuilding the image once is needed for this code change; the flag file
  itself works through the shared `data/` bind mount.

## 2. Stop the 3 h host schedule

- `systemctl --user stop bidscan-pipeline.timer` (unit files stay installed
  — rollback = `systemctl --user start bidscan-pipeline.timer`).
- `bidscan-callbacks|digest|followup|watchdog` timers stay.

## 3. Cap alerts at 3 per scan cycle

- `config.yaml` → `alerts.max_per_run: 15 → 3`.
- Keep `min_interval_seconds: 8` (spacing) and `per_source_per_cycle: 3`
  (per-source mix rule — with cap 3 a fan-out cycle can show up to 3
  different sources, one interleaved).
- Result: one `/scan` = up to 3 lead messages, one job per message, sent
  8 s apart; a bigger harvest backs up and carries into later cycles
  (Telegram pacing rule in AGENTS.md — unchanged).

## 4. Deploy

- Rebuild image + `docker compose up -d` only when `data/runner.lock` is
  idle (no in-flight cycle; verify with `lsof data/runner.lock`).
- Both schedulers (host + container) remain active for callbacks etc. per
  client choice 2026-11-06; with both `pipeline` loops stopped there is no
  double-scan risk, and one shared flock keeps even that safe in general.

## 5. Verify (definition of done)

- `bin/bidscan status` green.
- One old-fire window (≥30 min) passes → `data/logs/pipeline.log` shows no
  fresh `=====` banner that was NOT triggered by `/scan`.
- Host: `systemctl --user list-timers` shows `bidscan-pipeline.timer`
  inactive; container log shows no pipeline loop firing.
- `.env` untouched; no compliance change: collectors stay read-only, only
  already-approved alert sends happen.

## Rollback

1. `systemctl --user start bidscan-pipeline.timer`
2. `data/scheduler.json` → `{"pipeline_disabled": false}`
3. `alerts.max_per_run: 3 → 15` in `config.yaml`
