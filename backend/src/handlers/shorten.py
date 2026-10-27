"""POST /api/shorten"""
from linkpulse import http, ratelimit, repo, reputation, turnstile, validation
from linkpulse.codes import generate_code
from linkpulse.config import settings
from linkpulse.errors import err
from linkpulse.models import expires_at, link_state, now, to_iso


def _result(status, item, base_url, created):
    return http.response(status, {
        "code": item["short_code"], "short_url": f"{base_url}/{item['short_code']}", "created": created,
        "long_url": item["long_url"], "expires_at": item.get("expires_at"),
        "max_clicks": None if item.get("max_clicks") is None else int(item["max_clicks"])})


@http.api_handler
def lambda_handler(event, context):
    s = settings()
    ip = http.client_ip(event)
    ratelimit.hit(f"shorten#{ratelimit.ip_hash(ip)}", s.shorten_rate_limit, s.shorten_rate_window)

    owner = http.owner_id(event)
    data = validation.validate_shorten_input(http.parse_json(event))
    url, alias = data["url"], data["alias"]

    turnstile.verify(data["turnstile_token"], ip)

    ok, reason = validation.check_dns(url)
    if not ok:
        raise err(400, "invalid_url", reason)
    if reputation.is_blocked(url):
        raise err(400, "blocked_domain")

    # Cùng chủ sở hữu, không đặt alias: trả lại link còn hiệu lực cho đúng URL này (HTTP 200)
    if alias is None and owner:
        for item in repo.find_existing(owner, url):
            if link_state(item) == "active":
                return _result(200, item, s.base_url, created=False)

    created = now()
    reasons = reputation.suspicious_reasons(url)
    item = {"long_url": url, "created_at": to_iso(created), "click_count": 0,
            "status": "suspicious" if reasons else "active"}
    if owner:
        item["owner_id"] = owner
    if data["expires_in"]:
        item["expires_at"] = expires_at(created, data["expires_in"])
    if data["max_clicks"] is not None:
        item["max_clicks"] = data["max_clicks"]
    if reasons:
        item["flag_reason"] = ",".join(reasons)

    if alias is not None:
        if alias.lower() in validation.RESERVED_ALIASES:
            raise err(409, "alias_taken")
        item["short_code"] = alias
        if not repo.create_link(item):   # ghi có điều kiện: trùng (kể cả alias đã xóa) -> 409
            raise err(409, "alias_taken")
    else:
        for _ in range(s.max_retries):
            item["short_code"] = generate_code(s.code_length)
            if repo.create_link(item):
                break
        else:
            raise err(500, "internal_error", "code_generation_failed")

    if reasons:
        repo.incr_flagged()
    return _result(201, item, s.base_url, created=True)
