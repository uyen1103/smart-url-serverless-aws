"""Phân tích lưu lượng gần thời gian thực.

Ghi:  DynamoDB Stream của bảng `clicks` -> Lambda process_clicks -> cộng dồn (ADD nguyên tử) vào
      bảng `stats`, mỗi (scope, phút) một item. scope = "GLOBAL" hoặc "LINK#<code>".
      Mỗi item có: clicks, bot_clicks, các bộ đếm phẳng `c:<country>`, `d:<device>`, `b:<browser>`,
      `r:<referrer>`, (chỉ GLOBAL) `l:<code>`, và tập `ips` (ip_hash) để ước tính unique_visitors.
Đọc:  GET /api/stats[/code] truy vấn các item trong khoảng thời gian rồi cộng lại.

Giới hạn đã biết (ghi trong backend/README.md): stream là at-least-once nên khi retry có thể đếm dư;
một item không vượt 400 KB nên tập `ips`/`r:*` quá lớn trong 1 phút cần chuyển sang HyperLogLog hoặc
Kinesis + Flink khi lưu lượng rất cao.
"""
import time
from collections import Counter
from datetime import timedelta

from boto3.dynamodb.conditions import Key

from . import db
from .config import settings
from .models import parse_iso, to_iso

PREFIXES = {"c:": "countries", "d:": "devices", "b:": "browsers", "r:": "referrers"}
TOP_N = 10


def minute_of(ts_iso):
    return ts_iso[:16] + ":00Z"


def hour_of(minute_iso):
    return minute_iso[:13] + ":00:00Z"


def floor_minute(dt):
    return dt.replace(second=0, microsecond=0)


# ------------------------------------------------------------------------- ghi
def aggregate(events):
    """events: list dict (item của bảng clicks) -> {(scope, minute): {"counters": Counter, "ips": set}}"""
    groups = {}
    for e in events:
        minute = minute_of(e["timestamp"])
        code = e["short_code"]
        for scope in ("GLOBAL", f"LINK#{code}"):
            g = groups.setdefault((scope, minute), {"counters": Counter(), "ips": set()})
            c = g["counters"]
            c["clicks"] += 1
            if e.get("result") == "bot":
                c["bot_clicks"] += 1
            c["c:" + e.get("country", "XX")] += 1
            c["d:" + e.get("device", "other")] += 1
            c["b:" + e.get("browser", "Other")] += 1
            c["r:" + e.get("referrer", "direct")] += 1
            if scope == "GLOBAL":
                c["l:" + code] += 1
            if e.get("ip_hash"):
                g["ips"].add(e["ip_hash"])
    return groups


def apply_group(scope, minute, group):
    """Cộng dồn một nhóm vào bảng stats; trả về item sau cập nhật (để phát hiện bất thường)."""
    names, values, adds = {"#ttl": "expires_at"}, {":ttl": int(time.time()) + settings().stats_ttl_days * 86400}, []
    for i, (attr, n) in enumerate(group["counters"].items()):
        names[f"#a{i}"], values[f":v{i}"] = attr, n
        adds.append(f"#a{i} :v{i}")
    if group["ips"]:
        names["#ips"], values[":ips"] = "ips", set(group["ips"])
        adds.append("#ips :ips")
    resp = db.stats().update_item(
        Key={"scope": scope, "sk": f"M#{minute}"},
        UpdateExpression="ADD " + ", ".join(adds) + " SET #ttl = if_not_exists(#ttl, :ttl)",
        ExpressionAttributeNames=names, ExpressionAttributeValues=values, ReturnValues="ALL_NEW")
    return resp["Attributes"]


def update_recent(events, keep=20):
    """Giữ `keep` click mới nhất toàn hệ thống (cho khối 'click gần đây' của dashboard)."""
    key = {"scope": "META", "sk": "recent_clicks"}
    old = db.stats().get_item(Key=key).get("Item", {}).get("items", [])
    new = [{"timestamp": e["timestamp"], "code": e["short_code"], "country": e.get("country", "XX"),
            "device": e.get("device", "other"), "browser": e.get("browser", "Other"),
            "referrer": e.get("referrer", "direct"), "result": e.get("result", "valid")} for e in events]
    merged = sorted(old + new, key=lambda x: x["timestamp"], reverse=True)[:keep]
    db.stats().put_item(Item={**key, "items": merged})


# ------------------------------------------------------------------------- đọc
def _query_range(scope, frm, to):
    kwargs = dict(KeyConditionExpression=Key("scope").eq(scope) & Key("sk").between(
        f"M#{to_iso(floor_minute(frm))}", f"M#{to_iso(floor_minute(to))}"))
    while True:
        resp = db.stats().query(**kwargs)
        yield from resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def bucket_count(frm, to, granularity):
    step = 3600 if granularity == "hour" else 60
    return int((to - frm).total_seconds() // step) + 2


def get_stats(scope, frm, to, granularity, at):
    """Số liệu tổng hợp cho StatsResponse (chưa có `code`, `link`, `top_links`, `flagged_links`)."""
    timeline, total, bots, ips = {}, 0, 0, set()
    dims = {name: Counter() for name in PREFIXES.values()}
    links = Counter()
    for item in _query_range(scope, frm, to):
        minute = item["sk"][2:]
        key = hour_of(minute) if granularity == "hour" else minute
        clicks, bc = int(item.get("clicks", 0)), int(item.get("bot_clicks", 0))
        total, bots = total + clicks, bots + bc
        t = timeline.setdefault(key, [0, 0])
        t[0] += clicks
        t[1] += bc
        ips |= set(item.get("ips", ()))
        for attr, val in item.items():
            if attr[:2] in PREFIXES:
                dims[PREFIXES[attr[:2]]][attr[2:]] += int(val)
            elif attr.startswith("l:"):
                links[attr[2:]] += int(val)

    # Điền 0 cho các mốc không có click để biểu đồ liền mạch
    step = timedelta(hours=1) if granularity == "hour" else timedelta(minutes=1)
    cur = floor_minute(frm).replace(minute=0) if granularity == "hour" else floor_minute(frm)
    end = floor_minute(to)
    series = []
    while cur <= end:
        k = to_iso(cur)
        c, b = timeline.get(k, (0, 0))
        series.append({"bucket": k, "clicks": c, "bot_clicks": b})
        cur += step

    minutes = max(1.0, (to - frm).total_seconds() / 60)
    return {
        "updated_at": to_iso(at), "from": to_iso(frm), "to": to_iso(to), "granularity": granularity,
        "total_clicks": total, "bot_clicks": bots, "unique_visitors": len(ips),
        "avg_clicks_per_minute": round(total / minutes, 1),
        "timeline": series,
        "countries": _top(dims["countries"]), "devices": _top(dims["devices"]),
        "browsers": _top(dims["browsers"]), "referrers": _top(dims["referrers"]),
        "_links": links,
    }


def _top(counter, n=TOP_N):
    return [{"name": k, "clicks": v} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def top_links(counter, n=TOP_N):
    return [{"code": k, "clicks": v} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def recent_global():
    items = db.stats().get_item(Key={"scope": "META", "sk": "recent_clicks"}).get("Item", {}).get("items", [])
    return [dict(i) for i in items]


def recent_for_link(code, limit=20):
    resp = db.clicks().query(KeyConditionExpression=Key("short_code").eq(code), ScanIndexForward=False, Limit=limit)
    return [{"timestamp": i["timestamp"], "code": code, "country": i["country"], "device": i["device"],
             "browser": i["browser"], "referrer": i["referrer"], "result": i["result"]} for i in resp["Items"]]


def parse_range(frm_s, to_s, at):
    """Mặc định: 60 phút gần nhất. Ném ValueError nếu sai định dạng."""
    to = parse_iso(to_s) if to_s else at
    frm = parse_iso(frm_s) if frm_s else to - timedelta(minutes=60)
    return frm, to
