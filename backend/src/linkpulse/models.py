"""Mô hình link lưu trong DynamoDB (thời gian là chuỗi ISO 8601 UTC kết thúc bằng Z)."""
from datetime import datetime, timedelta, timezone

ISO = "%Y-%m-%dT%H:%M:%SZ"


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime(ISO)


def parse_iso(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def expires_at(created, expires_in):
    return to_iso(created + timedelta(seconds=expires_in)) if expires_in else None


def link_state(item, at=None):
    """Trạng thái hiển thị: deleted, blocked, expired, max_clicks, suspicious, active.
    Thứ tự theo spec: bị chặn, hết hạn, hết lượt click, đáng ngờ."""
    at = at or now()
    status = item.get("status", "active")
    if status in ("deleted", "blocked"):
        return status
    exp = item.get("expires_at")
    if exp and parse_iso(exp) <= at:
        return "expired"
    mc = item.get("max_clicks")
    if mc is not None and int(item.get("click_count", 0)) >= int(mc):
        return "max_clicks"
    if status == "suspicious":
        return "suspicious"
    return "active"


def _int_or_none(v):
    return None if v is None else int(v)


def public_link(item, base_url, at=None):
    """LinkItem trong spec."""
    return {
        "code": item["short_code"],
        "short_url": f"{base_url}/{item['short_code']}",
        "long_url": item["long_url"],
        "clicks": int(item.get("click_count", 0)),
        "created_at": item["created_at"],
        "expires_at": item.get("expires_at"),
        "max_clicks": _int_or_none(item.get("max_clicks")),
        "status": link_state(item, at),
    }
