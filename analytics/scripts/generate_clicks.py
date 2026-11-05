"""Sinh click giả và tổng hợp chúng bằng logic analytics của LinkPulse."""

from __future__ import annotations

import argparse
import importlib.util
import io
import os
import random
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from linkpulse import analytics, db  # noqa: E402
from linkpulse.events import record_click  # noqa: E402

SHORT_CODES = ("aB3xK9z", "Lm4Np2Q", "rT8uV1w", "xY5zA6b", "cD7eF8g")
COUNTRIES = ("VN", "US", "JP", "SG", "XX")
REFERRERS = (
    None,
    "https://www.facebook.com/",
    "https://www.google.com/",
    "https://zalo.me/",
    "https://x.com/",
)
VALID_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0"
BOT_USER_AGENT = "Googlebot/2.1"


def parse_args(argv=None):
    """Đọc tham số và từ chối đầu vào nằm ngoài giới hạn."""
    parser = argparse.ArgumentParser(description="Sinh click giả cho LinkPulse bằng Moto.")
    parser.add_argument("--count", type=int, default=200, help="Số click (0–1000, mặc định 200).")
    parser.add_argument("--bot-ratio", type=float, default=0.3, help="Tỷ lệ bot trong khoảng 0–1 (mặc định 0.3).")
    parser.add_argument("--seed", type=int, help="Seed tùy chọn để tái tạo cùng dữ liệu.")
    args = parser.parse_args(argv)
    if not 0 <= args.count <= 1000:
        parser.error("--count phải nằm trong khoảng 0–1000")
    if not 0 <= args.bot_ratio <= 1:
        parser.error("--bot-ratio phải nằm trong khoảng 0–1")
    return args


def _load_test_table_factory():
    """Nạp cách dựng bảng dùng chung với tests/conftest.py."""
    conftest_path = REPO_ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("linkpulse_test_conftest", conftest_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Không thể nạp fixture bảng DynamoDB: {conftest_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure_mock_environment(table_factory):
    """Dùng thông tin xác thực giả và tên bảng riêng cho Moto."""
    os.environ.update(
        {
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing",
            "AWS_DEFAULT_REGION": "ap-southeast-1",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
    )
    for key, (variable, _) in table_factory.table_specs().items():
        os.environ[variable] = table_factory.table_name(key)


def generate_clicks(count, bot_ratio, seed):
    """Ghi click qua events.record_click và kiểm tra kết quả bằng analytics.aggregate."""
    from moto import mock_aws

    table_factory = _load_test_table_factory()
    _configure_mock_environment(table_factory)
    rng = random.Random(seed)
    db.reset_cache()
    try:
        with mock_aws():
            table_factory.create_tables()
            for _ in range(count):
                is_bot = rng.random() < bot_ratio
                record_click(
                    rng.choice(SHORT_CODES),
                    ua=BOT_USER_AGENT if is_bot else VALID_USER_AGENT,
                    referer=rng.choice(REFERRERS),
                    country=rng.choice(COUNTRIES),
                    ip_hash_value=f"{rng.getrandbits(64):016x}",
                )

            events = db.clicks().scan()["Items"]
            groups = analytics.aggregate(events)
            global_groups = [
                group for (scope, _), group in groups.items() if scope == "GLOBAL"
            ]
            total_clicks = sum(group["counters"]["clicks"] for group in global_groups)
            bot_clicks = sum(group["counters"]["bot_clicks"] for group in global_groups)
            referrers = Counter()
            for group in global_groups:
                for key, value in group["counters"].items():
                    if key.startswith("r:"):
                        referrers[key[2:]] += value

            if total_clicks != count:
                raise RuntimeError(
                    f"Tổng click từ aggregate() là {total_clicks}, mong đợi {count}"
                )
            return total_clicks, bot_clicks, referrers
    finally:
        db.reset_cache()


def main(argv=None):
    """Chạy mô phỏng trong Moto và in kết quả."""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args(argv)

    total_clicks, bot_clicks, referrers = generate_clicks(
        args.count, args.bot_ratio, args.seed
    )
    print(f"Tổng click: {total_clicks}")
    print(f"Số bot: {bot_clicks}")
    print("Top referrer:")
    if referrers:
        for name, count in sorted(referrers.items(), key=lambda item: (-item[1], item[0]))[:5]:
            print(f"  {name}: {count}")
    else:
        print("  (không có)")
    print(f"Kiểm tra aggregate(): khớp ({total_clicks} click)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
