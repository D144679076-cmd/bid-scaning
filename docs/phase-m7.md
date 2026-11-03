# Phase M7 — App packaging: Docker isolation + config-driven runtime

Status: PLAN — approved direction 2026-11-03: "should be an app because the
production should be explicit from code which is developed, and we should
run inside Docker for isolation from unexpected changes of the main OS".

## Predecessor (done in M6, carried into Docker)
- profile.yaml is config-file driven (edit file → next cycle drafts change;
  no reseed). Carried over: bind-mount the same files into the container.

## Goal
Everything ship-able in ONE image; production = built image, development =
repo working tree. Host OS packages/updates can no longer break the scanner
(chromium libs, python versions, pip drift — all frozen in the image).

## Runtime model (no systemd inside containers)

Container = one supervisor process with 4 built-in scheduled loops
("cron" is IN the app — client requirement from M6):

```
scheduler loops (threads): pipeline */15 · callbacks */1 · digest 09:00 ·
                           followup */30 · watchdog */10
```

- `services/scheduler.py` — stdlib-only loop runner (threading + next-fire
  times read from cadence table; logs to data/logs like systemd did)
- `bin/bidscan` keeps working semantics: now wraps `docker compose`:
  `bidscan status/run/logs/doctor/install` (login helpers still run on HOST
  with a visible window — browser GUI can't pop from inside the container)

## Compose topology (RAM-aware, 7 GB host)

```
services:
  app:            # mcr.microsoft.com/playwright/python:v1.64.1 base
                  # collectors + pipeline + watchdog + scheduler + chromium
    volumes:      # config-driven + persisted state (nothing baked in)
      - ./config.yaml:/app/config.yaml:ro
      - ./profile.yaml:/app/profile.yaml
      - ./data:/app/data          # sqlite WAL + sessions + logs + state
      - ./.env:/app/.env:ro       # secrets never in image (AGENTS.md)
    environment:
      - OLLAMA_BASE=http://host.docker.internal:11434   # host ollama reused
  # ollama stays ON THE HOST (models ~GBs already downloaded; container
  # re-pull wasteful on 7 GB box). Compose only documents it.
```

## Production explicit from code (DFD: dev ≠ prod)

```
Dockerfile            build from repo → image: bidscan:<commit-sha>
docker-compose.yml    production wiring (env_file .env, volumes, health)
docker-compose.override.yml.example   dev extras (optional, git-ignored)
.env.example          documents the 3 keys (unchanged)
scripts/deploy.sh     docker compose build → up -d → watchdog green check
healthcheck           compose `test: python -c "db ok + ollama reach"` →
                      auto-restart on failure
```

- Image pins: python 3.14 base, pip freeze of current repo deps
  (playwright 1.64.1, pyyaml — nothing else new)
- Version stamp baked into image (`git describe` → accessible via
  `bidscan status`; built-from-code proof in every log header)

## Migration steps (safe order — AGENTS.md: never kill the working path first)
1. Build image from current commit (verify all 24 tests INSIDE container)
2. `compose up` alongside host timers for 1 proven cycle pair
3. Only then: `systemctl --user disable --now bidscan-*` (rollback = enable back)
4. Update docs (phase-m6 watchdog semantics → same checks inside scheduler)
5. Crontab cleaned in M6, n8n stays retired

## DoD
1. `docker compose run app python -m tests.*` — 24/24 green in container
2. Production run: 6 sources flowing, drafts/alerts identical to host runs
3. Container restart / image rebuild → data + sessions survive (volumes)
4. Host oilomama change (e.g. restarted) does not break container pipeline
5. `bidscan status` works post-Docker (wraps compose)
6. rollback verified: host systemd timers can be re-enabled in under 1 min

## Gate check with client
- One supervised `deploy.sh` run + `bidscan status` together
- Then still-open client items: profile.yaml fill, TG button gate check

## Out of scope
- Ollama containerization (host service reused)
- GPU support, multi-node, k8s — overkill for this box
- X source (still off; login helpers stay)
