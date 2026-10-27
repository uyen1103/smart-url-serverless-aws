"""Click event: phân tích User-Agent, referrer và ghi vào bảng `clicks` (nguồn của DynamoDB Stream)."""
import re
import time
from urllib.parse import urlparse

from . import db
from .config import settings
from .http import new_id
from .models import now, to_iso

BOT_RE = re.compile(r"bot|crawl|spider|slurp|curl|wget|python-requests|httpclient|headless|scrapy|"
                    r"facebookexternalhit|preview|monitor|uptime|go-http-client|okhttp", re.I)
TABLET_RE = re.compile(r"ipad|tablet|kindle|silk", re.I)
MOBILE_RE = re.compile(r"mobi|iphone|android|ipod", re.I)
# Thứ tự quan trọng: Edge/Opera/Samsung chứa "Chrome", Chrome chứa "Safari"
BROWSERS = [("Edge", r"edg(e|a|ios)?/"), ("Opera", r"opr/|opera"), ("Samsung", r"samsungbrowser"),
            ("Firefox", r"firefox|fxios"), ("Chrome", r"chrome|crios"), ("Safari", r"safari")]


def parse_user_agent(ua):
    """-> (device, browser, is_bot). device ∈ desktop|mobile|tablet|bot|other."""
    ua = ua or ""
    if not ua or BOT_RE.search(ua):
        return "bot", "Other", True
    low = ua.lower()
    browser = next((name for name, pat in BROWSERS if re.search(pat, low)), "Other")
    if TABLET_RE.search(ua):
        return "tablet", browser, False
    if MOBILE_RE.search(ua):
        return "mobile", browser, False
    return ("desktop" if re.search(r"windows|macintosh|linux|x11|cros", low) else "other"), browser, False


def referrer_domain(ref):
    if not ref:
        return "direct"
    host = (urlparse(ref).hostname or "").lower().removeprefix("www.")
    return host[:60] or "direct"


def record_click(code, *, ua, referer, country, ip_hash_value):
    """Ghi 1 click event. Lỗi ở đây không được làm hỏng redirect (caller bắt exception)."""
    s = settings()
    device, browser, is_bot = parse_user_agent(ua)
    ts = now()
    db.clicks().put_item(Item={
        "short_code": code,
        "sk": f"{to_iso(ts)}#{new_id()}",
        "timestamp": to_iso(ts),
        "country": country,
        "device": device,
        "browser": browser,
        "referrer": referrer_domain(referer),
        "ip_hash": ip_hash_value,
        "result": "bot" if is_bot else "valid",
        "expires_at": int(time.time()) + s.clicks_ttl_days * 86400,   # TTL của DynamoDB
    })
