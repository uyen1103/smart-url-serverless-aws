"""POST /api/shorten (handlers/shorten.py) chạy trên 5 bảng moto của conftest."""
import base64
import json

import pytest

from handlers import shorten
from helpers import OWNER_A, OWNER_B, add_link, body_of, error_of, make_event
from linkpulse import models, repo, turnstile, validation

ROUTE = "POST /api/shorten"
URL = "https://example.com/bai-viet?id=1"


def post(body, *, headers=None, ip="203.0.113.7", **kw):
    return shorten.lambda_handler(make_event(ROUTE, body=body, headers=headers, ip=ip, **kw), None)


def stored(tables, code):
    return tables["urls"].get_item(Key={"short_code": code})["Item"]


# ------------------------------------------------------------------ tạo link
def test_creates_a_link(tables):
    resp = post({"url": URL})
    body = body_of(resp)
    assert resp["statusCode"] == 201 and resp["headers"]["Content-Type"] == "application/json"
    assert validation.CODE_PATTERN.match(body["code"]) and len(body["code"]) == 7
    assert body["short_url"] == f"https://linkpulse.vn/{body['code']}"
    assert (body["created"], body["long_url"], body["expires_at"], body["max_clicks"]) == (True, URL, None, None)
    item = stored(tables, body["code"])
    assert (item["status"], int(item["click_count"]), item["long_url"]) == ("active", 0, URL)
    assert item["created_at"].endswith("Z") and "owner_id" not in item


def test_stores_owner_expiry_and_click_limit(tables):
    resp = post({"url": URL, "expires_in": 3600, "max_clicks": 5}, headers={"x-owner-id": OWNER_A.upper()})
    body = body_of(resp)
    item = stored(tables, body["code"])
    assert item["owner_id"] == OWNER_A                                  # lưu dạng chữ thường
    assert (models.parse_iso(item["expires_at"]) - models.parse_iso(item["created_at"])).total_seconds() == 3600
    assert (body["max_clicks"], int(item["max_clicks"])) == (5, 5) and body["expires_at"] == item["expires_at"]


def test_accepts_a_base64_body(tables):
    encoded = base64.b64encode(json.dumps({"url": URL}).encode()).decode()
    event = make_event(ROUTE, raw_body=encoded)
    event["isBase64Encoded"] = True
    assert shorten.lambda_handler(event, None)["statusCode"] == 201


# ------------------------------------------------------------------ cùng URL, cùng chủ sở hữu
def test_same_owner_and_url_returns_the_existing_link(tables):
    first = body_of(post({"url": URL}, headers={"x-owner-id": OWNER_A}))
    resp = post({"url": URL}, headers={"x-owner-id": OWNER_A})
    assert resp["statusCode"] == 200 and body_of(resp)["created"] is False
    assert body_of(resp)["code"] == first["code"] and tables["urls"].scan()["Count"] == 1


@pytest.mark.parametrize("headers, extra", [({"x-owner-id": OWNER_B}, {}), ({}, {}),
                                            ({"x-owner-id": OWNER_A}, {"alias": "ten-rieng"})],
                         ids=["other_owner", "no_owner", "with_alias"])
def test_other_cases_create_a_new_link(tables, headers, extra):
    first = body_of(post({"url": URL}, headers={"x-owner-id": OWNER_A}))
    resp = post({"url": URL, **extra}, headers=headers)
    assert resp["statusCode"] == 201 and body_of(resp)["code"] != first["code"]


@pytest.mark.parametrize("fields", [{"expires_at": "2020-01-01T00:00:00Z"}, {"status": "deleted"},
                                    {"status": "blocked"}, {"max_clicks": 1, "click_count": 1}],
                         ids=["expired", "deleted", "blocked", "max_clicks_reached"])
def test_an_unusable_old_link_is_not_returned(tables, fields):
    add_link("old1234", long_url=URL, owner_id=OWNER_A, **fields)
    resp = post({"url": URL}, headers={"x-owner-id": OWNER_A})
    assert resp["statusCode"] == 201 and body_of(resp)["code"] != "old1234"


# ------------------------------------------------------------------ alias
def test_custom_alias(tables):
    resp = post({"url": URL, "alias": "khuyen-mai"})
    assert (resp["statusCode"], body_of(resp)["code"]) == (201, "khuyen-mai")
    assert stored(tables, "khuyen-mai")["long_url"] == URL


def test_taken_alias_is_rejected_and_not_overwritten(tables):
    add_link("khuyen-mai", long_url="https://old.example/")
    resp = post({"url": URL, "alias": "khuyen-mai"})
    assert (resp["statusCode"], error_of(resp)["code"]) == (409, "alias_taken")
    assert stored(tables, "khuyen-mai")["long_url"] == "https://old.example/"


def test_a_deleted_alias_cannot_be_reused(tables):
    add_link("cu-roi", status="deleted")
    assert post({"url": URL, "alias": "cu-roi"})["statusCode"] == 409


@pytest.mark.parametrize("alias", sorted(validation.RESERVED_ALIASES) + ["API", "Dashboard"])
def test_reserved_aliases_are_rejected_in_any_case(tables, alias):
    resp = post({"url": URL, "alias": alias})
    # "js" chỉ 2 ký tự nên bị mẫu alias (3 đến 30 ký tự) chặn trước: 400 thay vì 409, nhưng vẫn không dùng được
    expected = (400, "invalid_alias") if len(alias) < 3 else (409, "alias_taken")
    assert (resp["statusCode"], error_of(resp)["code"]) == expected
    assert tables["urls"].scan()["Count"] == 0


@pytest.mark.parametrize("alias", ["ab", "a" * 31, "co dau", "dấu", "a_b", "a/b", 123, ["x"]])
def test_invalid_alias(tables, alias):
    assert error_of(post({"url": URL, "alias": alias}))["code"] == "invalid_alias"


# ------------------------------------------------------------------ đầu vào sai
@pytest.mark.parametrize("url, reason", [
    ("not-a-url", "scheme_not_allowed"), ("javascript:alert(1)", "scheme_not_allowed"),
    ("ftp://example.com/x", "scheme_not_allowed"), ("http://localhost/x", "host_not_allowed"),
    ("http://127.0.0.1/x", "host_not_allowed"), ("http://169.254.169.254/latest/meta-data", "host_not_allowed"),
    ("http://[::1]/x", "host_not_allowed"), ("https://linkpulse.vn/abc", "own_domain"),
    ("https://user:pw@example.com", "credentials_not_allowed"), ("", "url_empty"), (None, "url_empty"),
    ("https://example.com/" + "a" * 2100, "url_too_long"), ("https://exa mple.com", "url_has_whitespace")])
def test_invalid_url_is_rejected_with_a_reason(tables, url, reason):
    resp = post({"url": url})
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (400, "invalid_url", reason)
    assert tables["urls"].scan()["Count"] == 0


@pytest.mark.parametrize("field, value, code", [
    ("expires_in", 0, "invalid_expires_in"), ("expires_in", 59, "invalid_expires_in"),
    ("expires_in", 365 * 86400 + 1, "invalid_expires_in"), ("expires_in", "3600", "invalid_expires_in"),
    ("expires_in", True, "invalid_expires_in"), ("expires_in", 1.5, "invalid_expires_in"),
    ("max_clicks", 0, "invalid_max_clicks"), ("max_clicks", -1, "invalid_max_clicks"),
    ("max_clicks", "5", "invalid_max_clicks"), ("max_clicks", True, "invalid_max_clicks")])
def test_invalid_options(tables, field, value, code):
    resp = post({"url": URL, field: value})
    assert (resp["statusCode"], error_of(resp)["code"]) == (400, code)


@pytest.mark.parametrize("raw, reason", [(None, "body_missing"), ("", "body_missing"), ("{khong phai json", "body_not_json"),
                                         ("[1, 2]", "body_not_object")])
def test_bad_request_body(tables, raw, reason):
    resp = shorten.lambda_handler(make_event(ROUTE, raw_body=raw), None)
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (400, "invalid_request", reason)


def test_invalid_owner_id_header(tables):
    resp = post({"url": URL}, headers={"x-owner-id": "khong-phai-uuid"})
    assert (resp["statusCode"], error_of(resp)["reason"]) == (400, "invalid_owner_id")


def test_error_response_shape(tables):
    resp = post({"url": "nope"})
    assert resp["headers"]["Cache-Control"] == "no-store"
    assert set(error_of(resp)) == {"code", "message", "reason"} and error_of(resp)["message"]


# ------------------------------------------------------------------ DNS, blocklist, heuristic
def test_dns_check_rejects_a_public_name_that_points_inside(tables, monkeypatch):
    monkeypatch.setenv("DNS_CHECK", "true")
    monkeypatch.setattr(validation, "resolve_host", lambda host, port=443: ["10.0.0.5"])
    resp = post({"url": "https://sneaky.example/x"})
    assert (resp["statusCode"], error_of(resp)["reason"]) == (400, "host_not_allowed")


def test_dns_check_unresolvable_and_public(tables, monkeypatch):
    monkeypatch.setenv("DNS_CHECK", "true")

    def unresolvable(host, port=443):
        raise OSError("no such host")
    monkeypatch.setattr(validation, "resolve_host", unresolvable)
    assert error_of(post({"url": "https://nope.example/x"}))["reason"] == "host_unresolvable"
    monkeypatch.setattr(validation, "resolve_host", lambda host, port=443: ["93.184.216.34"])
    assert post({"url": "https://ok.example/x"})["statusCode"] == 201


@pytest.mark.parametrize("url", ["https://bad.example/x", "https://a.b.bad.example/x"])
def test_blocklisted_domain_and_its_subdomains(tables, url):
    tables["blocklist"].put_item(Item={"domain": "bad.example"})
    resp = post({"url": url})
    assert (resp["statusCode"], error_of(resp)["code"]) == (400, "blocked_domain")
    assert post({"url": "https://notbad.example/x"})["statusCode"] == 201


@pytest.mark.parametrize("url, reason", [("http://8.8.8.8/x", "ip_literal_host"), ("https://shop.tk/x", "risky_tld"),
                                         ("https://xn--abc.example/x", "punycode_host"),
                                         ("https://bit.ly/abc", "chained_shortener")])
def test_suspicious_url_is_created_but_flagged(tables, url, reason):
    body = body_of(post({"url": url}))
    item = stored(tables, body["code"])
    assert (item["status"], item["flag_reason"]) == ("suspicious", reason)
    assert repo.get_flagged() == 1


def test_normal_url_is_not_flagged(tables):
    assert stored(tables, body_of(post({"url": URL}))["code"])["status"] == "active"
    assert repo.get_flagged() == 0


# ------------------------------------------------------------------ rate limit, trùng mã
def test_rate_limit_per_ip(tables, monkeypatch):
    monkeypatch.setenv("SHORTEN_RATE_LIMIT", "2")
    assert [post({"url": URL})["statusCode"] for _ in range(2)] == [201, 201]
    limited = post({"url": URL})
    assert limited["statusCode"] == 429 and int(limited["headers"]["Retry-After"]) >= 1
    assert error_of(limited)["retry_after"] == int(limited["headers"]["Retry-After"])
    assert post({"url": URL}, ip="198.51.100.9")["statusCode"] == 201          # IP khác không bị ảnh hưởng


def test_rate_limit_zero_means_off(tables, monkeypatch):
    monkeypatch.setenv("SHORTEN_RATE_LIMIT", "0")
    assert all(post({"url": URL})["statusCode"] == 201 for _ in range(15))


def test_code_collision_retries_then_gives_up(tables, monkeypatch):
    add_link("aaaaaaa")
    codes = iter(["aaaaaaa", "aaaaaaa", "bbbbbbb"])
    monkeypatch.setattr(shorten, "generate_code", lambda length: next(codes))
    assert body_of(post({"url": URL}))["code"] == "bbbbbbb"
    monkeypatch.setattr(shorten, "generate_code", lambda length: "aaaaaaa")
    resp = post({"url": URL})
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (500, "internal_error",
                                                                                      "code_generation_failed")


# ------------------------------------------------------------------ Turnstile, kiểm tra origin
@pytest.fixture
def captcha(put_ssm_secret, monkeypatch):
    put_ssm_secret("/linkpulse/turnstile", "turnstile-secret")
    monkeypatch.setenv("TURNSTILE_SECRET_PARAM", "/linkpulse/turnstile")
    sent = []
    monkeypatch.setattr(turnstile, "_post", lambda data, timeout=3: sent.append(data) or {"success": True})
    return sent


def test_captcha_passes_with_a_valid_token(tables, captcha):
    assert post({"url": URL, "turnstile_token": "tok"})["statusCode"] == 201
    assert captcha == [{"secret": "turnstile-secret", "response": "tok", "remoteip": "203.0.113.7"}]


@pytest.mark.parametrize("token, reason", [(None, "token_missing"), ("", "token_missing")])
def test_captcha_requires_a_token_when_enabled(tables, captcha, token, reason):
    resp = post({"url": URL, "turnstile_token": token})
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (400, "captcha_failed", reason)


def test_captcha_rejected_or_unavailable_fails_closed(tables, captcha, monkeypatch):
    monkeypatch.setattr(turnstile, "_post", lambda data, timeout=3: {"success": False})
    assert error_of(post({"url": URL, "turnstile_token": "tok"}))["reason"] == "token_rejected"

    def down(data, timeout=3):
        raise OSError("network down")
    monkeypatch.setattr(turnstile, "_post", down)
    assert error_of(post({"url": URL, "turnstile_token": "tok"}))["reason"] == "verify_unavailable"


def test_captcha_token_must_be_a_string(tables):
    assert error_of(post({"url": URL, "turnstile_token": 123}))["reason"] == "turnstile_token_not_string"


def test_origin_secret_is_required_when_enabled(tables, put_ssm_secret, monkeypatch):
    put_ssm_secret("/linkpulse/origin-verify", "origin-secret-0123456789")
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET_PARAM", "/linkpulse/origin-verify")
    assert post({"url": URL})["statusCode"] == 403
    assert post({"url": URL}, headers={"x-origin-verify": "origin-secret-0123456789"})["statusCode"] == 201
