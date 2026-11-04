"""docs/api_spec.yaml phải khớp backend: route trong template, alias dành riêng, mã lỗi, trang lỗi của redirect.

Không thay cho việc đọc spec bằng mắt, nhưng bắt được kiểu lệch hay gặp: thêm route/mã lỗi vào code mà quên cập nhật spec.
"""
import re
from urllib.parse import urlparse

import pytest
import yaml

from conftest import BACKEND_SRC, REPO_ROOT, load_template
from handlers import redirect
from linkpulse import validation

SPEC_TEXT = (REPO_ROOT / "docs" / "api_spec.yaml").read_text(encoding="utf-8")
SPEC = yaml.safe_load(SPEC_TEXT)
METHODS = {"get", "post", "put", "patch", "delete"}


def spec_routes():
    """{(METHOD, đường dẫn đầy đủ)}: ghép tiền tố của server (global `/api`, riêng `/{code}` ở gốc) với path."""
    default = urlparse(SPEC["servers"][0]["url"]).path.rstrip("/")
    routes = set()
    for path, item in SPEC["paths"].items():
        prefix = urlparse(item["servers"][0]["url"]).path.rstrip("/") if "servers" in item else default
        routes |= {(method.upper(), prefix + path) for method in item if method in METHODS}
    return routes


def template_routes():
    routes = set()
    for resource in load_template()["Resources"].values():
        if resource["Type"] == "AWS::Serverless::Function":
            for event in (resource["Properties"].get("Events") or {}).values():
                if event["Type"] == "HttpApi":
                    routes.add((event["Properties"]["Method"].upper(), event["Properties"]["Path"]))
    return routes


def test_spec_and_template_describe_the_same_routes():
    assert spec_routes() == template_routes()


def test_spec_lists_every_reserved_alias():
    alias_doc = SPEC["components"]["schemas"]["ShortenRequest"]["properties"]["alias"]["description"]
    missing = sorted(a for a in validation.RESERVED_ALIASES if f"`{a}`" not in alias_doc)
    assert not missing, f"Spec thiếu alias dành riêng: {missing}"
    assert f"{len(validation.RESERVED_ALIASES)} tên dành riêng" in alias_doc


def test_every_error_code_raised_by_the_backend_is_documented():
    used = set()
    for path in BACKEND_SRC.rglob("*.py"):
        used |= set(re.findall(r'err\(\s*\d+,\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert used, "regex không tìm thấy mã lỗi nào: sửa lại regex của test"
    missing = sorted(code for code in used if code not in SPEC_TEXT)
    assert not missing, f"Spec chưa nhắc tới mã lỗi: {missing}"


@pytest.mark.parametrize("error_code, page", sorted(redirect.PAGES.items()))
def test_error_pages_in_the_spec_match_the_redirect_handler(error_code, page):
    assert f"`{error_code}`" in SPEC_TEXT and page in SPEC_TEXT
    if error_code == "link_suspicious":
        assert "&code=" in SPEC_TEXT                       # trang cảnh báo cần mã để gọi lại ?confirm=1
