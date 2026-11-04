"""Kiểm thử tính năng quản lý blocklist và logic chặn domain (TV5)."""
import re
from urllib.parse import urlparse

import pytest
from botocore.exceptions import ClientError
from linkpulse import db, reputation
from linkpulse.config import settings


def normalize_domain(value: str) -> str:
    """Mô phỏng logic chuẩn hóa domain trong blocklist.sh và blocklist.ps1."""
    d = value.strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = d.split("/")[0]
    d = d.split(":")[0]
    return d.strip(".")


def test_normalize_domain_cases():
    """Kiểm tra logic chuẩn hóa domain của script TV5."""
    assert normalize_domain("https://Bad.example.COM/path?a=1") == "bad.example.com"
    assert normalize_domain("http://evil.org:8080/foo") == "evil.org"
    assert normalize_domain("PHISHING.net/") == "phishing.net"
    assert normalize_domain("   sub.danger.xyz... ") == "sub.danger.xyz"


def test_empty_blocklist_allows_all(tables):
    """Khi bảng blocklist rỗng, không URL nào bị xem là blocklisted."""
    assert not reputation.is_blocklisted("https://example.com/test")
    assert not reputation.is_blocklisted("https://google.com")
    assert not reputation.is_blocklisted("https://sub.domain.org/path")


def test_blocklist_blocks_exact_and_subdomains(tables):
    """Chặn domain cha thì toàn bộ subdomain cũng bị chặn."""
    table = db.resource().Table(settings().blocklist_table)
    table.put_item(Item={
        "domain": "malicious.com",
        "reason": "phishing",
        "added_at": "2026-11-04T00:00:00Z"
    })

    # Domain chính xác
    assert reputation.is_blocklisted("https://malicious.com")
    assert reputation.is_blocklisted("http://malicious.com/login")
    assert reputation.is_blocklisted("https://malicious.com:8443/steal")

    # Subdomain cấp 1, cấp 2
    assert reputation.is_blocklisted("https://sub.malicious.com/account")
    assert reputation.is_blocklisted("https://a.b.c.malicious.com/page")

    # Domain tương tự nhưng không phải con thì KHÔNG bị chặn
    assert not reputation.is_blocklisted("https://notmalicious.com")
    assert not reputation.is_blocklisted("https://malicious.com.evil.org")
    assert not reputation.is_blocklisted("https://safe-site.com")


def test_blocklist_removal_unblocks(tables):
    """Xóa domain khỏi bảng blocklist thì link được phép tạo lại."""
    table = db.resource().Table(settings().blocklist_table)
    table.put_item(Item={"domain": "temp-block.org", "reason": "testing"})
    assert reputation.is_blocklisted("https://temp-block.org/test")

    table.delete_item(Key={"domain": "temp-block.org"})
    assert not reputation.is_blocklisted("https://temp-block.org/test")


def test_activate_flagged_link(tables):
    """Mô phỏng thao tác 'activate <code>' của script blocklist: đưa link về active."""
    urls_table = db.urls()
    urls_table.put_item(Item={
        "short_code": "flag001",
        "long_url": "https://example.com/safe",
        "status": "suspicious",
        "created_at": "2026-11-04T00:00:00Z",
        "click_count": 5
    })

    # Trước khi gỡ: link có status = suspicious
    item = urls_table.get_item(Key={"short_code": "flag001"}).get("Item")
    assert item["status"] == "suspicious"

    # Thao tác update về active giống script blocklist
    urls_table.update_item(
        Key={"short_code": "flag001"},
        UpdateExpression="SET #st = :act REMOVE flag_reason",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":act": "active"}
    )

    updated = urls_table.get_item(Key={"short_code": "flag001"}).get("Item")
    assert updated["status"] == "active"
    assert "flag_reason" not in updated
