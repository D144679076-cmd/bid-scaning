# Phase M5 — Remaining sources + follow-up & digest

Status: MOSTLY SHIPPED 2026-11-03 —
- `collectors/make_forum.py` LIVE (Discourse RSS: latest + `hire-a-pro`
  category id 50; 53 real items in first run; LLM classifier only allowed
  JD-shaped ones; fixture `tests/fixture_make_feed.rss`).
- `collectors/upwork_feed.py` (Upwork feed view + Freelancer search),
  `collectors/x_search.py`, `collectors/linkedin_feed.py` — code ready,
  OFF in config until sessions (login-walls tolerated → safety
  kill-switch after 2 hits).
- `pipeline/followup.py` LIVE — cron `*/30`: approved + sent > 24 h
  without follow-up → private TG reminder, once per request (reuses
  existing `followups` table — NO new column/no migration).
- LLM: client added `LLM_API_KEY` → cloud-first now real: gemma4:31b-cloud
  (free plan), 0.8 s vs 32 s local. `_parse_json` tolerates ```json fences.
- Multi-collector aggregation in `run_pipeline.py` — every enabled source
  flows the SAME dedup → spam → payment → classifier → alert order.
- Tests: `tests/test_m5.py` 10/10 (make normalize, de-noiser, kill-switch,
  loginwall detector, follow-up once-only).

> Index: see `docs/PLAN.md` §7. Rules: `AGENTS.md`.
> Depends on: M4 done.

## Files

```
collectors/make_forum.py      "Hire a Pro / Hire Help" board — RSS/light scrape.
collectors/upwork_feed.py     Playwright, feed VIEW ONLY.
                              HARD RULE (AGENTS.md): never submit proposals
                              via code; alerts only, human sends.
collectors/x_search.py        X search scrape, buying-intent phrases
                              ("looking for someone to automate…",
                              "need a developer to build…", etc.).
collectors/linkedin_feed.py   Playwright, feed view only.
pipeline/followup.py          cron: no reply 24–48 h after sent → TG reminder.
alerts/digest.py              daily 09:00: new leads, score<6 backlog sorted
                              by score desc (new rule 2026-11-02), sent
                              count, stats.
```

## Reuse

All new sources reuse the single pipeline; only collector adapters differ.
Same dedup, spam filter, classifier, alert flow. Same manual-send policy.

## DoD

- All 5 source types live end-to-end:
  Reddit · Make forum · Facebook · Upwork/Freelancer · X/Threads/LinkedIn.
- Follow-up reminders fire on no-reply.
- Daily digest arrives.
- `AGENTS.md` + `docs/PLAN.md` milestone statuses updated when milestone
  lands (AGENTS.md sync rule).

## Gate check with client

2-week full run review; tune poll rates, keywords, templates from real data.
