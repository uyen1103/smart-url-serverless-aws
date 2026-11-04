#!/usr/bin/env python3
"""Đo độ trễ p50/p95/p99 của API LinkPulse đã deploy, từ máy của bạn (chỉ dùng thư viện chuẩn).

    python scripts/measure_latency.py --base-url https://<domain>.cloudfront.net --code <mã link thử>

Mặc định đo GET /api/health và GET /api/stats; thêm --code để đo cả redirect GET /<code> (không đi theo 302, nên chỉ đo
Lambda chứ không đo trang đích). Mỗi lượt redirect ghi 1 click vào link thử, hãy dùng link tạo riêng để đo.
Yêu cầu đầu tiên được báo riêng (có thể dính cold start), thống kê p50/p95/p99 tính trên các yêu cầu còn lại.

Giới hạn an toàn (quyết định tuần 2 mục 14: không chạy tải lớn lên AWS): tối đa 300 yêu cầu mỗi đích, tuần tự, mặc định
cách nhau 250 ms (dưới giới hạn rate limit 300 lượt/phút của redirect). Muốn đo tải lớn thì chạy trên moto hoặc DynamoDB Local.

Thời gian chạy bên trong Lambda (không gồm mạng) xem bằng CloudWatch Logs Insights, chọn log group của hàm:
    filter @type = "REPORT" | stats count(*) as n, pct(@duration, 50) as p50, pct(@duration, 95) as p95,
        max(@duration) as max, count(@initDuration) as cold_starts, avg(@initDuration) as avg_cold_ms
"""
import argparse
import collections
import http.client
import json
import math
import sys
import time
from urllib.parse import urlsplit

MAX_REQUESTS = 300


def percentile(sorted_values, p):
    """Nearest-rank: giá trị nhỏ nhất mà ít nhất p% mẫu nhỏ hơn hoặc bằng nó."""
    if not sorted_values:
        raise ValueError("không có mẫu")
    return sorted_values[max(1, math.ceil(p / 100 * len(sorted_values))) - 1]


def summarize(samples_ms):
    ordered = sorted(samples_ms)
    return {"n": len(ordered), "min": ordered[0], "p50": percentile(ordered, 50), "p95": percentile(ordered, 95),
            "p99": percentile(ordered, 99), "max": ordered[-1], "mean": sum(ordered) / len(ordered)}


def measure(base_url, path, requests, delay_s, headers, timeout=10):
    parts = urlsplit(base_url)
    connection = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = connection(parts.netloc, timeout=timeout)
    samples, statuses, errors = [], collections.Counter(), 0
    for i in range(requests):
        started = time.perf_counter()
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            response.read()
            status = response.status
        except (OSError, http.client.HTTPException):
            status = None
            conn.close()
        elapsed_ms = (time.perf_counter() - started) * 1000
        statuses[str(status)] += 1
        if status is None or status >= 400:
            errors += 1
        else:
            samples.append(elapsed_ms)
        if delay_s and i < requests - 1:
            time.sleep(delay_s)
    conn.close()
    return {"path": path, "requests": requests, "errors": errors, "statuses": dict(statuses),
            "first_ms": samples[0] if samples else None,
            "warm": summarize(samples[1:]) if len(samples) > 1 else None}


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Đo p50/p95/p99 của API LinkPulse", epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="ví dụ https://<domain>.cloudfront.net (không có / cuối)")
    parser.add_argument("--code", help="mã link thử để đo redirect GET /<code>")
    parser.add_argument("--requests", type=int, default=50, help=f"số yêu cầu mỗi đích (1 đến {MAX_REQUESTS}, mặc định 50)")
    parser.add_argument("--delay-ms", type=int, default=250, help="nghỉ giữa hai yêu cầu (mặc định 250)")
    parser.add_argument("--header", action="append", default=[], metavar="'Tên: giá trị'",
                        help="header thêm vào (ví dụ X-Origin-Verify khi gọi thẳng API Gateway); có thể lặp lại")
    parser.add_argument("--json", help="ghi kết quả ra file JSON")
    args = parser.parse_args(argv)
    if not 1 <= args.requests <= MAX_REQUESTS:
        parser.error(f"--requests phải từ 1 đến {MAX_REQUESTS} (không chạy tải lớn lên AWS, xem mục 14 của quyết định tuần 2)")
    if args.delay_ms < 0:
        parser.error("--delay-ms không được âm")
    return args


def main(argv=None):
    args = parse_args(argv)
    headers = {}
    for line in args.header:
        name, _, value = line.partition(":")
        headers[name.strip()] = value.strip()
    targets = ["/api/health", "/api/stats"] + ([f"/{args.code}"] if args.code else [])
    results = []
    print(f"{'đích':<22}{'ok/tổng':>9}{'đầu tiên':>10}{'min':>8}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}   (ms)")
    for path in targets:
        result = measure(args.base_url.rstrip("/"), path, args.requests, args.delay_ms / 1000, headers)
        results.append(result)
        warm, first = result["warm"], result["first_ms"]
        cells = [f"{warm[k]:.0f}" for k in ("min", "p50", "p95", "p99", "max")] if warm else ["-"] * 5
        print(f"{path:<22}{result['requests'] - result['errors']:>4}/{result['requests']:<4}"
              f"{(f'{first:.0f}' if first is not None else '-'):>10}" + "".join(f"{c:>8}" for c in cells))
        if result["errors"]:
            print(f"  ! {result['errors']} lỗi, mã trả về: {result['statuses']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"base_url": args.base_url, "results": results}, f, ensure_ascii=False, indent=2)
    return 1 if any(r["errors"] == r["requests"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
