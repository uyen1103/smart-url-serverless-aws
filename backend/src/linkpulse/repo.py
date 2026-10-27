"""Truy cập bảng `urls` (và các bảng phụ trợ liên quan đến link)."""
import time

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from . import db
from .config import settings


def _cond_failed(e):
    return e.response["Error"]["Code"] == "ConditionalCheckFailedException"


def get_link(code):
    return db.urls().get_item(Key={"short_code": code}).get("Item")


def create_link(item):
    """Ghi link mới nếu mã chưa tồn tại (kể cả mã đã xóa). Trả về True/False."""
    try:
        db.urls().put_item(Item=item, ConditionExpression="attribute_not_exists(short_code)")
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


def find_existing(owner_id, long_url):
    """Link của cùng chủ sở hữu và cùng URL (ứng viên để trả lại link cũ). Dùng GSI owner-index."""
    resp = db.urls().query(
        IndexName="owner-index",
        KeyConditionExpression=Key("owner_id").eq(owner_id),
        FilterExpression=Attr("long_url").eq(long_url) & Attr("status").ne("deleted"),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def list_owner_links(owner_id):
    """Toàn bộ link chưa xóa của chủ sở hữu (mới nhất trước), tối đa MAX_LINKS_PER_OWNER."""
    cap = settings().max_links_per_owner
    items, kwargs = [], dict(
        IndexName="owner-index", KeyConditionExpression=Key("owner_id").eq(owner_id),
        FilterExpression=Attr("status").ne("deleted"), ScanIndexForward=False)
    while len(items) < cap:
        resp = db.urls().query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items[:cap]


def register_click(code, max_clicks):
    """Tăng click_count nguyên tử. Có max_clicks thì chỉ tăng khi chưa đạt giới hạn
    (tránh vượt giới hạn khi nhiều request đồng thời). False nếu đã đạt giới hạn."""
    cond = "attribute_exists(short_code)"
    values = {":one": 1}
    if max_clicks is not None:
        cond += " AND (attribute_not_exists(click_count) OR click_count < :max)"
        values[":max"] = int(max_clicks)
    try:
        db.urls().update_item(Key={"short_code": code}, UpdateExpression="ADD click_count :one",
                              ConditionExpression=cond, ExpressionAttributeValues=values)
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


def mark_deleted(code, owner_id):
    """Đánh dấu deleted (giữ lại để không cấp lại mã). Trả về 'ok' | 'not_found' | 'forbidden'."""
    try:
        db.urls().update_item(
            Key={"short_code": code}, UpdateExpression="SET #s = :d, deleted_at = :t",
            ConditionExpression="attribute_exists(short_code) AND owner_id = :o AND #s <> :d",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":d": "deleted", ":o": owner_id, ":t": int(time.time())})
        return "ok"
    except ClientError as e:
        if not _cond_failed(e):
            raise
    item = get_link(code)
    if item is None or item.get("status") == "deleted":
        return "not_found"
    return "forbidden"


def flag_link(code, reason, new_status="suspicious"):
    """Chuyển link đang `active` sang suspicious/blocked. True nếu vừa đổi trạng thái."""
    try:
        db.urls().update_item(
            Key={"short_code": code},
            UpdateExpression="SET #s = :n, flag_reason = :r, flagged_at = :t",
            ConditionExpression="attribute_exists(short_code) AND #s = :a",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":n": new_status, ":a": "active", ":r": reason, ":t": int(time.time())})
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


def purge_link_data(code):
    """Xóa click event và thống kê theo link (spec: xóa link thì dữ liệu thống kê bị xóa)."""
    for tbl, pk, pk_val, sk in ((db.clicks(), "short_code", code, "sk"),
                                (db.stats(), "scope", f"LINK#{code}", "sk")):
        kwargs = dict(KeyConditionExpression=Key(pk).eq(pk_val), ProjectionExpression="#pk, #sk",
                      ExpressionAttributeNames={"#pk": pk, "#sk": sk})  # `scope` là từ khóa dành riêng
        while True:
            resp = tbl.query(**kwargs)
            with tbl.batch_writer() as bw:
                for it in resp.get("Items", []):
                    bw.delete_item(Key={pk: it[pk], sk: it[sk]})
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


# --- Bộ đếm số link bị gắn cờ (hiển thị ở dashboard) ---------------------------------
def incr_flagged(n=1):
    db.stats().update_item(Key={"scope": "META", "sk": "flagged_links"},
                           UpdateExpression="ADD #v :n", ExpressionAttributeNames={"#v": "value"},
                           ExpressionAttributeValues={":n": n})


def get_flagged():
    item = db.stats().get_item(Key={"scope": "META", "sk": "flagged_links"}).get("Item")
    return int(item["value"]) if item else 0
