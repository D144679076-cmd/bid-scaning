# Bid Scanning System — Build Plan (v1 for review)

Date: 2026-11-02
Status: DRAFT — awaiting client review
Goal: Auto-discover people posting CUSTOM SOFTWARE / TOOL requests of any kind
(automation workflows, scripts, bots, scrapers, web/app dev, integrations,
SaaS help — not automation only) across social platforms, classify buying
intent, auto-draft proposals (bids), and route them through a human approval
queue on Telegram before anything is sent.

---

## 1. Decisions (confirmed with client)

| Item | Decision |
|---|---|
| Sources | Reddit + Make Community, Facebook groups, Upwork/Freelancer, X/Threads/LinkedIn — all from day 1 |
| Facebook unofficial scraping | Approved, must have from day 1 (ban risk accepted) |
| Bid sending mode | Draft + human approve via Telegram (no auto-send anywhere) |
| Stack | n8n orchestrator + Playwright collectors + Telegram bot notifications/interaction + LLM API |
| Client profile | Client will provide (name, portfolio, past work, pricing tiers) |

---

## 2. Source matrix

| # | Source | Collection method | Poll rate | Send mode |
|---|---|---|---|---|
| 1 | Reddit — r/automation, r/nocode, r/AI_Agents, r/AiAutomations, r/smallbusiness, r/Entrepreneur, r/n8n | Public JSON endpoints (https://www.reddit.com/r/<sub>/new.json), HTTP node, no auth | 10–15 min | Draft + manual send in thread |
| 2 | Make.com Community — "Hire a Pro / Hire Help" board | Forum RSS / lightweight scrape | 30 min | Draft + manual send |
| 3 | Facebook groups (agency/SMB/automation groups, per allowlist) | Playwright + logged-in session (storageState), feed scroll + post extraction | 2–4 h per group, randomized delay | MANUAL send only — system copies draft to clipboard, human pastes |
| 4 | Upwork / Freelancer job feeds | Playwright, feed view only; never submits proposals | 30–60 min | Manual send — system opens job page with draft ready |
| 5 | X / Threads / LinkedIn | X search scrape (or Nitter-style mirror) via HTTP; LinkedIn feed via Playwright | 1–2 h | Click-through reply, manual send |

### Compliance notes (must stay visible)

- **Meta removed the Facebook Groups API in April 2024 (Graph API v19).** No
  official third-party read/write access exists. FB collector is therefore
  unofficial browser automation under the client's own logged session.
  Risks: FB account ban (bot detection), ToS violation. Mitigations in §6.
- **Upwork/Freelancer ToS prohibits scraping and unauthorized automation.**
  Violation = account restriction or permanent ban. Upwork's official API/API
  key path exists but is rarely granted and forbids scraping — we do NOT rely
  on it in v1. Collector is read-only feed viewing; proposal submission stays
  100% human.
- Reddit public JSON is permitted usage in practice at moderate rates; keep
  polling low and cached.

---

## 3. Architecture

```
COLLECTOR (per source, scheduled workflow)
   │
   ▼
NORMALIZE + DEDUP   (SQLite, URL/fingerprint unique key)
   │
   ▼
INTENT CLASSIFIER (LLM)
   - buying-intent score 0–10  (score < 6 → status `low`, shown in daily
     digest sorted by score desc — not archived, per client 2026-11-02)
   - request_type: automation | script/bot | scraper | web/app dev |
     integration/SaaS | other software
   - extract: task_type, tools_needed[], budget, deadline,
     contact channel, language
   │
   ▼
BID WRITER (LLM)   ← reads client PROFILE table
   - per-source template (see §5)
   │
   ▼
TELEGRAM APPROVE QUEUE
   ✅ Approve / ✏️ Edit / ❌ Reject / 🔗 Open source
   │
   ▼
SEND (manual for FB & Upwork; draft-ready for others)
   │
   ▼
FOLLOW-UP TRACKER (reminder if no reply in 24–48 h)
   +
DAILY DIGEST 09:00 (new requests + low-score backlog sorted by score desc,
stats, spam filtered count)
```

---

## 4. Data model (SQLite)

```sql
CREATE TABLE requests (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,            -- reddit | make | facebook | upwork | x | linkedin
  url TEXT NOT NULL UNIQUE,        -- dedup key
  fingerprint TEXT NOT NULL UNIQUE, -- M1 migration note: sha256 of normalized text (AGENTS.md dedup rule); added in M1 build
  author TEXT,
  posted_at TEXT,
  raw_text TEXT NOT NULL,
  score INTEGER,                   -- 0–10 buying intent
  task_type TEXT,
  tools TEXT,                      -- JSON array
  budget TEXT,
  deadline TEXT,
  contact_channel TEXT,
  language TEXT,
  status TEXT DEFAULT 'lead',      -- lead|drafted|approved|sent|replied|won|lost|low|archived
  draft_text TEXT,
  sent_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE followups (
  request_id INTEGER REFERENCES requests(id),
  due_at TEXT,
  done INTEGER DEFAULT 0
);

CREATE TABLE profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT,
  portfolio_url TEXT,
  past_work TEXT,       -- JSON array of 2–3 blurbs
  pricing_tiers TEXT,   -- JSON
  tone TEXT             -- casual | professional | mixed-language
);
```

---

## 5. Bid writer — per-source templates

Prompt inputs: `profile` row + normalized request + source-specific style rules.

- **Reddit / communities (r/automation, r/nocode, …):** helpful-answer style.
  2-line sketch of the solution first, genuinely answer the question, then
  one line offering to build it + disclosure that you offer the service.
  Public thread reply only. Never cold-DM. Never hidden promotion (ban reason).
  Non-automation software requests (web app, scraper, script) get adapted: one
  line confirming you build that category, then solution sketch + offer.
- **Make.com Hire Help:** short pitch + portfolio link + fixed-price tier.
- **Facebook groups:** casual 1–2 sentences, optional light emoji, end with a
  question hook ("Do you want me to sketch the workflow for you?"). Paste-ready.
- **Upwork:** standard proposal — 1 intro line referencing their specific pain,
  3-bullet plan, price range, CTA. Human opens page and sends.
- **X / Threads / LinkedIn:** ≤ 280 chars for X, one value statement + question.

Language: match the original post's language (auto-detected), fallback
configurable in profile.tone.

---

## 6. Facebook collector — safety hardening

- Auth: manual login once, session persisted as Playwright `storageState`.
  FB credentials never stored in n8n.
- Behavior: randomized delays 3–10 s between scroll steps; 1 poll every
  2–4 h per group; read-only — NEVER like/comment/post via bot.
- Detection escape hatch: kill-switch workflow — if 2+ captcha/login-wall
  hits occur, pause the FB branch automatically + urgent Telegram alert.
- Allowlist: only group IDs/names explicitly added by client.
- Content filter: keyword + spam-noise filter before classification.

---

## 7. Build milestones

| Milestone | Scope | Definition of done |
|---|---|---|
| **M1 — core base** ✅ CLOSED 2026-11-02 | n8n + SQLite + Reddit collector + dedup + basic Telegram lead alerts (link + text, no LLM yet) | New Reddit requests appear in TG within 15 min |
| **M2 — classify** ✅ CODE COMPLETE 2026-11-03 (gate check pending) | LLM classifier (score + extract) wired into pipeline + TG approve buttons | Score ≥ 6 → instant alert + buttons; score < 6 → shown in daily digest sorted by score desc |
| **M3 — bid writer** ✅ code + tests green 2026-11-03, drafts live; ⚠ blocked on client profile.yaml | profile row + LLM draft generation shown in TG message | Press ✅ → draft ready to copy/send |
| **M4 — Facebook** ✅ code ready 2026-11-03; ⚠ awaiting client: manual login + group allowlist, then 3-day supervised run | Playwright FB collector + storageState + kill-switch | FB group posts show in TG with paste-ready draft |
| **M5 — rest + tracker** ✅ live 2026-11-03: Make forum LIVE, follow-up tracker LIVE, gemma4:31b-cloud LLM; ⚠ Upwork/Freelancer/X/LinkedIn coded but OFF until sessions | Upwork/Freelancer, X, Threads/LinkedIn collectors + follow-up tracker + daily digest | All 5 source types live; no-reply reminders fire |

Each milestone reviewed with client before starting the next.

### Detailed phase plans (one file per phase)

| Phase | Plan file |
|---|---|
| M1 — Foundation & Reddit pipeline | `docs/phase-m1.md` |
| M2 — LLM classifier + approvals | `docs/phase-m2.md` |
| M3 — Bid writer | `docs/phase-m3.md` |
| M4 — Facebook collector | `docs/phase-m4.md` |
| M5 — Remaining sources + tracker | `docs/phase-m5.md` |

Each phase file contains: files/deliverables, tasks, safety rules where
applicable, DoD, gate check with client, and needed client input.
Status per phase lives in its file header as a one-line marker.

## 8. Needed from client (before M3)

1. Agency/freelancer name
2. Portfolio links (site, Upwork profile, case studies)
3. 2–3 short past-work blurbs (problem → what you built → result)
4. Pricing tiers (e.g. quick fix $X / workflow build $Y / retainer $Z)
5. Tone: casual / professional / mixed-language
6. Facebook: login session + list of target groups (and an agreement that the
   FB account used is not the main personal account)
7. Telegram: bot token + chat ID for the approve queue

---

## 9. Out of scope (v1)

- Auto-submitting proposals on Upwork/Freelancer (ToS ban risk — rejected)
- Posting to FB groups via automation (API removed 2024; manual paste only)
- Multi-user/team roles, web dashboard (CLI + Telegram is the whole UI in v1)
- CRM beyond status field on `requests`
