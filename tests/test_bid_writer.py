"""M3 tests — bid writer (offline, stub LLM). Run: python3 -m tests.test_bid_writer
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
import db
from pipeline import bid_writer
from run_pipeline import draft_stage


def fake_client(cfg, messages):
    user_msg = messages[1]["content"]
    return {"draft": f"Hi — draft responding to the request. "
                     f"Profile: {len(user_msg)} chars context. "
                     f"Took notice of budget and deadline mentioned."}


CFG = yaml.safe_load(open(ROOT / "config.yaml"))


def make_conn_profile():
    c = db.connect(":memory:")
    c.execute("""INSERT INTO profile (id, name, portfolio_url, past_work,
                                      pricing_tiers, tone, contact_hint)
                 VALUES (1, 'Acme Automations', 'https://portfolio.test',
                          '[{"p":"x"}]', '[{"n":"Workflow"}]',
                          'casual EN', 'DM on platform')""")
    c.commit()
    return c


def item(source="reddit", db_id=None, note=None):
    d = {"db_id": db_id, "source": source, "url": "https://reddit.com/x",
         "author": "op", "posted_at": "now",
         "raw_text": "Need someone to build a scraper, budget $500",
         "score": 8, "request_type": "scraper", "tools": ["n8n"],
         "budget": "$500", "deadline": "1 week", "language": "en",
         "reason": "paid ask"}
    if note:
        d["client_note"] = note
    return d


class TestBidWriter(unittest.TestCase):
    def test_prompt_contains_profile_facts(self):
        conn = make_conn_profile()
        prof = bid_writer.load_profile(conn)
        self.assertEqual(prof["name"], "Acme Automations")
        self.assertIn("portfolio.test", prof["portfolio"])
        p = bid_writer.build_prompt(CFG, prof, item())
        self.assertIn("Acme Automations", p)
        self.assertIn("DM on platform", p)
        self.assertIn("Never invent credentials", p)      # hard_rules from profile.yaml
        self.assertIn("$500", p)
        self.assertIn("reddit", p)                        # source style
        self.assertEqual("900", p.split("max_chars")[1].split()[0].strip())

    def test_x_capped_280(self):
        client = lambda cfg, m: {"draft": "x" * 1000}
        conn = make_conn_profile()
        prof = bid_writer.load_profile(conn)
        draft = bid_writer.write_bid(CFG, client, prof, item(source="x"))
        self.assertLessEqual(len(draft), 300)  # 280 + margin for ellipsis

    def test_persist_sets_drafted(self):
        conn = make_conn_profile()
        conn.execute("INSERT INTO requests (source, url, fingerprint, raw_text) "
                     "VALUES ('reddit','u','f','txt')")  # id=1
        conn.commit()
        bid_writer.persist_draft(conn, item(db_id=1), "a draft text")
        row = conn.execute("SELECT status, draft_text FROM requests WHERE id=1").fetchone()
        self.assertEqual(("drafted", "a draft text"), (row["status"], row["draft_text"]))

    def test_persist_upserts(self):
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO requests (source, url, fingerprint, raw_text) VALUES "
                     "('reddit','u','f','txt')")  # id=1 status lead
        conn.commit()
        bid_writer.persist_draft(conn, {"db_id": 1}, "d1")
        row = conn.execute("SELECT status, draft_text FROM requests WHERE id=1").fetchone()
        self.assertEqual(row["status"], "drafted")
        self.assertEqual(row["draft_text"], "d1")

    def test_draft_stage_edited_becomes_approved(self):
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO requests (source, url, fingerprint, raw_text, score, "
                     "task_type, budget, status, draft_text) VALUES "
                     "('reddit','u2','f2','post text',8,'automation','$500',"
                     "'edited','my corrected note')")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM profile").fetchone()[0]
        if before == 0:
            make_conn_profile()
            # insert profile into THIS conn
            conn.execute("""INSERT INTO profile (id, name, portfolio_url, past_work,
                                 pricing_tiers, tone, contact_hint)
                            VALUES (1,'Acme','u','[]','[]','casual','DM')""")
            conn.commit()
        n = draft_stage(conn, CFG, fake_client, [])
        self.assertEqual(n, 1)
        row = conn.execute("SELECT status, draft_text FROM requests WHERE source='reddit'").fetchone()
        self.assertEqual(row["status"], "approved")
        self.assertIn("draft", row["draft_text"])

    def test_draft_stage_skips_empty_profile(self):
        conn = db.connect(":memory:")
        self.assertEqual(draft_stage(conn, CFG, fake_client, []), 0)


    def test_yaml_profile_takes_precedence(self):
        """Config-file driven: edit profile.yaml → next drafts use it, no seed."""
        import tempfile
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO requests (source, url, fingerprint, raw_text) "
                     "VALUES ('reddit','u','f','txt')")
        conn.commit()
        prof = bid_writer.load_profile(conn)  # ROOT profile.yaml = placeholder
        self.assertNotIn("Acme Yaml", prof.get("name", ""))  # DB not used here
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("name: Acme Yaml\nportfolio_url: https://y.test\n"
                    "contact_hint: 'TG @me'\ntone: friendly\n")
            tmp = f.name
        try:
            prof = bid_writer.load_profile(conn, tmp)
            self.assertEqual(prof["name"], "Acme Yaml")
            self.assertEqual(prof["contact_hint"], "TG @me")
            self.assertEqual(prof["portfolio"], "https://y.test")
        finally:
            os.unlink(tmp)

    def test_placeholder_yaml_falls_back_to_db(self):
        conn = make_conn_profile()  # DB row: Acme Automations
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("name: REPLACE-ME\n")
            tmp = f.name
        try:
            prof = bid_writer.load_profile(conn, tmp)
            self.assertEqual(prof["name"], "Acme Automations")
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
