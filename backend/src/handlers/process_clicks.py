"""Lambda được DynamoDB Stream của bảng `clicks` kích hoạt: cộng dồn thống kê theo phút và
phát hiện lạm dụng (đột biến click, lưu lượng bot) gần thời gian thực."""
import logging

from boto3.dynamodb.types import TypeDeserializer

from linkpulse import abuse, analytics, repo

log = logging.getLogger()
log.setLevel(logging.INFO)
_deser = TypeDeserializer()


def _to_event(record):
    return {k: _deser.deserialize(v) for k, v in record["dynamodb"]["NewImage"].items()}


def process_events(events):
    groups = analytics.aggregate(events)
    flagged = set()
    for (scope, minute), group in groups.items():
        item = analytics.apply_group(scope, minute, group)
        if scope.startswith("LINK#"):
            code = scope[5:]
            reason = abuse.evaluate(item)
            if reason and code not in flagged and repo.flag_link(code, reason):
                flagged.add(code)
                repo.incr_flagged()
                log.warning("link flagged code=%s reason=%s", code, reason)
    analytics.update_recent(events)
    return {"events": len(events), "flagged": sorted(flagged)}


def lambda_handler(event, context):
    events = [_to_event(r) for r in event.get("Records", []) if r.get("eventName") == "INSERT"]
    if not events:
        return {"events": 0, "flagged": []}
    # Ném exception để Lambda retry/bisect/đẩy vào DLQ theo cấu hình event source mapping
    result = process_events(events)
    log.info("processed %s", result)
    return result
