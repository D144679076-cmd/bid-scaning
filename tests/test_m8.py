"""M8 tests: freelancer relevance filter + B1 assisted comment drafts."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors import upwork_feed
from db import connect
from pipeline import comments


class TestFreelancerRelevance(unittest.TestCase):
    REQ = ["automation", "bot", "web", "developer", "python"]
    REJ = ["design", "typing", "writing", "translation", "animation"]

    def test_keeps_dev_jobs(self):
        self.assertTrue(upwork_feed._relevance_ok(
            "Build a scraper bot for my shop\n6 days left\nI need automation "
            "for pricing, budget $200 Avg Bid", self.REQ, self.REJ))
        self.assertTrue(upwork_feed._relevance_ok(
            "Web developer needed for SaaS dashboard\nAvg Bid $300",
            self.REQ, self.REJ))

    def test_drops_design_typing_writing(self):
        for txt in ("Logo designer needed\nAvg Bid $50",
                    "Typing work, copy text\nAvg Bid $20",
                    "Translate document EN→DE\nAvg Bid $80",
                    "3D animation for kids series\nAvg Bid $500"):
            self.assertFalse(upwork_feed._relevance_ok(txt, self.REQ, self.REJ),
                             txt)

    def test_requires_positive_match(self):
        self.assertFalse(upwork_feed._relevance_ok(
            "Board Member duties statement\nAvg Bid $11", self.REQ, self.REJ))


class TestCommentDrafts(unittest.TestCase):
    def _conn(self):
        c = connect(":memory:")
        c.execute("INSERT INTO requests (source, url, fingerprint, raw_text,"
                  " score, status) VALUES ('facebook','u','f','Need bot…',"
                  " 7, 'drafted')")
        c.commit()
        return c

    def test_comment_target_and_persist(self):
        conn = self._conn()
        item = {"db_id": 1, "source": "facebook", "url": "u",
                "raw_text": "I need a bot for my shop, DM me",
                "score": 7, "budget": ""}
        cfg = {"sources": {"facebook": {"enabled": True,
                                        "comments_per_cycle": 3}}}
        client = lambda cfg, msgs: {"comment": "Cool — what's the budget and "
                                    "timeline for the shop bot?"}
        written = comments.comment_stage(conn, cfg, client, [item])
        self.assertEqual(written, 1)
        row = conn.execute("SELECT comment_text FROM requests WHERE id=1"
                           ).fetchone()
        self.assertIn("budget", row["comment_text"])

    def test_skips_rows_with_budget(self):
        conn = self._conn()
        item = {"db_id": 1, "source": "facebook", "url": "u",
                "raw_text": "txt", "score": 7, "budget": "$500"}
        cfg = {"sources": {"facebook": {"enabled": True,
                                        "comments_per_cycle": 3}}}
        self.assertEqual(comments.comment_stage(conn, cfg, None, [item]), 0)

    def test_alert_message_shows_comment_block(self):
        from alerts import telegram
        msg = telegram.format_message({
            "source": "facebook", "url": "https://x", "raw_text": "t",
            "posted_at": "", "score": 7, "comment_text": "What is the budget?"})
        self.assertIn("💬 COMMENT DRAFT", msg)
        self.assertIn("What is the budget?", msg)


if __name__ == "__main__":
    unittest.main()
