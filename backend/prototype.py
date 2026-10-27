"""
Prototype backend rút gọn link LinkPulse (chạy local, dữ liệu giả trong bộ nhớ).

Thử logic của shorten() và redirect() (cùng delete_link()) trước khi đưa lên Lambda.
Tên trường, mã trạng thái và mã lỗi bám theo docs/api_spec.yaml, và khớp với mock
của frontend (frontend/prototype/mock/*.json).

Cách chạy (từ thư mục gốc repo):
    python backend/prototype.py        # chạy demo
    python -m pytest tests -v          # chạy test (hoặc: python -m unittest discover tests -v)
"""

import ipaddress
import re
import secrets
import socket
import string
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------
BASE_URL = "https://linkpulse.vn"                # domain của link rút gọn
OWN_DOMAINS = {"linkpulse.vn"}                   # không cho rút gọn link của chính hệ thống
ALPHABET = string.ascii_letters + string.digits  # Base62: a-z, A-Z, 0-9
CODE_LENGTH = 7                                  # 62^7 ~ 3,5 nghìn tỷ tổ hợp
MAX_RETRIES = 5                                  # số lần sinh lại khi trùng mã
MAX_URL_LENGTH = 2048
MIN_EXPIRES_IN = 60                              # giây
MAX_EXPIRES_IN = 365 * 24 * 3600                 # giây (365 ngày)
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9-]{3,30}$")  # theo ô Alias của TV2
# Alias trùng tên trang/đường dẫn của hệ thống thì không được dùng
RESERVED_ALIASES = {
    "api", "assets", "vendor", "css", "js", "mock", "index", "dashboard",
    "error", "warning", "stats", "links", "shorten", "admin", "favicon",
}
BLOCKED_HOSTNAMES = {"localhost"}                # chặn SSRF theo tên

# "Bảng urls" giả lập. Khi lên DynamoDB: khóa chính = short_code.
DB = {}
# Danh sách domain bị chặn (bảng blocklist của TV3/TV5). Rỗng khi chạy demo.
BLOCKED_DOMAINS = set()


def _now():
    return datetime.now(timezone.utc)


def _error(status, code, reason=None):
    """Lỗi dạng {"status": 400, "error": {"code": ..., "reason": ...}}.
    `code` là mã công khai (khớp spec/frontend), `reason` là chi tiết để debug."""
    error = {"code": code}
    if reason:
        error["reason"] = reason
    return {"status": status, "error": error}


# ---------------------------------------------------------------------------
# Kiểm tra URL
# ---------------------------------------------------------------------------
def _parse_ip_literal(host):
    """Nếu host là địa chỉ IP (kể cả dạng rút gọn như 127.1 hay số nguyên
    2130706433) thì trả về đối tượng IP, ngược lại trả về None."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        # inet_aton hiểu các dạng "lạ" mà kẻ tấn công hay dùng để né bộ lọc
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def _is_internal_ip(ip):
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local      # gồm 169.254.169.254 (metadata của AWS)
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _host_matches(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def validate_url(url):
    """Trả về (True, "") nếu hợp lệ, ngược lại (False, "lý do")."""
    if not isinstance(url, str) or not url.strip():
        return False, "url_empty"
    if url != url.strip() or any(c.isspace() for c in url):
        return False, "url_has_whitespace"
    if len(url) > MAX_URL_LENGTH:
        return False, "url_too_long"

    try:
        parsed = urlparse(url)
        parsed.port  # truy cập để phát hiện cổng sai (ví dụ :abc)
    except ValueError:
        return False, "url_malformed"

    if parsed.scheme not in ("http", "https"):
        return False, "scheme_not_allowed"     # chặn javascript:, file:, ftp:...
    if parsed.username or parsed.password:
        return False, "credentials_not_allowed"

    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return False, "host_missing"
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return False, "host_not_allowed"
    if _host_matches(host, OWN_DOMAINS):
        return False, "own_domain"             # tránh vòng lặp redirect về chính hệ thống

    ip = _parse_ip_literal(host)
    if ip is not None and _is_internal_ip(ip):
        return False, "host_not_allowed"       # chặn SSRF: 127.0.0.1, 10.x, 169.254.x...
    return True, ""


def _is_blocked_domain(url):
    host = (urlparse(url).hostname or "").rstrip(".").lower()
    return _host_matches(host, BLOCKED_DOMAINS)


# ---------------------------------------------------------------------------
# Sinh mã
# ---------------------------------------------------------------------------
def generate_code(length=CODE_LENGTH):
    """Sinh mã ngẫu nhiên Base62. Dùng `secrets` (an toàn mật mã), không dùng
    `random`, để mã khó bị đoán."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Trạng thái link
# ---------------------------------------------------------------------------
def link_state(item, now=None):
    """Trạng thái hiển thị của link: active, suspicious, blocked, expired,
    max_clicks hoặc deleted (khớp enum LinkStatus trong spec)."""
    now = now or _now()
    if item["status"] in ("deleted", "blocked", "suspicious"):
        return item["status"]
    if item["expires_at"] is not None and item["expires_at"] <= now:
        return "expired"
    if item["max_clicks"] is not None and item["click_count"] >= item["max_clicks"]:
        return "max_clicks"
    return "active"


def _find_existing(owner_id, long_url, now):
    """Tìm link còn hoạt động của cùng chủ sở hữu và cùng URL (để trả lại link cũ)."""
    for code, item in DB.items():
        if (item["owner_id"] == owner_id and item["long_url"] == long_url
                and link_state(item, now) == "active"):
            return code, item
    return None, None


def _result(status, code, item, created):
    return {
        "status": status,
        "code": code,
        "short_url": f"{BASE_URL}/{code}",
        "created": created,
        "long_url": item["long_url"],
        "expires_at": item["expires_at"],
        "max_clicks": item["max_clicks"],
    }


# ---------------------------------------------------------------------------
# Các hàm chính
# ---------------------------------------------------------------------------
def shorten(long_url, alias=None, expires_in=None, max_clicks=None, owner_id=None,
            code_generator=generate_code, now=None):
    """Tạo link rút gọn.

    expires_in: số GIÂY link còn hiệu lực (giống ô Thời hạn của frontend).
    owner_id: giá trị header X-Owner-Id (chủ sở hữu ẩn danh theo trình duyệt).

    Trả về dict có khóa "status":
      201 -> link mới          {"status": 201, "code", "short_url", "created": True, ...}
      200 -> link đã tồn tại   {"status": 200, ..., "created": False}
      400 -> invalid_url | blocked_domain | invalid_alias | invalid_expires_in | invalid_max_clicks
      409 -> alias_taken
      500 -> internal_error (reason: code_generation_failed)
    """
    now = now or _now()

    ok, reason = validate_url(long_url)
    if not ok:
        return _error(400, "invalid_url", reason)
    if _is_blocked_domain(long_url):
        return _error(400, "blocked_domain")

    if alias is not None and not (isinstance(alias, str) and ALIAS_PATTERN.match(alias)):
        return _error(400, "invalid_alias")
    if expires_in is not None and not (
            _is_int(expires_in) and MIN_EXPIRES_IN <= expires_in <= MAX_EXPIRES_IN):
        return _error(400, "invalid_expires_in")
    if max_clicks is not None and not (_is_int(max_clicks) and max_clicks >= 1):
        return _error(400, "invalid_max_clicks")

    # Không đặt alias: nếu cùng chủ sở hữu đã rút gọn URL này thì trả lại link cũ.
    if alias is None and owner_id is not None:
        code, item = _find_existing(owner_id, long_url, now)
        if item is not None:
            return _result(200, code, item, created=False)

    item = {
        "long_url": long_url,
        "owner_id": owner_id,
        "created_at": now,
        "expires_at": now + timedelta(seconds=expires_in) if expires_in else None,
        "max_clicks": max_clicks,
        "click_count": 0,
        "status": "active",
    }

    # Ở DynamoDB: PutItem + ConditionExpression attribute_not_exists(short_code).
    # Ở prototype: kiểm tra khóa trong dict.
    if alias is not None:
        if alias.lower() in RESERVED_ALIASES or alias in DB:
            return _error(409, "alias_taken")
        DB[alias] = item
        return _result(201, alias, item, created=True)

    for _ in range(MAX_RETRIES):
        code = code_generator()
        if code in DB:
            continue  # trùng mã -> sinh lại
        DB[code] = item
        return _result(201, code, item, created=True)
    return _error(500, "internal_error", "code_generation_failed")


def redirect(code, confirm=False, now=None):
    """Tra cứu mã và trả về thông tin chuyển hướng.

      302 -> {"status": 302, "location": <long_url>}  (đếm 1 click)
      403 -> link_blocked, hoặc link_suspicious (khi chưa gửi confirm=1)
      404 -> not_found (mã không tồn tại hoặc link đã bị xóa)
      410 -> link_expired, hoặc max_clicks_reached
    """
    item = DB.get(code)
    if item is None:
        return _error(404, "not_found")

    state = link_state(item, now)
    if state == "deleted":
        return _error(404, "not_found")
    if state == "blocked":
        return _error(403, "link_blocked")
    if state == "expired":
        return _error(410, "link_expired")
    if state == "max_clicks":
        return _error(410, "max_clicks_reached")
    if state == "suspicious" and not confirm:
        return _error(403, "link_suspicious")

    item["click_count"] += 1
    return {"status": 302, "location": item["long_url"]}


def delete_link(code, owner_id):
    """Xóa link (đánh dấu deleted). Chỉ chủ sở hữu mới xóa được.

      204 -> đã xóa
      401 -> thiếu owner_id (header X-Owner-Id)
      403 -> không phải chủ sở hữu
      404 -> không có link
    """
    if not owner_id:
        return _error(401, "unauthorized")
    item = DB.get(code)
    if item is None or item["status"] == "deleted":
        return _error(404, "not_found")
    if item["owner_id"] != owner_id:
        return _error(403, "forbidden")
    item["status"] = "deleted"
    return {"status": 204}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    owner = "11111111-1111-4111-8111-111111111111"

    print("1. Rút gọn link hợp lệ (201):")
    r = shorten("https://example.com/bai-viet-rat-dai?id=1", owner_id=owner)
    print("  ", r)

    print("2. Rút gọn lại đúng URL đó (200, created=False):")
    print("  ", shorten("https://example.com/bai-viet-rat-dai?id=1", owner_id=owner))

    print("3. Truy cập mã vừa tạo (302) và mã không tồn tại (404):")
    print("  ", redirect(r["code"]))
    print("  ", redirect("khongco1"))

    print("4. URL sai / nội bộ / chính hệ thống (400 invalid_url):")
    for bad in ["not-a-url", "javascript:alert(1)", "http://127.0.0.1/admin",
                "http://169.254.169.254/latest/meta-data/", "https://linkpulse.vn/abc"]:
        print("  ", bad, "->", shorten(bad))

    print("5. Alias:")
    print("  ", shorten("https://example.com/a", alias="khuyen-mai", owner_id=owner))
    print("  ", shorten("https://example.com/b", alias="khuyen-mai", owner_id=owner))
    print("  ", shorten("https://example.com/c", alias="api"))

    print("6. Domain bị chặn (400 blocked_domain):")
    BLOCKED_DOMAINS.add("bad.example")
    print("  ", shorten("https://sub.bad.example/x"))

    print("7. Giới hạn số click (max_clicks=2):")
    r3 = shorten("https://example.com/gioi-han", max_clicks=2)
    for i in range(3):
        print("  ", i + 1, redirect(r3["code"]))

    print("8. Link hết hạn (410):")
    r4 = shorten("https://example.com/het-han", expires_in=3600)
    print("  ", redirect(r4["code"], now=_now() + timedelta(hours=2)))

    print("9. Link đáng ngờ (403, rồi 302 khi confirm=1) và link bị chặn (403):")
    r5 = shorten("https://example.com/nghi-ngo")
    DB[r5["code"]]["status"] = "suspicious"
    print("  ", redirect(r5["code"]))
    print("  ", redirect(r5["code"], confirm=True))
    DB[r5["code"]]["status"] = "blocked"
    print("  ", redirect(r5["code"], confirm=True))

    print("10. Xóa link:")
    print("  ", delete_link(r["code"], owner_id="22222222-2222-4222-8222-222222222222"))
    print("  ", delete_link(r["code"], owner_id=owner))
    print("  ", redirect(r["code"]))
