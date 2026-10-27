"""GET /api/links  và  DELETE /api/links/{code}"""
import base64

from linkpulse import http, repo
from linkpulse.config import settings
from linkpulse.errors import err
from linkpulse.models import link_state, now, public_link
from linkpulse.validation import CODE_PATTERN

STATUSES = {"active", "suspicious", "blocked", "max_clicks", "expired"}
SORTS = {"created_at_desc", "created_at_asc", "clicks_desc", "clicks_asc"}


def _int_param(q, name, default, lo, hi):
    raw = q.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError:
        raise err(400, "invalid_request", f"{name}_not_integer")
    if not lo <= v <= hi:
        raise err(400, "invalid_request", f"{name}_out_of_range")
    return v


def _decode_cursor(raw):
    if not raw:
        return 0
    try:
        v = int(base64.urlsafe_b64decode(raw.encode()).decode())
        if v < 0:
            raise ValueError
        return v
    except Exception:  # noqa: BLE001
        raise err(400, "invalid_request", "cursor_invalid")


def _encode_cursor(offset):
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def list_links(event):
    owner = http.owner_id(event, required=True)
    q = http.query(event)
    status, sort = q.get("status"), q.get("sort", "created_at_desc")
    text = (q.get("q") or "")[:200].lower()
    if status and status not in STATUSES:
        raise err(400, "invalid_request", "status_invalid")
    if sort not in SORTS:
        raise err(400, "invalid_request", "sort_invalid")
    limit = _int_param(q, "limit", 20, 1, 50)
    offset = _decode_cursor(q.get("cursor"))

    at, base = now(), settings().base_url
    links = [public_link(i, base, at) for i in repo.list_owner_links(owner)]   # mới nhất trước
    summary = {"total_links": len(links),
               "active_links": sum(1 for l in links if l["status"] == "active"),
               "total_clicks": sum(l["clicks"] for l in links)}

    if status:
        links = [l for l in links if l["status"] == status]
    if text:
        links = [l for l in links if text in l["code"].lower() or text in l["long_url"].lower()]
    if sort == "created_at_asc":
        links.reverse()
    elif sort in ("clicks_desc", "clicks_asc"):
        links.sort(key=lambda l: l["clicks"], reverse=sort == "clicks_desc")

    page = links[offset:offset + limit]
    nxt = _encode_cursor(offset + limit) if offset + limit < len(links) else None
    return http.response(200, {"summary": summary, "items": page, "next_cursor": nxt})


def delete_link(event):
    owner = http.owner_id(event, required=True)
    code = http.path_param(event, "code") or ""
    if not CODE_PATTERN.match(code):
        raise err(404, "not_found")
    result = repo.mark_deleted(code, owner)
    if result == "not_found":
        raise err(404, "not_found")
    if result == "forbidden":
        raise err(403, "forbidden")
    repo.purge_link_data(code)
    return http.response(204)


@http.api_handler
def lambda_handler(event, context):
    route = event.get("routeKey", "")
    if route.startswith("GET "):
        return list_links(event)
    if route.startswith("DELETE "):
        return delete_link(event)
    raise err(404, "not_found")
