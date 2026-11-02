# Phase M5 — Remaining sources + follow-up & digest

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
alerts/digest.py              daily 09:00: new leads, sent count, stats.
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
