# Telegram → OpenCode Agent Control — Plan (draft)

> Status: draft, awaiting review. Not part of bid-scan pipeline; separate infra
> on the same server. Created 2026-11-04.

## Goal

Control the OpenCode coding agent from Telegram to manage multiple projects
fast, with one-click VSCode Remote-SSH jump-in from the laptop (with port
forwarding) for testing the remote app.

## Topology (all server-side, reachable via own domain)

```
Phone (Telegram) ──► Bot bridge ──► opencode serve (127.0.0.1:4096, systemd)
                                        │
                              sessions per project dir (multi-project)
                                        │
Laptop: click Telegram link ──► VSCode Remote-SSH ──► server (own domain)
                                        └─ auto port-forward → open in browser → test the app
```

## How OpenCode works (relevant parts investigated)

- Client–server: `opencode serve` exposes HTTP API (default `127.0.0.1:4096`).
  Docs: https://opencode.ai/v2/docs/build/client and /v2/docs/api.
- Session bound to a directory: `session.create({ location: { directory: "/path" }})`
  — one server, many project dirs = multi-project management built-in.
- Events stream: `client.event.subscribe()` → streaming tokens/tool events
  (bridge can live-edit messages into Telegram).
- Permission system: approve/deny per tool; headless runs need pre-allowed
  permissions or a bridge that forwards prompts via Telegram buttons.

Existing bridges (do not build from scratch):

| Project | Shape | Fit |
|---|---|---|
| `gabriel-trigo/opencode-telegram-bridge` | Standalone bot → OpenCode server URL, project aliases, allowlist, systemd wizard | Best for multi-project (chosen) |
| `Traves-Theberge/opencode-remote` | Node bot, allowlist, dangerous-command confirmation | Fallback |
| `agentjoey/opencode-remote-control`, `timjonez/opencode_telegram_plugin`, `@tormentalabs/opencode-telegram-plugin` | In-process OpenCode **plugin** | Best for permission approval via Telegram buttons (fallback if needed) |
| `vrieraj/tg-relay` | MCP + file inbox | Quirky |

## Phases

### Phase 1 — OpenCode server
- `opencode serve --hostname 127.0.0.1 --port 4096` as systemd **user** service.
- Auth token for the API; never expose 4096 publicly.
- Verify headless: `opencode api get /api/info`.

### Phase 2 — Bridge install (existing project)
- Install `gabriel-trigo/opencode-telegram-bridge`; point at
  `OPENCODE_SERVER_URL=http://127.0.0.1:4096`.
- **Separate Telegram bot token** (new @BotFather bot).
  ⚠️ Must NOT reuse the bid-scan `TG_TOKEN` — that bot long-polls `getUpdates`;
  a second process on same token = 409 conflict.
- Allowlist = our Telegram user ID only.

### Phase 3 — Multi-project sessions
- Register each project dir as alias; `/use <alias>` binds chat/session to dir.
- Manage many projects fast: `/session list`, `/stop`, `/diff`, `/model`.

### Phase 4 — Hybrid autonomy (per user decision)
- Per-project `opencode.json` permissions:
  - allow: read/grep/edit, bash patterns for build/test;
  - ask/deny: `rm -rf`, `git push`, `systemctl`, deploy-type commands.
- Gate: bridge must forward permission prompts to Telegram buttons. If not
  supported, install in-process permission plugin alongside (verify at build time).

### Phase 5 — VSCode jump-in
- Server: per-project `.vscode/settings.json` with `remote.forwardPorts`
  (app port auto-detected from project type).
- Laptop: SSH entry `Host devbox → <own domain>, user, key` in `~/.ssh/config`.
- Telegram `/open <project>` → bot replies with deep link:
  `vscode://vscode-remote/ssh-remote+devbox/<project-path>`
  → one click on laptop = VSCode opens connected to server, ports auto-forward,
  click forwarded port → browser test of the app.
- Optional later: small helper on laptop to auto-open without the click.

### Phase 6 — Pilot
- Wire 1–2 real projects; flow: prompt from phone → agent works → inspect
  diff in VSCode → run app via forwarded port → iterate.

## Security

- TG bot token in env only, never committed (same rule as bid-scan `.env`).
- OpenCode API bound to localhost, token-authed, not internet-exposed.
- SSH: key-only auth in `sshd_config`.
- User allowlist in bridge; deny all others.

## Open items at build time

- Confirm `gabriel-trigo/opencode-telegram-bridge` forwards OpenCode permission
  prompts (hybrid autonomy); fallback to in-process permission plugin.
- Confirm deep-link URI format against installed VSCode version.
- Separate bot token creation via @BotFather.
