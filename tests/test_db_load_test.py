
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from boto3.dynamodb.conditions import Key

from linkpulse import analytics, repo
from linkpulse.models import to_iso


LINK_COUNT = 5000
CLICK_COUNT = 50000
REPEATS = 10

OWNER_ID = "load-test-owner"
TARGET_CODE = "L000000"


def measure(func, repeats=REPEATS):
    samples = []

    for _ in range(repeats):
        started = time.perf_counter()
        func()
        samples.append((time.perf_counter() - started) * 1000)

    return {
        "min": min(samples),
        "avg": statistics.mean(samples),
        "max": max(samples),
    }


def count_all_pages(table, key_condition):
    """Count all items across DynamoDB Query pages."""
    kwargs = {
        "KeyConditionExpression": key_condition,
        "Select": "COUNT",
    }
    total = 0

    while True:
        response = table.query(**kwargs)
        total += response["Count"]

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break

        kwargs["ExclusiveStartKey"] = last_key

    return total


def seed_data(tables):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=59)

    # Seed 5,000 links
    with tables["urls"].batch_writer() as batch:
        for i in range(LINK_COUNT):
            code = f"L{i:06d}"
            created = now - timedelta(seconds=LINK_COUNT - i)

            batch.put_item(Item={
                "short_code": code,
                "owner_id": OWNER_ID,
                "long_url": f"https://example.com/article/{i}",
                "status": "active",
                "created_at": to_iso(created),
                "click_count": 0,
            })

    # Seed 50,000 click events for the target link
    events = []

    with tables["clicks"].batch_writer() as batch:
        for i in range(CLICK_COUNT):
            minute = start + timedelta(minutes=i % 60)

            event = {
                "short_code": TARGET_CODE,
                "sk": f"CLICK#{i:08d}",
                "timestamp": to_iso(minute),
                "country": ("VN", "US", "JP", "SG")[i % 4],
                "device": ("desktop", "mobile", "tablet")[i % 3],
                "browser": ("Chrome", "Firefox", "Safari")[i % 3],
                "referrer": ("direct", "google", "facebook")[i % 3],
                "result": "bot" if i % 10 == 0 else "valid",
                "ip_hash": f"ip-{i % 1000:04d}",
            }

            events.append(event)
            batch.put_item(Item=event)

    # Build stats using the actual analytics functions
    groups = analytics.aggregate(events)

    for (scope, minute), group in groups.items():
        analytics.apply_group(scope, minute, group)

    return start, start + timedelta(minutes=59)


@pytest.mark.skipif(
    os.getenv("RUN_DB_LOAD_TEST") != "1",
    reason="Set RUN_DB_LOAD_TEST=1 to run the database load benchmark",
)
def test_db_load_benchmark(tables, monkeypatch):
    # Allow list_owner_links to return all 5,000 links
    monkeypatch.setenv("MAX_LINKS_PER_OWNER", str(LINK_COUNT))

    print("\nSeeding 5,000 links and 50,000 clicks...")
    seed_started = time.perf_counter()

    frm, to = seed_data(tables)

    seed_seconds = time.perf_counter() - seed_started

    # Verify seed data
    assert tables["urls"].get_item(
        Key={"short_code": TARGET_CODE}
    ).get("Item") is not None

    actual_click_count = count_all_pages(
        tables["clicks"],
        Key("short_code").eq(TARGET_CODE),
    )
    assert actual_click_count == CLICK_COUNT

    print("Seed completed.")

    # 1. get_link
    get_link_result = measure(
        lambda: repo.get_link(TARGET_CODE)
    )

    # 2. list_owner_links
    list_result = measure(
        lambda: repo.list_owner_links(OWNER_ID)
    )

    listed = repo.list_owner_links(OWNER_ID)
    assert len(listed) == LINK_COUNT

    # 3. get_stats
    stats_result = measure(
        lambda: analytics.get_stats(
            f"LINK#{TARGET_CODE}",
            frm,
            to,
            "minute",
            to,
        )
    )

    stats = analytics.get_stats(
        f"LINK#{TARGET_CODE}",
        frm,
        to,
        "minute",
        to,
    )
    assert stats["total_clicks"] == CLICK_COUNT

    # 4. purge_link_data - destructive, run only once and last
    purge_started = time.perf_counter()
    repo.purge_link_data(TARGET_CODE)
    purge_ms = (time.perf_counter() - purge_started) * 1000

    # Verify purge
    remaining_clicks = count_all_pages(
        tables["clicks"],
        Key("short_code").eq(TARGET_CODE),
    )

    remaining_stats = count_all_pages(
        tables["stats"],
        Key("scope").eq(f"LINK#{TARGET_CODE}"),
    )

    assert remaining_clicks == 0
    assert remaining_stats == 0

    report = f"""# Database Load Test

## 1. Test configuration

| Metric | Value |
|---|---:|
| Links seeded | {LINK_COUNT:,} |
| Click events seeded | {CLICK_COUNT:,} |
| Benchmark repetitions | {REPEATS} |
| Database engine | Moto (in-memory DynamoDB mock) |
| Seed duration | {seed_seconds:.2f} seconds |

## 2. Latency results

Unit: milliseconds (ms).

| Operation | Min | Average | Max |
|---|---:|---:|---:|
| get_link | {get_link_result['min']:.3f} | {get_link_result['avg']:.3f} | {get_link_result['max']:.3f} |
| list_owner_links (5,000 links) | {list_result['min']:.3f} | {list_result['avg']:.3f} | {list_result['max']:.3f} |
| get_stats (50,000 clicks aggregated) | {stats_result['min']:.3f} | {stats_result['avg']:.3f} | {stats_result['max']:.3f} |
| purge_link_data (50,000 clicks) | {purge_ms:.3f} | N/A | N/A |

## 3. Verification

- [x] 5,000 links inserted.
- [x] 50,000 click events inserted.
- [x] get_stats returned {stats['total_clicks']:,} clicks.
- [x] purge_link_data removed all target click events.
- [x] purge_link_data removed all target link statistics.

Remaining target click events: {remaining_clicks}

Remaining target link-stat items: {remaining_stats}

## 4. Load threshold estimation

The Clicks table is configured with 4 WCU.

A single standard DynamoDB write of an item up to 1 KB consumes approximately 1 WCU. Under ideal conditions, 4 WCU supports approximately 4 such writes per second.

For 1,200 click writes:

- Ideal minimum write time: approximately 300 seconds at 4 writes/second.
- A burst of 1,200 writes in a short period can exceed provisioned throughput.
- Actual throttling depends on item size, traffic distribution, burst capacity, retries, and concurrent requests.

The delete-link Lambda has a 15-second timeout. Purging 50,000 click records may require multiple Query and BatchWriteItem requests. Whether it times out depends on request latency, pagination, retry behavior, and throughput.

These are theoretical estimates, not measured AWS throttling or Lambda timeout results.

## 5. Limitations

This benchmark uses Moto, an in-memory AWS service mock.

The latency measurements are useful for comparing application logic in this local test environment. They do not represent actual DynamoDB network latency, provisioned capacity, throttling, or AWS Lambda execution time.

The purge operation is measured once because it deletes the target test data.
"""

    output = Path("docs/db_load_test.md")
    output.write_text(report, encoding="utf-8")

    print("\nBenchmark results:")
    print(f"get_link average: {get_link_result['avg']:.3f} ms")
    print(f"list_owner_links average: {list_result['avg']:.3f} ms")
    print(f"get_stats average: {stats_result['avg']:.3f} ms")
    print(f"purge_link_data: {purge_ms:.3f} ms")
    print(f"\nReport saved to: {output}")
