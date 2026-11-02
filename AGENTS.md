# Bid Scanning — Project Rules

## Context

Automation bid-scan system per `docs/PLAN.md`. Auto-discover requests for
custom software / tools of any kind (automation workflows, scripts, bots,
scrapers, web/app dev, integrations — not automation only), classify buying
intent, draft bids, human approves via Telegram.

Stack: n8n orchestrator + Python collectors/libs + SQLite + Telegram bot.

## Must

- Read `docs/PLAN.md` before any task; follow milestone order M1→M5.
- Stack only: n8n workflows, Python libs, SQLite. No new dependencies without asking.

## Compliance (hard rules)

- Never auto-send bids/DMs/posts to any platform. All sends human-approved
  via Telegram (draft + manual send).
- Collectors are read-only. Reddit = public JSON endpoints, low poll rate
  (10–15 min), no authentication.
- Never store platform credentials. FB login = Playwright `storageState` only,
  if ever added (M4).
- Upwork/Freelancer: feed view only, never submit proposals via code.

## Code

- Pipeline step order: collector → dedup → spam filter → classifier → alert.
  Keep this order; do not reorder or skip steps.
- Dedup: normalized URL unique key + text fingerprint hash,
  `INSERT OR IGNORE`, new posts recorded with source + timestamp.
- Intent threshold rule: score ≥ 6 → instant alert with fields + buttons;
  score < 6 → status `low`, NO instant alert, displayed later in the daily
  digest sorted by score descending (updated 2026-11-02, per client:
  low-score requests are still shown, not silently archived).
- SQLite in WAL mode. Schema changes only via a noted migration block in docs.
- Keep files small, one module per pipeline step.

## Config

- Secrets in `.env` only (`TG_TOKEN`, `TG_CHAT_ID`). Never commit, never
  hardcode, never put inside n8n node credentials.
- Keywords, subreddit lists, poll rates live in `config.yaml`.

## Style

- Test each collector against one sample post before wiring into n8n.
- Keep `AGENTS.md` and `docs/PLAN.md` in sync when milestones land.
