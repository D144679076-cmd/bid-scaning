"""M9 stats tests — /stats analytics + topic column (2026-11-06).

Covers:
- db.connect() invariant migration: `topic` column exists on old DBs
- stats.totals / by_group (web-build vs tool-build rollup)
- stats.purposes (top topic ranking, blank topics excluded)
- stats.top_tools (JSON1 ranking, fallback OK)
- stats.build_report — full + section renders, empty-DB safe
- run_pipeline._persist writes topic
- classifier.classify_one passes topic through (mocked LLM client)

Run: python3 tests/test_stats.py   (unittest, no network)
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import connect  # noqa: E402
from alerts import stats as Stats  # noqa: E402


class TestTopicMigration(unittest.TestCase):
    def test_connect_adds_topic_column(self):
        with TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "bidscan.db")
            conn = connect(db)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
                self.assertIn("topic", cols)
            finally:
                conn.close()
            # reopen — idempotent, no ALTER on a column that now exists
            conn2 = connect(db)
            conn2.close()


def _seed(conn):
    conn.execute("""INSERT INTO requests
        (source, url, fingerprint, raw_text, score, task_type, tools,
         topic, status, created_at) VALUES
        ('reddit','u1','f1','text',7,'web/app dev','["n8n"]','crm',
         'lead','2026-11-06 10:00:00'),
        ('reddit','u2','f2','text',8,'web/app dev','["n8n"]','crm',
         'lead','2026-11-06 10:00:00'),
        ('freelancer','u3','f3','text',6,'scraper','["playwright"]','lead
         scraper','lead','2026-11-05 10:00:00'),
        ('upwork','u4','f4','text',7,'automation','["zapier"]','invoice bot',
         'lead','2026-11-06 10:00:00'),
        ('make','u5','f5','text',3,'not a request','[]',NULL,
         'low','2026-11-06 10:00:00')""")
    conn.commit()


class TestStats(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        from db import SCHEMA
        self.conn.executescript(SCHEMA)
        _seed(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_totals_counts_leads(self):
        t = Stats.totals(self.conn)
        self.assertEqual(t["total"], 5)
        self.assertEqual(t["leads"], 4)
        self.assertEqual(t["low"], 1)

    def test_window_filters(self):
        self.conn.execute(
            "INSERT INTO requests (source,url,fingerprint,raw_text,score,"
            "task_type,status,created_at) VALUES ('x','u8','f8','t',5,"
            "'automation','lead',datetime('now','-10 days'))")
        self.conn.commit()
        self.assertEqual(Stats.totals(self.conn, days=7)["total"], 5)
        self.assertEqual(Stats.totals(self.conn, days=0)["total"], 6)

    def test_by_group_rollup(self):
        g = Stats.by_group(self.conn)
        self.assertEqual(g[Stats.WEB_GROUP], 2)   # 2× web/app dev
        self.assertEqual(g[Stats.TOOL_GROUP], 2)  # scraper + automation

    def test_purposes_ranking(self):
        p = Stats.purposes(self.conn)
        self.assertEqual(p[0], ("crm", "web/app dev", 2))
        topics = [x[0] for x in p]
        self.assertIn("invoice bot", topics)

    def test_top_tools(self):
        tools = dict(Stats.top_tools(self.conn))
        self.assertEqual(tools.get("n8n"), 2)
        self.assertIn("playwright", tools)

    def test_top_tools_bad_json_fallback(self):
        self.conn.execute(
            "INSERT INTO requests (source,url,fingerprint,raw_text,tools,topic,"
            "status,created_at) VALUES ('x','u9','f9','t','not-json','x','lead',"
            "datetime('now'))")
        self.conn.commit()
        self.assertEqual(Stats.top_tools(self.conn), [])

    def test_build_report_sections(self):
        out = Stats.build_report(self.conn, days=0)
        self.assertIn("tool-build", out)
        self.assertIn("web-build", out)
        self.assertIn("reddit", Stats.build_report(self.conn, days=0,
                                                   section="source"))
        self.assertIn("tool-build", Stats.build_report(self.conn, days=0,
                                                       section="type"))
        self.assertIn("crm", Stats.build_report(self.conn, days=0,
                                                section="topic"))

    def test_build_report_empty_db(self):
        empty = sqlite3.connect(":memory:")
        empty.row_factory = sqlite3.Row
        from db import SCHEMA
        empty.executescript(SCHEMA)
        try:
            out = Stats.build_report(empty, days=0)
            self.assertIn("total 0", out)
        finally:
            empty.close()


class TestPersistTopic(unittest.TestCase):
    def test_persist_writes_topic(self):
        import run_pipeline
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        from db import SCHEMA
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO requests (source,url,fingerprint,raw_text)"
                     " VALUES ('reddit','u1','f1','t')")
        conn.commit()
        item = {"db_id": 1, "score": 7, "request_type": "web/app dev",
                "tools": ["n8n"], "topic": "crm", "budget": "", "language": ""}
        run_pipeline._persist(conn, item)
        row = conn.execute("SELECT topic, task_type FROM requests WHERE id=1"
                           ).fetchone()
        self.assertEqual(row["topic"], "crm")
        self.assertEqual(row["task_type"], "web/app dev")


class TestClassifierTopic(unittest.TestCase):
    def test_classify_one_passes_topic(self):
        from pipeline.classifier import classify_one

        def fake_client(cfg, messages):
            return {"is_request": True, "score": 8,
                    "request_type": "web/app dev",
                    "topic": "crm dashboard", "tools": [" wordpress"],
                    "budget": "$200", "deadline": "", "language": "en",
                    "pay_capability": "clear", "reason": "ok"}

        item = {"source": "reddit", "raw_text": "need a crm", "author": "a"}
        out = classify_one({}, fake_client, item)
        self.assertEqual(out["topic"], "crm dashboard")
        self.assertEqual(out["tools"], [" wordpress"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
