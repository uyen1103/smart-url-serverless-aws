"""Hàm dùng chung cho test_handlers_*.py: dựng sự kiện API Gateway HTTP API (payload 2.0), đọc phản hồi, thêm link."""
import json

from linkpulse import repo

OWNER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SOURCE_IP = "203.0.113.7"


def make_event(route, *, path_params=None, body=None, raw_body=None, headers=None, query=None, ip=SOURCE_IP):
    """route dạng "POST /api/shorten". `body` là dict (sẽ đổi sang JSON), `raw_body` là chuỗi gửi nguyên văn."""
    method, path = route.split(" ", 1)
    return {"version": "2.0", "routeKey": route, "rawPath": path, "headers": headers or {},
            "queryStringParameters": query, "pathParameters": path_params,
            "requestContext": {"http": {"method": method, "path": path, "sourceIp": ip}},
            "body": json.dumps(body) if body is not None else raw_body, "isBase64Encoded": False}


def body_of(resp):
    return json.loads(resp["body"])


def error_of(resp):
    return body_of(resp)["error"]


def add_link(code="abc1234", **fields):
    """Ghi thẳng 1 link vào bảng urls (đã chạy qua repo.create_link nên trùng mã sẽ báo lỗi)."""
    item = {"short_code": code, "long_url": "https://example.com/a", "click_count": 0,
            "created_at": "2026-10-01T00:00:00Z", "status": "active", **fields}
    assert repo.create_link(item), f"mã {code} đã tồn tại"
    return item
