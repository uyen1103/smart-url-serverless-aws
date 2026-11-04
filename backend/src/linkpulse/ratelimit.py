"""Rate limit theo cửa sổ cố định bằng ghi có điều kiện nguyên tử vào bảng `rate_limits`.
Lớp thứ hai sau AWS WAF (rate-based rule) và throttling của API Gateway."""
import hashlib
import hmac
import time

from botocore.exceptions import ClientError

from . import db
from .config import settings
from .errors import err


def ip_hash(ip, now_ts=None):
    """HMAC-SHA256(salt, ip) cắt 16 ký tự hex: không lưu IP thật. Đổi theo ngày nếu IP_HASH_DAILY."""
    s = settings()
    salt = s.ip_hash_salt
    if s.ip_hash_daily:
        salt += time.strftime("%Y%m%d", time.gmtime(now_ts or time.time()))
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


def hit(key, limit, window, now_ts=None):
    """Ghi nhận 1 lượt. Vượt `limit` trong cửa sổ `window` giây thì ném 429 kèm retry_after.

    Bảng rate_limits bị DynamoDB throttle thì ghi cảnh báo và cho request đi tiếp (fail-open): rate limit là
    lớp phụ, các lớp WAF và throttling của API Gateway vẫn còn, không để nó làm hỏng cả request (500).
    Lỗi khác (ví dụ AccessDenied) vẫn ném lên để lộ ra."""
    if limit <= 0:
        return
    now_ts = int(now_ts or time.time())
    bucket = now_ts // window
    try:
        db.rate_limits(best_effort=True).update_item(
            Key={"pk": f"{key}#{bucket}"},
            UpdateExpression="ADD cnt :one SET expires_at = :ttl",
            ConditionExpression="attribute_not_exists(cnt) OR cnt < :limit",
            ExpressionAttributeValues={":one": 1, ":limit": limit, ":ttl": (bucket + 2) * window})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise err(429, "rate_limited", retry_after=max(1, (bucket + 1) * window - now_ts))
        if db.throttled(e, "ratelimit"):
            return
        raise
