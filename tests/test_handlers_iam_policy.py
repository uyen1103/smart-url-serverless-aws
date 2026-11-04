"""Quyền IAM của từng Lambda trong backend/template.yaml phải đủ cho các thao tác DynamoDB mà handler thật thực hiện
(và không dùng ký tự đại diện). moto không kiểm tra IAM, nên thiếu quyền chỉ lộ ra khi deploy (AccessDenied).

Cách làm: chạy handler thật trên moto, ghi lại (bảng, thao tác, có dùng index) qua hook của botocore, rồi đối chiếu với
các statement trong template. Thêm lời gọi DynamoDB mới vào code mà chưa cấp quyền thì test này đỏ và nói rõ thiếu quyền gì.
"""
import json
from contextlib import contextmanager

import pytest

from conftest import TABLE_NAME_PREFIX, load_template, table_specs
from handlers import health, links, process_clicks, redirect, shorten, stats
from helpers import OWNER_A, add_link, make_event
from linkpulse import db, repo

URL = "https://example.com/bai-viet"
LOGICAL_TO_KEY = {logical: key for key, (_, logical) in table_specs().items()}


# ------------------------------------------------------------------ đọc quyền từ template
def _table_of(resource):
    """!GetAtt <Bảng>.Arn  ->  (khóa bảng, False);  !Sub '${<Bảng>.Arn}/index/*'  ->  (khóa bảng, True)."""
    if "Fn::GetAtt" in resource:
        return LOGICAL_TO_KEY[resource["Fn::GetAtt"].split(".")[0]], False
    sub = resource["Fn::Sub"]
    assert sub.endswith("/index/*"), f"Resource không nhận dạng được: {resource}"
    return LOGICAL_TO_KEY[sub[2:].split(".")[0]], True


def allowed(function_logical_id):
    """{(khóa bảng, thao tác, có dùng index)} mà Lambda được phép, đọc từ các statement tường minh trong template."""
    policies = load_template()["Resources"][function_logical_id]["Properties"].get("Policies", [])
    result = set()
    for policy in policies:
        if any(name.startswith("DynamoDB") for name in policy) and "Statement" not in policy:
            pytest.fail(f"{function_logical_id} dùng mẫu SAM {list(policy)}: hãy viết statement tường minh (xem các hàm khác)")
        for statement in policy.get("Statement", []) if "Statement" in policy else []:
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
            if not all(a.startswith("dynamodb:") for a in actions):
                continue                                                # SSM, SQS... không thuộc phạm vi test này
            assert statement["Effect"] == "Allow" and not any("*" in a for a in actions), statement
            assert "*" not in resources, f"{function_logical_id}: Resource '*' cho DynamoDB"
            result |= {(key, action.split(":")[1], is_index) for action in actions
                       for key, is_index in map(_table_of, resources)}
    return result


# ------------------------------------------------------------------ ghi lại thao tác DynamoDB thật
@pytest.fixture
def record(tables):
    """record() là context manager: chỉ ghi các lời gọi DynamoDB xảy ra bên trong (không tính bước gieo dữ liệu của test)."""
    state, used = {"on": False}, set()

    def hook(model, params, **_kwargs):
        if state["on"]:
            body = json.loads(params["body"])
            for name in [body["TableName"]] if "TableName" in body else list(body.get("RequestItems", {})):
                used.add((name[len(TABLE_NAME_PREFIX):], model.name, bool(body.get("IndexName"))))

    for resource in (db.resource(), db.best_effort_resource()):          # rate limit/đếm click/ghi click dùng client riêng
        resource.meta.client.meta.events.register("before-call.dynamodb", hook)

    @contextmanager
    def _record():
        used.clear()
        state["on"] = True
        try:
            yield used
        finally:
            state["on"] = False
    return _record


def call(module, route, **kw):
    resp = module.lambda_handler(make_event(route, **kw), None)
    assert resp["statusCode"] < 500, resp
    return resp


def run_shorten(tables, record, monkeypatch):
    with record() as used:
        call(shorten, "POST /api/shorten", body={"url": URL}, headers={"x-owner-id": OWNER_A})
        call(shorten, "POST /api/shorten", body={"url": URL}, headers={"x-owner-id": OWNER_A})           # trả link cũ
        call(shorten, "POST /api/shorten", body={"url": "https://shop.tk/x"})                              # gắn cờ + đếm flagged
    return used


def run_redirect(tables, record, monkeypatch):
    add_link("abc1234", long_url=URL)
    with record() as used:
        call(redirect, "GET /{code}", path_params={"code": "abc1234"})
        call(redirect, "GET /{code}", path_params={"code": "khongco1"})
    return used


def run_links(tables, record, monkeypatch):
    add_link("abc1234", owner_id=OWNER_A)
    tables["clicks"].put_item(Item={"short_code": "abc1234", "sk": "2026-10-01T00:00:00Z#1"})
    tables["stats"].put_item(Item={"scope": "LINK#abc1234", "sk": "M#2026-10-01T00:00:00Z", "clicks": 1})
    with record() as used:
        call(links, "GET /api/links", headers={"x-owner-id": OWNER_A})
        call(links, "DELETE /api/links/{code}", path_params={"code": "abc1234"}, headers={"x-owner-id": OWNER_A})
        call(links, "DELETE /api/links/{code}", path_params={"code": "abc1234"}, headers={"x-owner-id": OWNER_A})
    return used


def run_stats(tables, record, monkeypatch):
    add_link("abc1234")
    query = {"from": "2026-10-01T08:00:00Z", "to": "2026-10-01T08:10:00Z"}
    with record() as used:
        call(stats, "GET /api/stats", query=query)
        call(stats, "GET /api/stats/{code}", path_params={"code": "abc1234"}, query=query)
    return used


def run_health(tables, record, monkeypatch):
    with record() as used:
        call(health, "GET /api/health")
    return used


def run_process_clicks(tables, record, monkeypatch):
    monkeypatch.setenv("SPIKE_CLICKS_PER_MINUTE", "2")                    # 3 click trong 1 phút => gắn cờ link
    add_link("abc1234")
    events = [{"short_code": "abc1234", "timestamp": f"2026-10-01T08:00:{s:02d}Z", "country": "VN", "device": "mobile",
               "browser": "Chrome", "referrer": "direct", "ip_hash": f"h{s}", "result": "valid"} for s in (1, 2, 3)]
    with record() as used:
        result = process_clicks.process_events(events)
    assert result["flagged"] == ["abc1234"]
    return used


SCENARIOS = {"ShortenFunction": run_shorten, "RedirectFunction": run_redirect, "LinksFunction": run_links,
             "StatsFunction": run_stats, "HealthFunction": run_health, "ProcessClicksFunction": run_process_clicks}


@pytest.mark.parametrize("function", sorted(SCENARIOS))
def test_policy_covers_every_dynamodb_call_the_handler_makes(function, tables, record, monkeypatch):
    used = SCENARIOS[function](tables, record, monkeypatch)
    missing = sorted(used - allowed(function))
    assert not missing, (f"{function} cần thêm quyền trong template.yaml: " + ", ".join(
        f"dynamodb:{op} trên {key}{' (index)' if idx else ''}" for key, op, idx in missing))


@pytest.mark.parametrize("function", ["RedirectFunction", "StatsFunction", "HealthFunction"])
def test_read_mostly_functions_cannot_delete_or_scan(function):
    banned = {"DeleteItem", "Scan", "BatchWriteItem"}
    assert not {op for _, op, _ in allowed(function)} & banned


def test_only_links_may_delete_data_and_nobody_may_scan():
    deleters = {f for f in SCENARIOS if {op for _, op, _ in allowed(f)} & {"DeleteItem", "BatchWriteItem"}}
    assert deleters == {"LinksFunction"}
    assert not any(op == "Scan" for f in SCENARIOS for _, op, _ in allowed(f))
    assert repo.purge_link_data                                           # hàm này là lý do duy nhất để LinksFunction xóa
