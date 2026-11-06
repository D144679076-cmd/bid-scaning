# Phase M10 — Auto-send bids per platform

Date: 2026-11-06
Status: **M10a PART 1 SHIPPED 2026-11-06** (`85f3800` + `4a548a3`,
24 M10 tests): pricing_match + 💵 suggested price card + backfill (465
rows); freelancer sender module (dry_run default, byte-exact check,
drift-abort, send_log audit, killswitch 1 captcha hit, daily cap + hours
window, `bin/bidscan resume`, in-container scheduler job verified
running); `session_valid` token getter wired to sender gate + login
script. **Awaiting client:** run `python3 senders/freelancer_login.py`
once on the host (GUI window), then the dry-run week begins; flip
`senders.freelancer.mode: auto` after 5 verified previews. M10b/c/d
(Reddit, FB, hardening) not started. Client approved auto-send rules
§1 in chat 2026-11-06; no Mode C. Nothing here is live until the
session exists + 5 supervised sends pass.

Goal (as requested by client 2026-11-06): **press ✅ in Telegram → the system
sends the bid itself** —
- Freelancer: submit the proposal post
- Reddit: post the comment reply
- Facebook: post the comment **and** send the inbox / DM to the poster

Answer up front: **technically possible, but every one of these crosses a
hard compliance line the project has operated under since M1.** The plan
below defines an approval-gated auto-send (the ✅ press IS the approval) with
per-platform killswitches, dry-run stages, and supervised first sends. It
cannot go live until the client formally amends the rules (§1).

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

## 2. Modes and the chosen default

| Mode | What happens after ✅ | Risk | Use |
|---|---|---|---|
| **B (CHOSEN DEFAULT — all platforms)** | ✅ press → system submits itself: proposal / comment / DM. One press = one send | Medium-high | Freelancer, Reddit, FB comment, FB inbox |
| **A — Send-assist (fallback / trial-week step)** | System opens the post page with textarea filled + text on clipboard; owner clicks submit himself | Lowest | First week of each platform + whenever its killswitch is paused |
| **C — Full auto (no press)** | Pipeline auto-sends everything scoring ≥ threshold, no human | Highest — removes human judgment | **Not allowed, ever** |

Rollout per platform (client may reorder):

1. **Week 1 = dry-run + Mode A** on that platform — executor runs fully,
   except the final submit click is skipped and logged `dry_run`; owner sees
   the form filled for real and can click himself (this also validates the
   selectors end-to-end).
2. **Then flip `senders.<platform>.mode: auto`** → ✅ press = system send.
   First 5 live sends are supervised (owner online, watching).
3. **FB inbox specifically:** auto-DM only after 7 clean auto-comment days
   on the same session (one detector per platform, inbox reuses FB session
   state — if comments poison the session, inbox never turns on).

Permanent guarantees:
- No send without an ✅ press. Every send traceable to
  `approve:<request_id>` in the audit trail.
- Killswitch per platform: captcha / login wall / 2 failed sends → sender
  paused + urgent TG alert; flips back to Mode A automatically while paused
  (system still fills the form — batches keep flowing without waiting).

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

### Suggested price — displayed before ✅, auto-filled on send

Every scored card (score ≥ 6) shows a **💵 Suggested price** line, derived
from `profile.yaml pricing_tiers` matched against the classifier output
(`request_type`, `tools`, `budget` signal):

```
🆕 Request (freelancer)
⭐ Score: 8/10 · automation
💵 Suggested price: "$250–400 — workflow build tier"   ← NEW
💰 their budget: $200–300
📝 DRAFT ...
[✅ Approve] [✏️ Edit] [❌ Reject]
[📋 Copy draft] [🔗 Open]
```

- Matching = config rule (`pricing_match`: task_type/scope → tier name),
  LLM picker as fallback when rules are ambiguous (M2 classifier already
  returns what's needed).
- Owner can override the price with ✏️ like the draft text — the revised
  value persists with the draft.
- **Senders consume it:** Freelancer auto-send fills the platform's price
  field from `suggested_price` (byte-identical range, no LLM re-invention at
  send time); Reddit/FB/DM senders keep it inside the draft text (already in
  the M3 prompt via pricing tiers — now surfaced distinctly on the card).
- No price matchable → card shows `💵 not priced yet` and Freelancer
  auto-send is **blocked** (manual copy path) — an auto-submitted proposal
  without a price wastes a connect.

Pipeline order is unchanged: collector → dedup → spam → payment gate →
classifier → **draft → human approve (TG)** → send queue → sender. Senders
are a client of the approval, never a bypass of it.

## 3b. End-to-end flow after M10 (the "one press = sent" UX)

```
TG alert with buttons (draft visible in message)
   │
   ▼  owner taps ✅
callbacks.py: status → 'approved'  (now works, M10 fix fe15b7a)
   │
   ▼  send-queue worker (per platform cadence, pacing-capped)
sender:<platform> runs:
   - 'freelancer'        → opens proposal page for request.url,
                           fills textarea with draft_text, clicks submit,
                           reads back confirmation, status → 'sent'
   - 'reddit'            → OAuth api/comment on the thread, status → 'sent'
   - 'facebook_comment'  → posts comment on the group post (same session as M4 collector)
   - 'facebook_inbox'    → opens Messenger thread with the poster, sends the draft as first message
   │
   ▼
TG confirmation message: "📤 Sent on freelancer — request #123 (link)"
   on failure/killed session: "⚠️ Send failed on <platform> — switched to assist, draft filled on page"
```

Duplicate-send guard: send happens **once** per request — `send_log` +
`status='sent'` checked inside the queue transaction; a ✅ on an already-sent
row answers "already sent on <platform> at <time>" (toast, no new send).

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
ALTER TABLE requests ADD COLUMN suggested_price TEXT;  -- pricing_tiers match, shown pre-✅, consumed by senders
```

Status flow addition: `approved --sender--> sent | send_failed`.
Manual-copy path stays available: if `send_mode IS NULL` the row never
enters the send queue (backwards compatible with everything shipped M1–M9).

---

## 5. Build milestones

| Milestone | Scope | DoD |
|---|---|---|
| **M10a — Freelancer auto-send (Mode B)** | pricing_match rule + `suggested_price` display on scored cards (pre-✅); sender module, proposal form path, submit → read back confirmation → status `sent`; price field auto-filled from `suggested_price`, blocked when unset; 1 dry-run week (Mode A) then 5 supervised live sends | price shown on every instant card; cap-matched 10/10; 5 dry-runs logged `dry_run` → 5 supervised live sends accepted by owner; `send_log` row per attempt |
| **M10b — Reddit auto-send (Mode B)** | OAuth script app, `api/comment` submit path behind `senders.reddit.mode`; week 1 = Mode A assist | fill accurate on 10 posts (A); 5 supervised live auto-sends (B); zero suspensions during trial |
| **M10c — FB comment auto-send** | comment on group post via existing FB session; killswitch threshold = 1 captcha hit; week 1 = Mode A | assist works 10/10 (A); 5 supervised live auto-comments (B); 7 clean days before inbox unlocks |
| **M10d — FB inbox auto-send + hardening** | Messenger first-message send after 7 clean comment days; watchdog sender section, pacing caps, screenshots-on-failure, `bidscan sender-resume`, TG confirm/retry alerts | 3 supervised live DMs; sender killswitch fires < 2 min after simulated captcha; suite green incl. new M10 tests |

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
6. Confirm dry-run week and 7-day FB comment trial window
7. Confirm the pricing tier list the suggested price should pick from
   (profile.yaml `pricing_tiers` already set 2026-11-05 — verify ranges still
   valid) + a floor price for automation builds

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
