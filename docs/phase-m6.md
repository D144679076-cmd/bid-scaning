# Phase M6 — Self-running app (service layer)

Status: PLAN — not yet built. Client approved direction 2026-11-03:
"make this into an app that runs automatically with built-in cron".

## Goal
One app that installs, schedules, watches itself, survives reboot, reports
failures to Telegram. No changes to pipeline logic (collector → dedup →
spam → payment → classify → alert) — service layer only.

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`. Depends on: M1–M5.

## Decisions (defaults — client can veto before build)
- Supervisor: **systemd timers** (verify `systemctl` available in this WSL
  first; fallback: keep crontab + CLI wrapper only).
- **n8n retired from runtime** — the Python cron pipeline covers every step;
  frees ~300–500 MB RAM for ollama + browser collectors on the 7 GB box.
  Workflow JSON stays in repo for reference; nothing deletes data.
- New Python dependencies: **none** (stdlib + systemd only).

## Files to add

```
bin/bidscan                      # CLI (stdlib only):
  install    → copy units, enable timers, verify crontab entries removed
  start/stop → start/stop all timers (oneshot services)
  status     → all 4 jobs + ollama + last-run stats + session health
  run        → manual one pipeline cycle (wraps run_pipeline.py)
  logs [job] → tail data/logs/<job>.log
  login fb|x|linkedin  → matching one-time login helper
  doctor     → .env keys, DB WAL, killswitch state, session expiry, disk/mem

services/bidscan-pipeline.service + .timer   → oneshot run_pipeline.py, */15 min
services/bidscan-callbacks.service + .timer  → alerts/callbacks.py, */1 min
services/bidscan-digest.service + .timer     → alerts/digest.py, 09:00 daily
services/bidscan-followup.service + .timer   → pipeline/followup.py, */30 min
services/bidscan-watchdog.service + .timer   → */10 min:
  - ollama api/version reachable, else restart attempt + TG alert
  - session files parse + expected cookie names present, else TG
    "log in again: bidscan login fb"
  - log freshness (data/cron.log mtime > 20 min = pipeline stuck) → TG alert
  - disk/memory floor check (7 GB box!)

scripts/install.sh               # first-run wrapper → bin/bidscan install
services/watchdog.py             # watchdog logic
```

## Migration note (noted change, per AGENTS.md)
System crontab entries are removed only AFTER the first successful systemd
cycle pair is proven — never delete the working path first.

## DoD
1. All 4 timers enabled + firing (`systemctl list-timers | grep bidscan`)
2. Reboot test (wsl --shutdown + restart) → pipeline self-starts, zero manual
   steps
3. `bidscan status` all green + last-run stats per job
4. Simulated ollama kill → watchdog TG message ≤ 10 min + auto-restart works
5. Fake-expired FB session detected → TG "log in again" nudge
6. Stop n8n → no pipeline step fails (then remove from boot)

## Gate check with client
- Watch 2 boot cycles + 1 watchdog alert together
- Then finish still-open M3 items: `profile.yaml` fill + TG button gate check

## Out of scope (this phase)
- Authenticated Upwork scrape upgrade
- X re-enable (login helpers stay in repo, source stays off)
- Any send-automation — always manual per AGENTS.md
