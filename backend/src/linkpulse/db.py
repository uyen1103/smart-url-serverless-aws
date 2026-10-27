import boto3
from functools import lru_cache

from .config import settings


@lru_cache(maxsize=1)
def resource():
    # Khởi tạo ngoài handler (cache theo process) để tái sử dụng giữa các lần gọi (warm start)
    return boto3.resource("dynamodb")


def reset_cache():
    resource.cache_clear()


def table(name):
    return resource().Table(name)


def urls():
    return table(settings().urls_table)


def clicks():
    return table(settings().clicks_table)


def stats():
    return table(settings().stats_table)


def rate_limits():
    return table(settings().rate_table)


def blocklist():
    return table(settings().blocklist_table)
