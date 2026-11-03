"""GET /api/stats và GET /api/stats/{code} (handlers/stats.py). Dữ liệu gieo bằng chính hàm của pipeline analytics."""
import pytest

from handlers import stats
from helpers import add_link, body_of, error_of, make_event
from linkpulse import analytics, repo

RANGE = {"from": "2026-10-01T08:00:00Z", "to": "2026-10-01T08:10:00Z"}      # 11 mốc phút: 08:00 ... 08:10
GLOBAL, ONE = "GET /api/stats", "GET /api/stats/{code}"


def click(code, minute, *, hour=8, country="VN", device="mobile", browser="Chrome", referrer="direct", ip="h1",
          result="valid"):
    return {"short_code": code, "timestamp": f"2026-10-01T{hour:02d}:{minute:02d}:30Z", "country": country, "device": device,
            "browser": browser, "referrer": referrer, "ip_hash": ip, "result": result}


def seed(events):
    for (scope, minute), group in analytics.aggregate(events).items():
        analytics.apply_group(scope, minute, group)
    analytics.update_recent(events)


def get_global(**query):
    return stats.lambda_handler(make_event(GLOBAL, query=query or None), None)


def get_link(code, **query):
    return stats.lambda_handler(make_event(ONE, path_params={"code": code}, query=query or None), None)


@pytest.fixture
def seeded(tables):
    add_link("aaa1111", click_count=4)
    add_link("bbb2222", click_count=3)
    add_link("ccc3333", click_count=3)
    seed([click("aaa1111", 1, ip="h1", referrer="facebook.com"), click("aaa1111", 1, ip="h1", referrer="facebook.com"),
          click("aaa1111", 3, ip="h2", country="US", device="desktop", browser="Safari"),
          click("aaa1111", 3, ip="h3", device="bot", result="bot", browser="Other"),
          click("bbb2222", 3, ip="h1"), click("bbb2222", 5, ip="h4", country="JP"), click("ccc3333", 5, ip="h5"),
          click("ccc3333", 5, ip="h5"), click("ccc3333", 5, ip="h5"),
          click("aaa1111", 59, hour=7), click("aaa1111", 11, hour=8)])      # ngoài khoảng [08:00, 08:10]: không được tính


# ------------------------------------------------------------------ toàn hệ thống
def test_global_totals_and_dimensions(seeded):
    resp = get_global(**RANGE)
    body = body_of(resp)
    assert resp["statusCode"] == 200 and resp["headers"]["Cache-Control"] == "no-store"
    assert (body["code"], body["from"], body["to"], body["granularity"]) == (None, RANGE["from"], RANGE["to"], "minute")
    assert (body["total_clicks"], body["bot_clicks"], body["unique_visitors"]) == (9, 1, 5)
    assert body["avg_clicks_per_minute"] == 0.9 and body["updated_at"].endswith("Z") and "link" not in body
    assert body["countries"] == [{"name": "VN", "clicks": 7}, {"name": "JP", "clicks": 1}, {"name": "US", "clicks": 1}]
    assert body["devices"] == [{"name": "mobile", "clicks": 7}, {"name": "bot", "clicks": 1}, {"name": "desktop", "clicks": 1}]
    assert body["browsers"][0] == {"name": "Chrome", "clicks": 7}
    assert body["referrers"] == [{"name": "direct", "clicks": 7}, {"name": "facebook.com", "clicks": 2}]


def test_timeline_fills_every_minute_with_zeros(seeded):
    timeline = body_of(get_global(**RANGE))["timeline"]
    assert [t["bucket"] for t in timeline] == [f"2026-10-01T08:{m:02d}:00Z" for m in range(11)]
    assert {t["bucket"][14:16]: (t["clicks"], t["bot_clicks"]) for t in timeline if t["clicks"]} == {
        "01": (2, 0), "03": (3, 1), "05": (4, 0)}


def test_top_links_are_sorted_by_clicks(seeded):
    assert body_of(get_global(**RANGE))["top_links"] == [{"code": "aaa1111", "clicks": 4}, {"code": "ccc3333", "clicks": 3},
                                                         {"code": "bbb2222", "clicks": 2}]


def test_top_links_tie_is_broken_by_code_and_capped_at_ten(tables):
    seed([click("zzz9999", 1), click("zzz9999", 2), click("aaa1111", 1), click("aaa1111", 2), click("mmm5555", 1)])
    assert body_of(get_global(**RANGE))["top_links"] == [{"code": "aaa1111", "clicks": 2}, {"code": "zzz9999", "clicks": 2},
                                                         {"code": "mmm5555", "clicks": 1}]
    seed([click(f"lnk{n:04d}", 4) for n in range(12)])
    assert len(body_of(get_global(**RANGE))["top_links"]) == 10


def test_flagged_counter_and_recent_clicks(seeded):
    repo.incr_flagged(2)
    body = body_of(get_global(**RANGE))
    assert body["flagged_links"] == 2
    recent = body["recent_clicks"]
    assert len(recent) == 11 and recent[0]["timestamp"] >= recent[-1]["timestamp"]
    assert set(recent[0]) == {"timestamp", "code", "country", "device", "browser", "referrer", "result"}


def test_hour_granularity_groups_minutes(seeded):
    body = body_of(get_global(**{"from": "2026-10-01T07:00:00Z", "to": "2026-10-01T08:30:00Z"}, granularity="hour"))
    assert [(t["bucket"], t["clicks"]) for t in body["timeline"]] == [("2026-10-01T07:00:00Z", 1), ("2026-10-01T08:00:00Z", 10)]
    assert body["granularity"] == "hour"


def test_empty_system(tables):
    body = body_of(get_global(**RANGE))
    assert (body["total_clicks"], body["unique_visitors"], body["flagged_links"], body["top_links"], body["recent_clicks"]) == (
        0, 0, 0, [], [])
    assert body["countries"] == [] and all(t["clicks"] == 0 for t in body["timeline"]) and len(body["timeline"]) == 11


def test_default_range_is_the_last_hour(tables):
    body = body_of(get_global())
    assert len(body["timeline"]) in (60, 61) and body["to"] == body["updated_at"][:19] + "Z"


@pytest.mark.parametrize("query, reason", [
    ({"granularity": "day"}, "granularity_invalid"), ({"from": "hom-qua"}, "time_format_invalid"),
    ({"to": "2026-13-01T00:00:00Z"}, "time_format_invalid"),
    ({"from": RANGE["to"], "to": RANGE["from"]}, "from_must_be_before_to"), ({"from": RANGE["from"], "to": RANGE["from"]},
                                                                            "from_must_be_before_to"),
    ({"from": "2026-01-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"}, "range_too_large")])
def test_invalid_range(tables, query, reason):
    resp = get_global(**query)
    assert (resp["statusCode"], error_of(resp)["code"], error_of(resp)["reason"]) == (400, "invalid_request", reason)


def test_hour_granularity_allows_a_longer_range(tables):
    resp = get_global(**{"from": "2026-09-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"}, granularity="hour")
    assert resp["statusCode"] == 200 and len(body_of(resp)["timeline"]) == 721


# ------------------------------------------------------------------ theo link
def test_link_stats_only_counts_that_link(seeded, tables):
    for sk, device in (("2026-10-01T08:01:30Z#a", "mobile"), ("2026-10-01T08:03:30Z#b", "bot")):
        tables["clicks"].put_item(Item={"short_code": "aaa1111", "sk": sk, "timestamp": sk[:20], "country": "VN", "device": device,
                                        "browser": "Chrome", "referrer": "direct", "result": "bot" if device == "bot" else "valid"})
    body = body_of(get_link("aaa1111", **RANGE))
    assert (body["code"], body["total_clicks"], body["bot_clicks"], body["unique_visitors"]) == ("aaa1111", 4, 1, 3)
    assert body["link"]["code"] == "aaa1111" and body["link"]["status"] == "active" and body["link"]["clicks"] == 4
    assert "top_links" not in body and "flagged_links" not in body
    assert [r["timestamp"] for r in body["recent_clicks"]] == ["2026-10-01T08:03:30Z", "2026-10-01T08:01:30Z"]
    assert body["recent_clicks"][0]["result"] == "bot" and body["countries"] == [{"name": "VN", "clicks": 3},
                                                                                 {"name": "US", "clicks": 1}]


def test_link_without_clicks_has_empty_stats(tables):
    add_link("new1234")
    body = body_of(get_link("new1234", **RANGE))
    assert (body["total_clicks"], body["recent_clicks"]) == (0, [])


@pytest.mark.parametrize("code, fields", [("khongco1", None), ("deleted1", {"status": "deleted"}), ("a", None), ("co dau", None)])
def test_unknown_deleted_or_malformed_code_is_404(tables, code, fields):
    if fields:
        add_link(code, **fields)
    resp = get_link(code, **RANGE)
    assert (resp["statusCode"], error_of(resp)["code"]) == (404, "not_found")


def test_link_stats_validates_the_range_after_the_code(tables):
    add_link("aaa1111")
    assert error_of(get_link("aaa1111", granularity="day"))["reason"] == "granularity_invalid"
    assert get_link("khongco1", granularity="day")["statusCode"] == 404           # mã sai thì trả 404 trước


def test_expired_link_still_shows_its_stats(tables):
    add_link("old1234", expires_at="2020-01-01T00:00:00Z")
    assert body_of(get_link("old1234", **RANGE))["link"]["status"] == "expired"
