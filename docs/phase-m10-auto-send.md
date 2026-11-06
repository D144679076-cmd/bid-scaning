# Phase M10 — Auto-send bids per platform (DRAFT v1, for review)

Date: 2026-11-06
Status: DRAFT — awaiting client review. **Not started. Nothing here is
built yet.**

Goal (as requested by client 2026-11-06): after the owner presses ✅ in
Telegram, the system sends the bid itself —
- Freelancer: submit the proposal post
- Reddit: post the comment reply
- Facebook: post the comment **and** open the inbox / DM the poster

Answer up front: **technically possible, but every one of these crosses a
hard compliance line the project has operated under since M1.** The plan
below defines an opt-in, approval-gated version with explicit client
sign-off, per-platform killswitches, and a supervised trial. It cannot go
live until the client formally amends the rules (§1).

---

## 1. Compliance gate (read first)

Current rules that this phase would change (AGENTS.md hard rules, confirmed
with client 2026-11-02):

| Rule | Effect on M10 |
|---|---|
| "Never auto-send bids/DMs/posts to any platform. All sends human-approved via Telegram (draft + manual send)" | M10 = the core of this phase — amended to "human-approved + system-dispatched" |
| "Collectors are read-only" | Collectors stay read-only; a new **sender** module is separate |
| "Reddit = public RSS feeds, no authentication" | Reddit auto-reply needs an authenticated Reddit account + OAuth app |
| "Upwork/Freelancer: feed view only, never submit proposals via code" | Freelancer auto-proposal submits via logged-in Playwright |
| "FB: never like/comment/post via bot" | FB comment + inbox = logged-in Playwright automation |

ToS / account-risk reality per platform:

| Platform | Auto-send mechanism | Risk | Notes |
|---|---|---|---|
| **Freelancer** | Playwright: open proposal page → fill textarea → click submit | High | Freelancer ToS prohibits automated submission. Best case: detected eventually → account ban (client loses profile/history). Rate limits + sleep rules must mimic human cadence |
| **Reddit** | OAuth "script" app, `api.comment` via `oauth.reddit.com`, own account | High | Reddit detection is aggressive; new/aged account replying with service pitches gets site-wide suspended fast, especially outside r/automation.Disclosure line (already in template §5) is mandatory |
| **FB comment** | Playwright storageState (existing FB session), comment on group post | **Highest** | Groups API gone since 2024; unofficial automation only. Comment + DM double the detection surface. A comment ban often poisons the whole account |
| **FB inbox** | Playwright → open Messenger thread → send first message | **Highest** | Cold-DM automation is explicitly against plan §5 ("never cold-DM" was a rule for Reddit; on FB it's the requested feature). FB weighs unsolicited DM patterns heavily → 24h+ mute, then ban |

**Client decision required before any code:** approve the rules amendment
above in writing (TG message is fine). The builder will update AGENTS.md +
PLAN.md §9 at M10 start to record that approval. Without that, M10 does not
begin.

---

## 2. Recommendation: three modes, phrased as risk levels

| Mode | What happens after ✅ | Risk | Verdict |
|---|---|---|---|
| **A — Send-assist** | System opens the post page with textarea filled + text on clipboard; owner clicks submit | Lowest — no automated submit click | **Recommended for Reddit + FB** |
| **B — Approved auto-send** | System submits itself after ✅ (one press = one send) | Medium-high | Reasonable for **Freelancer** |
| **C — Full auto** | No human press; pipeline auto-sends everything scoring ≥ threshold | Highest, removes human judgment on focus/quality | **Not recommended anywhere** |

Default proposal (client may override):
- Freelancer → Mode B (approved auto-send)
- Reddit → Mode A (fill textarea, human presses send; avoids Reddit auto-posting to the degree possible while keeping one human action)
- FB comment → Mode A first 2 weeks, then Mode B if ban-rate is zero
- FB inbox → Mode A only (open thread + prefill text; **never** automated cold-DM delivery initially)

This satisfies the client ask ("auto send for each platform") at B for the
platform safe enough, and keeps a human finger on the platforms that ban
hardest.

---

## 3. Architecture

```
TELEGRAM ✅ PRESS (unchanged — approval stays mandatory in Mode B/A)
   │  callback approve:<id> → status 'approved'
   ▼
SEND QUEUE (new)  — rows status 'approved' + send_mode not null, not yet sent
   │  worker per platform, cadence like collectors (phase-cadence table)
   ▼
SENDER (per platform, 1 module each)
   - freelancers/send_freelancer.py  → submits proposal form
   - senders/reddit_sender.py        → OAuth app comment (Mode B) or open+fill (Mode A)
   - senders/fb_sender.py            → comment (Mode A/B) + inbox prefill (Mode A)
   ▼
SEND LOG + STATUS UPDATE
   - requests.status → 'sent' | 'send_failed'
   - send_log table: full audit trail
   ▼
TELEGRAM CONFIRM/retry alert   → "📤 Sent on Freelancer • proposal submitted"
```

Pipeline order is unchanged: collector → dedup → spam → payment gate →
classifier → **draft → human approve (TG)** → send queue → sender. Senders
are a client of the approval, never a bypass of it.

### Safety hardening (mirrors M4 FB collector rules)

- **Killswitch per platform (senders vs collectors):** 2+ failed sends or 1
  captcha/login-wall → sender paused for that platform + urgent TG alert; resume = manual `bidscan sender-resume <platform>`.
- **Pacing:** hard caps in `config.yaml senders`: per-platform daily max
  (proposed: Freelancer 8/day, Reddit 5/day, FB comment 6/day, FB inbox 3/day),
  random 3–10 min gaps, human-hours-only window (client local time, e.g. 08:00–21:00).
- **No credential storage:** same as M4 — Playwright `storageState` only,
  manual login once, sessions live in `data/session_*.json`.
- **Draft byte-exactness:** the text submitted = exactly the byte sequence of
  `requests.draft_text` shown in the ✅ message (post-edit note, minus
  truncation). Any drift → abort + alert.
- **Dry-run everywhere:** `senders.dry_run: true` default for 1st week;
  everything runs except the final submit click, logged as `dry_run` in send_log.
- **Audit:** every attempt gets a row (success, fail, misclick catch, screenshot
  on failure kept for 7 days).

### Sessions & detection escape hatches

- Watchdog gains a sender section: session-expiry on any sender platform →
  urgent TG alert < 2h, sender paused (same as FB collector killswitch).
- FB: reuse the M4 captcha/login-wall detector against new screenshots;
  comment/inbox automation raises the stakes → tighten the trigger from
  "2+ hits" to "1 hit" for senders.

---

## 4. Data model (noted migration, per AGENTS.md)

```sql
-- migration block M10 (docs/phase-m10-auto-send.md) — do not run before client approves §1
CREATE TABLE send_log (
  id INTEGER PRIMARY KEY,
  request_id INTEGER REFERENCES requests(id),
  platform TEXT NOT NULL,           -- freelancer | reddit | facebook_comment | facebook_inbox
  mode TEXT NOT NULL,               -- auto | assist | dry_run
  outcome TEXT NOT NULL,            -- sent | failed | paused_captcha | drifted
  screenshot_path TEXT,
  error TEXT,
  attempted_at TEXT DEFAULT (datetime('now'))
);
ALTER TABLE requests ADD COLUMN send_mode TEXT;   -- auto | assist | NULL = manual copy (M1-M9 behavior)
```

Status flow addition: `approved --sender--> sent | send_failed`.
Manual-copy path stays available: if `send_mode IS NULL` the row never
enters the send queue (backwards compatible with everything shipped M1–M9).

---

## 5. Build milestones

| Milestone | Scope | DoD |
|---|---|---|
| **M10a — Freelancer Mode B** | sender module, playbook form path, submit → read back confirmation line → status `sent`; dry_run first | 5 dry-runs → 1 supervised live send → owner confirms in TG; `send_log` row per attempt |
| **M10b — Reddit Mode A (+B optional later)** | OAuth script app, `api/comment` path behind a `mode` flag default `assist` (open + fill, one human click) | fill accurate on 10 posts; if owner later flips Mode B, 1 supervised live send |
| **M10c — FB comment Mode A → B** | comment on group post via existing FB session; killswitch threshold = 1 captcha hit | assist works 10/10; auto-comment only after 14 clean days; FB inbox Mode A: thread open + prefill, never auto-send |
| **M10d — Hardening + full-mode wiring** | watchdog sender section, pacing caps, screenshots-on-failure, `bidscan sender-resume`, TG confirm/retry alerts | sender killswitch fires < 2 min after simulated captcha; suite green incl. new M10 tests |

Each milestone gates on client review (milestone N+1 doesn't start before N
is signed off + supervised.)

---

## 6. Out of scope (M10)

- Upwork auto-send — remains manual copy / feed view (ToS risk accepted to be too high)
- X / Threads / LinkedIn auto-send — X is disabled since M5; LinkedIn stays click-through
- Mass/high-frequency sending — caps stay personal-scale
- Any send without a ✅ press (Mode C) — never

## 7. Needed from client (before M10a)

1. Written approval of the §1 rules amendment (changes AGENTS.md + PLAN.md §9)
2. For Reddit: say which Reddit account may post (an aged account, not the main personal one), and create the OAuth script app
3. For Freelancer: confirm proposals are submitted from the client's real Freelancer profile; state the budget/price line policy (must match what was shown in the TG draft)
4. For FB: keep the existing M4 login session donor; separate throwaway account strongly recommended (same as M4)
5. Pick the daily caps (proposed: F 8 / R 5 / FBc 6 / FBi 3)
6. Confirm dry-run week and 14-day FB comment trial window

---

## 8. Compliance rewrite (what AGENTS.md becomes after approval)

Only two rules change; everything else (read-only collectors, .env secrets,
payment gate, dedup, pacing) stays byte-identical:

- "Never auto-send" → **"Sends are human-approved on Telegram, then
  system-dispatched by `senders/` (Mode A or B). No fully-automated Mode C —
  every send must trace to an ✅ press + `approval` row."**
- "Collectors are read-only" → collectors unchanged; **`senders/` exists as a
  separate explicit module set**, each platform gated by its own killswitch +
  caps.
