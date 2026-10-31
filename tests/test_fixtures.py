"""Kiểm tra chính các fixture trong tests/conftest.py (để TV3, TV4 tin dùng được).

Phần schema viết tường minh (không đọc lại từ template) làm đối chứng độc lập: ai đổi khóa/GSI/TTL/Stream trong
backend/template.yaml thì test đỏ, nhắc cập nhật cả tài liệu và code truy cập (quyết định #5).
"""
import json
import os
import re

import pytest

from conftest import BACKEND_SRC, TEST_ENV, UNSET_ENV, load_template, table_name, table_specs

OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

KEYS = {
    "urls": [("short_code", "HASH")],
    "clicks": [("short_code", "HASH"), ("sk", "RANGE")],
    "stats": [("scope", "HASH"), ("sk", "RANGE")],
    "rate_limits": [("pk", "HASH")],
    "blocklist": [("domain", "HASH")],
}
GSI = {"urls": {"owner-index": [("owner_id", "HASH"), ("created_at", "RANGE")]}}
TTL_TABLES = {"clicks", "stats", "rate_limits"}      # TTL bật ở thuộc tính expires_at
STREAM_TABLES = {"clicks": "NEW_IMAGE"}


def _pairs(key_schema):
    return [(k["AttributeName"], k["KeyType"]) for k in key_schema]


# ------------------------------------------------------------------ đường dẫn và biến môi trường
def test_backend_src_is_importable():
    import handlers.shorten  # noqa: F401
    import linkpulse.repo  # noqa: F401


def test_env_is_fake_and_offline():
    from linkpulse.config import settings

    assert os.environ["AWS_ACCESS_KEY_ID"] == "testing"
    assert "AWS_PROFILE" not in os.environ
    s = settings()
    assert s.dns_check is False                      # không phân giải DNS thật
    assert s.error_page_mode == "json"
    assert (s.turnstile_secret_param, s.safe_browsing_key_param, s.origin_verify_secret_param) == ("", "", "")


def test_ip_hash_salt_meets_template_minimum():
    min_length = load_template()["Parameters"]["IpHashSalt"]["MinLength"]
    assert min_length == 16 and len(os.environ["IP_HASH_SALT"]) >= min_length


def test_every_config_env_var_is_isolated():
    """Thêm biến môi trường mới vào config.py mà chưa khai báo trong conftest thì test này nhắc."""
    source = (BACKEND_SRC / "linkpulse" / "config.py").read_text(encoding="utf-8")
    used = set(re.findall(r'_[sib]\(\s*"([A-Z][A-Z0-9_]*)"', source))
    managed = set(TEST_ENV) | set(UNSET_ENV) | {var for var, _ in table_specs().values()}
    assert used, "regex không tìm thấy biến nào trong config.py: sửa lại regex của test"
    assert used <= managed, f"Khai báo thêm vào TEST_ENV hoặc UNSET_ENV trong tests/conftest.py: {sorted(used - managed)}"


# ------------------------------------------------------------------ bảng DynamoDB
def test_creates_exactly_the_five_tables(dynamodb, tables):
    expected = {"urls", "clicks", "stats", "rate_limits", "blocklist"}
    assert set(tables) == expected
    assert set(dynamodb.meta.client.list_tables()["TableNames"]) == {table_name(k) for k in expected}


def test_table_names_come_from_environment(tables):
    from linkpulse import db
    from linkpulse.config import settings

    s = settings()
    assert tables["urls"].name == s.urls_table != "urls"            # khác tên mặc định của config.py
    assert db.urls().name == s.urls_table
    assert db.clicks().name == s.clicks_table
    assert db.stats().name == s.stats_table
    assert db.rate_limits().name == s.rate_table
    assert db.blocklist().name == s.blocklist_table


@pytest.mark.parametrize("key", sorted(KEYS))
def test_key_schema_and_indexes(dynamodb, key):
    desc = dynamodb.meta.client.describe_table(TableName=table_name(key))["Table"]
    assert _pairs(desc["KeySchema"]) == KEYS[key]
    gsis = {g["IndexName"]: _pairs(g["KeySchema"]) for g in desc.get("GlobalSecondaryIndexes", [])}
    assert gsis == GSI.get(key, {})
    if key == "urls":
        assert desc["GlobalSecondaryIndexes"][0]["Projection"]["ProjectionType"] == "ALL"


@pytest.mark.parametrize("key", sorted(KEYS))
def test_ttl_matches_template(dynamodb, key):
    spec = dynamodb.meta.client.describe_time_to_live(TableName=table_name(key))["TimeToLiveDescription"]
    if key in TTL_TABLES:
        assert (spec["TimeToLiveStatus"], spec["AttributeName"]) == ("ENABLED", "expires_at")
    else:
        assert spec["TimeToLiveStatus"] == "DISABLED"


@pytest.mark.parametrize("key", sorted(KEYS))
def test_stream_matches_template(dynamodb, key):
    desc = dynamodb.meta.client.describe_table(TableName=table_name(key))["Table"]
    if key in STREAM_TABLES:
        assert desc["StreamSpecification"] == {"StreamEnabled": True, "StreamViewType": STREAM_TABLES[key]}
        assert desc["LatestStreamArn"]
    else:
        assert not desc.get("StreamSpecification", {}).get("StreamEnabled")


def test_owner_index_is_queryable(tables):
    from boto3.dynamodb.conditions import Key

    for code, created in (("aaa1111", "2026-10-01T00:00:00Z"), ("bbb2222", "2026-10-02T00:00:00Z")):
        tables["urls"].put_item(Item={"short_code": code, "owner_id": OWNER, "created_at": created,
                                      "long_url": "https://example.com"})
    tables["urls"].put_item(Item={"short_code": "ccc3333", "owner_id": "other", "created_at": "2026-10-03T00:00:00Z",
                                  "long_url": "https://example.com"})
    resp = tables["urls"].query(IndexName="owner-index", KeyConditionExpression=Key("owner_id").eq(OWNER),
                                ScanIndexForward=False)
    assert [i["short_code"] for i in resp["Items"]] == ["bbb2222", "aaa1111"]


# Hai test dưới chạy liền nhau theo thứ tự khai báo: test đầu ghi dữ liệu, test sau phải thấy bảng rỗng.
def test_isolation_part1_write(tables):
    tables["urls"].put_item(Item={"short_code": "leak123", "long_url": "https://example.com"})
    tables["blocklist"].put_item(Item={"domain": "bad.example"})
    assert tables["urls"].scan()["Count"] == 1


def test_isolation_part2_tables_start_empty(tables):
    for key, table in tables.items():
        assert table.scan()["Count"] == 0, f"bảng {key} còn dữ liệu của test trước"


# ------------------------------------------------------------------ SSM
def test_put_ssm_secret_drives_origin_verification(put_ssm_secret, monkeypatch):
    from linkpulse import origin
    from linkpulse.errors import ApiError

    origin.verify({})                                  # chưa cấu hình tham số: không kiểm tra
    put_ssm_secret("/linkpulse/origin-verify", "origin-secret-0123456789")
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET_PARAM", "/linkpulse/origin-verify")
    origin.verify({"headers": {"x-origin-verify": "origin-secret-0123456789"}})
    with pytest.raises(ApiError) as exc:
        origin.verify({"headers": {"x-origin-verify": "sai"}})
    assert (exc.value.status, exc.value.code) == (403, "forbidden")


# ------------------------------------------------------------------ chạy thử handler thật
def _event(method, path, *, body=None, headers=None, path_params=None):
    return {"version": "2.0", "rawPath": path, "headers": headers or {}, "pathParameters": path_params,
            "requestContext": {"http": {"method": method, "path": path, "sourceIp": "203.0.113.7"}},
            "body": None if body is None else json.dumps(body), "isBase64Encoded": False}


def test_fixtures_are_enough_to_run_shorten_then_redirect(tables):
    """Smoke test: handler thật chạy trọn vẹn trên 5 bảng moto (không DNS, không captcha, không mạng)."""
    from handlers import redirect, shorten

    created = shorten.lambda_handler(
        _event("POST", "/api/shorten", body={"url": "https://example.com/bai-viet"},
               headers={"x-owner-id": OWNER}), None)
    assert created["statusCode"] == 201
    code = json.loads(created["body"])["code"]
    assert tables["urls"].get_item(Key={"short_code": code})["Item"]["owner_id"] == OWNER

    hit = redirect.lambda_handler(
        _event("GET", f"/{code}", path_params={"code": code},
               headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120", "cloudfront-viewer-country": "VN"}),
        None)
    assert hit["statusCode"] == 302
    assert hit["headers"]["Location"] == "https://example.com/bai-viet"
    assert tables["urls"].get_item(Key={"short_code": code})["Item"]["click_count"] == 1
    clicks = tables["clicks"].scan()["Items"]
    assert len(clicks) == 1 and clicks[0]["short_code"] == code and clicks[0]["country"] == "VN"
    assert tables["rate_limits"].scan()["Count"] >= 1          # rate limit đã ghi vào bảng rate_limits
