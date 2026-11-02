"""M1 tests — offline, one sample post (AGENTS.md: test collector first).

Covers: collector normalize, dedup idempotency, spam filter, alert message
format (no network). Run: python3 -m tests.test_m1
"""

import sqlite3
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json

import db
from collectors import reddit
from pipeline import dedup, spam_filter
from alerts import telegram

FIXTURE = ROOT / "tests" / "sample_listing.json"


def make_conn() -> sqlite3.Connection:
    return db.connect(":memory:")


def sample_items() -> list[dict]:
    children = json.loads(FIXTURE.read_text())["data"]["children"]
    return reddit.normalize(children)


class TestCollector(unittest.TestCase):
    def test_normalize_shapes(self):
        items = sample_items()
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["source"], "reddit")
        self.assertIn("reddit.com", first["url"])
        self.assertTrue(first["raw_text"].startswith("Need help automating"))
        self.assertEqual(first["posted_at"], 1762000000.0)

    def test_skips_empty_text(self):
        children = [{"data": {"title": "", "selftext": "", "permalink": "/x/"}}]
        self.assertEqual(reddit.normalize(children), [])


class TestDedup(unittest.TestCase):
    def test_first_insert_fresh_second_ignored(self):
        conn = make_conn()
        items = sample_items()
        fresh1 = dedup.store(conn, items)
        self.assertEqual(len(fresh1), 2)
        fresh2 = dedup.store(conn, items)
        self.assertEqual(fresh2, [])  # idempotent

    def test_fingerprint_catches_repost(self):
        conn = make_conn()
        item = sample_items()[0]
        repost = dict(item)
        repost["url"] = item["url"].replace("sample001", "sample009")
        fresh = dedup.store(conn, [item, repost])
        self.assertEqual(len(fresh), 1)  # same text → 1 row


class TestSpamFilter(unittest.TestCase):
    def test_noise_archived_goods_survive(self):
        conn = make_conn()
        dedup.store(conn, sample_items())
        survivors = spam_filter.filter_noise(
            conn,
            [{"source": "reddit", "url": "https://www.reddit.com/r/automation/comments/sample001/need_help_automating_my_email_workflow/",
              "author": "x", "posted_at": None, "raw_text": "Need help automating my email workflow…"},
             {"source": "reddit", "url": "https://www.reddit.com/r/automation/comments/sample002/spam_post/",
              "author": "x", "posted_at": None, "raw_text": "[HIRING] crypto casino followers"}],
            ["[HIRING]", "casino", "follow for follow"],
        )
        self.assertEqual(len(survivors), 1)
        statuses = {r["status"]: 1 for r in conn.execute("SELECT status FROM requests")}
        self.assertIn("archived", statuses)


class TestAlertFormat(unittest.TestCase):
    def test_message_contains_parts(self):
        msg = telegram.format_message(sample_items()[0])
        self.assertIn("reddit", msg)
        self.assertIn("samplebuy", msg)
        self.assertIn("https://www.reddit.com/r/automation/comments/sample001", msg)

    def test_alert_requires_creds(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("TG_TOKEN", "TG_CHAT_ID")}
        try:
            conn = make_conn()
            with self.assertRaises(RuntimeError):
                telegram.alert(conn, sample_items())
        finally:
            os.environ.update({k: v for k, v in saved.items() if v is not None})


if __name__ == "__main__":
    unittest.main(verbosity=2)
