"""Đánh giá độ tin cậy của URL đích khi tạo link:
 - blocklist nội bộ (bảng `blocklist`)  -> chặn (400 blocked_domain)
 - Google Safe Browsing (nếu có key)    -> chặn
 - heuristic                            -> cho tạo nhưng gắn trạng thái `suspicious`
"""
import json
import urllib.request

from botocore.exceptions import ClientError

from . import db
from .config import settings
from .secrets_store import get_secret
from .validation import host_matches, hostname_of, parse_ip_literal

SHORTENER_DOMAINS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "ow.ly", "rebrand.ly"}
RISKY_TLDS = {"tk", "ml", "ga", "cf", "gq"}


def _parents(host):
    labels = host.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)] or [host]


def is_blocklisted(url):
    """Tra bảng blocklist theo host và các domain cha (sub.bad.example -> bad.example)."""
    host = hostname_of(url)
    keys = [{"domain": d} for d in _parents(host)]
    resp = db.resource().batch_get_item(RequestItems={settings().blocklist_table: {"Keys": keys}})
    return bool(resp["Responses"].get(settings().blocklist_table))


def _safe_browsing_post(url, payload, timeout=3):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def safe_browsing_flagged(url):
    param = settings().safe_browsing_key_param
    if not param:
        return False
    try:
        key = get_secret(param)
        body = {"client": {"clientId": "linkpulse", "clientVersion": "1.0"},
                "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                               "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                               "threatEntries": [{"url": url}]}}
        res = _safe_browsing_post(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}", body)
        return bool(res.get("matches"))
    except Exception:  # noqa: BLE001  fail open: không để dịch vụ ngoài làm hỏng việc tạo link
        return False


def is_blocked(url):
    return is_blocklisted(url) or safe_browsing_flagged(url)


def suspicious_reasons(url):
    host = hostname_of(url)
    reasons = []
    if parse_ip_literal(host) is not None:
        reasons.append("ip_literal_host")
    if any(label.startswith("xn--") for label in host.split(".")):
        reasons.append("punycode_host")          # nguy cơ giả mạo tên miền (homograph)
    if host.count(".") >= 4:
        reasons.append("many_subdomains")
    if host.rsplit(".", 1)[-1] in RISKY_TLDS:
        reasons.append("risky_tld")
    if host_matches(host, SHORTENER_DOMAINS):
        reasons.append("chained_shortener")      # che giấu đích đến thật
    return reasons
