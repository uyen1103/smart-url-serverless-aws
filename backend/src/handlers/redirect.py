"""GET /{code} : tra mã, kiểm tra trạng thái, đếm click, ghi click event, trả 302."""
import logging
from urllib.parse import quote

from linkpulse import events, http, ratelimit, repo
from linkpulse.config import settings
from linkpulse.errors import ApiError, err
from linkpulse.models import link_state
from linkpulse.validation import CODE_PATTERN

log = logging.getLogger()

# Trang giao diện của TV2 (dùng khi ERROR_PAGE_MODE=redirect và trình duyệt gửi Accept: text/html)
PAGES = {
    "not_found": "/error.html?type=404",
    "link_expired": "/error.html?type=expired",
    "max_clicks_reached": "/error.html?type=max_clicks",
    "link_blocked": "/warning.html?reason=blocked",
    "link_suspicious": "/warning.html?reason=suspicious",
}


def _fail(event, e, code):
    if (settings().error_page_mode == "redirect" and e.code in PAGES
            and "text/html" in (http.header(event, "accept") or "")):
        page = PAGES[e.code]
        if e.code == "link_suspicious":
            page += "&code=" + quote(code, safe="")
        return http.redirect_response(page)
    return http.error_response(e)


@http.api_handler
def lambda_handler(event, context):
    s = settings()
    code = http.path_param(event, "code") or ""
    try:
        if not CODE_PATTERN.match(code):          # /favicon.ico, /robots.txt... khỏi tốn một lượt đọc DB
            raise err(404, "not_found")

        ip = http.client_ip(event)
        iph = ratelimit.ip_hash(ip)
        ratelimit.hit(f"redirect#{iph}", s.redirect_rate_limit, s.redirect_rate_window)

        item = repo.get_link(code)
        if item is None:
            raise err(404, "not_found")
        state = link_state(item)
        if state == "deleted":
            raise err(404, "not_found")
        if state == "blocked":
            raise err(403, "link_blocked")            # confirm=1 không vượt được link bị chặn
        if state == "expired":
            raise err(410, "link_expired")
        if state == "max_clicks":
            raise err(410, "max_clicks_reached")
        if state == "suspicious" and http.query(event).get("confirm") != "1":
            raise err(403, "link_suspicious")

        if not repo.register_click(code, item.get("max_clicks")):
            raise err(410, "max_clicks_reached")
    except ApiError as e:
        if e.status == 429:
            return http.error_response(e)
        return _fail(event, e, code)

    try:
        events.record_click(code, ua=http.header(event, "user-agent"), referer=http.header(event, "referer"),
                            country=http.country(event), ip_hash_value=iph)
    except Exception:  # noqa: BLE001  ghi analytics lỗi thì vẫn chuyển hướng
        log.exception("record_click failed")
    return http.redirect_response(item["long_url"])
