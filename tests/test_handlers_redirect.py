"""GET /{code} (handlers/redirect.py) chạy trên 5 bảng moto của conftest."""
import time

import pytest

from handlers import redirect
from helpers import add_link, body_of, error_of, make_event
from linkpulse import http, ratelimit, repo
from linkpulse.config import settings

CODE = "abc1234"
LONG_URL = "https://example.com/bai-viet"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
PAST, FUTURE = "2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"


def visit(code=CODE, *, headers=None, query=None, ip="203.0.113.7"):
    return redirect.lambda_handler(make_event("GET /{code}", path_params={"code": code}, headers=headers,
                                              query=query, ip=ip), None)


def link(tables):
    return tables["urls"].get_item(Key={"short_code": CODE})["Item"]


def clicks(tables):
    return tables["clicks"].scan()["Items"]


# ------------------------------------------------------------------ chuyển hướng thành công
def test_active_link_redirects_with_302_and_no_store(tables):
    add_link(CODE, long_url=LONG_URL)
    resp = visit()
    assert resp["statusCode"] == 302 and "body" not in resp
    assert resp["headers"] == {"Location": LONG_URL, "Cache-Control": "no-store"}


def test_every_visit_counts_one_click_and_stores_one_event(tables):
    add_link(CODE)
    for _ in range(3):
        assert visit()["statusCode"] == 302
    assert int(link(tables)["click_count"]) == 3 and len(clicks(tables)) == 3


def test_click_event_content_and_privacy(tables):
    add_link(CODE)
    visit(headers={"user-agent": CHROME, "referer": "https://www.facebook.com/post/1", "cloudfront-viewer-country": "vn",
                   "cloudfront-viewer-address": "203.0.113.9:4711"})
    (event,) = clicks(tables)
    assert (event["short_code"], event["country"], event["device"], event["browser"], event["referrer"],
            event["result"]) == (CODE, "VN", "desktop", "Chrome", "facebook.com", "valid")
    assert event["ip_hash"] == ratelimit.ip_hash("203.0.113.9") and len(event["ip_hash"]) == 16
    assert "203.0.113.9" not in str(event) and "user_agent" not in event                  # không lưu IP và User-Agent gốc
    assert event["timestamp"].endswith("Z") and event["sk"].startswith(event["timestamp"] + "#")
    ttl = int(event["expires_at"]) - time.time()
    assert abs(ttl - settings().clicks_ttl_days * 86400) < 60


@pytest.mark.parametrize("ua, device, browser, result", [
    (CHROME, "desktop", "Chrome", "valid"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1",
     "mobile", "Safari", "valid"),
    ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1",
     "tablet", "Safari", "valid"),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 Safari/537.36 Edg/120.0", "desktop", "Edge", "valid"),
    ("curl/8.4.0", "bot", "Other", "bot"), ("Googlebot/2.1", "bot", "Other", "bot"), ("", "bot", "Other", "bot")],
    ids=["chrome", "iphone", "ipad", "edge", "curl", "googlebot", "no_user_agent"])
def test_user_agent_classification(tables, ua, device, browser, result):
    add_link(CODE)
    visit(headers={"user-agent": ua})
    (event,) = clicks(tables)
    assert (event["device"], event["browser"], event["result"]) == (device, browser, result)


@pytest.mark.parametrize("country, expected", [("vn", "VN"), ("US", "US"), ("Vietnam", "XX"), ("", "XX"), (None, "XX")])
def test_country_header(tables, country, expected):
    add_link(CODE)
    visit(headers={"cloudfront-viewer-country": country} if country is not None else {})
    assert clicks(tables)[0]["country"] == expected


def test_referrer_defaults_to_direct(tables):
    add_link(CODE)
    visit()
    assert clicks(tables)[0]["referrer"] == "direct"


@pytest.mark.parametrize("headers, expected", [
    ({"cloudfront-viewer-address": "198.51.100.1:4711", "x-forwarded-for": "10.0.0.1"}, "198.51.100.1"),
    ({"cloudfront-viewer-address": "[2001:db8::1]:4711"}, "2001:db8::1"),
    ({"x-forwarded-for": "198.51.100.2, 10.0.0.1"}, "198.51.100.2"), ({}, "203.0.113.7")])
def test_client_ip_priority(headers, expected):
    assert http.client_ip(make_event("GET /{code}", headers=headers)) == expected


# ------------------------------------------------------------------ không chuyển hướng
@pytest.mark.parametrize("code", ["favicon.ico", "robots.txt", "ab", "a" * 31, "co dau", "dấu-hiệu"])
def test_invalid_code_is_404_without_reading_the_database(tables, monkeypatch, code):
    monkeypatch.setattr(repo, "get_link", lambda c: pytest.fail("không được đọc DB với mã sai định dạng"))
    resp = visit(code)
    assert (resp["statusCode"], error_of(resp)["code"]) == (404, "not_found")


@pytest.mark.parametrize("fields, status, code", [
    ({}, 404, "not_found"),                                        # mã không tồn tại (không tạo link)
    ({"status": "deleted"}, 404, "not_found"),
    ({"status": "blocked"}, 403, "link_blocked"),
    ({"expires_at": PAST}, 410, "link_expired"),
    ({"max_clicks": 2, "click_count": 2}, 410, "max_clicks_reached"),
    ({"status": "suspicious"}, 403, "link_suspicious"),
    # thứ tự ưu tiên: bị chặn > hết hạn > hết lượt click > đáng ngờ
    ({"status": "blocked", "expires_at": PAST}, 403, "link_blocked"),
    ({"expires_at": PAST, "max_clicks": 1, "click_count": 1}, 410, "link_expired"),
    ({"status": "suspicious", "max_clicks": 1, "click_count": 1}, 410, "max_clicks_reached"),
    ({"status": "suspicious", "expires_at": PAST}, 410, "link_expired")],
    ids=["unknown", "deleted", "blocked", "expired", "max_clicks", "suspicious", "blocked_over_expired",
         "expired_over_max_clicks", "max_clicks_over_suspicious", "expired_over_suspicious"])
def test_unusable_link_states(tables, fields, status, code):
    if fields:
        add_link(CODE, **fields)
    resp = visit()
    assert (resp["statusCode"], error_of(resp)["code"]) == (status, code)
    assert resp["headers"]["Cache-Control"] == "no-store" and "Location" not in resp["headers"]
    assert clicks(tables) == []                                                          # lỗi thì không ghi click
    if fields:
        assert int(link(tables)["click_count"]) == int(fields.get("click_count", 0))


def test_future_expiry_still_redirects(tables):
    add_link(CODE, expires_at=FUTURE)
    assert visit()["statusCode"] == 302


def test_suspicious_link_needs_confirm_equal_to_1(tables):
    add_link(CODE, status="suspicious", long_url=LONG_URL)
    for query in (None, {"confirm": "0"}, {"confirm": "true"}, {"confirm": "2"}):
        assert visit(query=query)["statusCode"] == 403
    assert clicks(tables) == []
    resp = visit(query={"confirm": "1"})
    assert (resp["statusCode"], resp["headers"]["Location"]) == (302, LONG_URL)
    assert int(link(tables)["click_count"]) == 1 and len(clicks(tables)) == 1


def test_confirm_never_bypasses_a_blocked_link(tables):
    add_link(CODE, status="blocked")
    resp = visit(query={"confirm": "1"})
    assert (resp["statusCode"], error_of(resp)["code"]) == (403, "link_blocked")


def test_click_limit_is_enforced_across_visits(tables):
    add_link(CODE, max_clicks=2)
    assert [visit()["statusCode"] for _ in range(3)] == [302, 302, 410]
    assert int(link(tables)["click_count"]) == 2 and len(clicks(tables)) == 2


def test_click_limit_is_atomic_when_the_item_read_is_stale(tables, monkeypatch):
    """Nhiều request cùng lúc: bản đọc link còn cũ (click_count=0) nhưng DB đã đủ giới hạn thì vẫn trả 410."""
    stale = add_link(CODE, max_clicks=1)
    tables["urls"].update_item(Key={"short_code": CODE}, UpdateExpression="SET click_count = :one",
                               ExpressionAttributeValues={":one": 1})
    monkeypatch.setattr(repo, "get_link", lambda code: stale)
    resp = visit()
    assert (resp["statusCode"], error_of(resp)["code"]) == (410, "max_clicks_reached")
    assert int(link(tables)["click_count"]) == 1 and clicks(tables) == []


# ------------------------------------------------------------------ chế độ ERROR_PAGE_MODE=redirect (trang của TV2)
HTML = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


@pytest.mark.parametrize("fields, location", [
    ({}, "/error.html?type=404"), ({"expires_at": PAST}, "/error.html?type=expired"),
    ({"max_clicks": 1, "click_count": 1}, "/error.html?type=max_clicks"),
    ({"status": "blocked"}, "/warning.html?reason=blocked"),
    ({"status": "suspicious"}, f"/warning.html?reason=suspicious&code={CODE}")],
    ids=["not_found", "expired", "max_clicks", "blocked", "suspicious_carries_the_code"])
def test_browser_is_redirected_to_the_error_page(tables, monkeypatch, fields, location):
    monkeypatch.setenv("ERROR_PAGE_MODE", "redirect")
    if fields:
        add_link(CODE, **fields)
    resp = visit(headers=HTML)
    assert (resp["statusCode"], resp["headers"]["Location"], resp["headers"]["Cache-Control"]) == (302, location, "no-store")


@pytest.mark.parametrize("mode, headers", [("json", HTML), ("redirect", {}), ("redirect", {"accept": "application/json"})],
                         ids=["json_mode", "no_accept_header", "accept_json"])
def test_other_clients_still_get_json_errors(tables, monkeypatch, mode, headers):
    monkeypatch.setenv("ERROR_PAGE_MODE", mode)
    add_link(CODE, expires_at=PAST)
    resp = visit(headers=headers)
    assert (resp["statusCode"], error_of(resp)["code"]) == (410, "link_expired")


# ------------------------------------------------------------------ rate limit, origin
def test_rate_limit_returns_json_429_even_for_browsers(tables, monkeypatch):
    monkeypatch.setenv("ERROR_PAGE_MODE", "redirect")
    monkeypatch.setenv("REDIRECT_RATE_LIMIT", "2")
    add_link(CODE)
    assert [visit(headers=HTML)["statusCode"] for _ in range(2)] == [302, 302]
    limited = visit(headers=HTML)
    assert limited["statusCode"] == 429 and int(limited["headers"]["Retry-After"]) >= 1
    assert body_of(limited)["error"]["code"] == "rate_limited"
    assert visit(headers=HTML, ip="198.51.100.9")["statusCode"] == 302                  # IP khác không bị ảnh hưởng


def test_origin_secret_is_checked_before_anything_else(tables, put_ssm_secret, monkeypatch):
    add_link(CODE)
    put_ssm_secret("/linkpulse/origin-verify", "origin-secret-0123456789")
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET_PARAM", "/linkpulse/origin-verify")
    assert visit()["statusCode"] == 403 and clicks(tables) == []
    assert visit(headers={"x-origin-verify": "origin-secret-0123456789"})["statusCode"] == 302
