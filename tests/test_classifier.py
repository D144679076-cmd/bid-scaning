import sqlite3
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db
from pipeline import dedup, spam_filter, payment_check, classifier


CFG_MIN = {"payment_signals": ["\\$\\d", "\\bbudget\\b", "\\bpay\\b"],
           "amount_patterns": ["\\$\\d"],
           "classifier": {"instant_alert_min_score": 6}}


def fake_client_high(cfg, messages):
    return {"is_request": True, "score": 8, "request_type": "automation", "tools": ["n8n"],
            "budget": "$500", "deadline": "this week", "language": "en",
            "pay_capability": "clear", "reason": "explicit paid ask"}


def fake_client_low(cfg, messages):
    return {"is_request": True, "score": 3, "request_type": "tool question", "tools": [],
            "budget": "", "deadline": "", "language": "en",
            "pay_capability": "implied", "reason": "discussion"}


def fake_client_freebie(cfg, messages):
    return {"is_request": True, "score": 9, "request_type": "automation", "tools": [],
            "budget": "", "deadline": "", "language": "en",
            "pay_capability": "none", "reason": "wants free"}


def make(cfg, client, text, url):
    conn = db.connect(":memory:")
    item = {"source": "reddit", "url": url, "raw_text": text,
            "author": "x", "posted_at": None}
    dedup.store(conn, [item])
    fresh = [item]
    fresh = payment_check.gate_payments(conn, fresh, cfg["payment_signals"],
                                        cfg["amount_patterns"])
    if fresh:
        # attach DB id for classifier run
        row = conn.execute("SELECT id, url FROM requests WHERE url=?",
                           (url,)).fetchone()
        fresh[0]["db_id"] = row["id"]
    return conn, classifier.run_classifier(cfg, client, fresh)


class TestClassifier(unittest.TestCase):
    def test_high_score_instant(self):
        conn, (instant, dig) = make(
            CFG_MIN, fake_client_high, "Build me a bot, budget $500", "u1")
        self.assertEqual(len(instant), 1)
        self.assertEqual(instant[0]["score"], 8)
        self.assertEqual(instant[0]["request_type"], "automation")
        self.assertIn("n8n", instant[0]["tools"])

    def test_low_score_digest(self):
        conn, (instant, dig) = make(
            CFG_MIN, fake_client_low, "Which automation tool should I buy, my budget is small?", "u2")
        self.assertEqual(len(instant), 0)
        self.assertEqual(len(dig), 1)
        self.assertEqual(dig[0]["_digest_reason"], "score<6")

    def test_freebie_never_instant(self):
        conn, (instant, dig) = make(
            CFG_MIN, fake_client_freebie, "build me something, will pay $ if you can cheap", "u3")
        self.assertEqual(instant, [])  # pay=none even at score 9
        self.assertEqual(dig[0]["_digest_reason"], "pay=none")

    def test_stub_zero_when_no_client(self):
        conn, (instant, dig) = make(CFG_MIN, None, "I can pay you for this please", "u4")
        self.assertEqual(instant, [])  # no LLM → everything to digest side
        self.assertEqual(dig[0]["score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
