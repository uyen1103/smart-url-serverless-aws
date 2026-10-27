"""Phát hiện lạm dụng gần thời gian thực từ số liệu từng phút của một link."""
from .config import settings


def evaluate(minute_item):
    """minute_item: item stats (scope LINK#code) của phút vừa cập nhật. Trả về lý do hoặc None."""
    s = settings()
    clicks = int(minute_item.get("clicks", 0))
    bots = int(minute_item.get("bot_clicks", 0))
    if clicks >= s.spike_clicks_per_minute:
        return "click_spike"
    if clicks >= s.bot_min_clicks and bots / clicks >= s.bot_ratio:
        return "bot_traffic"
    return None
