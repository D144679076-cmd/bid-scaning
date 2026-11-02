# Phase M2 — LLM classifier + interactive approvals

Status: CODE COMPLETE 2026-11-03 — pending: client gate check (press the
buttons once in Telegram, verify digest message at 09:00, confirm chat
quality). Full edit round-trip note: button ✏️ stores your typed note now
(status 'edited'); this correction re-drafting lands in M3 per plan.

Extras shipped during M2 (double from original scope):
- dual Ollama (local qwen3:1.7b + cloud deepseek-v4-flash-0731) cloud-first
  failover chain [cloud → local]
- `is_request` JD-shaped-post rule (client feedback: blogs ≠ requests)
- collector de-noiser for blog/showcase title shapes
- per-cycle classification cap + unscored-lead rescue drain

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

2026-11-03 UPDATE (client feedback "Reddit feed = blogs, not JDs"):
- `is_request` new LLM field. Blog/discussion/showcase/tip → `false` →
  score limited to ≤ 2 (falls to daily digest, never instant alert).
- Paid exchange for NON-labor (buying credits/accounts/data/trade) →
  `is_request=false`. Only requests for someone's build/automation labor
  count.
- Collector early de-noiser: `[discussion]/[blog]/[showcase]/i built/i made/
  case study/...` title shapes skipped before LLM (cheap filter).
- local config memory note: `qwen3:1.7b` pulled; `deepseek-v4-flash-0731`
  is Ollama-CLOUD-only; `gemma4` local (6.6 GB) does not fit this machine.

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

## Gate check with client (how to verify, 5 min)

1. Wait one 15-min cron cycle → new TG message should be a JD-shaped post
   with ⭐ score / request_type / 💰 / ⏳ fields + 4 buttons
2. Press ❌ Reject on one → status flips to archived
3. Press ✏️ Edit on another → type a note in chat → status 'edited'
4. Tomorrow 09:00 → digest with low-score backlog sorted by score desc
5. If chat quality looks right → M3 start

## Client input for M2+

- LLM provider RESOLVED 2026-11-02/03: Ollama dual-profile (local qwen3:1.7b
  pulled; gemma4 + deepseek-v4-flash are Cloud-only and fit the machine
  limit; `LLM_API_KEY` in .env upgrades to cloud — chain [cloud → local]).
