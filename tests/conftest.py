"""Fixture dùng chung cho toàn bộ test (quyết định #10 trong docs/QUYET_DINH_CHOT_TUAN_2.md).

Chủ sở hữu: TV1. TV3 (test_repo.py) và TV4 (test_analytics*.py) dùng lại, KHÔNG tự tạo fixture riêng.

    def test_vi_du(tables):            # 5 bảng DynamoDB (moto) đã tạo sẵn, rỗng
        tables["urls"].put_item(Item={"short_code": "abc1234", "long_url": "https://example.com"})

Fixture: aws_env (tự động, mọi test: biến môi trường giả + reset cache boto3/SSM của linkpulse) ·
mock_aws_env (bật moto) · dynamodb (moto + 5 bảng, trả về linkpulse.db.resource()) ·
tables (dict "urls"/"clicks"/"stats"/"rate_limits"/"blocklist" -> Table) ·
put_ssm_secret(name, value) (tạo SecureString trong SSM giả, để test origin/turnstile).

Bảng được dựng từ backend/template.yaml (nguồn sự thật của schema DB, quyết định #5): khóa chính, GSI,
TTL, Stream đọc thẳng từ template; tên bảng lấy từ các biến <X>_TABLE mà template gắn vào Lambda. BillingMode,
ProvisionedThroughput và PITR cố ý bỏ qua vì test không kiểm tra dung lượng. Test không bao giờ gọi AWS thật.
"""
import functools
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "Thiếu PyYAML (conftest đọc backend/template.yaml). Chạy: pip install -r backend/requirements-dev.txt"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SRC = REPO_ROOT / "backend" / "src"
TEMPLATE = REPO_ROOT / "backend" / "template.yaml"

# Lambda chạy với CodeUri: src/ nên `import linkpulse` / `import handlers.x` tính từ backend/src
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

TEST_REGION = "ap-southeast-1"          # chỉ để boto3 có region; moto không phụ thuộc region
TEST_IP_HASH_SALT = "test-ip-hash-salt-0123456789"   # >= 16 ký tự (template: IpHashSalt MinLength 16)
TABLE_NAME_PREFIX = "linkpulse-test-"   # khác tên mặc định của config.py để bắt lỗi quên đọc biến môi trường

# Biến môi trường đặt cố định cho mọi test (giá trị tắt các tính năng gọi ra ngoài)
TEST_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_EC2_METADATA_DISABLED": "true",
    "BASE_URL": "https://linkpulse.vn",
    "OWN_DOMAINS": "linkpulse.vn",
    "IP_HASH_SALT": TEST_IP_HASH_SALT,
    "TURNSTILE_SECRET_PARAM": "",       # để trống = tắt captcha
    "SAFE_BROWSING_KEY_PARAM": "",      # để trống = tắt
    "ORIGIN_VERIFY_SECRET_PARAM": "",   # để trống = không kiểm tra header X-Origin-Verify
    "ERROR_PAGE_MODE": "json",          # lỗi JSON đúng spec; test cần chế độ redirect thì tự monkeypatch
    "REDIRECT_RATE_LIMIT": "300",       # = mặc định của template
    "DNS_CHECK": "false",               # không phân giải DNS thật trong test
}

# Biến tinh chỉnh: xóa để code dùng mặc định của config.py (không để máy dev làm test chạy khác nhau).
UNSET_ENV = (
    "AWS_PROFILE", "CODE_LENGTH", "CODE_MAX_RETRIES", "MAX_LINKS_PER_OWNER", "IP_HASH_DAILY",
    "SHORTEN_RATE_LIMIT", "SHORTEN_RATE_WINDOW", "REDIRECT_RATE_WINDOW",
    "SPIKE_CLICKS_PER_MINUTE", "BOT_MIN_CLICKS", "BOT_RATIO", "STATS_TTL_DAYS", "CLICKS_TTL_DAYS",
)


# --------------------------------------------------------------------------- đọc template.yaml
class _CfnLoader(yaml.SafeLoader):
    """YAML loader hiểu các tag của CloudFormation (!Ref, !Sub, !If, !GetAtt...) bằng cách đổi thành dict."""


def _cfn_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {("Ref" if suffix == "Ref" else f"Fn::{suffix}"): value}


_CfnLoader.add_multi_constructor("!", _cfn_tag)


@functools.lru_cache(maxsize=1)
def load_template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return yaml.load(f, Loader=_CfnLoader)


@functools.lru_cache(maxsize=1)
def table_specs():
    """{"urls": ("URLS_TABLE", "UrlsTable"), ...} lấy từ các biến `<X>_TABLE: !Ref <Bảng>` của template.
    Bảng DynamoDB nào thiếu biến môi trường tương ứng thì báo lỗi rõ ràng."""
    template = load_template()
    resources = template["Resources"]
    env = template["Globals"]["Function"]["Environment"]["Variables"]
    specs = {}
    for var, value in env.items():
        if isinstance(value, dict) and set(value) == {"Ref"}:
            logical = value["Ref"]
            if resources.get(logical, {}).get("Type") == "AWS::DynamoDB::Table":
                specs[var.removesuffix("_TABLE").lower()] = (var, logical)
    declared = {n for n, r in resources.items() if r.get("Type") == "AWS::DynamoDB::Table"}
    missing = declared - {logical for _, logical in specs.values()}
    if missing:
        raise RuntimeError(
            f"Bảng {sorted(missing)} có trong template.yaml nhưng chưa có biến môi trường <TÊN>_TABLE "
            "trong Globals.Function.Environment.Variables, nên conftest không biết đặt tên bảng."
        )
    return specs


def table_name(key):
    return TABLE_NAME_PREFIX + key


def _create_kwargs(name, props):
    kwargs = {
        "TableName": name,
        "AttributeDefinitions": props["AttributeDefinitions"],
        "KeySchema": props["KeySchema"],
        "BillingMode": "PAY_PER_REQUEST",
    }
    gsis = props.get("GlobalSecondaryIndexes")
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = [
            {"IndexName": g["IndexName"], "KeySchema": g["KeySchema"], "Projection": g["Projection"]}
            for g in gsis
        ]
    stream = props.get("StreamSpecification")
    if stream:
        kwargs["StreamSpecification"] = {"StreamEnabled": True, "StreamViewType": stream["StreamViewType"]}
    return kwargs


def create_tables():
    """Tạo đủ các bảng của template trong moto (đang bật mock_aws). Trả về {khóa ngắn: tên bảng}."""
    client = boto3.client("dynamodb")
    resources = load_template()["Resources"]
    names = {}
    for key, (_, logical) in table_specs().items():
        props = resources[logical]["Properties"]
        name = table_name(key)
        client.create_table(**_create_kwargs(name, props))
        ttl = props.get("TimeToLiveSpecification")
        if ttl and ttl.get("Enabled", True) is not False:   # Enabled kiểu !Ref/!If thì coi là bật
            client.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": ttl["AttributeName"]},
            )
        names[key] = name
    return names


# --------------------------------------------------------------------------- fixture
def _reset_linkpulse_caches():
    """db.resource() và secrets_store.get_secret() cache theo process; phải xóa để mỗi test dùng moto mới."""
    from linkpulse import db, secrets_store

    db.reset_cache()
    secrets_store.reset_cache()


@pytest.fixture(autouse=True)
def aws_env(monkeypatch, tmp_path):
    """Môi trường giả cho MỌI test: không đọc cấu hình/khóa AWS thật của máy dev."""
    for var in UNSET_ENV:
        monkeypatch.delenv(var, raising=False)
    for var, value in TEST_ENV.items():
        monkeypatch.setenv(var, value)
    # Trỏ file cấu hình/khóa AWS sang đường dẫn không tồn tại để boto3 không đọc ~/.aws
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    for key, (var, _) in table_specs().items():
        monkeypatch.setenv(var, table_name(key))
    _reset_linkpulse_caches()
    yield
    _reset_linkpulse_caches()


@pytest.fixture
def mock_aws_env(aws_env):
    """Bật moto cho toàn bộ AWS trong test này (DynamoDB, SSM...). Trạng thái được xóa sau mỗi test."""
    with mock_aws():
        yield


@pytest.fixture
def dynamodb(mock_aws_env):
    """5 bảng DynamoDB (moto) đã tạo theo backend/template.yaml. Trả về boto3 resource của linkpulse.db."""
    from linkpulse import db

    create_tables()
    return db.resource()


@pytest.fixture
def tables(dynamodb):
    """dict khóa ngắn -> boto3 Table: urls, clicks, stats, rate_limits, blocklist."""
    return {key: dynamodb.Table(table_name(key)) for key in table_specs()}


@pytest.fixture
def put_ssm_secret(mock_aws_env):
    """put_ssm_secret(name, value): tạo SecureString trong SSM giả (dùng kèm monkeypatch.setenv
    "ORIGIN_VERIFY_SECRET_PARAM" hoặc "TURNSTILE_SECRET_PARAM")."""
    from linkpulse import secrets_store

    ssm = boto3.client("ssm")

    def _put(name, value):
        ssm.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True)
        secrets_store.reset_cache()

    return _put
