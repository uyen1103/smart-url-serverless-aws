"""Cấu hình đọc từ biến môi trường (khai báo trong template.yaml).

Đọc lại mỗi lần gọi `settings()` để test đổi được môi trường; chi phí không đáng kể.
"""
import os
from dataclasses import dataclass, field


def _s(name, default=""):
    return os.environ.get(name, default)


def _i(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


def _b(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    # Bảng DynamoDB
    urls_table: str = field(default_factory=lambda: _s("URLS_TABLE", "urls"))
    clicks_table: str = field(default_factory=lambda: _s("CLICKS_TABLE", "clicks"))
    stats_table: str = field(default_factory=lambda: _s("STATS_TABLE", "stats"))
    rate_table: str = field(default_factory=lambda: _s("RATE_LIMITS_TABLE", "rate_limits"))
    blocklist_table: str = field(default_factory=lambda: _s("BLOCKLIST_TABLE", "blocklist"))

    # Link
    base_url: str = field(default_factory=lambda: _s("BASE_URL", "https://linkpulse.vn").rstrip("/"))
    own_domains: frozenset = field(default_factory=lambda: frozenset(
        d.strip().lower() for d in _s("OWN_DOMAINS", "linkpulse.vn").split(",") if d.strip()))
    code_length: int = field(default_factory=lambda: _i("CODE_LENGTH", 7))
    max_retries: int = field(default_factory=lambda: _i("CODE_MAX_RETRIES", 5))
    max_links_per_owner: int = field(default_factory=lambda: _i("MAX_LINKS_PER_OWNER", 1000))

    # Chống lạm dụng
    dns_check: bool = field(default_factory=lambda: _b("DNS_CHECK", "true"))
    turnstile_secret_param: str = field(default_factory=lambda: _s("TURNSTILE_SECRET_PARAM"))
    safe_browsing_key_param: str = field(default_factory=lambda: _s("SAFE_BROWSING_KEY_PARAM"))
    origin_verify_secret_param: str = field(default_factory=lambda: _s("ORIGIN_VERIFY_SECRET_PARAM"))
    ip_hash_salt: str = field(default_factory=lambda: _s("IP_HASH_SALT"))
    ip_hash_daily: bool = field(default_factory=lambda: _b("IP_HASH_DAILY", "false"))
    shorten_rate_limit: int = field(default_factory=lambda: _i("SHORTEN_RATE_LIMIT", 10))
    shorten_rate_window: int = field(default_factory=lambda: _i("SHORTEN_RATE_WINDOW", 60))
    redirect_rate_limit: int = field(default_factory=lambda: _i("REDIRECT_RATE_LIMIT", 300))  # 0 = tắt
    redirect_rate_window: int = field(default_factory=lambda: _i("REDIRECT_RATE_WINDOW", 60))
    spike_clicks_per_minute: int = field(default_factory=lambda: _i("SPIKE_CLICKS_PER_MINUTE", 300))
    bot_min_clicks: int = field(default_factory=lambda: _i("BOT_MIN_CLICKS", 50))
    bot_ratio: float = field(default_factory=lambda: float(_s("BOT_RATIO", "0.8")))

    # Phân tích
    stats_ttl_days: int = field(default_factory=lambda: _i("STATS_TTL_DAYS", 8))
    clicks_ttl_days: int = field(default_factory=lambda: _i("CLICKS_TTL_DAYS", 30))
    max_buckets: int = 1440

    # Hiển thị lỗi redirect: "json" (đúng spec) hoặc "redirect" (302 sang error.html/warning.html
    # khi trình duyệt gửi Accept: text/html). Điểm cần chốt với TV2/TV5.
    error_page_mode: str = field(default_factory=lambda: _s("ERROR_PAGE_MODE", "json"))


def settings():
    return Settings()
