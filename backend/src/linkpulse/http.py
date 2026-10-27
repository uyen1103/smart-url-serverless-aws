"""Tiện ích cho Lambda proxy payload v2.0 của API Gateway HTTP API."""
import base64
import functools
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from . import origin
from .errors import ApiError, err

log = logging.getLogger()
log.setLevel(logging.INFO)

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise TypeError(f"not serializable: {type(o)}")


def response(status, body=None, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    out = {"statusCode": status, "headers": h}
    if body is not None:
        out["body"] = json.dumps(body, default=_json_default, ensure_ascii=False)
    return out


def redirect_response(location):
    # 302 + no-store: mỗi lượt truy cập đều qua server để đếm click (docs/backend_research.md mục 4)
    return {"statusCode": 302, "headers": {"Location": location, "Cache-Control": "no-store"}}


def error_response(e):
    body = {"code": e.code}
    if e.message:
        body["message"] = e.message
    if e.reason:
        body["reason"] = e.reason
    headers = {"Cache-Control": "no-store"}
    if e.retry_after is not None:
        body["retry_after"] = e.retry_after
        headers["Retry-After"] = str(e.retry_after)
    return response(e.status, {"error": body}, headers)


def api_handler(fn):
    """Bắt ApiError -> JSON lỗi đúng spec; lỗi khác -> 500 internal_error (không lộ chi tiết)."""

    @functools.wraps(fn)
    def wrapper(event, context):
        try:
            origin.verify(event)      # chỉ nhận request đi qua CloudFront (nếu đã cấu hình)
            return fn(event, context)
        except ApiError as e:
            return error_response(e)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error")
            return error_response(err(500, "internal_error"))

    return wrapper


def header(event, name):
    return (event.get("headers") or {}).get(name.lower())


def query(event):
    return event.get("queryStringParameters") or {}


def path_param(event, name):
    return (event.get("pathParameters") or {}).get(name)


def client_ip(event):
    """IP người dùng. Ưu tiên CloudFront-Viewer-Address, rồi X-Forwarded-For, cuối cùng là sourceIp của API Gateway.
    Header của CloudFront chỉ đáng tin khi origin chỉ nhận request qua CloudFront (xem origin.py): nếu không,
    client gọi thẳng API có thể tự đặt header này để giả IP và né rate limit."""
    viewer = header(event, "cloudfront-viewer-address")
    if viewer:
        return viewer.rsplit(":", 1)[0].strip("[]")
    xff = header(event, "x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return ((event.get("requestContext") or {}).get("http") or {}).get("sourceIp", "0.0.0.0")


def country(event):
    c = (header(event, "cloudfront-viewer-country") or "").upper()
    return c if re.fullmatch(r"[A-Z]{2}", c) else "XX"


def owner_id(event, required=False):
    value = header(event, "x-owner-id")
    if not value:
        if required:
            raise err(401, "unauthorized")
        return None
    if not UUID_RE.match(value):
        raise err(400, "invalid_request", "invalid_owner_id") if not required else err(401, "unauthorized")
    return value.lower()


def parse_json(event):
    raw = event.get("body")
    if raw is None or raw == "":
        raise err(400, "invalid_request", "body_missing")
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:  # noqa: BLE001
            raise err(400, "invalid_request", "body_not_decodable")
    try:
        data = json.loads(raw)
    except ValueError:
        raise err(400, "invalid_request", "body_not_json")
    if not isinstance(data, dict):
        raise err(400, "invalid_request", "body_not_object")
    return data


def new_id():
    return uuid.uuid4().hex[:8]
