# Telegram → OpenCode Agent — Setup Guide & Implementation Plan

> Companion to `docs/telegram-agent-plan.md` (architecture decisions).
> This file: what YOU prepare, what I build, in order.
> Status: Phase 1 done (server running). Phases 2–5 below.

## Current state (already built, 2026-11-04)

| Component | State |
|---|---|
| OpenCode server | Running on `127.0.0.1:4096`, systemd user service `opencode-serve`, auto-restart on failure |
| API password | Pinned in `~/.config/opencode/serve.env` (perm 600, stable across restarts) |
| Bridge binary | `opencode-telegram-bridge` v1.8.5 installed (Node, global) |
| Bridge service | Unit `opencode-telegram-bridge.service` created + enabled (starts on boot) |
| Bridge env file | `~/.config/opencode-telegram-bridge/opencode-telegram-bridge.env` created (perm 600) — **2 empty fields awaiting your input** |
| API capability check | Confirmed: permission endpoints (`permission.asked` events + reply) exist → hybrid autonomy is implementable |

---

## Part 1 — What YOU prepare (30 min)

### 1.1 Create the agent bot

1. Telegram → open **@BotFather** → `/newbot`.
2. Name it e.g. `my-opencode-agent`. Keep it private (does not need to be discoverable).
3. Copy the token: looks like `123456789:AAxxxx...`.
4. In the same BotFather chat: `/setprivacy` → choose your new bot → **Disable**.
   Reason: privacy OFF lets the bot receive your **plain text messages** as prompts.
   Slash commands work even with privacy ON, but prompts-as-text do not.

⚠️ Do NOT touch the bid-scan bot (`TG_TOKEN` in `.env`). It stays privacy **ON**
(it only needs its own inline-button callbacks).

### 1.2 Get your Telegram user ID

1. Message **@userinfobot** — it replies with your numeric ID (e.g. `123456789`).
2. This ID goes into the bridge **allowlist**. Any other Telegram user is denied.

### 1.3 Fill the bridge env file

```sh
nano ~/.config/opencode-telegram-bridge/opencode-telegram-bridge.env
```

Two fields are empty — fill them:

```
TELEGRAM_BOT_TOKEN=<bot token from 1.1>
TELEGRAM_ALLOWED_USER_ID=<numeric ID from 1.2>
```

Everything else in that file is already pre-filled (server URL, API password
read from `serve.env`, restart commands). Do not change them.

### 1.4 Create the control group

1. Create a Telegram group, e.g. `Agent Control`.
2. Add **both** bots to it: the bid-scan bot and the new agent bot.
   - Two different tokens = two independent update streams → no conflict.
   - Safety rule stays: never let two processes share one bot token.
3. Distinguishing commands:
   - `/stop@bidscan_bot` → bid-scan bot
   - `/use@my-opencode-agent <project>` → agent bot
   - With privacy OFF on the agent bot, plain text in the group = agent prompt.
4. Noise caution: everything typed in the group reaches the agent as a prompt.
   If that gets noisy during digest hours, keep the agent in a private chat
   with the agent bot instead of a group. Your choice, works either way.

### 1.5 Laptop prep (for Phase 5 VSCode jump-in)

1. Install **VSCode** (stable) + extension **Remote - SSH**.
2. Add `~/.ssh/config` entry on the laptop:

   ```
   Host devbox
     HostName <your-domain>
     User lynxadmin
     IdentityFile <path-to-your-key>
   ```

3. Server side (`sshd_config`, do once): `PasswordAuthentication no`,
   key-only auth — confirm before removing password auth.
4. Test from a laptop terminal: `ssh devbox` → expect login without password.

### 1.6 Checklist before handing back to me

- [ ] Agent bot created, token in bot chat
- [ ] Privacy mode disabled for agent bot
- [ ] User ID from @userinfobot
- [ ] Env file: 2 fields filled
- [ ] (Optional now) group created, both bots added
- [ ] (Phase 5 only) laptop SSH config + key auth tested

---

## Part 2 — My implementation plan (after 1.6)

### Phase 2 finish — start + verify bridge

1. `systemctl --user start opencode-telegram-bridge`
2. Verify: journal shows bot connected to Telegram + OpenCode; no 409 conflicts;
   wrong-user test → denied.
3. Telegram test: `/help` from your account → command list replies.

### Phase 3 — Multi-project sessions

1. Register project aliases (bridge stores them in
   `~/.opencode-telegram-bridge/projects.db`).
2. Candidate projects: `bid-scaning` + 1–2 of your own repos per pilot.
3. Flow: `/use@agent <alias>` → your plain text becomes a prompt in that
   project's directory → `/session list` / `/stop` / `/diff` to manage.

### Phase 4 — Hybrid autonomy

1. Per project `opencode.json` `permissions`:
   - **allow**: read/grep/edit tools; bash patterns for build/test
     (`npm test`, `pytest`, `python run_pipeline.py`, etc.).
   - **ask**: `rm -rf`, `git push`, `systemctl`, deploy-like commands.
2. "ask" prompts surface through the API as `permission.asked` events /
   pending permission requests → bridge surfaces them in Telegram →
   you reply YES / ALWAYS / NO.
3. Gate: if this bridge version does not forward API-level permission
   requests, fall back to an in-process permission plugin (small addition
   next to the bridge, verified at build time).

### Phase 5 — VSCode jump-in (`/open`)

The bridge has no `/open` command by default — I add a small wrapper.

1. Server side: detect each project's app port (e.g. 3000 web dev, 8000
   FastAPI/django) → write `.vscode/settings.json` with
   `remote.forwardPorts: [<port>]` in the project — Remote-SSH auto-forwards
   when you connect to that folder.
2. Wrapter (systemd service alongside bridge) exposes `/open <alias>`:
   returns deep link to Telegram:
   `vscode://vscode-remote/ssh-remote+devbox/<project-path>`
3. One click on the laptop → VSCode opens → connected to server → port
   forwarded → click port in PORTS panel → browser test of the app.
4. Optional later: tiny laptop-side helper that auto-opens on message,
   no click.

### Phase 6 — Pilot run

1. Pick one project. From phone: `/use@agent <alias>` → prompt → watch agent
   work → `/diff` in Telegram → cross-check in VSCode.
2. Run the app through the forwarded port, test, iterate.
3. Tune permission rules from observed behavior (what should be `ask`).
4. Update `docs/telegram-agent-plan.md` status when phases land.

---

## Security rules (standing)

- Bot token + API password live in env files only (perm 600), never committed.
- OpenCode API binds to localhost only; never exposed by reverse proxy / firewall.
- SSH: key-only auth; shared key stays on your laptop.
- Bridge allowlist: your user ID only.
- Agent edits code centrally; compliance/archive rules from `AGENTS.md` are
  unaffected (no auto-sends; bid-scan behavior untouched).

## File locations (reference)

| File | Purpose |
|---|---|
| `~/.config/systemd/user/opencode-serve.service` | OpenCode API server unit |
| `~/.config/opencode/serve.env` | Pinned API password |
| `~/.config/systemd/user/opencode-telegram-bridge.service` | Bridge unit |
| `~/.config/opencode-telegram-bridge/opencode-telegram-bridge.env` | Bot token, allowlist, API password |
| `~/.opencode-telegram-bridge/projects.db` | Bridge project aliases / chat state |
