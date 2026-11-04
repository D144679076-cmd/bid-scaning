# Bid-Scan

Self-scanning job-lead finder with human-approved sending. Discovers requests
for custom software / automation work across 6 sources, scores buying intent
with an LLM, drafts the bid, and waits for a human to approve and send it.

**Production = Docker container `bidscan-app`.** Development happens in this
repo; what you deploy is a version-stamped, isolated build of that code —
host OS changes (apt/pip/browser updates) cannot break the scanner.

---

## How the app runs (production)

```
docker compose up -d      # one container: the whole app
```

Inside the container there is no external cron/systemd —
`services/scheduler.py` runs the schedule itself (built-in cron):

| Loop |cadence | What it does |
|---|---|---|
| pipeline | every 30 min | scan all sources → dedup → spam filter → payment gate → LLM classify → draft → Telegram alert |
| callbacks | every 1 min | watch TG button presses (✅ approve / ✏️ edit / ❌ reject / 🔗 open) |
| digest | 09:00 daily | low-score (1–5) backlog message, sorted by score desc |
| followup | every 30 min | TG nudge if an approved draft got no recorded follow-up for 24 h |
| watchdog | every 10 min | ollama down → auto-restart + 🚨 alert · expired login session → "log in again" nudge · stuck pipeline log → 🚨 alert · disk/memory floor check |

Plus one **boot cycle** of the pipeline runs the moment the container starts,
so the app is never waiting 15 min for its first scan.

Loop intervals live in `services/scheduler.py` (`CADENCE` table).

### Hard separation: production vs development

- Production = image built **from this code** (`git` SHA stamped into every
  log header + `/app/VERSION`). `bid-scan 228b84e 2026-11-04`
- Development = the repo tree you're editing. Nothing it contains reaches
  production until `docker compose build`.
- Runtime fixes/config changes are **not baked**: `config.yaml`,
  `profile.yaml`, `.env`, `data/` are bind-mounted — editable on the host,
  read live by the container on its next cycle.

### What is isolated

| Layer | Inside the image (frozen at build) |
|---|---|
| Browser stack | Chromium + its system libraries (playwright 1.64.1 base image) |
| Python | version + `pyyaml` + `playwright`, pip drift impossible |
| Code | exactly one git SHA |

| Layer | Live on the host (bind-mounts) |
|---|---|
| `config.yaml` `profile.yaml` | editable runtime configuration (ro) |
| `.env` | secrets — `TG_TOKEN`, `TG_CHAT_ID`, `LLM_API_KEY` (ro, gitignored) |
| `data/` | SQLite WAL DB, login sessions, logs, watchdog state (rw) |

Ollama stays **on the host** (models ~GB, already on disk) — the container
reaches it via `OLLAMA_BASE` → `host.docker.internal`.

### Sessions & safety (AGENTS.md)

- Login sessions (Facebook / LinkedIn / X) live only in `data/session_*.json`
  — gitignored, no passwords anywhere.
- Login-wall / captcha guard: 2 hits → that source pauses + TG alert
  (`pipeline/safety.py`).
- **Nothing is ever auto-sent to any platform** — every bid requires a human
  press on the ✅ Approve button and a manual paste into the source site.

---

## The `bidscan` CLI

`bin/bidscan` — one command for everything. Run from the project folder:

```bash
bidscan CMD
```

| Command | What it does / when to use |
|---|---|
| `bidscan status` | **go-to daily check.** Timer/loop health, ollama up/down, last-pipeline timestamp, session file ages, RAM. All green = you're scanning. |
| `bidscan install` | first-time (or after rebuild): copies systemd units (host fallback mode) and prints timer state + status. In Docker mode use `docker compose up -d` — install is optional legacy. |
| `bidscan start` | begins the scheduled loops (host-systemd fallback mode / timers). In Docker mode the app is on/off with `docker compose up -d` / `down`. |
| `bidscan stop` | pauses all scheduled loops — nothing scanned/alerted meanwhile (host fallback mode). |
| `bidscan run` | one pipeline cycle RIGHT NOW (ignores schedule). Use to test after config/keyword edits: `bidscan run --limit-msgs 5`. |
| `bidscan logs [job]` | tail loop output: `bidscan logs pipeline` (or callbacks/digest/followup/watchdog). For the container: `docker compose logs -f app`. |
| `bidscan login fb` | one-time visible browser window → log in Facebook → session auto-saves, window closes itself. Repeat when watchdog says session expired. |
| `bidscan login linkedin` | same flow for LinkedIn (`li_at` cookie). |
| `bidscan login x` | same flow for X (source currently disabled — kept for later). |
| `bidscan doctor` | deep health: `.env` keys present, SQLite WAL mode, status counts in DB, session files, disk/mem. Use when something "feels off". |
| `bidscan docker` | helpers around the container (compose wrapper). |

### Editing what the scanner looks for / writes

| You want to change | Edit | Applies |
|---|---|---|
| Job sources, subreddits, keywords, payment signals, LLM choice/failover | `config.yaml` | next 15-min cycle |
| **Your bid identity** (agency name, portfolio, contact hint, 2–3 past-work blurbs, pricing tiers, tone, hard rules) | `profile.yaml` | next cycle — NO reseed/restart (config-file driven) |
| Allowed TG recipients / secrets | `.env` | next container start |
| Classifier thresholds, alert pacing | `config.yaml` → `classifier:` `alerts:` | next cycle |

After editing, only a container restart is needed if you touched `.env`.

---

## Development loop

```bash
python3 -m tests.test_m1          # host: pipeline unit tests
python3 -m tests.test_classifier
python3 -m tests.test_bid_writer
python3 -m tests.test_m5
docker compose run --rm app python3 -m tests.test_m1   # same tests in production image

docker compose build              # new image from current code (bakes VERSION/SHA)
docker compose up -d              # restart production on the new image
```

Rollback at any time (host fallback kept):
```bash
docker compose down
systemctl --user enable --now bidscan-*
```
(produces identical behaviour minus browser-stack isolation)

---

## Compliance envelope (non-negotiable, from AGENTS.md)

1. Never auto-send bids/DMs/posts to any platform — human pressed the button.
2. Collectors are strictly read-only (public RSS where available; logged-in
   pages are only ever *read*, never interacted with).
3. Payment proof required before something becomes a lead (keyword gate +
   💰 display).
4. Credentials live ONLY in `.env` / `data/session_*.json` — gitignored.
5. Telegram pacing: ≥ 8 s between messages, ≤ 15 per run; backlog waits.

---

## Docs index

| Phase doc | Contents |
|---|---|
| `docs/PLAN.md` | master plan + milestone table (M1..M7 state) |
| `docs/phase-m1.md` … `phase-m5.md` | collectors / classifier / writer / trackers |
| `docs/phase-m6.md` | self-running app (systemd + CLI + watchdog) |
| `docs/phase-m7.md` | Docker packaging — this README's runtime model |
