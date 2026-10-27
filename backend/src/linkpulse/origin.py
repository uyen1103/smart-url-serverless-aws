"""Chỉ nhận request đi qua CloudFront.

CloudFront gắn header bí mật `X-Origin-Verify` vào mọi request gửi tới API (infra/edge.yaml). Backend từ chối
request thiếu/sai header này, nên không ai gọi thẳng `*.execute-api.amazonaws.com` để né WAF được, và các header
do CloudFront đặt (CloudFront-Viewer-Address, CloudFront-Viewer-Country) mới đáng tin để lấy IP/quốc gia.

Tắt khi ORIGIN_VERIFY_SECRET_PARAM để trống (chạy dev/test). Bật mà không đọc được bí mật thì fail closed.
"""
import hmac

from .config import settings
from .errors import err
from .secrets_store import get_secret

HEADER = "x-origin-verify"


def verify(event):
    param = settings().origin_verify_secret_param
    if not param:
        return
    expected = get_secret(param)
    given = (event.get("headers") or {}).get(HEADER, "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise err(403, "forbidden", "origin_not_allowed")
