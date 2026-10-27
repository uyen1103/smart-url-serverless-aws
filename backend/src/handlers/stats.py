"""GET /api/stats  và  GET /api/stats/{code}"""
from linkpulse import analytics, http, repo
from linkpulse.config import settings
from linkpulse.errors import err
from linkpulse.models import now, public_link
from linkpulse.validation import CODE_PATTERN


def _range(event):
    q = http.query(event)
    gran = q.get("granularity", "minute")
    if gran not in ("minute", "hour"):
        raise err(400, "invalid_request", "granularity_invalid")
    at = now()
    try:
        frm, to = analytics.parse_range(q.get("from"), q.get("to"), at)
    except ValueError:
        raise err(400, "invalid_request", "time_format_invalid")
    if frm >= to:
        raise err(400, "invalid_request", "from_must_be_before_to")
    if analytics.bucket_count(frm, to, gran) > settings().max_buckets:
        raise err(400, "invalid_request", "range_too_large")
    return frm, to, gran, at


def global_stats(event):
    frm, to, gran, at = _range(event)
    out = analytics.get_stats("GLOBAL", frm, to, gran, at)
    links = out.pop("_links")
    out.update({"code": None, "flagged_links": repo.get_flagged(),
                "top_links": analytics.top_links(links), "recent_clicks": analytics.recent_global()})
    return http.response(200, out, {"Cache-Control": "no-store"})


def link_stats(event):
    code = http.path_param(event, "code") or ""
    if not CODE_PATTERN.match(code):
        raise err(404, "not_found")
    item = repo.get_link(code)
    if item is None or item.get("status") == "deleted":
        raise err(404, "not_found")
    frm, to, gran, at = _range(event)
    out = analytics.get_stats(f"LINK#{code}", frm, to, gran, at)
    out.pop("_links")
    out.update({"code": code, "link": public_link(item, settings().base_url, at),
                "recent_clicks": analytics.recent_for_link(code)})
    return http.response(200, out, {"Cache-Control": "no-store"})


@http.api_handler
def lambda_handler(event, context):
    if "{code}" in event.get("routeKey", ""):
        return link_stats(event)
    return global_stats(event)
