"""GET /api/health"""
from handlers import health
from helpers import body_of, error_of, make_event

ROUTE = "GET /api/health"


def test_health_returns_ok_without_touching_the_database():          # không dùng fixture dynamodb: không có bảng nào
    resp = health.lambda_handler(make_event(ROUTE), None)
    assert resp["statusCode"] == 200 and body_of(resp) == {"status": "ok"}
    assert resp["headers"]["Cache-Control"] == "no-store"
    assert resp["headers"]["Content-Type"] == "application/json"


def test_health_also_requires_the_origin_secret_when_enabled(put_ssm_secret, monkeypatch):
    put_ssm_secret("/linkpulse/origin-verify", "origin-secret-0123456789")
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET_PARAM", "/linkpulse/origin-verify")
    denied = health.lambda_handler(make_event(ROUTE, headers={"x-origin-verify": "sai"}), None)
    assert (denied["statusCode"], error_of(denied)["code"]) == (403, "forbidden")
    allowed = health.lambda_handler(make_event(ROUTE, headers={"x-origin-verify": "origin-secret-0123456789"}), None)
    assert allowed["statusCode"] == 200
