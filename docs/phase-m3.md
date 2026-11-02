# Phase M3 — Bid writer

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`. Scope: any custom-software
> request, templates adapt per `request_type`.
> Depends on: M2 done.

## Client prerequisites (blocking — from PLAN.md §8 items 1–5)

1. Agency/freelancer name
2. Portfolio links (site, Upwork profile, case studies)
3. 2–3 short past-work blurbs (problem → built → result)
4. Pricing tiers (quick fix / workflow build / retainer …)
5. Tone: casual / professional / mixed-language

## Files

- `profile_seed.py` — loads client answers into `profile` table (row id=1).
- `pipeline/bid_writer.py` — per-source templates (PLAN.md §5), LLM.
- `alerts/telegram.py` — alert message gains draft block.

## Template rules (per source)

- **Reddit / communities:** helpful-answer style — 2-line solution sketch
  first, genuinely answer the question, then one line offering to build it +
  disclosure of the service. Public thread reply only, never cold-DM.
  Non-automation requests get one adapted line confirming the category.
- **Make.com Hire Help:** short pitch + portfolio link + fixed-price tier.
- **Facebook:** casual 1–2 sentences, optional light emoji, end with a
  question hook. Paste-ready.
- **Upwork:** standard proposal — 1 intro line referencing their specific
  pain, 3-bullet plan, price range, CTA. Human sends.
- **X / Threads:** ≤ 280 chars, one value statement + question.

Draft language matches the original post's language (auto-detected, fallback
from `profile.tone`).

## State handling

- ✅ Approve → status `approved`, draft stored.
- ✏️ Edit → round-trip typed correction (one TG round-trip).
- ❌ Reject → status `archived`.

## DoD

- Pressing ✅ on a TG message yields a paste-ready bid draft.
- Drafts use client profile facts only — no invented credentials/results.

## Gate check with client

Client rates 5–10 generated drafts; tone adjusted before M4.
