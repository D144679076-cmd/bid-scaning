# Phase M4 — Facebook collector (experimental, read-only)

Status: CODE READY 2026-11-03 — `fb_login.py` + `fb_feed.py` +
`pipeline/safety.py` (kill-switch, delays, storageState) all testable;
`facebook` source flag OFF in config until the client completes the
one-time manual login + group allowlist. Playwright 1.64.1 + chromium
installed. Run `python3 -m collectors.fb_login` → storageState lands in
data/session_facebook.json → set `sources.facebook.enabled: true`.
Supervised 3-day run (DoD still pending).

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`.
> Depends on: M3 done. Risks accepted by client (unofficial — Groups API
> removed by Meta April 2024, Playwright + own logged session only).

## Client prerequisites (blocking — PLAN.md §8 items 6)

- FB account to use — NOT the main personal account.
- Target group list (allowlist).
- One-time manual login session.

## Files

```
collectors/fb_login.py   one-time manual login → Playwright storageState file.
                         Session only inside storageState; NO passwords stored.
collectors/fb_feed.py    group feed scroll + post extraction, allowlist only.
pipeline/safety.py       randomized delays 3–10 s, UA/viewport rotation,
                         1 poll per group per 2–4 h, STRICTLY read-only
                         (never like/comment/post), captcha/login-wall
                         detection → kill-switch.
```

## Safety hardening

- Auth via `storageState` only — credentials never in n8n or repo (AGENTS.md).
- Read-only always; human sends everything manually.
- Kill-switch: 2+ captcha/login-wall hits → pause FB branch + urgent TG alert.
- Posts flow through the SAME pipeline order — collector → dedup → spam
  filter → classifier → alert (AGENTS.md, no reorder/skip).
- FB leads marked **manual send**: alert button provides copy-ready draft.

## DoD

- FB group requests appear in TG with paste-ready draft.
- Kill-switch tested by simulating a login wall.
- Delays verified in log.

## Gate check with client

3 days supervised run before expanding the group list.
