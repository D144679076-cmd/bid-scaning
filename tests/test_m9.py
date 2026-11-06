"""M9 tests — balance + FB re-point (2026-11-05).

Covers:
- fair alert queue (per-source quotas, M9 B1)
- runtime overrides (/quota, /filter) — pipeline/source_state.py
- Vietnamese payment signals + amount extraction (fb tool-market groups)
- FB buyer-ask filter (_fb_relevance_ok) against REAL sampled posts
  from the 2026-11-05 live probes (docs/fb-scan-report.md addendum §C)
- fb-skeleton detection contract (_visible_articles returns 2-tuple)

Run: python3 tests/test_m9.py   (unittest, no network)
"""

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import source_state  # noqa: E402
from run_pipeline import _fair_queue  # noqa: E402
from pipeline.payment_check import (  # noqa: E402
    extract_amounts, gate_payments, has_payment_signal, compile_patterns)

# ---- 2026-11-06: contact-first FB gate + dedup chrome-fix + EN filter ----
import yaml  # noqa: E402
from pipeline.dedup import _fingerprint, content_hash  # noqa: E402
from pipeline.dedup import _CHROME_LINE  # noqa: E402
from collectors.fb_feed import (  # noqa: E402
    _fb_relevance_ok, _is_vietnamese)

_CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
_FB = _CFG["sources"]["facebook"]


def _memconn2():
    conn = _memconn()
    conn.execute("ALTER TABLE requests ADD COLUMN score INTEGER")
    conn.execute("ALTER TABLE requests ADD COLUMN contact_channel TEXT")
    return conn


def _memconn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE requests (
        id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE,
        fingerprint TEXT UNIQUE, author TEXT, posted_at TEXT,
        raw_text TEXT, status TEXT, created_at TEXT, budget TEXT)""")
    return conn


class TestFairQueue(unittest.TestCase):
    def test_round_robin_and_caps(self):
        scored = ([{"source": "freelancer"}] * 20 + [{"source": "upwork"}] * 5
                  + [{"source": "make"}] * 4 + [{"source": "reddit"}] * 1)
        q = _fair_queue(scored, {"freelancer": 4}, 3)
        from collections import Counter
        c = Counter(x["source"] for x in q)
        self.assertEqual(c["freelancer"], 4)
        self.assertEqual(c["upwork"], 3)
        self.assertEqual(c["make"], 3)
        self.assertEqual(c["reddit"], 1)

    def test_mute(self):
        scored = [{"source": "s"}] * 5
        q = _fair_queue(scored, {"s": 0}, 3)
        self.assertEqual(q, [])


class TestSourceState(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.patch_a = patch.object(source_state, "DATA",
                                    Path(self.tmp.name))
        self.patch_b = patch.object(source_state, "STATE_FILE",
                                    Path(self.tmp.name, "source_state.json"))
        self.patch_c = patch.object(
            source_state, "OVERRIDES_FILE",
            Path(self.tmp.name, "source_overrides.json"))
        for p in (self.patch_a, self.patch_b, self.patch_c):
            p.start()
            self.addCleanup(p.stop)

    def test_quota_roundtrip(self):
        ovr = source_state.quota("freelancer", alerts_n=4, max_n=8)
        self.assertEqual(ovr["alerts_per_cycle"]["freelancer"], 4)
        self.assertEqual(ovr["max_items"]["freelancer"], 8)
        ovr = source_state.quota("facebook", alerts_n=0)
        self.assertEqual(ovr["alerts_per_cycle"]["facebook"], 0)

    def test_record_and_report(self):
        source_state.record({"reddit": 7, "facebook": 0})
        rows = source_state._read(source_state.STATE_FILE, {})
        self.assertEqual(rows["reddit"]["count"], 7)

    def test_filter_add_del(self):
        ovr = source_state.filter_words(require=["nhận làm"],
                                        reject=["bao test", "bảo hành"])
        self.assertIn("nhận làm", ovr["filter_add"]["require"])
        ovr = source_state.filter_words(reject_del=["bao test"])
        self.assertNotIn("bao test", ovr["filter_add"]["reject"])
        self.assertIn("bảo hành", ovr["filter_add"]["reject"])


class TestVietnamesePaymentSignals(unittest.TestCase):
    PATTERNS = [
        "\\$\\d", "\\bbudget\\b",
        "\\bgi[áa]\\b", "\\bb[áa]o gi[áa]\\b", "\\bbao nhi[êe]u\\b",
        "\\bth[ổo]a thu[ạa]n\\b", "\\bd[ựu] [áa]n\\b",
        "\\b\\d+([.,]\\d+)?\\s?(k|tr|tri[êe]u|vnd)\\b",
        "\\b\\d+(?:[.,]\\d+)?(?:k|tr|tri[êe]u)[\\d.,]*\\b",
        "\\bai\\b[^.]{0,60}\\btool\\b",
        "\\b\\d+([.,]\\d+)?\\s?(k|tr|tri[êe]u|vnd)\\b",
        "\\bs[ôo] ti[êe]n\\b", "\\bin?b?\\s?(hoặc|để)\\s?b[áa]o\\b",
        "\\bd[àa]t c[ôo]c\\b",
        "\\bcần(\\s+tìm|\\s+thuê)?\\b[^.]{0,80}\\b(tool|code|phần mềm|bot|app|web|script)\\b",
        "\\bthu[êe]\\b[^.]{0,60}\\b(code|tool|dev|làm|viết)\\b",
        "\\b(tìm|ai)\\s?(người|bác|bạn|ae|các bác)?\\s?(làm|code|viết|giúp)\\b",
        "\\bv[ềi]t\\s?v?c?od(e|ing)?\\b",
        "\\bvi[êe]t code\\b", "\\bvi[êe]t app\\b",
        "\\bvi[êe]t ch[ưư][ơo]ng tr[ìi]nh\\b",
        "\\bcần người\\b",
        "\\bs[ảa]n ph[ẩả]m thi\\b",
        "\\bthi (khkt|s[áa]ng t[ậa]o|hi[ểe]n|khph)\\b",
    ]

    def test_real_marketplace_posts_pass(self):
        """2026-11-05..06 live samples (docs/fb-scan-report.md addendum)."""
        for post in ("E cần tìm bác nào biết về tool C/C++ Mu Online ạ.",
                     "Ae ai ở hn có tool nào sài outo up bài cho Fb ko ạ",
                     "Bác nào nhận làm site bằng 1tr5 không",
                     "Tool mmo giá 500k bản trad",
                     "Ib để báo giá chi tiết nha ae",
                     "E đang cần người viết cod cho 1 sản phẩm thi KHKT. "
                     "Liên hệ e với ạ"):
            self.assertTrue(has_payment_signal(
                post, compile_patterns(self.PATTERNS)), post)

    def test_real_noise_rejected(self):
        for post in ("Th kệ, đi bus cho nó ấm mà bạn ơi",
                     "Việt phải không em? ở đâu vậy bạn, mình ở sg nek",
                     "Web nào bác ơi nhắn zalo em"):
            self.assertFalse(has_payment_signal(
                post, compile_patterns(self.PATTERNS)), post)

    def test_gate_passes_vn_paid_posts(self):
        post = ("E cần tìm bác nào biết về tool C/C++ Mu Online ạ. "
                "sẵn ib để báo giá cho e")
        self.assertTrue(has_payment_signal(
            post, compile_patterns(self.PATTERNS)))
        post2 = "Ae ai có tool nào sài outo up bài cho Fb ko ạ, hỏi giá"
        self.assertTrue(has_payment_signal(
            post2, compile_patterns(self.PATTERNS)))

    def test_gate_rejects_chit_chat(self):
        post = "Th kệ, đi bus cho nó ấm mà bạn ơi"
        self.assertFalse(has_payment_signal(
            post, compile_patterns(self.PATTERNS)))

    def test_amounts_vn(self):
        pats = ["\\b\\d[\\d.,]*\\s?(?:k|tr|tri[êe]u)(?:\\d)?\\b",
                "gi[áa]\\s?\\d[\\d.,]*\\s?(?:k|tr|tri[êe]u|vnd|đ)?"]
        self.assertIn("500k", extract_amounts("tool giá 500k cho", pats))
        self.assertTrue(extract_amounts("làm giá 1tr5", pats))


class TestFbRelevanceFilter(unittest.TestCase):
    import collectors.fb_feed as fb

    REQUIRE = ["cần", "tìm", "thuê", "hỏi giá", "ai biết", "giúp", "hộ",
               "làm tool", "viết tool", "code tool", "tool nào",
               "cần viết", "cần code", "tìm người"]
    REJECT = ["nhận code", "nhận làm", "nhận viết", "nhận gia công",
              "dịch vụ", "uy tín", "bao test", "bảo hành", "cam kết",
              "theo dõi", "sẵn nha", "giữ liên hệ"]

    def test_buyer_ask_kept(self):
        self.assertTrue(self.fb._fb_relevance_ok(
            "E cần tìm bác nào biết về tool C/C++ Mu Online ạ.",
            self.REQUIRE, self.REJECT))
        self.assertTrue(self.fb._fb_relevance_ok(
            "Ae ai ở hn có tool nào sài outo up bài cho Fb ko ạ",
            self.REQUIRE, self.REJECT))

    def test_seller_promo_rejected(self):
        self.assertFalse(self.fb._fb_relevance_ok(
            "DK Tech - Website Theo Yêu Cầu — theo dõi — dựng tool con "
            "game kiếm hiệp, liên hệ utín kết quả cam kết",
            self.REQUIRE, self.REJECT))
        self.assertFalse(self.fb._fb_relevance_ok(
            "Tool mmo bao test bảo hành / ib tele toolmmohup có bản test",
            self.REQUIRE, self.REJECT))

    def test_chat_rejected(self):
        self.assertFalse(self.fb._fb_relevance_ok(
            "Việt phải không em? ở đâu vậy bạn, mình ở sg nek",
            self.REQUIRE, self.REJECT))


class TestSkeletonTuple(unittest.TestCase):
    """_visible_articles must return (filled, raw) — M9 contract."""

    def test_skeleton_tuple(self):
        import collectors.fb_feed as fb
        import inspect
        src = inspect.getsource(fb._visible_articles)
        self.assertIn("->", src)
        self.assertIn("len(nodes", src)


class TestFbDedup(unittest.TestCase):
    """M9 dedup fix: per-post pseudo-URLs — every distinct post is stored
    even from the same group page (this bug previously capped FB at
    1 row/group/cycle silently)."""

    def test_distinct_posts_same_group_survive(self):
        from pipeline import dedup
        conn = _memconn()
        a, b, c = "post text one", "post text two", "post text one"
        items = []
        for txt in (a, b, c):
            items.append({"source": "facebook",
                          "url": "http://g/p",
                          "raw_text": txt})
        # simulate fb_feed's pseudo-URL treatment
        import hashlib
        for it in items:
            it["url"] = ("http://g/p?p="
                         + hashlib.sha1(it["raw_text"].encode()).hexdigest()[:12])
        fresh = dedup.store(conn, items)
        self.assertEqual(len(fresh), 2)  # a + b kept, c deduped by URL
        n = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        self.assertEqual(n, 2)


class TestContactFirstGate(unittest.TestCase):
    """Client rule 2026-11-06: FB = contact first (ib/inbox culture); price
    negotiated after contact. Non-FB gate behavior byte-identical."""

    FB_ASK = "E cần tìm bác nào biết về tool C/C++ Mu Online ạ. ib em để báo giá."
    REQUESTS = [{"source": "facebook", "url": "https://x?f=1",
                 "raw_text": FB_ASK}]

    def test_fb_ask_with_ib_passes_gate(self):
        conn = _memconn2()
        conn.execute("INSERT INTO requests(url,fingerprint,raw_text,status,"
                     "contact_channel) VALUES('https://x?f=1','fp1','x','lead',NULL)")
        out = gate_payments(conn, self.REQUESTS,
                            _CFG["payment_signals"], _CFG["amount_patterns"],
                            contact_patterns=_CFG["contact_signals"],
                            gate_policy=_CFG["gate_policy"])
        self.assertEqual(len(out), 1)          # not unpaid
        self.assertEqual(out[0].get("contact_channel"), "ib")

    def test_fb_silent_ask_no_signal_unpaid(self):
        conn = _memconn2()
        conn.execute("INSERT INTO requests(url,fingerprint,raw_text,status) "
                     "VALUES('https://y?f=1','fp2','x','lead')")
        item = [{"source": "facebook", "url": "https://y?f=1",
                 "raw_text": "hôm nay trời đẹp quá"}]
        out = gate_payments(conn, item, _CFG["payment_signals"],
                            _CFG["contact_signals"])
        self.assertEqual(len(out), 0)          # → unpaid, no alert

    def test_freelancer_gate_unchanged(self):
        conn = _memconn2()
        conn.execute("INSERT INTO requests(url,fingerprint,raw_text,status) "
                     "VALUES('https://z?f=1','fp3','x','lead')")
        item = [{"source": "freelancer", "url": "https://z?f=1",
                 "raw_text": "Need a script built, budget $500, DM me"}]
        out = gate_payments(conn, item, _CFG["payment_signals"],
                            _CFG["amount_patterns"],
                            contact_patterns=_CFG["contact_signals"],
                            gate_policy=_CFG["gate_policy"])
        self.assertEqual(len(out), 1)          # passes the PAYMENT rule
        item = [{"source": "freelancer", "url": "https://z?f=1",
                 "raw_text": "Need a script built, DM me"}]
        out = gate_payments(conn, item, _CFG["payment_signals"],
                            _CFG["amount_patterns"],
                            contact_patterns=_CFG["contact_signals"],
                            gate_policy=_CFG["gate_policy"])
        self.assertEqual(len(out), 0)          # no money words → still unpaid


class TestFacebookFilters(unittest.TestCase):
    def _ok(self, body):
        return _fb_relevance_ok(
            body, _FB["require_keywords"], _FB["reject_keywords"],
            require_en=_FB["require_keywords_en"],
            reject_en=_FB["reject_keywords_en"])

    def test_real_leaking_seller_ads_rejected(self):
        # DB rows 1265/1284 and 1268 — leaked as low/unpaid before tightening
        self.assertFalse(self._ok(
            "Dạ em chào anh! Nếu anh đang cần thiết kế web/app bên em "
            "sẽ tư vấn miễn phí, báo giá phù hợp"))
        self.assertFalse(self._ok(
            "Mình đang có sẵn phần mềm đăng bài báo, tin rao vặt theo yêu cầu"))
        self.assertFalse(self._ok(
            "Thiệp in hàng loạt mà thông tin mỗi khách hàng khác nhau"))

    def test_real_buyer_ask_kept(self):
        self.assertTrue(self._ok(
            "E cần tìm bác nào biết về tool C/C++ Mu Online ạ."))

    def test_language_detection(self):
        self.assertTrue(_is_vietnamese("E cần tìm bác nào về tool ạ"))
        self.assertFalse(_is_vietnamese("Can anyone build me a booking bot?"))

    def test_en_branch(self):
        self.assertTrue(self._ok(
            "Can anyone build a scraper for my shop? DM me your rate"))
        self.assertFalse(self._ok(
            "We are agency offering cheap rates, check my page"))


class TestDedupChromeFix(unittest.TestCase):
    """Same FB post re-polls with a different relative-time line — the
    fingerprint + pseudo-URL hash must be stable (DB rows 1265/1284)."""

    BODIES = [
        "Nguyen Bi Anh\n·\n32 phút\nDạ em chào anh!",
        "Nguyen Bi Anh\n·\n3 giờ\nDạ em chào anh!",
        "Nguyen Bi Anh\n·\n2h\nDạ em chào anh!",
    ]

    def test_fingerprint_stable_across_time_chrome(self):
        hs = {_fingerprint(b) for b in self.BODIES}
        self.assertEqual(len(hs), 1)

    def test_pseudo_url_stable(self):
        hs = {content_hash(b) for b in self.BODIES}
        self.assertEqual(len(hs), 1)

    def test_chrome_line_regex(self):
        self.assertTrue(_CHROME_LINE.match("48 phút"))
        self.assertTrue(_CHROME_LINE.match("· 2 hours ago"))
        self.assertFalse(_CHROME_LINE.match("E cần tìm bác nào về tool"))


class TestConfigContactsPolicy(unittest.TestCase):
    def test_gate_policy_and_signals_present(self):
        self.assertEqual(_CFG["gate_policy"]["facebook"], "contact_first")
        rx = compile_patterns(_CFG["contact_signals"])
        for probe in ("ib em", "inbox", "DM me", "zalo", "0987654321",
                      "tele"):
            self.assertTrue(any(r.search(probe) for r in rx), probe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
