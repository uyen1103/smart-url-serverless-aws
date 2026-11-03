import logging
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import settings

log = logging.getLogger()

# Mã lỗi DynamoDB khi bị giới hạn dung lượng (bảng provisioned hết WCU/RCU hoặc vượt hạn mức tài khoản)
THROTTLE_CODES = frozenset({"ProvisionedThroughputExceededException", "ThrottlingException",
                            "RequestLimitExceeded"})
# Thao tác "có cũng được, không có cũng không sao" (rate limit, đếm click, ghi click event) chỉ thử lại 2 lần.
# Mặc định của botocore với DynamoDB là 10 lần, chờ cộng dồn ~25 giây, trong khi Lambda chỉ có timeout 5 giây:
# request sẽ hết giờ trước khi kịp "bỏ qua lỗi". Với 2 lần thử lại, tổng thời gian chờ chỉ ~0,15 giây.
BEST_EFFORT_RETRIES = 2


@lru_cache(maxsize=1)
def resource():
    # Khởi tạo ngoài handler (cache theo process) để tái sử dụng giữa các lần gọi (warm start)
    return boto3.resource("dynamodb")


@lru_cache(maxsize=1)
def best_effort_resource():
    return boto3.resource("dynamodb", config=Config(retries={"max_attempts": BEST_EFFORT_RETRIES, "mode": "legacy"}))


def reset_cache():
    resource.cache_clear()
    best_effort_resource.cache_clear()


def table(name, best_effort=False):
    return (best_effort_resource() if best_effort else resource()).Table(name)


def throttled(exc, op):
    """True nếu `exc` là lỗi throttle của DynamoDB (đã ghi cảnh báo): nơi gọi bỏ qua lỗi và cho request đi tiếp.
    Chỉ dùng cho thao tác không bắt buộc. Cảnh báo có từ khóa DYNAMODB_THROTTLED để lọc/đặt alarm trên CloudWatch."""
    if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in THROTTLE_CODES:
        log.warning("DYNAMODB_THROTTLED op=%s: bỏ qua lỗi, request vẫn được xử lý", op)
        return True
    return False


def urls(best_effort=False):
    return table(settings().urls_table, best_effort)


def clicks(best_effort=False):
    return table(settings().clicks_table, best_effort)


def stats():
    return table(settings().stats_table)


def rate_limits(best_effort=False):
    return table(settings().rate_table, best_effort)


def blocklist():
    return table(settings().blocklist_table)
