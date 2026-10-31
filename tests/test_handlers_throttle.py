"""DynamoDB bị throttle ở thao tác phụ (rate limit, đếm click, ghi click event) thì request vẫn đi tiếp.

Nguyên tắc: chỉ thao tác KHÔNG bắt buộc mới fail-open; đọc link, ghi link, hoặc lỗi khác (AccessDenied...) vẫn ra 500.
"""
import io
import json
import logging
from types import SimpleNamespace

import botocore.endpoint
import pytest
import urllib3
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError

from handlers import redirect, shorten
from linkpulse import db, ratelimit, repo
from linkpulse.errors import ApiError

CODE = "abc1234"
THROTTLE = "ProvisionedThroughputExceededException"


def client_error(code=THROTTLE, op="UpdateItem"):
    return ClientError({"Error": {"Code": code, "Message": "test"}}, op)


class AlwaysFails:
    """Bảng giả: mọi thao tác (update_item, put_item...) đều ném `error`."""

    def __init__(self, error):
        self.error = error

    def __getattr__(self, _name):
        def fail(*_args, **_kwargs):
            raise self.error
        return fail


def break_best_effort(monkeypatch, accessor, error=None):
    """Chỉ thao tác best_effort của bảng `accessor` ("rate_limits"/"urls"/"clicks") bị lỗi; phần còn lại chạy thật trên moto."""
    real, fake = getattr(db, accessor), AlwaysFails(error or client_error())
    monkeypatch.setattr(db, accessor, lambda best_effort=False: fake if best_effort else real())


def event(route, *, path_params=None, body=None, headers=None):
    method, path = route.split(" ", 1)
    return {"version": "2.0", "routeKey": route, "rawPath": path, "headers": headers or {},
            "pathParameters": path_params,
            "requestContext": {"http": {"method": method, "path": path, "sourceIp": "203.0.113.7"}},
            "body": None if body is None else json.dumps(body), "isBase64Encoded": False}


def add_link(tables, **extra):
    assert repo.create_link({"short_code": CODE, "long_url": "https://example.com/a", "click_count": 0,
                             "created_at": "2026-10-01T00:00:00Z", "status": "active", **extra})


def visit():
    return redirect.lambda_handler(event(f"GET /{{code}}", path_params={"code": CODE}), None)


# ------------------------------------------------------------------ ratelimit.hit
@pytest.mark.parametrize("code", sorted(db.THROTTLE_CODES))
def test_hit_lets_the_request_through_when_throttled(monkeypatch, caplog, code):
    break_best_effort(monkeypatch, "rate_limits", client_error(code))
    with caplog.at_level(logging.WARNING):
        assert ratelimit.hit("redirect#x", 5, 60) is None            # không ném lỗi
    assert "DYNAMODB_THROTTLED op=ratelimit" in caplog.text


def test_hit_still_returns_429_over_the_limit(tables):
    ratelimit.hit("k", 2, 60, now_ts=1000)
    ratelimit.hit("k", 2, 60, now_ts=1000)
    with pytest.raises(ApiError) as exc:
        ratelimit.hit("k", 2, 60, now_ts=1000)
    assert (exc.value.status, exc.value.code, exc.value.retry_after) == (429, "rate_limited", 20)


def test_hit_does_not_hide_other_dynamodb_errors(monkeypatch):
    break_best_effort(monkeypatch, "rate_limits", client_error("AccessDeniedException"))
    with pytest.raises(ClientError):
        ratelimit.hit("redirect#x", 5, 60)


def test_best_effort_client_gives_up_well_before_the_lambda_timeout(monkeypatch):
    """Mặc định botocore thử lại DynamoDB 10 lần, chờ cộng dồn ~25 giây (Lambda chỉ có 5 giây): throttle sẽ thành timeout
    chứ không thành 'bỏ qua lỗi'. Giả lập phản hồi throttle thật ở tầng HTTP để đếm số lần gọi và thời gian chờ."""
    calls, slept = [], []

    def throttle_response(request, **_kwargs):
        calls.append(1)
        body = json.dumps({"__type": f"com.amazonaws.dynamodb.v20120810#{THROTTLE}", "message": "x"}).encode()
        raw = urllib3.response.HTTPResponse(body=io.BytesIO(body), status=400, preload_content=False)
        return AWSResponse(request.url, 400, {}, raw)

    db.best_effort_resource().meta.client.meta.events.register("before-send.dynamodb.UpdateItem", throttle_response)
    monkeypatch.setattr(botocore.endpoint, "time", SimpleNamespace(sleep=slept.append))   # không chờ thật
    ratelimit.hit("redirect#x", 5, 60)                                                     # fail-open, không ném lỗi
    assert len(calls) == db.BEST_EFFORT_RETRIES + 1
    assert sum(slept) < 1


# ------------------------------------------------------------------ redirect
def test_redirect_still_works_when_rate_limit_is_throttled(tables, monkeypatch, caplog):
    add_link(tables)
    break_best_effort(monkeypatch, "rate_limits")
    with caplog.at_level(logging.WARNING):
        resp = visit()
    assert (resp["statusCode"], resp["headers"]["Location"]) == (302, "https://example.com/a")
    assert "DYNAMODB_THROTTLED op=ratelimit" in caplog.text
    assert tables["urls"].get_item(Key={"short_code": CODE})["Item"]["click_count"] == 1
    assert tables["clicks"].scan()["Count"] == 1


def test_redirect_still_works_when_click_counter_is_throttled(tables, monkeypatch, caplog):
    add_link(tables)
    break_best_effort(monkeypatch, "urls")
    with caplog.at_level(logging.WARNING):
        resp = visit()
    assert resp["statusCode"] == 302
    assert "DYNAMODB_THROTTLED op=register_click" in caplog.text
    assert tables["urls"].get_item(Key={"short_code": CODE})["Item"]["click_count"] == 0     # mất 1 lượt đếm
    assert tables["clicks"].scan()["Count"] == 1                                              # click event vẫn ghi


def test_redirect_still_works_when_click_event_is_throttled(tables, monkeypatch, caplog):
    add_link(tables)
    break_best_effort(monkeypatch, "clicks")
    with caplog.at_level(logging.WARNING):
        resp = visit()
    assert resp["statusCode"] == 302
    assert "DYNAMODB_THROTTLED op=record_click" in caplog.text
    assert tables["urls"].get_item(Key={"short_code": CODE})["Item"]["click_count"] == 1
    assert tables["clicks"].scan()["Count"] == 0


def test_redirect_survives_an_unexpected_click_event_error(tables, monkeypatch, caplog):
    add_link(tables)
    break_best_effort(monkeypatch, "clicks", client_error("InternalServerError"))
    with caplog.at_level(logging.WARNING):
        assert visit()["statusCode"] == 302                        # caller trong redirect.py bắt mọi lỗi ghi click
    assert "record_click failed" in caplog.text


def test_redirect_returns_500_for_a_real_error_in_the_click_counter(tables, monkeypatch):
    add_link(tables)
    break_best_effort(monkeypatch, "urls", client_error("AccessDeniedException"))
    resp = visit()
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"])["error"]["code"] == "internal_error"


# ------------------------------------------------------------------ shorten
def create(headers=None):
    return shorten.lambda_handler(event("POST /api/shorten", body={"url": "https://example.com/x"},
                                        headers=headers), None)


def test_shorten_not_500_when_rate_limit_is_throttled(tables, monkeypatch, caplog):
    break_best_effort(monkeypatch, "rate_limits")
    with caplog.at_level(logging.WARNING):
        resp = create()
    assert resp["statusCode"] == 201
    assert "DYNAMODB_THROTTLED op=ratelimit" in caplog.text


def test_shorten_still_returns_429_over_the_limit(tables, monkeypatch):
    monkeypatch.setenv("SHORTEN_RATE_LIMIT", "1")
    assert create()["statusCode"] == 201
    resp = create()
    assert resp["statusCode"] == 429
    assert int(resp["headers"]["Retry-After"]) >= 1
    assert json.loads(resp["body"])["error"]["code"] == "rate_limited"
