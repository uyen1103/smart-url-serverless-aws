"""Đọc bí mật từ SSM Parameter Store (SecureString), cache theo process.
Không để bí mật trong biến môi trường (xem docs/backend_research.md mục 1.5)."""
import boto3
from functools import lru_cache


@lru_cache(maxsize=8)
def get_secret(param_name):
    if not param_name:
        return ""
    ssm = boto3.client("ssm")
    return ssm.get_parameter(Name=param_name, WithDecryption=True)["Parameter"]["Value"]


def reset_cache():
    get_secret.cache_clear()
