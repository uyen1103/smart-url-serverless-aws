"""GET /api/links và DELETE /api/links/{code} (handlers/links.py) chạy trên 5 bảng moto của conftest."""
import base64

import pytest

from handlers import links, shorten
from helpers import OWNER_A, OWNER_B, add_link, body_of, error_of, make_event
from linkpulse import repo

LIST, DELETE = "GET /api/links", "DELETE /api/links/{code}"
KEYS = {"code", "short_url", "long_url", "clicks", "created_at", "expires_at", "max_clicks", "status"}
PAST = "2020-01-01T00:00:00Z"


def listing(owner=OWNER_A, **query):
    headers = {"x-owner-id": owner} if owner else {}
    return links.lambda_handler(make_event(LIST, headers=headers, query=query or None), None)


def delete(code, owner=OWNER_A):
    headers = {"x-owner-id": owner} if owner else {}
    return links.lambda_handler(make_event(DELETE, path_params={"code": code}, headers=headers), None)


def codes(resp):
    return [i["code"] for i in body_of(resp)["items"]]


@pytest.fixture
def five(tables):
    """5 link của OWNER_A (c1 cũ nhất ... c5 mới nhất) + 1 link đã xóa + 1 link của người khác."""
    for n in range(1, 6):
        add_link(f"c{n}xxxx", owner_id=OWNER_A, long_url=f"https://site{n}.example/page", created_at=f"2026-10-0{n}T00:00:00Z",
                 click_count=n * 10 if n != 3 else 0)
    add_link("gone123", owner_id=OWNER_A, status="deleted", created_at="2026-10-06T00:00:00Z", click_count=99)
    add_link("other12", owner_id=OWNER_B, created_at="2026-10-07T00:00:00Z")


# ------------------------------------------------------------------ danh sách
@pytest.mark.parametrize("owner", [None, "khong-phai-uuid"])
def test_list_requires_a_valid_owner(tables, owner):
    resp = listing(owner)
    assert (resp["statusCode"], error_of(resp)["code"]) == (401, "unauthorized")


def test_empty_list(tables):
    assert body_of(listing()) == {"summary": {"total_links": 0, "active_links": 0, "total_clicks": 0},
                                  "items": [], "next_cursor": None}


def test_lists_only_my_links_newest_first_without_deleted(five):
    resp = listing()
    assert resp["statusCode"] == 200 and codes(resp) == [f"c{n}xxxx" for n in (5, 4, 3, 2, 1)]
    first = body_of(resp)["items"][0]
    assert set(first) == KEYS and first["short_url"] == "https://linkpulse.vn/c5xxxx" and first["clicks"] == 50
    assert codes(listing(OWNER_B)) == ["other12"]


def test_summary_counts_everything_regardless_of_filters(tables):
    add_link("act1111", owner_id=OWNER_A, click_count=5)
    add_link("exp1111", owner_id=OWNER_A, click_count=7, expires_at=PAST)
    add_link("blk1111", owner_id=OWNER_A, click_count=1, status="blocked")
    body = body_of(listing(status="expired"))
    assert body["summary"] == {"total_links": 3, "active_links": 1, "total_clicks": 13}
    assert [i["code"] for i in body["items"]] == ["exp1111"]


@pytest.mark.parametrize("fields, status", [({}, "active"), ({"expires_at": PAST}, "expired"), ({"status": "blocked"}, "blocked"),
                                            ({"status": "suspicious"}, "suspicious"),
                                            ({"max_clicks": 1, "click_count": 1}, "max_clicks")])
def test_each_status_filter(tables, fields, status):
    add_link("x" * 7, owner_id=OWNER_A, **fields)
    add_link("other77", owner_id=OWNER_A, status="blocked" if status != "blocked" else "suspicious")
    assert codes(listing(status=status)) == ["xxxxxxx"]


@pytest.mark.parametrize("text, expected", [("SITE3", ["c3xxxx"]), ("c2x", ["c2xxxx"]), ("example/page", ["c5xxxx", "c4xxxx", "c3xxxx",
                                            "c2xxxx", "c1xxxx"]), ("khong-co", [])])
def test_search_matches_code_or_url_case_insensitively(five, text, expected):
    assert codes(listing(q=text)) == expected


@pytest.mark.parametrize("sort, expected", [("created_at_desc", [5, 4, 3, 2, 1]), ("created_at_asc", [1, 2, 3, 4, 5]),
                                            ("clicks_desc", [5, 4, 2, 1, 3]), ("clicks_asc", [3, 1, 2, 4, 5])])
def test_sorting(five, sort, expected):
    assert codes(listing(sort=sort)) == [f"c{n}xxxx" for n in expected]


def test_cursor_pagination_walks_every_page_once(five):
    seen, cursor = [], None
    for _ in range(5):
        body = body_of(listing(limit="2", **({"cursor": cursor} if cursor else {})))
        seen += [i["code"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"c{n}xxxx" for n in (5, 4, 3, 2, 1)] and cursor is None


def test_last_page_has_no_cursor(five):
    assert body_of(listing(limit="5"))["next_cursor"] is None and body_of(listing(limit="4"))["next_cursor"]


def test_owner_link_cap(five, monkeypatch):
    monkeypatch.setenv("MAX_LINKS_PER_OWNER", "3")
    body = body_of(listing())
    assert [i["code"] for i in body["items"]] == ["c5xxxx", "c4xxxx", "c3xxxx"] and body["summary"]["total_links"] == 3


@pytest.mark.parametrize("query, reason", [
    ({"status": "dang-hoat-dong"}, "status_invalid"), ({"sort": "ngau_nhien"}, "sort_invalid"),
    ({"limit": "0"}, "limit_out_of_range"), ({"limit": "51"}, "limit_out_of_range"), ({"limit": "abc"}, "limit_not_integer"),
    ({"cursor": "@@@"}, "cursor_invalid"), ({"cursor": base64.urlsafe_b64encode(b"-5").decode()}, "cursor_invalid")])
def test_invalid_query_parameters(tables, query, reason):
    resp = listing(**query)
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (400, "invalid_request", reason)


def test_limit_50_is_allowed(tables):
    assert listing(limit="50")["statusCode"] == 200


# ------------------------------------------------------------------ xóa
def test_owner_can_delete_and_data_is_purged(tables):
    add_link("del1234", owner_id=OWNER_A)
    tables["clicks"].put_item(Item={"short_code": "del1234", "sk": "2026-10-01T00:00:00Z#1"})
    tables["stats"].put_item(Item={"scope": "LINK#del1234", "sk": "M#2026-10-01T00:00:00Z", "clicks": 1})
    tables["stats"].put_item(Item={"scope": "GLOBAL", "sk": "M#2026-10-01T00:00:00Z", "clicks": 1})
    resp = delete("del1234")
    assert resp["statusCode"] == 204 and "body" not in resp
    item = tables["urls"].get_item(Key={"short_code": "del1234"})["Item"]
    assert item["status"] == "deleted" and item["deleted_at"]                       # giữ lại bản ghi để không cấp lại mã
    assert tables["clicks"].scan()["Count"] == 0
    assert [i["scope"] for i in tables["stats"].scan()["Items"]] == ["GLOBAL"]      # chỉ xóa thống kê của link này
    assert codes(listing()) == []


def test_other_owner_cannot_delete(tables):
    add_link("keep123", owner_id=OWNER_A)
    tables["clicks"].put_item(Item={"short_code": "keep123", "sk": "2026-10-01T00:00:00Z#1"})
    resp = delete("keep123", OWNER_B)
    assert (resp["statusCode"], error_of(resp)["code"]) == (403, "forbidden")
    assert tables["urls"].get_item(Key={"short_code": "keep123"})["Item"]["status"] == "active"
    assert tables["clicks"].scan()["Count"] == 1


@pytest.mark.parametrize("code", ["khongco1", "a", "co dau", "bad/path"])
def test_delete_unknown_or_malformed_code(tables, code):
    assert delete(code)["statusCode"] == 404


def test_delete_twice_and_without_owner(tables):
    add_link("del1234", owner_id=OWNER_A)
    assert delete("del1234", None)["statusCode"] == 401
    assert [delete("del1234")["statusCode"] for _ in range(2)] == [204, 404]


def test_link_without_owner_cannot_be_deleted_by_anyone(tables):
    add_link("anon123")
    assert delete("anon123")["statusCode"] == 403


def test_deleted_alias_is_never_reissued(tables):
    add_link("ten-rieng", owner_id=OWNER_A)
    delete("ten-rieng")
    resp = shorten.lambda_handler(make_event("POST /api/shorten", body={"url": "https://example.com", "alias": "ten-rieng"}), None)
    assert resp["statusCode"] == 409 and repo.get_link("ten-rieng")["status"] == "deleted"


def test_unsupported_method_is_404(tables):
    resp = links.lambda_handler(make_event("PUT /api/links", headers={"x-owner-id": OWNER_A}), None)
    assert (resp["statusCode"], error_of(resp)["code"]) == (404, "not_found")
