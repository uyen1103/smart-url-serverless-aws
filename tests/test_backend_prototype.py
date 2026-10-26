"""Test cho backend/prototype.py. Chạy từ thư mục gốc repo:
    python -m pytest tests -v        (hoặc: python -m unittest discover tests -v)
"""
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import prototype as p  # noqa: E402

OWNER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def error_code(result):
    return result["error"]["code"]


class BaseTest(unittest.TestCase):
    def setUp(self):
        p.DB.clear()
        p.BLOCKED_DOMAINS.clear()


class ValidateUrlTests(unittest.TestCase):
    def test_valid(self):
        for u in ["http://example.com", "https://example.com/a/b?x=1#y",
                  "https://sub.example.co.uk:8080/path", "http://8.8.8.8/"]:
            self.assertTrue(p.validate_url(u)[0], u)

    def test_invalid_format(self):
        for u in ["", "   ", None, 123, "not-a-url", "example.com",
                  "http://", "https:///path", "http://exa mple.com",
                  "http://example.com:abc", "https://user:pass@example.com"]:
            self.assertFalse(p.validate_url(u)[0], repr(u))

    def test_scheme_not_allowed(self):
        for u in ["ftp://example.com", "javascript:alert(1)",
                  "file:///etc/passwd", "data:text/html,<h1>x</h1>"]:
            self.assertFalse(p.validate_url(u)[0], u)

    def test_too_long(self):
        self.assertFalse(p.validate_url("https://example.com/" + "a" * 2100)[0])

    def test_ssrf_blocked(self):
        for u in ["http://localhost/x", "http://LOCALHOST./x", "http://a.localhost/x",
                  "http://127.0.0.1/x", "http://127.1/x", "http://2130706433/x",
                  "http://0x7f.0.0.1/x", "http://10.0.0.5/x", "http://192.168.1.1/x",
                  "http://172.16.0.1/x", "http://169.254.169.254/latest/meta-data/",
                  "http://[::1]/x", "http://0.0.0.0/x"]:
            ok, reason = p.validate_url(u)
            self.assertFalse(ok, u)
            self.assertEqual(reason, "host_not_allowed", u)

    def test_own_domain_blocked(self):
        for u in ["https://linkpulse.vn/abc", "https://www.linkpulse.vn/abc",
                  "https://LinkPulse.vn./abc"]:
            self.assertEqual(p.validate_url(u), (False, "own_domain"), u)
        self.assertTrue(p.validate_url("https://notlinkpulse.vn/abc")[0])


class ShortenTests(BaseTest):
    def test_success_shape(self):
        r = p.shorten("https://example.com/a")
        self.assertEqual(r["status"], 201)
        self.assertTrue(r["created"])
        self.assertEqual(len(r["code"]), p.CODE_LENGTH)
        self.assertTrue(all(c in p.ALPHABET for c in r["code"]))
        self.assertEqual(r["short_url"], "https://linkpulse.vn/" + r["code"])
        self.assertIn(r["code"], p.DB)

    def test_invalid_url(self):
        for bad in ["abc", "http://127.0.0.1", "https://linkpulse.vn/x"]:
            r = p.shorten(bad)
            self.assertEqual((r["status"], error_code(r)), (400, "invalid_url"), bad)
        self.assertEqual(len(p.DB), 0)

    def test_blocked_domain(self):
        p.BLOCKED_DOMAINS.add("bad.example")
        for u in ["https://bad.example/x", "https://sub.bad.example/x"]:
            r = p.shorten(u)
            self.assertEqual((r["status"], error_code(r)), (400, "blocked_domain"), u)
        self.assertEqual(p.shorten("https://notbad.example/x")["status"], 201)

    def test_invalid_options(self):
        cases = [({"expires_in": 0}, "invalid_expires_in"),
                 ({"expires_in": 10}, "invalid_expires_in"),
                 ({"expires_in": p.MAX_EXPIRES_IN + 1}, "invalid_expires_in"),
                 ({"expires_in": "3600"}, "invalid_expires_in"),
                 ({"expires_in": True}, "invalid_expires_in"),
                 ({"max_clicks": 0}, "invalid_max_clicks"),
                 ({"max_clicks": "5"}, "invalid_max_clicks"),
                 ({"alias": "ab"}, "invalid_alias"),
                 ({"alias": "a" * 31}, "invalid_alias"),
                 ({"alias": "co dau"}, "invalid_alias"),
                 ({"alias": "dấu"}, "invalid_alias")]
        for kwargs, code in cases:
            r = p.shorten("https://example.com", **kwargs)
            self.assertEqual((r["status"], error_code(r)), (400, code), kwargs)

    def test_expires_in_seconds(self):
        now = p._now()
        r = p.shorten("https://example.com", expires_in=3600, now=now)
        self.assertEqual(r["expires_at"], now + timedelta(hours=1))

    def test_alias_ok_and_taken(self):
        r = p.shorten("https://example.com/a", alias="khuyen-mai")
        self.assertEqual((r["status"], r["code"]), (201, "khuyen-mai"))
        r2 = p.shorten("https://example.com/b", alias="khuyen-mai")
        self.assertEqual((r2["status"], error_code(r2)), (409, "alias_taken"))
        self.assertEqual(p.DB["khuyen-mai"]["long_url"], "https://example.com/a")

    def test_reserved_alias(self):
        for alias in ["api", "API", "dashboard", "error", "warning"]:
            r = p.shorten("https://example.com", alias=alias)
            self.assertEqual((r["status"], error_code(r)), (409, "alias_taken"), alias)

    def test_duplicate_same_owner_returns_existing(self):
        first = p.shorten("https://example.com/a", owner_id=OWNER_A)
        again = p.shorten("https://example.com/a", owner_id=OWNER_A)
        self.assertEqual((again["status"], again["created"]), (200, False))
        self.assertEqual(again["code"], first["code"])
        self.assertEqual(len(p.DB), 1)

    def test_duplicate_other_owner_creates_new(self):
        a = p.shorten("https://example.com/a", owner_id=OWNER_A)
        b = p.shorten("https://example.com/a", owner_id=OWNER_B)
        self.assertEqual(b["status"], 201)
        self.assertNotEqual(a["code"], b["code"])

    def test_no_dedupe_without_owner_or_with_alias(self):
        self.assertNotEqual(p.shorten("https://example.com/a")["code"],
                            p.shorten("https://example.com/a")["code"])
        p.shorten("https://example.com/a", owner_id=OWNER_A)
        r = p.shorten("https://example.com/a", alias="ten-rieng", owner_id=OWNER_A)
        self.assertEqual((r["status"], r["code"]), (201, "ten-rieng"))

    def test_expired_link_is_not_reused(self):
        now = p._now()
        first = p.shorten("https://example.com/a", owner_id=OWNER_A,
                          expires_in=3600, now=now)
        later = now + timedelta(hours=2)
        again = p.shorten("https://example.com/a", owner_id=OWNER_A, now=later)
        self.assertEqual(again["status"], 201)
        self.assertNotEqual(again["code"], first["code"])

    def test_collision_retries(self):
        p.DB["AAAAAAA"] = {"long_url": "https://old.com", "status": "active"}
        codes = iter(["AAAAAAA", "AAAAAAA", "BBBBBBB"])
        r = p.shorten("https://example.com", code_generator=lambda: next(codes))
        self.assertEqual((r["status"], r["code"]), (201, "BBBBBBB"))
        self.assertEqual(p.DB["AAAAAAA"]["long_url"], "https://old.com")  # không bị ghi đè

    def test_collision_gives_up(self):
        p.DB["AAAAAAA"] = {"long_url": "https://old.com", "status": "active"}
        r = p.shorten("https://example.com", code_generator=lambda: "AAAAAAA")
        self.assertEqual((r["status"], error_code(r)), (500, "internal_error"))
        self.assertEqual(r["error"]["reason"], "code_generation_failed")

    def test_codes_are_unique_in_bulk(self):
        codes = {p.shorten("https://example.com/%d" % i)["code"] for i in range(2000)}
        self.assertEqual(len(codes), 2000)


class RedirectTests(BaseTest):
    def test_redirect_counts_click(self):
        code = p.shorten("https://example.com/a")["code"]
        r = p.redirect(code)
        self.assertEqual((r["status"], r["location"]), (302, "https://example.com/a"))
        p.redirect(code)
        self.assertEqual(p.DB[code]["click_count"], 2)

    def test_not_found(self):
        r = p.redirect("zzzzzzz")
        self.assertEqual((r["status"], error_code(r)), (404, "not_found"))

    def test_expired(self):
        code = p.shorten("https://example.com", expires_in=3600)["code"]
        r = p.redirect(code, now=p._now() + timedelta(hours=2))
        self.assertEqual((r["status"], error_code(r)), (410, "link_expired"))
        self.assertEqual(p.DB[code]["click_count"], 0)  # link hết hạn không tính click

    def test_max_clicks(self):
        code = p.shorten("https://example.com", max_clicks=2)["code"]
        self.assertEqual(p.redirect(code)["status"], 302)
        self.assertEqual(p.redirect(code)["status"], 302)
        r = p.redirect(code)
        self.assertEqual((r["status"], error_code(r)), (410, "max_clicks_reached"))

    def test_blocked_never_redirects(self):
        code = p.shorten("https://example.com")["code"]
        p.DB[code]["status"] = "blocked"
        for confirm in (False, True):
            r = p.redirect(code, confirm=confirm)
            self.assertEqual((r["status"], error_code(r)), (403, "link_blocked"))
        self.assertEqual(p.DB[code]["click_count"], 0)

    def test_suspicious_needs_confirm(self):
        code = p.shorten("https://example.com/x")["code"]
        p.DB[code]["status"] = "suspicious"
        r = p.redirect(code)
        self.assertEqual((r["status"], error_code(r)), (403, "link_suspicious"))
        self.assertEqual(p.DB[code]["click_count"], 0)
        ok = p.redirect(code, confirm=True)
        self.assertEqual((ok["status"], ok["location"]), (302, "https://example.com/x"))

    def test_blocked_takes_priority_over_expired(self):
        code = p.shorten("https://example.com", expires_in=3600)["code"]
        p.DB[code]["status"] = "blocked"
        r = p.redirect(code, now=p._now() + timedelta(hours=2))
        self.assertEqual(error_code(r), "link_blocked")


class DeleteTests(BaseTest):
    def test_owner_can_delete(self):
        code = p.shorten("https://example.com", owner_id=OWNER_A)["code"]
        self.assertEqual(p.delete_link(code, OWNER_A), {"status": 204})
        self.assertEqual(p.redirect(code)["status"], 404)  # sau khi xóa: không còn link

    def test_other_owner_cannot_delete(self):
        code = p.shorten("https://example.com", owner_id=OWNER_A)["code"]
        r = p.delete_link(code, OWNER_B)
        self.assertEqual((r["status"], error_code(r)), (403, "forbidden"))
        self.assertEqual(p.redirect(code)["status"], 302)  # link vẫn còn

    def test_missing_owner_and_missing_link(self):
        code = p.shorten("https://example.com", owner_id=OWNER_A)["code"]
        self.assertEqual(p.delete_link(code, None)["status"], 401)
        self.assertEqual(p.delete_link("khongco", OWNER_A)["status"], 404)

    def test_delete_twice_and_alias_not_reusable(self):
        p.shorten("https://example.com", alias="ten-rieng", owner_id=OWNER_A)
        p.delete_link("ten-rieng", OWNER_A)
        self.assertEqual(p.delete_link("ten-rieng", OWNER_A)["status"], 404)
        r = p.shorten("https://example.com/khac", alias="ten-rieng", owner_id=OWNER_B)
        self.assertEqual((r["status"], error_code(r)), (409, "alias_taken"))


if __name__ == "__main__":
    unittest.main()
