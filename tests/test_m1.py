"""M1 tests — offline, against recorded real Reddit Atom feed (AGENTS.md:
test collector against one sample post first).

Covers: collector normalize (RSS), dedup idempotency, spam filter, alert
message format (no network). Run: python3 -m tests.test_m1
"""

import os
import sqlite3
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db
from collectors import reddit
from pipeline import dedup, spam_filter
from alerts import telegram

FIXTURE = ROOT / "tests" / "sample_feed.rss"

# Fake items cut down from the recorded feed for targeted tests
POSITIVE = {
    "source": "reddit",
    "url": "https://www.reddit.com/r/automation/comments/sample001/need_help_automating_my_email_workflow/",
    "author": "samplebuy",
    "posted_at": "2026-11-02T15:55:01+00:00",
    "raw_text": "Need help automating my email workflow\n\n"
                "I spend 6 hours a week copying leads from email into our CRM. "
                "Is there a tool that can do this automatically? Paid project.",
}
SPAM = {
    "source": "reddit",
    "url": "https://www.reddit.com/r/automation/comments/sample002/spam_post/",
    "author": "spammer99",
    "posted_at": None,
    "raw_text": "[HIRING] crypto casino followers — buy followers, follow for follow, SEO services",
}


def make_conn() -> sqlite3.Connection:
    return db.connect(":memory:")


def real_items() -> list[dict]:
    return reddit.normalize(FIXTURE.read_bytes())


class TestCollector(unittest.TestCase):
    def test_normalize_real_feed(self):
        items = real_items()
        self.assertGreater(len(items), 0)
        first = items[0]
        self.assertEqual(first["source"], "reddit")
        self.assertIn("reddit.com", first["url"])
        self.assertTrue(first["raw_text"].strip())
        self.assertTrue(first["url"].startswith("https://www.reddit.com"))

    def test_urls_unique_in_feed(self):
        items = real_items()
        urls = [i["url"] for i in items]
        self.assertEqual(len(urls), len(set(urls)))

    def test_skips_empty_text(self):
        import xml.etree.ElementTree as ET
        empty = ET.fromstring(
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title></title>'
            '<content type="html"></content><link href="https://x"/></entry></feed>'
        )
        import io
        self.assertEqual(reddit.normalize(ET.tostring(empty)), [])


class TestDedup(unittest.TestCase):
    def test_first_insert_fresh_second_ignored(self):
        conn = make_conn()
        items = [POSITIVE, SPAM]
        self.assertEqual(len(dedup.store(conn, items)), 2)
        self.assertEqual(dedup.store(conn, items), [])  # idempotent

    def test_fingerprint_catches_repost(self):
        conn = make_conn()
        repost = dict(POSITIVE, url=POSITIVE["url"].replace("sample001", "sample009"))
        self.assertEqual(len(dedup.store(conn, [POSITIVE, repost])), 1)


class TestSpamFilter(unittest.TestCase):
    def test_noise_archived_goods_survive(self):
        conn = make_conn()
        dedup.store(conn, [POSITIVE, SPAM])
        survivors = spam_filter.filter_noise(conn, [POSITIVE, SPAM], ["[HIRING]", "casino", "follow for follow"])
        self.assertEqual(len(survivors), 1)
        statuses = [r["status"] for r in conn.execute("SELECT status FROM requests")]
        self.assertIn("archived", statuses)
        self.assertIn("lead", statuses)


class TestAlertFormat(unittest.TestCase):
    def test_message_contains_parts(self):
        msg = telegram.format_message(POSITIVE)
        self.assertIn("reddit", msg)
        self.assertIn("samplebuy", msg)
        self.assertIn("https://www.reddit.com/r/automation/comments/sample001", msg)

    def test_alert_requires_creds(self):
        saved = {k: os.environ.pop(k, None) for k in ("TG_TOKEN", "TG_CHAT_ID")}
        try:
            with self.assertRaises(RuntimeError):
                telegram.alert(make_conn(), [POSITIVE])
        finally:
            os.environ.update({k: v for k, v in saved.items() if v is not None})


if __name__ == "__main__":
    unittest.main(verbosity=2)
