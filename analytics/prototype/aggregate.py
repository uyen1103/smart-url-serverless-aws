"""Prototype analytics local: tạo, lưu, đọc lại và tổng hợp click event.

Thuộc khâu thử nghiệm trước pipeline DynamoDB Streams. Sinh dữ liệu giả thay cho
click từ redirect Lambda; nhận số lượng event và đường dẫn JSONL tùy chọn, trả
về kết quả tổng hợp theo phút, top link và thiết bị. Không gọi AWS.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SHORT_CODES = ("aB3xK9z", "Lm4Np2Q", "rT8uV1w", "xY5zA6b", "cD7eF8g", "hJ9kL0m")
COUNTRIES = ("VN", "US", "JP", "SG", "XX")
DEVICES = ("desktop", "mobile", "tablet", "bot", "other")
BROWSERS = ("Chrome", "Safari", "Firefox", "Edge", "Other")
REFERRERS = ("direct", "facebook.com", "google.com", "zalo.me", "x.com")


def generate_click_events(
    count: int = 1000,
    seed: int = 42,
    start_time: datetime | None = None,
) -> list[dict[str, str]]:
    """Tạo event click giả có schema nhất quán.

    Args:
        count: Số event cần tạo, không được âm.
        seed: Seed để lần chạy sau tái tạo được cùng bộ dữ liệu.
        start_time: Mốc UTC kết thúc; mặc định là thời điểm hiện tại.

    Returns:
        Danh sách event có đủ trường theo docs/click_event_schema.json.

    Vì sao cần: cho phép kiểm tra logic analytics trước khi API redirect và AWS
    được tích hợp. ip_hash giả là chuỗi hex ngẫu nhiên, không bắt nguồn từ IP.
    """
    if count < 0:
        raise ValueError("count không được âm")

    rng = random.Random(seed)
    end_time = start_time or datetime.now(timezone.utc)
    if end_time.tzinfo is None:
        raise ValueError("start_time phải có timezone")
    end_time = end_time.astimezone(timezone.utc)
    first_minute = end_time.replace(second=0, microsecond=0) - timedelta(minutes=9)

    events: list[dict[str, str]] = []
    for _ in range(count):
        event_time = first_minute + timedelta(
            seconds=rng.randrange(10 * 60),
        )
        events.append(
            {
                "short_code": rng.choice(SHORT_CODES),
                "timestamp": event_time.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "ip_hash": rng.randbytes(32).hex(),
                "country": rng.choice(COUNTRIES),
                "device": rng.choice(DEVICES),
                "browser": rng.choice(BROWSERS),
                "referrer": rng.choice(REFERRERS),
                "user_agent": f"Prototype/{rng.choice(BROWSERS)} on {rng.choice(DEVICES)}",
            }
        )

    return events


def write_events(events: list[dict[str, str]], output_path: Path) -> None:
    """Ghi mỗi click event thành một dòng JSON trong file JSONL.

    Args:
        events: Danh sách event cần lưu.
        output_path: Đường dẫn file JSONL; thư mục cha được tạo nếu cần.

    Returns:
        Không trả về giá trị.

    Vì sao cần: JSONL mô phỏng dữ liệu từng dòng để prototype có thể đọc lại
    như một nguồn dữ liệu độc lập với bước sinh event.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as event_file:
        for event in events:
            event_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(input_path: Path) -> list[dict[str, Any]]:
    """Đọc lại JSONL và báo lỗi rõ nếu file có dòng không phải JSON hợp lệ.

    Args:
        input_path: Đường dẫn file JSONL.

    Returns:
        Danh sách event đã giải mã từ JSON.

    Vì sao cần: tách bước đọc khỏi bước sinh để kiểm tra luồng dữ liệu lưu-trữ
    rồi-tổng-hợp giống cách consumer nhận record từ pipeline.
    """
    events: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as event_file:
        for line_number, line in enumerate(event_file, start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError(f"Dòng {line_number} phải là một JSON object")
            events.append(event)
    return events


def aggregate_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Tổng hợp click/phút, năm link nhiều click nhất và số click theo thiết bị.

    Args:
        events: Danh sách click event đã đọc.

    Returns:
        Mapping có tổng số click, series theo phút, top 5 link và thiết bị.

    Vì sao cần: minh họa các phép tổng hợp cốt lõi trước khi ghi số liệu vào
    stats_agg và trả dữ liệu qua stats_api.
    """
    clicks_by_minute: Counter[str] = Counter()
    clicks_by_link: Counter[str] = Counter()
    clicks_by_device: Counter[str] = Counter()

    for event in events:
        timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        minute = timestamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
        minute_label = minute.isoformat(timespec="minutes").replace("+00:00", "Z")
        clicks_by_minute[minute_label] += 1
        clicks_by_link[event["short_code"]] += 1
        clicks_by_device[event["device"]] += 1

    return {
        "total_clicks": len(events),
        "clicks_per_minute": [
            {"minute": minute, "clicks": clicks_by_minute[minute]}
            for minute in sorted(clicks_by_minute)
        ],
        "top_links": [
            {"short_code": code, "clicks": count}
            for code, count in sorted(
                clicks_by_link.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ],
        "devices": [
            {"name": device, "clicks": clicks_by_device[device]}
            for device in sorted(clicks_by_device)
        ],
    }


def main() -> None:
    """Chạy prototype từ terminal và in kết quả tổng hợp dạng JSON."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Sinh và tổng hợp click event giả ở local."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Số event giả cần sinh (mặc định: 1000).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="File JSONL để lưu event; bỏ trống thì dùng file tạm và tự dọn.",
    )
    args = parser.parse_args()
    if args.count < 0:
        parser.error("--count không được âm")

    events = generate_click_events(count=args.count)
    if args.output:
        write_events(events, args.output)
        result = aggregate_events(read_events(args.output))
        print(f"Đã lưu và đọc lại {len(events)} event: {args.output}")
    else:
        with tempfile.TemporaryDirectory(prefix="analytics-prototype-") as folder:
            output_path = Path(folder) / "events.jsonl"
            write_events(events, output_path)
            result = aggregate_events(read_events(output_path))
        print(f"Đã sinh, lưu tạm, đọc lại và tổng hợp {len(events)} event.")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
