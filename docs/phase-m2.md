# Phase M2 — LLM classifier + interactive approvals

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`.
> Depends on: M1 done.

## Files

- `pipeline/classifier.py` — LLM call, prompt returns strict JSON.
- `alerts/telegram.py` — extended with inline buttons.
- n8n Telegram-callback workflow (button press handling).

## LLM setup

- New `.env` key (provider decided at start of M2: cloud API key or local
  Ollama). Never stored in n8n node credentials (AGENTS.md config rule).

## Classifier output (strict JSON)

```json
{
  "score": 0,
  "request_type": "automation",
  "tools": [],
  "budget": null,
  "deadline": null,
  "language": "en"
}
```

`request_type` enum: `automation | script/bot | scraper | web/app dev |
integration/SaaS | other software`. Prompt covers ANY custom-software request,
not automation only (scope decision 2026-11-02).

## Rules implemented (updated 2026-11-02 per client — low-score still shown)

- score ≥ 6 → status `lead`, instant alert with extracted fields + buttons:
  ✅ Approve / ✏️ Edit / ❌ Reject / 🔗 Open source.
- score < 6 → status `low`, NO instant alert; displayed in the DAILY DIGEST
  message, sorted by score descending. Not silently archived anymore.
- Button presses handled by callback workflow → update `requests.status`.

## DoD

- Noise archived silently; every score ≥ 6 request appears with fields +
  working buttons.
- Low-score (score 1–5) requests visible in next daily digest, sorted by
  score desc, with score shown next to each entry.
- State survives bot restart (statuses in DB, never in memory).

## Gate check with client

Classification accuracy on ~20 real posts reviewed together → M3.

## Client input needed for M2

- Choice of LLM provider — RESOLVED 2026-11-02: Ollama dual-profile built in.
  Local `qwen3:1.7b` pulled (7GB RAM cap → gemma4/deepseek-v4-flash cannot
  run locally; they are Cloud-only). `cloud` profile = one-line switch in
  config.yaml + LLM_API_KEY in .env whenever the client wants the upgrade.
