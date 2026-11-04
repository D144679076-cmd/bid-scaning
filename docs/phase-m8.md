# Phase M8 — Freelancer relevance + Facebook group reach (B1)

Status: SHIPPED 2026-11-04 (P1 + P2A + B1; B2 parked pending client sign-off).

1. Freelancer returns design/typing/writing jobs — should return web/app,
   automation, bot, CS, dev jobs only
2. Facebook should scan ALL MMO + freelancer groups, and comment sometimes
   to surface jobs/potential jobs

---

## P1 — Freelancer job relevance

### Root cause
`/jobs/{category}/` is a CATEGORY bucket, not a keyword search. "Automation"
category includes off-site/misc rows (translation, board-member, HVAC promo
video, animation) because posters pick that taxonomy loosely. Our
`search_query: automation bot scraper` is currently only used for the URL
slug (`/jobs/automation/`), never applied as a filter.

### Changes
1. **Probe first (read-only):** does a keyword project search render
   login-less? `https://www.freelancer.com/job-search/projects/?keyword=...`
   previously rendered nothing — recheck with longer wait + scroll; also try
   the mobile host `m_freelancer.com` patterns. If a keyword URL renders,
   switch URL = query applied server-side, keep card extraction as-is.
2. **Guaranteed fix regardless of (1): in-code relevance filter**
   - config additions:
     ```yaml
     sources:
       freelancer:
         require_keywords: [web, app, automation, bot, scraper, crawl,
                            script, develop, developer, software, code,
                            api, integration, ai, chatbot, discord,
                            telegram, shopify, wordpress, python, node]
         reject_keywords: [design, logo, typing, transcription, writing,
                           translate, translation, video editor, animation,
                           voice over, data entry, virtual assistant,
                           illustration, photoshop, caption, subtitle]
     ```
   - filter AFTER card extraction, BEFORE dedup: title+first 200 chars must
     contain ≥1 require word AND 0 reject words; drop otherwise
   - same filter shape reusable for upwork (optional flag) — upwork already
     search-server-side so default stays off there
3. Keep payment gate + classifier order unchanged (filter is part of the
   collector's de-noising, like SKIP_MARKERS in make_forum).

### DoD
- 10 consecutive fresh freelancer rows: 100% dev/automation/app type
- counts stay stable (46 rows/cycle now; expect ~15–25 traces after filter)
- tests: fixture card texts pass/filter correctly (unit)

## P2A — Facebook: scan all MMO / freelancer groups (READ-ONLY)

### Changes
1. **Group auto-discovery (uses saved session, still read-only):** from FB
   search results pages for terms like "make money online", "freelance",
   "automation jobs", collect `facebook.com/groups/<id-slug>` links; dedupe;
   merge into `sources.facebook.groups` allowlist (cap 25 groups).
2. **Sharded polling to stay polite:** full sweep per cycle is too heavy —
   shard groups into `poll_groups_per_cycle` (default 10) and rotate; each
   group still polled ≤ 1× per 2–4 h (poll_hours unchanged).
3. Keep all existing guards: own-echo filter, login-wall kill-switch, 15
   cap/group, randomized delays. Watchdog reports group health.
4. Optional `sources.facebook.keywords_filter` (same require/reject shape as
   P1.2) — MMO groups are noisy with non-job memes; default: only a light
   skip-list, let the classifier decide.

### DoD
- allowlist grows from 8 → up to 25 groups without config file edit (=
  discovery runs, writes back to config-driven flow, humanly reviewable)
- FB rows in DB/Telegram carry real group post bodies (own echoes gone)

## P2B — Commenting for jobs (NEEDS CLIENT DECISION — compliance)

**Current hard rule (AGENTS.md, docs): collectors are strictly read-only;
never like/comment/post/DM.** Auto-commenting changes the compliance
envelope. Two modes:

| Mode | Flow | Compliance |
|---|---|---|
| **B1 — Assisted comment (recommended first)** | Post without enough info → friendly comment DRAFTED into Telegram wie bids → ✅ approve → human pastes it manually | Unchanged envelope; zero auto-send |
| **B2 — Semi-auto comment (needs explicit sign-off)** | Approved comment drafts (same ✅ flow) are posted by the collector account itself via UI automation; caps: ≤3 comments/day, only posts with payment signal, randomized 30–120 s delays, kill-switch + TG notice per comment | CHANGES the rule — documented exceptions in AGENTS.md + PLAN; `sources.facebook.auto_comment: false` default |

Recommended sequencing: ship P1 + P2A now; enable **B1** immediately after;
revisit **B2** after 1 week of B1 data (if manual paste is too slow).

Comments only ever target posts that ALREADY ask for bot/automation/dev
work (score ≥ payment-gate) — never cold outreach.

## Order of work
1. P1 probe + relevance filter (collector-only, no gate/classifier change)
2. P2A discovery + sharded polling
3. P2B B1 assisted-comment drafts (needs no rule change)
4. (later, after client sign-off) P2B B2

---

## Shipped (2026-11-04)

### P1 — relevance filter (LIVE)
- `config.yaml → sources.freelancer.require_keywords / reject_keywords`
  (client-editable anytime; applies next cycle)
- `_relevance_ok()` in `collectors/upwork_feed.py`: title + first 260 chars,
  word-boundary match; rejects include seo/marketing/campaign/design/typing/
  writing/translation/video/animation/data-entry
- Proof: 46 raw cards → 11 dev/automation rows; sample checks: "Shopify
  Store Sales Boost Campaign" DROP, "Multi-Tenant Hospitality WiFi SaaS" PASS

### P2A — FB discovery + shards (LIVE)
- `discover_groups()`: FB group search (5 MMO/freelance terms) → ids merged
  into `data/fb_groups.json` (config stays primary allowlist; cap 25)
- `_shard()`: `data/fb_poll_state.json` tracks last-poll per group; each
  cycle polls the `poll_groups_per_cycle` (10) OLDEST-polled groups that are
  due (≥ poll_hours) — no group hammered, allowlist can grow to 25
- read-only preserved: search pages are read, nothing clicked/liked

### B1 — assisted comment drafts (LIVE, client-approved)
- `pipeline/comments.py`: FB rows score ≥ 6 with NO budget → LLM writes ONE
  short friendly scope/budget question; persisted to `requests.comment_text`
- Schema migration (M8 note): `ALTER TABLE requests ADD COLUMN comment_text
  TEXT` — auto-applied at connect(), idempotent
- TG alert shows `💬 COMMENT DRAFT (B1: approve → paste manually)` block
- COMPLIANCE: zero auto-send — comment is a draft like bids; the human
  copies it into the post. AGENTS.md envelope unchanged.

### Config knobs added
```yaml
sources.freelancer.require_keywords / reject_keywords
sources.facebook.poll_groups_per_cycle: 10
sources.facebook.discovery: true / discovery_cap: 25
sources.facebook.comments_per_cycle: 3
```

### Tests
`tests/test_m8.py` (5): filter keep/drop/require-match, comment target +
persist + budget-skip, TG 💬 block. Suite total 28 green.
