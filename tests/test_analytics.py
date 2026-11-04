import json
from pathlib import Path

import pytest
from boto3.dynamodb.types import TypeSerializer
from jsonschema import FormatChecker, validate

from handlers import process_clicks, stats as stats_handler
from helpers import add_link, body_of, error_of, make_event
from linkpulse import abuse, analytics, repo
from linkpulse.events import record_click, referrer_domain
from linkpulse.models import parse_iso


@pytest.mark.parametrize(
    "referrer",
    [None, "", "http://[:1", "not a url", "http://a:99999999/", "WWW.Facebook.com"],
)
def test_referrer_domain_returns_direct_for_missing_or_invalid_url(referrer):
    assert referrer_domain(referrer) == "direct"


def test_referrer_domain_normalizes_www_host():
    assert referrer_domain("https://WWW.Facebook.com/x") == "facebook.com"


def test_referrer_domain_truncates_long_host_to_60_characters():
    host = "a" * 70 + ".com"
    assert referrer_domain(f"https://{host}/path") == host[:60]


def test_aggregate_caps_referrers_at_20_and_counts_overflow_as_other():
    events = [
        {
            "short_code": "abc1234",
            "timestamp": "2026-10-01T08:00:30Z",
            "country": "VN",
            "device": "desktop",
            "browser": "Chrome",
            "referrer": "direct" if index == 0 else f"source{index}.example",
        }
        for index in range(100)
    ]

    group = analytics.aggregate(events)[("GLOBAL", "2026-10-01T08:00:00Z")]
    referrers = {key: value for key, value in group["counters"].items() if key.startswith("r:")}
    assert len(referrers) == 21
    assert referrers["r:direct"] == 1
    assert referrers["r:other"] == 80
    assert group["counters"]["clicks"] == 100


def test_record_click_item_matches_click_event_schema(tables):
    record_click(
        "abc1234",
        ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0",
        referer="https://www.facebook.com/x",
        country="VN",
        ip_hash_value="0123456789abcdef",
    )
    item = tables["clicks"].scan()["Items"][0]
    schema_item = {key: value for key, value in item.items() if key not in {"sk", "expires_at"}}
    schema_path = Path(__file__).resolve().parents[1] / "docs" / "click_event_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    validate(schema_item, schema, format_checker=FormatChecker())


def click(code, timestamp, *, referrer="direct", ip_hash="ip-1", result="valid"):
    return {
        "short_code": code,
        "timestamp": timestamp,
        "country": "VN",
        "device": "bot" if result == "bot" else "desktop",
        "browser": "Other" if result == "bot" else "Chrome",
        "referrer": referrer,
        "ip_hash": ip_hash,
        "result": result,
    }


def persist(events):
    for (scope, minute), group in analytics.aggregate(events).items():
        analytics.apply_group(scope, minute, group)


def test_apply_group_adds_counts_across_calls(tables):
    events = [
        click("abc1234", "2026-10-01T08:00:10Z", ip_hash="ip-1"),
        click("abc1234", "2026-10-01T08:00:20Z", ip_hash="ip-2", result="bot"),
    ]
    group = analytics.aggregate(events)[("GLOBAL", "2026-10-01T08:00:00Z")]

    analytics.apply_group("GLOBAL", "2026-10-01T08:00:00Z", group)
    updated = analytics.apply_group("GLOBAL", "2026-10-01T08:00:00Z", group)

    assert updated["clicks"] == 4
    assert updated["bot_clicks"] == 2
    assert updated["ips"] == {"ip-1", "ip-2"}


def test_get_stats_fills_empty_minute_buckets(tables):
    persist([
        click("abc1234", "2026-10-01T08:00:10Z"),
        click("abc1234", "2026-10-01T08:02:10Z", ip_hash="ip-2"),
    ])
    result = analytics.get_stats(
        "GLOBAL",
        parse_iso("2026-10-01T08:00:00Z"),
        parse_iso("2026-10-01T08:02:00Z"),
        "minute",
        parse_iso("2026-10-01T08:03:00Z"),
    )

    assert [(bucket["clicks"], bucket["bot_clicks"]) for bucket in result["timeline"]] == [
        (1, 0),
        (0, 0),
        (1, 0),
    ]


def test_get_stats_groups_buckets_by_hour(tables):
    persist([
        click("abc1234", "2026-10-01T08:00:10Z"),
        click("abc1234", "2026-10-01T09:00:10Z", ip_hash="ip-2"),
    ])
    result = analytics.get_stats(
        "GLOBAL",
        parse_iso("2026-10-01T08:00:00Z"),
        parse_iso("2026-10-01T09:00:00Z"),
        "hour",
        parse_iso("2026-10-01T09:01:00Z"),
    )

    assert [(bucket["bucket"], bucket["clicks"]) for bucket in result["timeline"]] == [
        ("2026-10-01T08:00:00Z", 1),
        ("2026-10-01T09:00:00Z", 1),
    ]


def test_stats_handler_rejects_ranges_over_1440_buckets(tables):
    response = stats_handler.lambda_handler(
        make_event(
            "GET /api/stats",
            query={"from": "2026-10-01T00:00:00Z", "to": "2026-10-03T00:00:00Z"},
        ),
        None,
    )

    assert response["statusCode"] == 400
    assert error_of(response)["reason"] == "range_too_large"


@pytest.mark.parametrize(
    "minute_item, expected",
    [
        ({"clicks": 299}, None),
        ({"clicks": 300}, "click_spike"),
        ({"clicks": 50, "bot_clicks": 40}, "bot_traffic"),
    ],
)
def test_abuse_evaluate_thresholds(monkeypatch, minute_item, expected):
    monkeypatch.setenv("SPIKE_CLICKS_PER_MINUTE", "300")
    monkeypatch.setenv("BOT_MIN_CLICKS", "50")
    monkeypatch.setenv("BOT_RATIO", "0.8")

    assert abuse.evaluate(minute_item) == expected


def test_process_clicks_ignores_non_insert_records_and_flags_once(tables, monkeypatch):
    add_link("abc1234")
    monkeypatch.setenv("SPIKE_CLICKS_PER_MINUTE", "2")
    serializer = TypeSerializer()

    def record(event_name, click_event):
        return {
            "eventName": event_name,
            "dynamodb": {
                "NewImage": {
                    key: serializer.serialize(value)
                    for key, value in click_event.items()
                }
            },
        }

    inserted_events = [
        click("abc1234", "2026-10-01T08:00:10Z", ip_hash="ip-1"),
        click("abc1234", "2026-10-01T08:00:20Z", ip_hash="ip-2"),
        click("abc1234", "2026-10-01T08:01:10Z", ip_hash="ip-3"),
        click("abc1234", "2026-10-01T08:01:20Z", ip_hash="ip-4"),
    ]
    flag_calls = []
    original_flag_link = repo.flag_link

    def track_flag(code, reason):
        flag_calls.append((code, reason))
        return original_flag_link(code, reason)

    monkeypatch.setattr(repo, "flag_link", track_flag)
    response = process_clicks.lambda_handler(
        {
            "Records": [
                *(record("INSERT", event) for event in inserted_events),
                record("MODIFY", click("abc1234", "2026-10-01T08:00:30Z")),
                {"eventName": "REMOVE"},
            ]
        },
        None,
    )

    assert response == {"events": 4, "flagged": ["abc1234"]}
    assert len(flag_calls) == 1
    assert repo.get_flagged() == 1
    assert repo.get_link("abc1234")["status"] == "suspicious"


def test_stats_handler_returns_404_for_unknown_link(tables):
    response = stats_handler.lambda_handler(
        make_event("GET /api/stats/{code}", path_params={"code": "abc1234"}),
        None,
    )

    assert response["statusCode"] == 404


def test_stats_handler_returns_400_for_invalid_granularity(tables):
    response = stats_handler.lambda_handler(
        make_event("GET /api/stats", query={"granularity": "day"}),
        None,
    )

    assert response["statusCode"] == 400
    assert error_of(response)["reason"] == "granularity_invalid"
