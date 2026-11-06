# Facebook source — scan check report

Date: 2026-11-05
Scope: verify how the FB collector is currently scanning, find why it
returns 0 posts in every pipeline cycle since 2026-11-04 (client problem:
FB stop feeding alerts), no changes made during this check (read-only
probes only, same rules as the collector).

---

## 1. How FB scanning currently works (`collectors/fb_feed.py`)

Per pipeline cycle (every 30 min, `services/scheduler.py`):

1. Gate: `sources.facebook.enabled: true` in `config.yaml` AND
   `safety.branch_paused("facebook")` false → currently passes (the
   login-wall killswitch has only ever fired for **linkedin**).
2. Group list: config.yaml allowlist (8 groups, discovered 2026-11-03)
   merged with `data/fb_groups.json` (M8 auto-discovery state). This file
   is **MISSING** — discovery never persisted a group since it was wired;
   effectively the collector polls only the 8 config groups.
3. Sharding (`_shard`): oldest-polled groups first, max
   `poll_groups_per_cycle: 10` per cycle, only groups stale for
   `poll_hours: 2` are due. State lives in `data/fb_poll_state.json`
   (root-owned — written inside the container).
4. Per group: open `https://www.facebook.com/groups/{id}` with the saved
   storageState (`data/session_facebook.json`), random 3–6 s page wait,
   `safety.is_loginwall()` check (single 4000-char window, needs ≥2
   markers), ONE wheel scroll (1500 px), then read the first 15
   `div[role=article]` bodies ≥40 chars — skip markers + own-chat echo
   removal (Vietnamese UI markers included).
5. Items carry `url = <group page url>` (no permalink) and flow through
   the shared pipeline: dedup → spam → payment gate → classifier → alert.

## 2. Measured state right now

| Signal | Value | Meaning |
|---|---|---|
| Pipeline cycles with `src_facebook: 0` | last 43/43 in current log | branch runs but collects nothing |
| Last day any FB row appeared in DB | 2026-11-03 | production feed silent for 2 days |
| FB rows in DB | 7 (all `unpaid`) | old only |
| `fb_poll_state.json` | all 8 groups re-stamped 2026-11-05 02:47 | shard IS visiting groups — browser opens them on schedule |
| killswitch.json facebook entry | none | **no login-wall / captcha ever detected on FB** |
| session file | 2026-11-03 18:32, 10 cookies, `c_user` valid 364 d, `xs` valid 89 d | login cookie set is NOT expired |
| fb_login.log (last login) | ended at FB `auth_platform/afad` redirect then timeout | login flow itself fought FB's ad-flow wall on Nov 3 |

## 3. Live probes (read-only, 2026-11-05)

Probe A — fresh headless chromium + storageState, group
`PLC & AUTOMATION VIETNAM` (198816334568531):

- Page title + group header render correctly, logged-in state confirmed
  (`"Bạn viết gì đi..."` composer visible, notification counts present).
- `is_loginwall` → False. No caption, no checkpoint.
- `div[role=article]` nodes exist (2) but **`inner_text()` is empty**.
- Same result after: `/feed` deep link, a second group
  (721352586496807), 3 scroll rounds spread over ~15 s, 8 s waits, bigger
  viewport, and even a live click on the "Thảo luận" tab (couldn't click —
  element force-hidden by hydration state).
- Body text stops at the group intro shell (3685 chars); repeated
  `Facebook` placeholder rows where the post list should hydrate.

Probe B — `https://www.facebook.com/` home feed with the same session:

- Renders **real posts** through the same `role=article` DOM path
  (post + author + relative time extracted). So the session and the
  article-extraction mechanics still work for the home feed.

Probe C — Firefox engine: not installed in the container
(`ms-playwright/firefox-1555` missing), skipped.

## 4. Interpretation

- The branch is not dead by config, session, killswitch, or sharding —
  all those steps pass and groups ARE opened on schedule.
- Failure is at content extraction: Facebook serves the mobile/lounge
  **feed skeleton** for group pages in this headless chromium context and
  never hydrates post bodies (server-side change coinciding with 2026-11-04;
  same browser fingerprint worked on 2026-11-03 when 736 posts were
  collected). Because the empty articles simply fail the ≥40-char filter,
  the collector exits silently with 0 items — no warn, no login-wall hit,
  so no TG alert ever fires. That silence is why it went unnoticed until
  the client noticed FB content missing.
- Home feed vs group feed behaves differently with the identical session —
  strongly suggests a group-feed-specific anti-headless countermeasure, not
  a broken login.
- Discovery regression (no `fb_groups.json`) compounds the diversity
  issue: only the fixed 8 groups are ever polled (none of which are
  confirmed to still be posting jobs).

## 5. Options to restore FB (for client decision; M9 follow-up)

Ranked by compliance cost:

1. **Group-feed hydration fix (try first, no new risk):**
   wait for `browser hydrated state via `page.wait_for_function` on
   non-empty article text (e.g. 30 s); retry scroll; if still skeleton,
   log a distinct warn line `fb-skeleton` so silence can't hide it again.
   Cheap; may fail if FB deliberately refuses headless group feeds.
2. **Mobile layout endpoint** (`mbasic`/`m.facebook.com` groups feed with
   the same storageState) — historically hydrates server-side, far less
   JS. Keep read-only + same delays.
3. **Human-in-the-browser capture (render mode):** run a supervised
   headed (non-headless) poll on the host when the watchdog detects the
   skeleton (`bidscan run fb` opens a window the owner watches; capture
   is the same read-only extraction) — safest for ban risk, weakest for
   automation cadence.
4. **Park FB:** accept FB as paused (M9 B4 watchdog already will surface
   it) and lean on the new-source work (M9 B7: r/forhire etc. RSS) to
   re-balance the mix.

## 6. DoD for any fix

- ≥1 fresh FB row in DB within 24 h with zero `login-wall` kills.
- Distinct `fb-skeleton` warn line (never silent 0 again) when the feed
  fails to hydrate.
- Watchdog source-freshness alert fires if 0 fresh across 6 cycles
  (M9 B4).
- All compliance gates unchanged: read-only, storageState only, no
  like/comment/post, killswitch intact.

---
Compliance note: all probes here were read-only page opens with the
existing storageState (same as the collector), no interactions beyond
scroll, no messages sent, no new sessions stored.

---

# Addendum 2026-11-05 — problem 2: wrong group pool + language mismatch

Follow-up check (read-only) after client feedback: the FB scan does not
target freelancer / MMO groups, which is where most "build me a tool"
work actually happens. Verified below: what the current groups contain,
where the real job posts live, and what languages they are in.

## A. What the current 8 groups actually are (live titles)

| Group | Members | Content reality |
|---|---|---|
| PLC & AUTOMATION VIETNAM | 6,5K | industrial PLC engineer discussion |
| AI+ Machine Vision Inspection & Automation | 457 | machine-vision talk |
| Automation plc group | 21,1K | PLC talk |
| AI & Automation Việt Nam | 1,4K | AI learning community |
| AI Agents & Automation \| Work & Product | 7,8K | general AI chatter |
| Cộng đồng AI Automation (Học AI & Marketing) | 8,8K | course/learning community |
| Cộng đồng Claude AI & AI Agents Việt Nam | 388,6K | huge but consumer-AI chat |
| AI Automation Academy — AI Cho Non-coders | 2,7K | beginner course community |

Verdict: **every single group is a Vietnamese AI-education/PLC community,
not a freelancer/MMO marketplace.** The 7 FB rows in the DB confirm it —
most are chat fragments/housekeeping ("Th kệ, đi bus cho nó ấm",
"Sinh viên lao động giá rẻ và chết trẻ", own-chat echoes 😇😇), zero
tool-build job posts. Two of them also show the own-chat-echo filter did
not catch everything (see §E).

## B. Where the tool-build jobs on FB actually live (search sweep, live)

Group-search sweep with hiring-side queries found dedicated Vietnamese
"hire a coder to build a tool" marketplaces — slugs are self-explanatory:

- `thuecodetooltheoyeucau` — "Thuê code tool theo yêu cầu" (rent a coder
  to build a tool on demand)
- `codetooltheoyc`, `codetheoyeucau`, `thuecodetool`
- `codetoolwebappuytin` — "code tool web/app uy tín" (trusted tool/web/app
  coders)
- `chiasetool` — tool sharing/swap
- `giacongphanmem`, `thietkecongcuphanmemtheoyeucau`, `vnsogroup`
  — "gia công phần mềm" (software outsourcing)
- `TimViecLamOnlineGroup` — online-work board
- EN-side MMO groups also surfaced (`make money online` search: 5 numeric
  ids) but were returned without labels/skeleton-feeds — lower priority.

English queries ("freelancer group") returned generic/global groups
(`remote.freelance.it`, `jobsflexible`) — real marketplace behavior, but
the Vietnamese tool-market communities are where demand matches the
client's offer.

## C. What those posts look like (live sample, `thuecodetooltheoyeucau`)

6 sampled posts from the live feed:

- "E cần tìm bác nào biết về tool C/C++ Mu Online ạ." — **real buyer ask**
  (need a C/C++ tool dev for a game ecosystem)
- "DK Tech - Website Theo Yêu Cầu / ... hỗ trợ thiết kế, lập trình tool
  con game kiếm hiệp..." — seller self-promo (noise)
- "inbox nhận code babe ei" — seller
- "Ae ai ở hn có tool nào sài outo up bài cho Fb ko ạ" — buyer for FB
  auto-post tool
- "Sẵn nha ib" / "Việt phải không em?" — chatter

Ratio in this sample: ≈2 of 6 are buyer asks, rest is seller promo/chatter.
Feed **hydrates fully** here (11 roles, 9 filled) — unlike the education
groups (§4 of this report) which never hydrated at all. So switching the
group pool to these marketplaces largely fixes BOTH the relevance problem
AND the skeleton problem in one move.

## D. Language answer

- **Everything job-related found on FB is Vietnamese** — written in
  "teencode"/chat style: `e/ae/bác/ní/ib/inbox/zalo/tele`, "tool tự động",
  "outo" (sic), "bao test bảo hành" (tested + warranty sellers).
- English it is only on global groups (not the relevant market for the
  client's offering, per sample).
- The stored DB rows are Vietnamese chat; `language` column is empty on
  all 7 (the pipeline never got far enough to set it).

**Consequence discovered:** the current pipeline is English-built —
`keywords` ("looking for someone to", "need a developer"…),
`payment_signals` (`\$`, £, "budget", "willing to pay"...), and the
freelancer `require/reject_keywords` will all MISS Vietnamese asks. Even
after re-pointing the scan at the right groups, most posts would fall:
spam filter OK → **payment gate FAIL → status `unpaid` → no alert**.
Classic example: "E cần tìm bác nào biết về tool C/C++" has zero English
money words yet is a paid request waiting for a quote ("ib để báo giá").

## E. Also found: own-chat echo filter leak

DB rows #294–295 (`"Bạn đã gửi / Nhập, Tin nhắn do Bạn gửi lúc ..."`)
are own-chat echoes that were stored **before** the 2026-11-04 echo
filter landed; current filter code would catch them. Historical noise
only — no code change needed, but worth re-testing the filter against
this exact row when touching `fb_feed.py` next (AGENTS.md style rule).

## F. Fix plan (proposal, needs client approval)

**Status: IMPLEMENTED 2026-11-05** (client approved "implement the plan").
What landed:

- `config.yaml`: FB group pool re-pointed (9 VN tool-market slugs +
  1 AB test group); VN keywords (17), VN payment signals (10), VN
  amount patterns (`500k / 1tr5 / 2 triệu`); FB require/reject lists
  (14 / 17 incl. recruiter post rejects).
- `collectors/fb_feed.py`: DISCOVER_TERMS re-pointed to VN/MMO niche;
  `_fb_relevance_ok` buyer-ask filter; per-post pseudo-URLs
  (`?p=<sha1>` — previously one row/group per cycle, URL-conflict bug);
  `fb-skeleton` warn line (never silently 0 again); per-group ask cap 5.
- Payment gate: hire-phrase + product-word regexes added so real VN
  marketplace asks pass without dollar figures (verified against the
  live samples of this report §C/D — buyer asks PASS, chatter and
  seller promos REJECT).
- `pipeline/bid_writer.py`: facebook draft style notes VN teencode
  matching (e/ae/bác/ib register).
- `tests/test_m9.py`: 15 tests incl. real-sample gate + dedup fix +
  fair-queue (M9 B1) — all green; full regression suite green
  (test_m5's 1 error = pre-existing root-owned killswitch.json, env issue).

Original plan (for the record):

1. **Re-point the group pool** (one `config.yaml` edit):
   drop or park the 8 education groups; add the live tool-market slugs
   above. Keep 2–3 "long-shot" groups only if the client wants them
   (e.g. AI Agents & Automation | Work & Product — 7,8K, generic-active).
   Estimated green replacement pool: 8–12 groups.
2. **Repoint discovery terms** (`fb_feed.py::DISCOVER_TERMS`) to the
   same money niche: "thuê code tool", "gia công phần mềm", "nhận làm
   tool tự động", "web app theo yêu cầu", "make money online" (EN MMO).
3. **Vietnamese pipeline support** (M9 extension, must-have):
   - `keywords`: add VI ask phrases (`cần tìm bác nào`, `thuê`,
     `nhận làm`, `làm giúp`, `ai biết làm`, `inb/tìm người code`…).
   - `payment_signals`: add VI money signals (`giá`, `báo giá`,
     `bao nhiêu`, `$$`, `k$,` `đ/cx`, `thỏa thuận`, `ib để báo giá`,
     `zalo/tele` + phone-number pattern).
   - bid-draft prompts: match VI tone (profile.tone already
     mixed-language capable).
4. **FB-side relevance filter** (like freelancer's, per-source):
   require buyer-ask shape; demote seller self-promo
   ("bao test", "bảo hành", "nhận code", "sẵn nha", "sản phẩm", brand+
   "theo dõi") so the 5:1 seller-to-buyer ratio doesn't flood the queue.
   Queue must stay fair to Reddit/Upwork (M9 B1 quotas already handle mix).
5. **Skeleton warn** stays needed for groups that (still) fail hydration
   (see §5 of this report) — but with the right pool this becomes a
   rare-path, not the daily 0.

DoD (when implemented): ≥1 relevant tool-build lead/24 h in TG from the
new pool; VN/EN language tag populated; no seller-promo >30% of FB
alerts; education-group chit-chat 0 in the queue.

---

# Addendum 2026-11-06 — contact-first gate + EN pool + dedup chrome fix

Client request: FB flows differently from freelancer/Upwork — deal norm is
CONTACT FIRST, requirement + price negotiated in the inbox ("ib để báo
giá"), so the strict payment-signal gate was wrongly killing real buyer
asks (45 of 51 FB rows stuck `unpaid`/`low`). Also: widen FB beyond VN
groups (client → English only), and never store the same post twice.

## A. Account identity check (read-only probe, in-container)

- storageState probe (headless, same rules as collector): logged in as
  **"Duy Nguyen"**, FB user ID `61595855926804`; session refreshed
  2026-11-06 14:32 (`c_user`/`xs` valid to ~2028-08). Page renders
  logged-in, killswitch has never fired for facebook.
- ⚠ Client to confirm: this must be the **dedicated burner** profile, not
  the main personal account (M4 rule). Email/password never stored — no
  credentials touched.

## B. What landed (all tests green: test_m9 26 ✅, m5 ✅, m8 ✅)

1. **Dedup chrome fix** (`pipeline/dedup.py` + `fb_feed.py`): FB re-renders
   its relative-time line every poll ("3 giờ" → "32 phút"), shifting the
   text hash — same post re-stored each cycle (DB rows 1265/1284).
   `_CHROME_LINE` drops time-stamp lines before `_fingerprint()`; per-post
   pseudo-URL re-hashes via `content_hash()` → stable across polls
   (verified against the actual duplicate rows in the DB).
2. **Contact-first gate** (client 2026-11-06): `config.gate_policy:
   {facebook: contact_first}` + `contact_signals` (ib/inbox/zalo/tele/
   DM+phone). `payment_check.gate_payments()` passes FB on payment signal
   OR contact signal + buyer-ask; records `contact_channel` ( TG 📞 badge).
   All non-FB sources keep the strict M1 gate, byte-identical (test).
   Pipeline order unchanged (gate still 4th).
3. **Classifier FB note**: buy-ask + contact path = `pay_capability`
   implied; missing budget never demotes FB posts (quote comes in DM).
4. **Bid writer** `facebook_contact` style: confirm-build line + 2 scope/
   timeline questions + "ib để em báo giá" hook (VN teencode or EN per
   post language). No price numbers — clarify then quote. One question
   style shared with the 💬 comment stage.
5. **EN filter branch** (`_fb_relevance_ok`): VN-diacritic detection → VN
   lists (existing), otherwise EN `require_keywords_en` /
   `reject_keywords_en` (new config). Buyer asks pass, agency self-promo
   rejected. `DISCOVER_TERMS` + EN queries.
6. **Reject-list tightening** (leaks measured in DB): VN seller shapes
   ("Dạ em chào anh…tư vấn", "đang có sẵn", thiệp-in ads, "nếu bạn còn
   cần…ib trực tiếp", "có thể hỗ trợ…để trao đổi" — DK Tech brand ads).
7. **EN group pool** (live sweep, read-only, container): EN FB groups are
   seller-heavy (samples: "check my work", agency walls, recruiter boards);
   only 3 active (<24 h posts) trial groups kept: `752790164383176`
   (Web Developer Jobs and Projects), `smallbusinessownerandentrepreneurs`
   (Small Business Owners & Entrepreneurs), `facebook.comgroupsaiforsmallbusinessowners`
   (AI for Small Business Owners). VN "tuyển dụng" recruiter boards
   rejected: employment ads ≠ client asks. `discovery_cap` 25→40.
8. **Group hygiene**: dead education group `1646560306600683` removed
   (permanent fb-skeleton); 8 stale numeric IDs pruned from
   `fb_poll_state.json` (root-owned → pruned in container). New
   `data/fb_skeleton.json`: 3 dead cycles in a row → group skipped that
   cycle (slot freed, streak resets on one successful feed).
9. **Watchdog M9 B4** (`services/watchdog.py::check_source_freshness`):
   source with 0 fresh items 6 cycles in a row → one-off TG alert (the
   silent-zero lesson). `unittest-src` killswitch pollution cleared
   (root-owned file was pausing test source; test_m5 green again).
10. **regate rescue**: contact-first pass ran over the stuck FB unpaid
    rows with the SAME buyer-ask guard — real historical rows are all
    seller/chat (0 flips, correctly); real buyer asks already enter live
    through the ask-shape payment regexes + new contact path.

## C. Known-open items

- EN trial groups under watch: if 48 h of polling yields no buyer-ask
  leads, they swap out (EN FB demand looks thinner than VN tool-market —
  measured, per §B samples).
- LinkedIn is live again per M9 (killswitch reset + 4-post smoke) —
  untouched here.
- Container image needs `docker compose build` to pick up code changes
  (data/config are bind-mounted, code is baked).
