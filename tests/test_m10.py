"""M10 tests — suggested price, send queue, sender dry-run guard rails.

Contract under test (docs/phase-m10-auto-send.md):
- pricing_match: keyword rules → tier range; poster budget excluded;
  no hit → None; match_price never raises on odd/missing fields.
- queue: ONLY status='approved' freelancer rows with a draft enter; any
  send_log record removes the row (one attempt per request).
- dry-run: the submit button is never pressed — verified via page mock.
- log_attempt: only outcome 'sent' flips status; others leave 'approved'.
- Bytes contract: textarea != draft_text → drift abort, no submit.
- Login-wall on sender path = instant killswitch (threshold 1, plan §3).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import connect
from pipeline import pricing
from senders import freelancer_sender as fs

CFG_MIN = {
    "pricing_match": [
        {"tier": "Retainer",
         "keywords": ["ongoing", "retainer", "maintenance"]},
        {"tier": "Workflow build",
         "keywords": ["automation", "scraper", "workflow", "n8n", "bot"]},
        {"tier": "Quick fix",
         "keywords": ["script", "one-off", "small"]},
    ],
    "senders": {"freelancer": {"enabled": True, "mode": "dry_run",
                               "hours": [0, 24], "daily_cap": 8,
                               "state_file": "data/session_freelancer.json"}},
}

PRICE = "$200-600 — Workflow build tier"
DRAFT = "I build these."


class TestPricing(unittest.TestCase):
    def test_workflow_hit(self):
        got = pricing.match_price(CFG_MIN, {
            "request_type": "automation",
            "raw_text": "Need a scraper for daily price pull"})
        self.assertIsNotNone(got)
        self.assertEqual(got["tier"], "Workflow build")
        self.assertEqual(got["range"],
                         pricing._profile_tiers()["Workflow build"])
        self.assertIn("$", got["amount"])

    def test_first_rule_priority(self):
        got = pricing.match_price(CFG_MIN, {
            "request_type": "web",
            "raw_text": "ongoing maintenance support for our tooling"})
        self.assertEqual(got["tier"], "Retainer")

    def test_poster_budget_excluded(self):
        got = pricing.match_price(CFG_MIN, {
            "request_type": "web",
            "raw_text": "please fix my login script; my budget is $5000"})
        # 'script' hits Quick fix; their $ figure must not shift the tier
        self.assertEqual(got["tier"], "Quick fix")

    def test_no_match_none(self):
        self.assertIsNone(pricing.match_price(CFG_MIN, {
            "request_type": "other", "raw_text": "something vague"}))

    def test_no_rules_none(self):
        self.assertIsNone(pricing.match_price({}, {"raw_text": "automation"}))

    def test_odd_input_never_raises(self):
        for odd in ({}, {"tools": None}, {"raw_text": None},
                    {"request_type": 5, "raw_text": 7}):
            try:
                pricing.match_price(CFG_MIN, odd)
            except Exception as exc:
                self.fail(f"match_price raised on {odd}: {exc}")

    def test_price_amount_display(self):
        self.assertEqual(pricing.price_amount(PRICE), "$200-600")
        self.assertEqual(pricing.price_amount(None), "")
        self.assertEqual(pricing.price_amount(""), "")

    def test_tier_range_matches_profile(self):
        tiers = pricing._profile_tiers()
        self.assertIn("Workflow build", tiers)
        self.assertTrue(tiers["Workflow build"].startswith("$"))


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.conn = connect("data/test.db")

    def tearDown(self):
        self.conn.close()
        os.chdir(self.old_cwd)

    def _add(self, rid, url, fingerprint, status, draft, price=PRICE,
             source="freelancer"):
        self.conn.execute(
            """INSERT INTO requests (id, source, url, fingerprint, raw_text,
                                     status, score, draft_text,
                                     suggested_price)
               VALUES (?,?,?,?,?,?,7,?,?)""",
            (rid, source, url, fingerprint, "txt", status, draft, price))
        self.conn.commit()

    def test_only_approved_freelancer_with_draft(self):
        self._add(1, "u1", "f1", "approved", DRAFT)
        self._add(2, "u2", "f2", "lead", "not approved yet")
        self._add(3, "u3", "f3", "approved", "")
        self._add(4, "u4", "f4", "approved", DRAFT, source="reddit")
        self.assertEqual([r["id"] for r in fs.queue(self.conn)], [1])

    def test_any_send_log_record_removes_row(self):
        self._add(1, "u1", "f1", "approved", DRAFT)
        for outcome in ("dry_run", "failed", "sent"):
            self.conn.execute(
                """INSERT INTO send_log (request_id, platform, mode, outcome)
                   VALUES (1, 'freelancer', 'dry_run', ?)""", (outcome,))
            self.conn.commit()
            self.assertEqual(fs.queue(self.conn), [])
            self.conn.execute("DELETE FROM requests WHERE id=1")
            self.conn.execute("DELETE FROM send_log")
            self.conn.commit()
            self._add(1, "u1", "f1", "approved", DRAFT)


class TestSubmitFlow(unittest.TestCase):
    """Page-mock runs of the real fs.submit path."""

    def setUp(self):
        # alert()/notify_outcome() MUST NOT fire real TG messages from
        # tests (the throttled-killswitch alert sent a real chat message
        # during the first M10 test run — client-visible pollution)
        self._real_alert = fs.alert
        fs.alert = lambda *a, **k: None
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.conn = connect("data/test.db")
        self.conn.execute(
            """INSERT INTO requests
               (id, source, url, fingerprint, raw_text, status, score,
                draft_text, suggested_price)
               VALUES (1, 'freelancer', 'https://f.example/x', 'fx1', 'txt',
                       'approved', 7, ?, ?)""", (DRAFT, PRICE))
        self.conn.commit()
        self.row = fs.queue(self.conn)[0]
        self.logdir = Path("data/logs")

    def tearDown(self):
        self.conn.close()
        os.chdir(self.old_cwd)
        fs.alert = self._real_alert

    def _out_status(self):
        return self.conn.execute(
            "SELECT status FROM requests WHERE id=1").fetchone()[0]

    def test_dry_run_never_clicks(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True)
        res = fs.submit(page, self.row, "dry_run", self.logdir)
        self.assertEqual(res["outcome"], "dry_run")
        self.assertFalse(page.submitted)

    def test_auto_clicks_and_marks_sent(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True,
                        confirm="thanks for your bid")
        res = fs.submit(page, self.row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "sent")
        self.assertTrue(page.submitted)
        fs.log_attempt(self.conn, 1, "auto", res)
        row = self.conn.execute(
            "SELECT status, send_mode FROM requests WHERE id=1").fetchone()
        self.assertEqual((row["status"], row["send_mode"]),
                         ("sent", "auto"))

    def test_bytes_mismatch_aborts_before_submit(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True,
                        leak=" ")
        res = fs.submit(page, self.row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "drifted")
        self.assertIn("textarea-mismatch", res["error"])
        self.assertFalse(page.submitted)
        self.assertEqual(self._out_status(), "approved")

    def test_no_price_blocked(self):
        self.conn.execute(
            "UPDATE requests SET suggested_price = NULL WHERE id = 1")
        self.conn.commit()
        row = fs.queue(self.conn)[0]
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True)
        res = fs.submit(page, row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "blocked_no_price")
        self.assertFalse(page.submitted)
        self.assertEqual(self._out_status(), "approved")

    def test_missing_price_input_is_drift_not_submit(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True,
                        price_field=False)
        res = fs.submit(page, self.row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "drifted")
        self.assertIn("amount", res["error"])
        self.assertFalse(page.submitted)

    def test_loginwall_instant_killswitch_no_fill(self):
        page = MockPage(wall=True)
        res = fs.submit(page, self.row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "paused_captcha")
        self.assertFalse(page.submitted)
        self.assertTrue(fs.safety.killswitch_state()
                        .get("freelancer_sender", {}).get("paused"))

    def test_no_entry_point_is_drift(self):
        page = MockPage()
        res = fs.submit(page, self.row, "dry_run", self.logdir)
        self.assertEqual(res["outcome"], "drifted")
        self.assertIn("proposal-entry", res["error"])

    def test_click_without_confirm_stays_approved(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True,
                        confirm="")
        res = fs.submit(page, self.row, "auto", self.logdir)
        self.assertEqual(res["outcome"], "failed")
        self.assertTrue(page.submitted)  # click happened
        fs.log_attempt(self.conn, 1, "auto", res)
        self.assertEqual(self._out_status(), "approved")  # no false 'sent'

    def test_outcome_row_written(self):
        page = MockPage(open_ok=True, form_ok=True, submit_ok=True)
        res = fs.submit(page, self.row, "dry_run", self.logdir)
        fs.log_attempt(self.conn, 1, "dry_run", res)
        row = self.conn.execute(
            "SELECT platform, mode, outcome FROM send_log").fetchone()
        self.assertEqual((row["platform"], row["mode"], row["outcome"]),
                         ("freelancer", "dry_run", "dry_run"))


class MockPage:
    """Playwright Page stand-in. Real fs.submit code drives this — only
    the CSS/text resolution and click effects are mocked."""

    def __init__(self, open_ok=False, form_ok=False, submit_ok=False,
                 price_field=True, wall=False, confirm="", leak=""):
        self.open_ok = open_ok
        self.form_ok = form_ok
        self.submit_ok = submit_ok
        self.price_field = price_field
        self.wall = wall
        self.confirm = confirm
        self.leak = leak
        self.submitted = False
        self.textarea_value = ""
        self._textarea_seen = False  # set when the form was reached

    def goto(self, url, timeout=None):
        self._content = ("sign in or log in to continue verify"
                         if self.wall else "project page")
        return self

    def content(self):
        return self._content

    def _text(self, rx):
        s = str(rx).lower()
        open_match = ("bid" in s or "offer" in s or "ch[àa]o" in s
                      or "submit a proposal" in s)
        submit_match = ("submit proposal" in s or "place my bid" in s
                        or "send" in s)
        visible = (self.open_ok and open_match) or \
                  (self.submit_ok and submit_match)
        # clicks AFTER the form was reached are submit clicks (mock can't
        # see which button text matched — order is the only state)
        kind = "submit-text" if self._textarea_seen else "text"
        return MockLoc(visible=visible, page=self, kind=kind)

    def locator(self, sel):
        if sel.startswith("text=/"):
            return self._text(sel)
        if sel.startswith("textarea"):
            self._textarea_seen = True  # form reached from here on
            return MockLoc(visible=self.form_ok, page=self, kind="textarea")
        if sel.startswith("input") or "placeholder" in sel:
            return MockLoc(visible=self.form_ok and self.price_field,
                           page=self, kind="amount")
        return MockLoc(visible=False, page=self, kind="other")

    def get_by_text(self, rx, exact=None):
        return self._text(str(rx))

    def get_by_role(self, role, name=None):
        return self._text(str(name))

    def screenshot(self, path=None, full_page=False):
        Path(path or "x.png").write_text("png")


class MockLoc:
    def __init__(self, visible, page=None, kind="text"):
        self.ok = visible
        self.page = page
        self.kind = kind
        # playwright Locator.first is a PROPERTY (locator.first, no parens)
        self.first = self

    def count(self):
        return 1 if self.ok else 0

    def is_visible(self):
        return self.ok

    def click(self):
        if self.kind == "submit-text" and self.page is not None \
                and self.page.submit_ok:
            self.page.submitted = True
            self.page._content = self.page.confirm or "no marker"

    def fill(self, value):
        if self.kind == "textarea":
            self.page.textarea_value = value

    def input_value(self):
        return (self.page.textarea_value + self.page.leak
                if self.page else "")

    def wait_for(self, state=None, timeout=None):
        pass


if __name__ == "__main__":
    unittest.main()
