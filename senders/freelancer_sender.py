"""Freelancer auto-send (M10a — docs/phase-m10-auto-send.md).

Contract (client-approved 2026-11-06, AGENTS.md amendment):
- ONLY rows the owner pressed ✅ on (status 'approved' in Telegram) may
  enter the send queue. No ✅, no send — Mode C does not exist.
- mode `dry_run` (week 1): full flow runs, but the submit click is NOT
  pressed; full-page screenshot + send_log row `dry_run` for owner review.
- mode `auto`: presses submit after a byte-exact draft fill, verifies the
  success marker, marks requests.status='sent'.
- Killswitch key `freelancer_sender`: login-wall/captcha pauses the sender
  + urgent TG alert (throttled 1/2h); queue defers while paused.
- No suggested price → send blocked ('blocked_no_price', row stays approved).
- daily_cap / hours window from config.yaml senders.freelancer.

Selectors are best-effort placeholders pending the first live dry-run —
text/CSS candidates per step live in SELECTORS; anything unmatchable
aborts cleanly as outcome 'drifted' (screenshot saved) — never a wrong or
double submission.

Run: python3 senders/freelancer_sender.py  (scheduler job, every 5 min)
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as Config
from db import connect
from alerts import telegram
from pipeline import safety, pricing

PLATFORM = "freelancer"
KS = "freelancer_sender"
ALERT_STATE = Path("data/sender_alert_state.json")

# Proposal-form entry points + fields. First candidate that resolves wins;
# plain strings = CSS selectors, other strings = text regex (i, ^…$).
SELECTORS = {
    "open_proposal": [r"bid on this project", r"submit a proposal",
                      r"make an offer", r"đ[ăa]ng ch[àa]o"],
    "proposal_text": ["textarea#proposal_textarea", "textarea[name='proposal']",
                      "textarea.proposalTextArea", "textarea[id*='proposal']",
                      "textarea"],
    "amount": ["input[name='amount']", "input#amount",
               "input[placeholder*='budget']", "input[id*='amount']"],
    "submit": [r"submit proposal", r"place my bid", r"send proposal"],
    "success": ["proposal submitted", "bid placed", "thanks for your bid",
                "successfully submitted"],
}


def queue(conn) -> list[dict]:
    """Approved, unattempted freelancer rows as plain dicts (sqlite3.Row
    lacks .get — senders read optional fields). ANY send_log record (even
    a failed/drifted attempt) removes the row — retries stay manual (the
    manual-copy path always still works; one attempt per request avoids
    double-processed/double sends)."""
    return [dict(r) for r in conn.execute(
        """SELECT r.id, r.url, r.draft_text, r.suggested_price, r.author
           FROM requests r
           WHERE r.status = 'approved' AND r.source = 'freelancer'
             AND r.draft_text IS NOT NULL AND TRIM(r.draft_text) != ''
             AND NOT EXISTS (SELECT 1 FROM send_log s
                             WHERE s.request_id = r.id)
           ORDER BY r.id LIMIT 10""").fetchall()]


def _stats(conn) -> dict:
    today = datetime.now().strftime("%F")
    sent_today = conn.execute(
        """SELECT COUNT(*) FROM send_log
           WHERE platform = ? AND outcome = 'sent' AND attempted_at >= ?""",
        (PLATFORM, f"{today} 00:00")).fetchone()[0]
    return {"sent_today": sent_today, "pending": len(queue(conn))}


def in_hours(cfg: dict, now: datetime | None = None) -> bool:
    """Send window (owner local time). Outside = defer quietly."""
    hours = ((cfg.get("senders", {}).get(PLATFORM, {}) or {})
             .get("hours", [0, 24]))
    h = (now or datetime.now()).hour
    return hours[0] <= h < hours[1]


def deferred_outcomes(conn, cfg) -> tuple[int, str]:
    """Non-page preconditions for the batch → (runnable, reason). Reasons
    are logged, never raised — the scheduler calls every cadence slot."""
    src = cfg.get("senders", {}).get(PLATFORM, {}) or {}
    if safety.killswitch_state().get(KS, {}).get("paused"):
        alert("⛔ freelancer sender PAUSED by killswitch — proposals stay "
              "approved; resume with `bin/bidscan sender-resume freelancer`")
        return 0, "killswitch_paused"
    if not src.get("enabled", False) or src.get("mode", "dry_run") == "off":
        return 0, "disabled"
    if not safety.load_state_file(
            src.get("state_file", "data/session_freelancer.json")):
        alert("⚠️ No freelancer login session yet — log in once with "
              "`python3 senders/freelancer_login.py`, then the send queue "
              "flows itself")
        return 0, "no_session"
    if not in_hours(cfg):
        return 0, "outside_hours"
    stats = _stats(conn)
    cap = int(src.get("daily_cap", 8))
    if stats["sent_today"] >= cap:
        return 0, "daily_cap"
    if not stats["pending"]:
        return 0, "queue_empty"
    return min(stats["pending"], cap - stats["sent_today"]), "ok"


def _text_el(page, regexes: list[str]):
    """First visible button/link matching any text regex (3 probing
    strategies; misses → None, caller decides drift)."""
    for rx in regexes:
        try:
            el = page.locator(f"text=/{rx}/i").first
            if el and el.count() and el.is_visible():
                return el
        except Exception:
            continue
    for rx in regexes:
        try:
            el = page.get_by_text(re.compile(rx, re.I)).first
            if el and el.count():
                return el
        except Exception:
            continue
    for rx in regexes:
        try:
            el = page.get_by_role("link", name=re.compile(rx, re.I)).first
            if el and el.count():
                return el
        except Exception:
            continue
    return None


def _css_el(page, css_list: list[str]):
    for css in css_list:
        if css.startswith(("textarea", "input", "button", "div", "a", "form")):
            try:
                el = page.locator(css).first
                if el and el.count():
                    el.wait_for(state="visible", timeout=3_000)
                    return el
            except Exception:
                continue
    return None


def open_proposal(page, url: str) -> tuple[object, str | None]:
    """Navigate to the request page → proposal form. Returns (page, error):
    None err = form open; 'LOGINWALL' = session dead; 'DRIFT:*' otherwise.
    Content checks happen before ANY click."""
    try:
        page.goto(url, timeout=45_000)
    except Exception as exc:
        return page, f"DRIFT:goto ({exc})"
    if safety.is_loginwall(page.content()):
        return page, "LOGINWALL"
    time.sleep(2)  # settle; collectors use the same polite cadence
    btn = _text_el(page, SELECTORS["open_proposal"])
    if btn is None:
        return page, "DRIFT:proposal-entry"
    btn.click()
    time.sleep(3)
    return page, None


def fill_form(page, row: dict) -> str | None:
    """Draft bytes must land in the textarea EXACTLY (post-write compare);
    price fills from stored suggested_price only — never re-asked/re-guessed.
    Returns drift reason or None."""
    ta = _css_el(page, SELECTORS["proposal_text"])
    if ta is None:
        return "DRIFT:textarea"
    ta.fill(row["draft_text"])
    try:
        if ta.input_value() != row["draft_text"]:
            return "DRIFT:textarea-mismatch"
    except Exception:
        return "DRIFT:textarea-mismatch"
    if pricing.price_amount(row.get("suggested_price") or "") == "":
        return "DRIFT:no-price"
    amount = _css_el(page, SELECTORS["amount"])
    if amount is None:
        return "DRIFT:amount"
    amount.fill(pricing.price_amount(row["suggested_price"]))
    return None


def _shot(page, path: str) -> str:
    try:
        page.screenshot(path=path, full_page=True)
        return path
    except Exception:
        return ""


def submit(page, row: dict, mode: str, shot_dir: Path) -> dict:
    """One attempt. Outcomes: dry_run | sent | failed | drifted |
    paused_captcha | blocked_no_price. submit exists ONLY via mode='auto'
    (dry_run never presses it — screenshot is the review artifact)."""
    shot = _shot(page, str(shot_dir / f"send_{row['id']}_{int(time.time())}.png"))
    page, err = open_proposal(page, row["url"])
    if err:
        if err == "LOGINWALL":
            # senders pause on the FIRST hit (plan §3 hardening)
            state = safety.hit_loginwall(KS, threshold=1)
            if state.get("paused"):
                alert("⛔ freelancer sender PAUSED after login-wall — "
                      "relogin: `python3 senders/freelancer_login.py`")
            return {"outcome": "paused_captcha", "error": err,
                    "screenshot": shot}
        return {"outcome": "drifted", "error": err, "screenshot": shot}
    drift = fill_form(page, row)
    if drift:
        res = {"outcome": ("blocked_no_price" if drift == "DRIFT:no-price"
                           else "drifted"), "error": drift}
        res["screenshot"] = _shot(page, shot)
        return res
    if mode != "auto":
        return {"outcome": "dry_run", "screenshot": shot}
    btn = _text_el(page, SELECTORS["submit"])
    if btn is None:
        return {"outcome": "failed", "error": "DRIFT:submit-button",
                "screenshot": shot}
    btn.click()
    time.sleep(4)
    body = (page.content() or "").lower()
    if any(m in body for m in SELECTORS["success"]):
        return {"outcome": "sent"}
    shot2 = _shot(page, str(shot_dir / f"fail_{row['id']}_{int(time.time())}.png"))
    return {"outcome": "failed", "error": "no-confirmation-marker",
            "screenshot": shot2}


def log_attempt(conn, rid: int, mode: str, res: dict) -> None:
    """One send_log row per attempt (audit contract §3). Only 'sent'
    flips requests.status — everything else leaves the row approved."""
    conn.execute(
        """INSERT INTO send_log (request_id, platform, mode, outcome,
                                  screenshot_path, error)
           VALUES (?,?,?,?,?,?)""",
        (rid, PLATFORM, mode, res.get("outcome", "failed"),
         res.get("screenshot", ""), res.get("error", "")))
    if res.get("outcome") == "sent":
        conn.execute(
            "UPDATE requests SET status='sent', send_mode='auto', "
            "sent_at=datetime('now') WHERE id=? AND status='approved'",
            (rid,))
    conn.commit()


def alert(text: str) -> None:
    """Urgent sender alert, throttled to 1 per 2h — killswitch/no-session
    branches re-trigger every scheduler cycle otherwise."""
    import os
    Config.load_env()
    st = {}
    if ALERT_STATE.exists():
        try:
            st = json.loads(ALERT_STATE.read_text())
        except json.JSONDecodeError:
            st = {}
    if time.time() - st.get("last_alert_ts", 0) < 2 * 3600:
        return
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    if token and chat:
        try:
            telegram.send(token, chat, text)
        except Exception as exc:
            print(f"[warn] sender tg alert: {exc}", flush=True)
    st["last_alert_ts"] = time.time()
    ALERT_STATE.write_text(json.dumps(st))


def notify_outcome(row: dict, mode: str, res: dict) -> None:
    """Per-attempt TG confirm (plan §3: owner sees every dispatch)."""
    import os
    Config.load_env()
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    if not (token and chat):
        return
    outcome = res.get("outcome", "failed")
    icon = {"dry_run": "🧪", "sent": "📤", "failed": "⚠️", "drifted": "🧭",
            "paused_captcha": "⛔", "blocked_no_price": "💵"}.get(outcome, "•")
    body = {
        "dry_run": (f"🧪 DRY-RUN preview — request #{row['id']} — form "
                    f"filled ({pricing.price_amount(row.get('suggested_price') or '')}) "
                    "but NOT submitted. Screenshot: data/logs. Flip "
                    "senders.freelancer.mode: auto after 5 verified previews."),
        "sent": (f"📤 AUTO-SENT on freelancer — proposal submitted "
                 f"(#{row['id']}). Verify in the Freelancer UI."),
        "blocked_no_price": ("💵 no suggested price — auto-send blocked "
                             "for this one; ✏️ price it first"),
        "paused_captcha": "⛔ login-wall/captcha hit — sender paused",
        "drifted": (f"🧭 selector drift: {res.get('error')} — NOT submitted, "
                    "row stays approved; manual copy still holds"),
        "failed": (f"⚠️ submit failed: {res.get('error')} — no retry "
                   "(one attempt per request; manual copy path holds)"),
    }.get(outcome, str(res))
    try:
        telegram.send(token, chat, f"{icon} {body}\n🔗 {row['url']}")
    except Exception as exc:
        print(f"[warn] tg send: {exc}", flush=True)


def run_batch(conn, cfg) -> int:
    """Attempts this cycle. Browser kept in one session for the batch
    (one login-touch per 10 rows max, human-label)."""
    runnable, reason = deferred_outcomes(conn, cfg)
    print(f"[sender] {reason} (runnable {runnable})", flush=True)
    if not runnable:
        return 0
    src = cfg.get("senders", {}).get(PLATFORM, {}) or {}
    mode = src.get("mode", "dry_run")
    state_file = src.get("state_file", "data/session_freelancer.json")
    shot_dir = Path("data/logs")
    shot_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state_file,
                                  **safety.launch_headless())
        page = ctx.new_page()
        for row in queue(conn)[:runnable]:
            res = submit(page, row, mode, shot_dir)
            log_attempt(conn, row["id"], mode, res)
            notify_outcome(row, mode, res)
            done += 1
            safety.human_pause(20, 90)  # per-send jitter (plan §3 hardening)
        browser.close()
    return done


def main() -> int:
    Config.load_env()
    cfg = Config.load_config()
    import fcntl
    lock = Path("data/sender.lock")
    lock.parent.mkdir(exist_ok=True)
    conn = None
    with open(lock, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another sender already active", flush=True)
            return 0
        try:
            conn = connect(cfg.get("db", {}).get("path", "data/bidscan.db"))
            n = run_batch(conn, cfg)
            print(f"[sender] {PLATFORM}: attempted {n}", flush=True)
            return 0
        finally:
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    sys.exit(main())
