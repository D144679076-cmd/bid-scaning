"""M4/M5 tests — make forum collector, safety kill-switch, follow-up tracker.
Run: python3 -m tests.test_m5
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db
from collectors import make_forum
from pipeline import followup, safety

SAMPLE_RSS = (ROOT / "tests" / "fixture_make_feed.rss").read_bytes()

CFG = {
    "sources": {"make": {"enabled": True, "include_hire_a_pro": True,
                          "hire_a_pro_category_id": 50}},
    "followup": {"enabled": True, "after_hours": 24, "max_per_run": 5},
}


class TestMakeForum(unittest.TestCase):
    def test_normalize_rss_items(self):
        items = make_forum.normalize(SAMPLE_RSS)
        self.assertTrue(items)
        it = items[0]
        for key in ("source", "url", "author", "posted_at", "raw_text"):
            self.assertIn(key, it)
        self.assertEqual(it["source"], "make")
        self.assertTrue(it["url"].startswith("http"))

    def test_de_noiser_skips_showcase(self):
        items = make_forum.normalize(SAMPLE_RSS)
        titles = " ".join(i["raw_text"].lower()[:200] for i in items)
        self.assertNotIn("[showcase]", titles)

    def test_disabled_source_yields_nothing(self):
        self.assertEqual(
            make_forum.collect_make({"sources": {"make": {"enabled": False}}}), [])

    def test_live_feed_shapes_staff(self):  # light live check, tolerant
        got = make_forum.collect_make({"sources": {"make": {"enabled": True}}})
        if got:  # network up
            self.assertIn("source", got[0])


class TestSafety(unittest.TestCase):
    def test_killswitch_after_two_hits(self):
        state = safety.hit_loginwall("unittest-src")
        self.assertFalse(state["paused"])
        state = safety.hit_loginwall("unittest-src")
        self.assertTrue(state["paused"])
        self.assertTrue(safety.branch_paused("unittest-src"))

    def test_loginwall_detector(self):
        self.assertFalse(safety.is_loginwall("<html><h3>Welcome</h3></html>"))
        self.assertTrue(safety.is_loginwall("Sign in or log in to continue verify"))

    def test_state_roundtrip(self):
        safety.save_state("unittest-src", {"cookies": [1]})
        self.assertTrue(safety.load_state("unittest-src"))


class TestFollowup(unittest.TestCase):
    def _mem_conn(self):
        conn = db.connect(":memory:")
        return conn

    @staticmethod
    def _fake_send(token, method, payload):
        TestFollowup.sent.append(payload)
        return {}

    def setUp(self):
        TestFollowup.sent = []

    def test_reminds_old_approved_once(self):
        conn = self._mem_conn()
        conn.execute(
            "INSERT INTO requests (source, url, fingerprint, raw_text, status,"
            " sent_at) VALUES ('reddit','u','f1','txt','approved',"
            "datetime('now','-30 hours'))")
        conn.commit()
        tgm = mock.patch.object(followup.telegram, "call_api",
                                self._fake_send)
        with tgm, mock.patch.dict(followup.os.environ,
                                  {"TG_TOKEN": "t", "TG_CHAT_ID": "c"}):
            res = followup.run(CFG, conn)
        self.assertEqual(res["reminded"], 1)
        self.assertEqual(len(TestFollowup.sent), 1)
        # second run → no duplicate reminder
        with tgm, mock.patch.dict(followup.os.environ,
                                  {"TG_TOKEN": "t", "TG_CHAT_ID": "c"}):
            res = followup.run(CFG, conn)
        self.assertEqual(res["reminded"], 0)

    def test_recent_approved_not_reminded(self):
        conn = self._mem_conn()
        conn.execute(
            "INSERT INTO requests (source, url, fingerprint, raw_text, status,"
            " sent_at) VALUES ('reddit','u','f2','txt','approved',"
            "datetime('now','-2 hours'))")
        conn.commit()
        tgm = mock.patch.object(followup.telegram, "call_api",
                                self._fake_send)
        with tgm, mock.patch.dict(followup.os.environ,
                                  {"TG_TOKEN": "t", "TG_CHAT_ID": "c"}):
            res = followup.run(CFG, conn)
        self.assertEqual(res["reminded"], 0)

    def test_disabled(self):
        conn = self._mem_conn()
        res = followup.run({"followup": {"enabled": False}}, conn)
        self.assertEqual(res["reminded"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
