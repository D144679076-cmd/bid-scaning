# Manual TODO — client actions

> Things only you (client) can do by hand. Code side needs nothing from you
> otherwise. AGENTS.md: secrets only in `.env`, never committed / hardcoded.

## 1. Telegram bot + chat (M1 finishing requirement) — DO THIS NOW

Create the bot:

1. Open Telegram, search **@BotFather** → `/start` → `/newbot`
2. Name it e.g. `Bid Scan Lead Bot`, username anything ending in `bot`
3. BotFather replies with a **token** like:
   `123456789:AAH3k...your-token-here`
4. Copy it — that is your `TG_TOKEN`

Get your chat ID:

5. Open your own chat with the bot in Telegram, press **START** (or `/start`)
   — this makes the bot able to message you (required by Telegram, do before
   first run)
6. Open in browser (replace token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
7. You will see JSON like `"chat":{"id":123456789,...}` — that number is your
   `TG_CHAT_ID` (optionally check `results` array if empty — you may have
   missed /start, do it then retry the URL)

Write to `.env`:

```bash
cd /home/lynxadmin/project/bid-scaning
cp .env.example .env
nano .env    # put your TG_TOKEN and TG_CHAT_ID inside, save
```

Test manually (optional but recommended):

```bash
python3 run_pipeline.py --limit-msgs 3
```

→ should print `{'collected': N, ...}` and you get real lead messages in
Telegram within seconds. If it errors `TG_TOKEN missing` → check `.env` name
and values. Never paste actual `.env` contents back into chat — commit check
happens for you (`.gitignore` already has `.env`).

## 2. n8n after install completes (I will import workflows with you)

- [ ] Run `n8n start` and open `http://localhost:5678`
- [ ] Create account / login (local instance, no registration elsewhere)
- [ ] Import `n8n/bid-scan-m1.json` via Workflows → Import from File
- [ ] Create separate "Bid Scan — Error Alert" workflow per
      `n8n/bid-scan-m1.json` → `_second_workflow_on_import_create_separately`
- [ ] Set that as error workflow of the collector workflow

## 3. Later phases (from docs/phase-m3.md etc. — not M1)

- [ ] Agency name, portfolio, 2–3 past-work blurbs, pricing tiers, tone (M3)
- [ ] FB: secondary account (NOT personal), group allowlist, login session (M4)
- [ ] Confirm subreddit list (default 7) or add more
