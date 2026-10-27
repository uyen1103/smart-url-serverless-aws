"""Kiểm tra đầu vào. Port từ backend/prototype.py, thêm phân giải DNS."""
import ipaddress
import re
import socket
from urllib.parse import urlparse

from .config import settings
from .errors import err

ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9-]{3,30}$")
CODE_PATTERN = ALIAS_PATTERN  # mã tự sinh (7 ký tự Base62) cũng khớp mẫu này
MAX_URL_LENGTH = 2048
MIN_EXPIRES_IN = 60
MAX_EXPIRES_IN = 365 * 24 * 3600
BLOCKED_HOSTNAMES = {"localhost"}
RESERVED_ALIASES = {
    "api", "assets", "vendor", "css", "js", "mock", "index", "dashboard", "error", "warning",
    "stats", "links", "shorten", "admin", "favicon", "health", "static", "login", "robots",
}


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_ip_literal(host):
    """IP kể cả dạng rút gọn (127.1) hoặc số nguyên (2130706433); không phải IP thì None."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def is_internal_ip(ip):
    return (ip.is_private or ip.is_loopback or ip.is_link_local  # gồm 169.254.169.254
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def host_matches(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def hostname_of(url):
    return (urlparse(url).hostname or "").rstrip(".").lower()


def validate_url(url):
    """(True, "") nếu hợp lệ, ngược lại (False, "lý do")."""
    if not isinstance(url, str) or not url.strip():
        return False, "url_empty"
    if url != url.strip() or any(c.isspace() for c in url):
        return False, "url_has_whitespace"
    if len(url) > MAX_URL_LENGTH:
        return False, "url_too_long"
    try:
        parsed = urlparse(url)
        parsed.port
    except ValueError:
        return False, "url_malformed"
    if parsed.scheme not in ("http", "https"):
        return False, "scheme_not_allowed"
    if parsed.username or parsed.password:
        return False, "credentials_not_allowed"
    host = hostname_of(url)
    if not host:
        return False, "host_missing"
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return False, "host_not_allowed"
    if host_matches(host, settings().own_domains):
        return False, "own_domain"
    ip = parse_ip_literal(host)
    if ip is not None and is_internal_ip(ip):
        return False, "host_not_allowed"
    return True, ""


def resolve_host(host, port=443):
    """Tách riêng để test thay thế được."""
    return [ai[4][0] for ai in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_dns(url):
    """Tên miền công khai nhưng trỏ về IP nội bộ -> từ chối. Chưa chống DNS rebinding hoàn toàn
    (DNS có thể đổi sau khi tạo link); đây chỉ là lớp chặn tại thời điểm tạo."""
    if not settings().dns_check:
        return True, ""
    host = hostname_of(url)
    if parse_ip_literal(host) is not None:
        return True, ""
    try:
        addrs = resolve_host(host)
    except OSError:
        return False, "host_unresolvable"
    for a in addrs:
        try:
            if is_internal_ip(ipaddress.ip_address(a.split("%")[0])):
                return False, "host_not_allowed"
        except ValueError:
            continue
    return True, ""


def validate_shorten_input(body):
    """Kiểm tra các trường của POST /shorten; ném ApiError nếu sai. Trả về dict đã chuẩn hóa."""
    url = body.get("url")
    ok, reason = validate_url(url)
    if not ok:
        raise err(400, "invalid_url", reason)

    alias = body.get("alias")
    if alias is not None and not (isinstance(alias, str) and ALIAS_PATTERN.match(alias)):
        raise err(400, "invalid_alias")
    expires_in = body.get("expires_in")
    if expires_in is not None and not (is_int(expires_in) and MIN_EXPIRES_IN <= expires_in <= MAX_EXPIRES_IN):
        raise err(400, "invalid_expires_in")
    max_clicks = body.get("max_clicks")
    if max_clicks is not None and not (is_int(max_clicks) and max_clicks >= 1):
        raise err(400, "invalid_max_clicks")
    token = body.get("turnstile_token")
    if token is not None and not isinstance(token, str):
        raise err(400, "invalid_request", "turnstile_token_not_string")
    return {"url": url, "alias": alias, "expires_in": expires_in,
            "max_clicks": max_clicks, "turnstile_token": token}
