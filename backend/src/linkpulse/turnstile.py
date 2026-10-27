"""Xác minh Cloudflare Turnstile ở backend (widget ở frontend chỉ sinh token)."""
import json
import urllib.parse
import urllib.request

from .config import settings
from .errors import err
from .secrets_store import get_secret

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _post(data, timeout=3):
    req = urllib.request.Request(VERIFY_URL, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL cố định, https)
        return json.loads(r.read().decode())


def verify(token, ip):
    """Tắt khi chưa cấu hình TURNSTILE_SECRET_PARAM (chạy dev). Bật mà token thiếu/sai/lỗi mạng
    -> 400 captcha_failed (fail closed)."""
    param = settings().turnstile_secret_param
    if not param:
        return
    if not token:
        raise err(400, "captcha_failed", "token_missing")
    try:
        result = _post({"secret": get_secret(param), "response": token, "remoteip": ip})
    except Exception:  # noqa: BLE001
        raise err(400, "captcha_failed", "verify_unavailable")
    if not result.get("success"):
        raise err(400, "captcha_failed", "token_rejected")
