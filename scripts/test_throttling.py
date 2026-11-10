#!/usr/bin/env python3
"""Kiểm thử throttling của API Gateway (TV5, issue #27 mục 2).

Route POST /api/shorten bị giới hạn 10 request/giây, burst 20; toàn API 100/giây, burst 200.
Phải gửi SONG SONG mới vượt được ngưỡng: vòng for tuần tự không đủ.

Hai lớp 429 cần phân biệt:
  - API Gateway:        body {"message":"Too Many Requests"}, KHÔNG có header Retry-After
  - rate limit Lambda: body {"error":{"code":"rate_limited",...}} kèm header Retry-After

Cách dùng:
    python scripts/test_throttling.py [--par 120] [--conc 60] [--keep-links]

Vì sao dùng Python thay vì xargs/curl:
    Mỗi request bằng xargs -P cần spawn một tiến trình bash + curl, độ trễ spawn làm các
    request tới lệch nhau vài trăm ms nên tốc độ thực tế không vượt quá 10 rps, API Gateway
    không kịp trả 429. Thread + Barrier trong Python đẩy đồng thời thật sự.
"""
import argparse
import concurrent.futures
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_CF_DOMAIN = "d3rsimgoxz85kx.cloudfront.net"
DEFAULT_OWNER = "22222222-2222-4222-8222-222222222222"


def send_one(cf_domain, owner, index, timeout=20):
    """Gửi 1 POST /api/shorten. Trả về dict kết quả."""
    url = f"https://{cf_domain}/api/shorten"
    body = json.dumps({"url": f"https://example.com/agw-test-{index}"}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Owner-Id": owner,
    })
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read(400).decode("utf-8", "replace")
            status = resp.status
            retry_after = resp.headers.get("Retry-After")
    except urllib.error.HTTPError as e:
        payload = e.read(400).decode("utf-8", "replace")
        status = e.code
        retry_after = e.headers.get("Retry-After")
    except Exception as e:  # noqa: BLE001
        return {"index": index, "status": 0, "retry_after": None,
                "payload": f"{type(e).__name__}: {e}", "elapsed": 0.0, "code": None}
    elapsed = time.perf_counter() - started
    code = None
    try:
        code = json.loads(payload).get("code")
    except (ValueError, AttributeError):
        pass
    return {"index": index, "status": status, "retry_after": retry_after,
            "payload": payload, "elapsed": elapsed, "code": code}


def classify(res):
    """'agw' | 'lambda' | 'other' | '' theo loại 429.

    Body của API Gateway: {"message":"Too Many Requests"}
    Body của rate limit Lambda: {"error":{"code":"rate_limited",...}} kèm header Retry-After
    """
    if res["status"] != 429:
        return ""
    body = res["payload"]
    if re.search(r'"message"\s*:\s*"Too Many Requests"', body):
        return "agw"
    if re.search(r'"code"\s*:\s*"rate_limited"', body):
        return "lambda"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cf-domain", default=DEFAULT_CF_DOMAIN)
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--par", type=int, default=120, help="tổng số request")
    ap.add_argument("--conc", type=int, default=60, help="số request chạy song song")
    ap.add_argument("--keep-links", action="store_true")
    args = ap.parse_args()

    # Chờ sang phút mới: bộ đếm rate limit theo IP của phút trước không ảnh hưởng.
    while int(time.strftime("%S", time.gmtime())) > 3:
        time.sleep(1)

    print(f"Bắt đầu lúc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} UTC")
    print(f"Gửi {args.par} request, {args.conc} chạy song song")
    print()

    results = []
    lock = threading.Lock()
    index = iter(range(1, args.par + 1))
    barrier = threading.Barrier(args.conc)

    def worker():
        barrier.wait()
        while True:
            with lock:
                try:
                    i = next(index)
                except StopIteration:
                    return
            res = send_one(args.cf_domain, args.owner, i)
            with lock:
                results.append(res)

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.conc) as pool:
        futures = [pool.submit(worker) for _ in range(args.conc)]
        for f in futures:
            f.result()
    elapsed = time.perf_counter() - started

    results.sort(key=lambda r: r["index"])

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"--- thời gian gửi: {elapsed:.2f}s "
          f"(tốc độ {args.par / elapsed:.1f} rps) ---")
    print("--- tổng hợp mã trả về ---")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  HTTP {status}")
    print()

    agw = sum(1 for r in results if classify(r) == "agw")
    lam = sum(1 for r in results if classify(r) == "lambda")
    other = sum(1 for r in results if classify(r) == "other")
    print("--- phân loại hai lớp 429 ---")
    print(f"  API Gateway 429 (body message/Too Many Requests, không có Retry-After): {agw}")
    print(f"  Lambda rate limit 429 (body error.code/rate_limited, có Retry-After):   {lam}")
    print(f"  429 khác:                                                                    {other}")
    print()

    ok = [r for r in results if r["status"] == 201]
    throttled = [r for r in results if r["status"] == 429]
    errors = [r for r in results if r["status"] not in (201, 429)]
    print(f"--- {min(12, len(ok))} request thành công đầu tiên ---")
    for r in ok[:12]:
        print(f"  {r['index']:3d}  HTTP {r['status']}  {r['elapsed']:.3f}s  {r['payload'][:150]}")
    print()
    print(f"--- {min(12, len(throttled))} request 429 đầu tiên ---")
    for r in throttled[:12]:
        print(f"  {r['index']:3d}  HTTP {r['status']}  {r['elapsed']:.3f}s  "
              f"Retry-After={r['retry_after'] or 'none'}  {r['payload'][:150]}")
    if errors:
        print()
        print(f"--- {min(6, len(errors))} request lỗi khác ---")
        for r in errors[:6]:
            print(f"  {r['index']:3d}  HTTP {r['status']}  {r['elapsed']:.3f}s  {r['payload'][:150]}")
    print()
    print(f"Kết thúc lúc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} UTC")

    if not args.keep_links:
        print()
        print(f"Xoá link test (chủ sở hữu {args.owner}):")
        for r in ok:
            if not r["code"]:
                continue
            req = urllib.request.Request(
                f"https://{args.cf_domain}/api/links/{r['code']}", method="DELETE",
                headers={"X-Owner-Id": args.owner})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    status = resp.status
            except urllib.error.HTTPError as e:
                status = e.code
            except Exception as e:  # noqa: BLE001
                status = f"{type(e).__name__}"
            print(f"  DELETE {r['code']} -> {status}")

    return 0 if (agw > 0 or lam > 0) else 1


if __name__ == "__main__":
    sys.exit(main())
