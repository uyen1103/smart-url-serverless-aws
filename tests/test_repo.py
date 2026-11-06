
import time

import pytest
from botocore.exceptions import ClientError

from linkpulse import repo


def make_link(
    short_code="abc1234",
    owner_id="owner-1",
    long_url="https://example.com",
    status="active",
    created_at="2026-11-01T10:00:00Z",
):
    return {
        "short_code": short_code,
        "owner_id": owner_id,
        "long_url": long_url,
        "status": status,
        "created_at": created_at,
        "click_count": 0,
    }


# ------------------------------------------------------------------
# create_link
# ------------------------------------------------------------------

def test_create_link_success(tables):
    item = make_link()

    assert repo.create_link(item) is True

    saved = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert saved["long_url"] == "https://example.com"


def test_create_link_duplicate(tables):
    item = make_link()

    assert repo.create_link(item) is True
    assert repo.create_link(item) is False


# ------------------------------------------------------------------
# get_link
# ------------------------------------------------------------------

def test_get_link_existing(tables):
    tables["urls"].put_item(Item=make_link())

    result = repo.get_link("abc1234")

    assert result is not None
    assert result["short_code"] == "abc1234"


def test_get_link_not_found(tables):
    assert repo.get_link("missing") is None


# ------------------------------------------------------------------
# find_existing
# ------------------------------------------------------------------

def test_find_existing_returns_matching_active_links(tables):
    tables["urls"].put_item(Item=make_link())
    tables["urls"].put_item(
        Item=make_link(
            short_code="deleted1",
            status="deleted",
        )
    )
    tables["urls"].put_item(
        Item=make_link(
            short_code="other01",
            owner_id="owner-2",
        )
    )

    result = repo.find_existing(
        "owner-1",
        "https://example.com",
    )

    assert len(result) == 1
    assert result[0]["short_code"] == "abc1234"


# ------------------------------------------------------------------
# register_click
# ------------------------------------------------------------------

def test_register_click_without_limit(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.register_click("abc1234", None) is True

    item = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert item["click_count"] == 1


def test_register_click_within_limit(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.register_click("abc1234", 2) is True
    assert repo.register_click("abc1234", 2) is True

    item = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert item["click_count"] == 2


def test_register_click_exceeds_limit(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.register_click("abc1234", 1) is True
    assert repo.register_click("abc1234", 1) is False

    item = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert item["click_count"] == 1


def test_register_click_missing_link(tables):
    assert repo.register_click("missing", None) is False


def test_register_click_throttled(monkeypatch):
    from linkpulse import db

    error = ClientError(
        {
            "Error": {
                "Code": "ProvisionedThroughputExceededException",
                "Message": "Throttled",
            }
        },
        "UpdateItem",
    )

    class FakeTable:
        def update_item(self, **kwargs):
            raise error

    monkeypatch.setattr(
        db,
        "urls",
        lambda best_effort=False: FakeTable(),
    )
    monkeypatch.setattr(
        db,
        "throttled",
        lambda exc, op: True,
    )

    assert repo.register_click("abc1234", None) is True


# ------------------------------------------------------------------
# mark_deleted
# ------------------------------------------------------------------

def test_mark_deleted_success(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.mark_deleted("abc1234", "owner-1") == "ok"

    item = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert item["status"] == "deleted"
    assert "deleted_at" in item


def test_mark_deleted_not_found(tables):
    assert repo.mark_deleted("missing", "owner-1") == "not_found"


def test_mark_deleted_forbidden(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.mark_deleted("abc1234", "owner-2") == "forbidden"


# ------------------------------------------------------------------
# flag_link
# ------------------------------------------------------------------

def test_flag_link_success(tables):
    tables["urls"].put_item(Item=make_link())

    assert repo.flag_link(
        "abc1234",
        "suspicious activity",
    ) is True

    item = tables["urls"].get_item(
        Key={"short_code": "abc1234"}
    )["Item"]

    assert item["status"] == "suspicious"
    assert item["flag_reason"] == "suspicious activity"
    assert "flagged_at" in item


def test_flag_link_already_flagged(tables):
    tables["urls"].put_item(
        Item=make_link(status="suspicious")
    )

    assert repo.flag_link("abc1234", "another reason") is False


def test_flag_link_missing(tables):
    assert repo.flag_link("missing", "reason") is False


# ------------------------------------------------------------------
# list_owner_links
# ------------------------------------------------------------------

def test_list_owner_links_filters_deleted_and_other_owners(tables):
    tables["urls"].put_item(Item=make_link())

    tables["urls"].put_item(
        Item=make_link(
            short_code="deleted1",
            status="deleted",
        )
    )

    tables["urls"].put_item(
        Item=make_link(
            short_code="other01",
            owner_id="owner-2",
        )
    )

    result = repo.list_owner_links("owner-1")

    assert len(result) == 1
    assert result[0]["short_code"] == "abc1234"


def test_list_owner_links_respects_limit(tables, monkeypatch):
    monkeypatch.setenv("MAX_LINKS_PER_OWNER", "2")

    for i in range(5):
        tables["urls"].put_item(
            Item=make_link(
                short_code=f"code{i:03d}",
                created_at=f"2026-11-0{i + 1}T10:00:00Z",
            )
        )

    result = repo.list_owner_links("owner-1")

    assert len(result) == 2


# ------------------------------------------------------------------
# purge_link_data
# ------------------------------------------------------------------

def test_purge_link_data_deletes_only_target_link_data(tables):
    tables["clicks"].put_item(
        Item={
            "short_code": "abc1234",
            "sk": "CLICK#001",
        }
    )

    tables["clicks"].put_item(
        Item={
            "short_code": "other01",
            "sk": "CLICK#001",
        }
    )

    tables["stats"].put_item(
        Item={
            "scope": "LINK#abc1234",
            "sk": "M#202611011000",
            "clicks": 5,
        }
    )

    tables["stats"].put_item(
        Item={
            "scope": "LINK#other01",
            "sk": "M#202611011000",
            "clicks": 3,
        }
    )

    repo.purge_link_data("abc1234")

    clicks = tables["clicks"].scan()["Items"]
    stats = tables["stats"].scan()["Items"]

    assert len(clicks) == 1
    assert clicks[0]["short_code"] == "other01"

    assert len(stats) == 1
    assert stats[0]["scope"] == "LINK#other01"


# ------------------------------------------------------------------
# flagged counter
# ------------------------------------------------------------------

def test_flagged_counter(tables):
    assert repo.get_flagged() == 0

    repo.incr_flagged()
    repo.incr_flagged(2)

    assert repo.get_flagged() == 3


# ------------------------------------------------------------------
# DynamoDB TTL
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "table_name",
    ["clicks", "stats", "rate_limits"],
)
def test_table_ttl_enabled(tables, table_name):
    table = tables[table_name]

    response = table.meta.client.describe_time_to_live(
        TableName=table.table_name
    )

    ttl = response["TimeToLiveDescription"]

    assert ttl["TimeToLiveStatus"] in (
        "ENABLED",
        "ENABLING",
    )
    assert ttl["AttributeName"] == "expires_at"
