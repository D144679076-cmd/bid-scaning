# Phase M9 — Source Balance & Diversity

Date: 2026-11-05
Status: PLANNED — awaiting client review
Problem (client 2026-11-05): Telegram feed is nearly 100% Freelancer job
cards. Sources lack variety: Reddit dies in the payment gate + HTTP 429s,
Facebook session expired silently, LinkedIn paused by killswitch, so the
only thing still flowing is Freelancer (266 alerted rows on Nov 4 alone).

---

## 1. Current state (measured 2026-11-05)

| Source | Rows | Drafted/alerted | Unpaid | Last output | State |
|---|---|---|---|---|---|
| freelancer | 286 | 266 | 1 | Nov 4 | flooded |
| reddit | 421 | 15 | 256 | Nov 4 | gate-blocked + 429 storms |
| make | 51 | 11 | 34 | Nov 4 | mostly unpaid |
| upwork | 20 | 14 | 6 | Nov 4 | fine, small |
| facebook | 7 | 0 | 7 | Nov 3 | session expired, silent |
| linkedin | 1 | 0 | 1 | — | killswitch paused (2 login-wall hits) |
| x | — | — | — | — | disabled (client 2026-11-03) |

Root causes:

1. **No per-source quota.** Collector returns 10–65 Freelancer cards/cycle;
   every card has "Avg Bid $" so it passes the payment gate; classifier
   scores ≥6; `classifier.max_per_cycle: 12` + `alerts.max_per_run: 15`
   are one shared pool → Freelancer fills it first, every cycle.
2. **Payment-gate asymmetry.** Community posts (Reddit/Make) rarely contain
   `$`/budget/hire signals → `unpaid` → never alerted. Job-feed tiles always
   carry a price. Same rule, opposite outcome per source type.
3. **Reddit health.** Constant 429/SSL errors: 7 subs × frequent polls from
   one IP outruns RSS rate tolerance.
4. **Session health unmonitored.** FB = 0 collected since Nov 3 with no TG
   notification; LinkedIn auto-paused with no re-login prompt.
5. **Freelancer filter leak.** "dallas-hvac-promo-videos" (AV editing) passed
   the M8 require/reject filter because the probe reads only the first 260
   chars of combined text.

## 2. Build steps (order = impact)

### B1 — Per-source alert fairness (first, fixes the visible problem) ✅ 2026-11-05

- DONE: `run_pipeline._fair_queue` (round-robin by source, per-source
  cap, `0` mutes a source; config `alerts.per_source_per_cycle: 3`) +
  runtime `/quota` command (`data/source_overrides.json`).
- TODO: source emoji + name prefix in alert messages (nice-to-have).

- New config `alerts.per_source_per_cycle` (default 3): when building the
  instant-alert queue, group by source, interleave round-robin
  (freelancer, upwork, make, reddit, …), then cap per source.
- Add source emoji + name prefix to alert messages so the mix is visible at
  a glance.
- File: `run_pipeline.py` (queue build), `alerts/telegram.py`, `config.yaml`.

### B2 — Per-source collector caps ✅ 2026-11-05

- DONE: `sources.<name>.max_items` runtime cap via `/quota <src> cap <n>`
  (override file) enforced in `run_pipeline`; FB additionally caps asks
  per group (5) in `fb_feed.py`.

- New config `sources.<name>.max_items_per_cycle` (freelancer default 8):
  trim collector output after dedup-safe ordering (existing items first,
  newest first by posted text).
- Keeps any single source from hogging the classifier cap (12) and draft
  budget (5).
- File: `run_pipeline.py`, `collectors/upwork_feed.py`, `config.yaml`.

### B3 — Reddit recovery (RSS only, no auth per AGENTS.md)

- Stagger subreddits across cycles: poll 2–3 subs per run instead of all 7
  at once; rotate the list to keep per-sub interval at ~30–60 min.
- On HTTP 429: back off that subreddit for 30 min (persist in
  `data/reddit_backoff.json`), never hammer through a rate limit.
- Explicit User-Agent header (Reddit robots etiquette:>) for RSS pulls.
- File: `collectors/reddit.py`, `config.yaml` (`poll_rate_minutes`,
  `subs_per_cycle`).

### B4 — Session health watchdog (FB / LinkedIn silent death)

- Extend watchdog: a session source (facebook/linkedin) returning 0 items
  for N cycles (default 6) while enabled → TG alert "session likely expired,
  run fb_login / manual LinkedIn login".
- Record LinkedIn paused state into the alert so the client knows why.
- File: `services/watchdog.py`.
- Update 2026-11-05: root-cause check for FB's 0-item silence landed in
  `docs/fb-scan-report.md` — FB group feed serves an un-hydrated skeleton
  to headless chromium (session is valid; the home feed still renders).
  A distinct `fb-skeleton` warn line + watchdog trigger became the fix
  anchor; see that report for restore options.

### B5 — Freelancer relevance tightening

- Probe = separate title + first 400 body chars; reject wins checked on
  both; add missing reject words: `promo video`, `av editing`, `audio`,
  `voice`, `animation`, `subtitles`, `transcripts`.
- Keep M8 require/reject design; only widen the probe and list.
- File: `collectors/upwork_feed.py`, `config.yaml`.

### B6 — Make/Reddit unpaid promotion (OPTIONAL — needs client decision)

- Today: no payment signal → `unpaid`, never alerted (hard rule). Community
  posts die from this. Optional M2-style step: LLM verifies "real hiring /
  budget intent" for posts that lack regex signals but contain hire words
  ("need a developer", "build me"); promoted → classified + digest.
- This changes the 2026-11-02 payment rule — client must approve scope;
  otherwise Reddit/Make stay digest-only and diversity comes from B7.

### B7 — New sources (diversity, compliance-first, read-only via code)

- LinkedIn ✅ RE-OPENED 2026-11-06: killswitch entry for `linkedin` reset
  (2 login-wall hits from 2026-11-04 — session itself was valid, `li_at`
  364d left). Two collector fixes while opening it:
  `linkedin_feed._parse_posts` now issues per-post pseudo-URLs (same
  url-UNIQUE collapse bug as FB — max 1 row/cycle before), and
  `page.content()` navigation race gets a settle-retry (live error seen
  first probe). Live smoke: 4 posts extracted, no login-wall. EN search
  query as configured; add VI/ask-flavored search keywords later if the
  LinkedIn feed turns out ask-poor.- FB addition (2026-11-05 check, `docs/fb-scan-report.md` addendum): the
  real tool-build demand on FB is in Vietnamese tool-market groups
  (`thuecodetooltheoyeucau`, `codetoolwebappuytin`, `giacongphanmem`, …) —
  feeds that hydrate properly, unlike the current education-group pool;
  posts are Vietnamese teencode → pipeline needs VI keywords +
  payment_signals or every VN lead dies at the payment gate.

Candidates (each enters the standard pipeline: dedup → spam → payment gate
→ classifier → alert, same as everything else):

| Source | Method | Compliance | Notes |
|---|---|---|---|
| r/forhire, r/freelance_forhire, r/jobbit | Reddit RSS (new subs) | Same as existing Reddit — official public RSS, low poll | `[Hiring]` posts are paid-signal rich, will pass gate |
| Guru / PeoplePerHour public feeds | RSS if public page offers it without login | Read-only, no auth | Verify during build; skip if login-required |
| LinkedIn | Re-login + existing `linkedin_feed.py` | Feed view only | Blocked by B4 until client re-logs in |

- Config: new `sources.<name>` blocks; nothing auto-enabled without client OK.
- caveat: client picks the list; nothing new goes live before approval.

### B8 — Diversity reporting

- Daily digest gains per-source counts (collected / unpaid / low / alerted
  per source + % share) so imbalance is visible daily.
- `alerted` per-source share tracked in stats dict.
- Files: `alerts/digest.py`, `run_pipeline.py`.

## 3. Definition of done

- Trailing 24h instant alerts: no single source >50%; every healthy enabled
  source appears in the queue daily.
- Reddit cycles: no more than intermittent 429s; backoff visible in log.
- FB/LinkedIn dead session triggers a TG alert within ~2 h.
- All existing tests stay green (28/28); new tests for per-source queue
  interleave + caps (`tests/test_m9.py`).
- PLAN.md milestone table gains M9 row; AGENTS.md untouched rules stay true
  (no auto-send, RSS-only Reddit, read-only collectors, .env secrets).

## 4. Needed from client

1. Approve per-source alert quota numbers (proposed: 3/source/cycle,
   alerts/run cap stays 15).
2. Approve B6 (LLM unpaid rescue) or decline — changes the payment rule.
3. Approve new source list (B7) before anything is enabled.
4. Re-run `fb_login.py` + LinkedIn manual login when prompted.
5. Confirm freelancer poll rate preference (category page is static; may
   lower to 60 min).

## 5. Out of scope (M9)

- Any auto-sending (still manual approve on Telegram).
- Upwork/Freelancer API keys (still ToS-risky, keep feed view only).
- X/Twitter (stays disabled per 2026-11-03 client decision).

## 6. Post-M9 fix — TG approve buttons dead (2026-11-06)

`alerts/callbacks.py` gated the ✅✏️❌ callbacks on `status='lead'`, but since
M3 alerts fire on rows already in status `'drafted'` (draft_stage runs before
alerting) → every press matched 0 rows; fake success toast hid it. Evidence:
567 rows stuck `'drafted'`, 0 `'approved'`/`'archived'` since M3. Fix commit
`fe15b7a`: gate now `status IN ('lead','drafted')`, honest skipped-toast
(rowcount), getUpdates network errors soft-fail instead of killing the run.
Image rebuilt, `bidscan-app` recreated. Full suite green (test_m5 killswitch
failure was state pollution from a stale `unittest-src` key in
`data/killswitch.json` — synthetic key removed).
