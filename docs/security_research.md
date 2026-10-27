# Security Research — Chống lạm dụng cho Smart URL Serverless (LinkPulse)

> **Module:** TV5 — Security, Anti-abuse & DevOps · **Issue:** Week 1 / #5
> **Phạm vi:** `CloudFront + WAF (us-east-1) → API Gateway HTTP API → Lambda Python 3.11 → DynamoDB`
> (`urls`, `clicks`, `stats_agg`, `rate_limits`, `blocklist`), redirect `302 + no-store`,
> analytics `DynamoDB Streams (NEW_IMAGE, INSERT-only) → click_processor`.
> **Đọc cùng:** `docs/threat_model.md` (T-01…T-15), `docs/api_spec.yaml`, `docs/backend_research.md`, `docs/architecture.md`.
> **Ngày:** 27/10/2026 · **Trạng thái:** v1.0 — chốt phương án Week 2, số liệu giá/quota đối chiếu tháng 10/2026 (kiểm tra lại trước khi thanh toán).

---

## 0. Tóm tắt quyết định (TL;DR cho nhóm)

| Lớp phòng thủ | Chốt v1 | Vì sao |
|---|---|---|
| Edge | **CloudFront + AWS WAF** (Web ACL ở **`us-east-1`**, scope `CLOUDFRONT`) | HTTP API không gắn WAF trực tiếp và không có usage plan (TV1 §2) → chặn ở edge rẻ và sớm nhất; WAF CloudFront bắt buộc ở `us-east-1` |
| WAF rules | **Rate-based** `/api/shorten` + `/{code}` + **Managed: Common Rule Set, Known Bad Inputs, Amazon IP Reputation** (Count trước, Block sau) | Chặn flood/bot/automation với false-positive thấp nhất; IP Reputation miễn phí sức mạnh cao |
| API Gateway | **HTTP API throttling** (stage/route) + **token-bucket `rate_limits` trong DynamoDB** ở Lambda | HTTP API không có API key/usage plan → giới hạn theo IP ở Lambda + hiển thị `429 + Retry-After` đúng `api_spec.yaml` |
| URL độc hại | **Google Safe Browsing v4 + URLhaus**, kiểm tra **bất đồng bộ (async) + cache verdict**, không chặn luồng redirect nóng | GSB chính xác/phủ rộng, URLhaus miễn phí không key cho lookup; async để redirect luôn < 300 ms |
| Bot tạo link | **Cloudflare Turnstile** bắt buộc ở `POST /shorten` (verify server-side, one-time token) | Nhẹ, riêng tư, miễn phí không giới hạn; chặn automation mà không làm khó người thật |
| Validate | **Whitelist `http/https` + max 2048 ký tự + chặn `data:`/`javascript:`/`ftp:`/`file:` + chặn IP nội bộ 2 lớp (literal + DNS resolve-all)** | Chặn SSRF/open-redirect/XSS ngay ở Lambda, tương đương `backend/prototype.py` + bổ sung DNS |
| Vận hành | Budget **$5/tháng** + billing alarm + CloudWatch alarms + kill-switch | Chống bill-shock/economic-DoS (T-09) |

---

## 1. AWS WAF

### 1.1. WAF gắn ở đâu? Vì sao là CloudFront + `us-east-1`?

Hệ thống dùng **API Gateway HTTP API** (rẻ, trễ thấp — TV1 §2). Hệ quả kiến trúc:

- HTTP API **không hỗ trợ** gắn AWS WAF trực tiếp (chỉ REST API, AppSync, Cognito, ALB… hỗ trợ trực tiếp).
- HTTP API **không có** API key / usage plan (chỉ REST API có).
- → **Mọi chính sách WAF phải đặt ở CloudFront** (distribution phía trước, trỏ behavior `/api/*` → API Gateway, `/{code}` → redirect backend), scope **`CLOUDFRONT`**.

> **Quy tắc vùng (bắt buộc):** Web ACL cho CloudFront **luôn tạo ở Region `us-east-1` (N. Virginia)** bất kể distribution và origin ở đâu (`ap-southeast-1/2`). Tạo ở region khác sẽ không attach được vào distribution. CloudFormation/SAM deploy Web ACL với `Scope: CLOUDFRONT` phải chạy ở `us-east-1`; các tài nguyên còn lại ở `ap-southeast-1` (Singapore — region nhóm đã thống nhất, lưu ý tài khoản Free-plan kiểu mới bị cố định region theo project, xem TV1 §6.2).

Kiến trúc gắn kết:

```
Client → CloudFront (cache behavior: /api/* → HTTP API origin; /{code} → HTTP API origin, no-cache)
             │  ▲ WAF Web ACL (us-east-1, scope CLOUDFRONT) đánh giá TRƯỚC khi vào origin
             │  ├─ Rate-based rules (đếm theo IP + URI path)
             │  ├─ Managed: AWSManagedRulesCommonRuleSet, KnownBadInputs, IPReputationList
             │  └─ Custom: geo/blocklist, size-constraint (body > 16 KB → chặn /shorten)
         API Gateway HTTP API → Lambda → DynamoDB
```

### 1.2. Thiết kế Rate-based Rule (ngưỡng/5 phút/IP)

Rate-based rule đếm request trong **cửa sổ trượt 5 phút** cho mỗi IP (có thể thu hẹp bằng scope-down statement theo URI path). Vượt ngưỡng → action Block (khuyến nghị block tạm thời, tự hết khi rate giảm; hoặc CAPTCHA/Challenge nếu dùng bản có Bot Control).

**Ngưỡng đề xuất v1** (hiệu chỉnh sau 1–2 tuần log thực tế; số dưới cho đồ án demo, không phải production banking):

| Rule | Scope-down | Limit / 5 phút / IP | Action | Lý do |
|---|---|---|---|---|
| `RL-Shorten` | URI path bắt đầu `/api/shorten` (POST) | **100** | Block | Người thật tạo ≤ vài link/phút; 100/5' vẫn thoáng, bot tạo ồ ạt (T-02) bị cắt ngay. UI hiển thị giới hạn 10 link/phút/IP ở tầng app |
| `RL-Redirect` | URI path khớp single-segment `/{code}` (GET, loại trừ `/api/*`, static) | **1.000** | Block | Redirect là traffic lớn nhất; 1000/5' ≈ 3.3 rps/IP — đủ cho demo; bot quét enumeration (T-03) / click-fraud (T-08) bị chặn |
| `RL-Stats` | `/api/stats*`, `/api/links*` | **300** | Block | Chống scraper dashboard polling quá đà (TV2 poll 5s ≈ 60 req/5') |
| `RL-Global-Flood` | (toàn distribution) | **5.000** | Block | Lưới an toàn cuối trước economic-DoS (T-09) |

> Chi tiết triển khai xem `terraform/foundation.tf` (§5 trong file Terraform đính kèm: `aws_wafv2_web_acl` + `rate_based_statement` + `scope_down_statement`). Với console: WAF → Web ACLs (us-east-1) → Add rules → Rate-based → cấu hình như bảng trên.

**Lưu ý vận hành:**

- NAT/CGNAT (ký túc xá, công ty) dồn nhiều user sau 1 IP → ngưỡng quá thấp gây false-positive. Giảm thiểu: scope-down hẹp (chỉ `/shorten`), kết hợp token-bucket app-layer theo `X-Owner-Id` + IP-hash thay vì block cứng IP ở edge.
- Luôn bật **logging WAF → S3/CloudWatch** (`logging_configuration` trong Terraform) để hiệu chỉnh ngưỡng và làm bằng chứng abuse.
- Khi bị tấn công DDoS lớn: hạ ngưỡng tạm thời + bật AWS Shield Standard (miễn phí, tự động ở CloudFront) → liên hệ AWS Shield Advanced chỉ khi cần SLA.

### 1.3. AWS Managed Rules — chọn gì, vì sao

| Rule group (Vendor: AWS) | Tác dụng với hệ thống này | Khuyến nghị v1 |
|---|---|---|
| **AWSManagedRulesCommonRuleSet** (CRS) | Chặn OWASP Top 10 cơ bản: SQLi/XSS/LFI/RFI patterns trong query/body/header. Bảo vệ `/shorten` (JSON body `url`, `alias`) và `/{code}?confirm=` | ✅ Bật, **Count mode 3–7 ngày đầu**, loại trừ (exclude) rule gây nhiễu URL dài hợp lệ rồi chuyển Block |
| **AWSManagedRulesKnownBadInputs** | Chặn input độc hại đã biết (Log4Shell, shells…). Rẻ, nhiễu thấp | ✅ Bật Block ngay |
| **AWSManagedRulesAmazonIpReputationList** | Chặn IP trong danh sách AWS threat-intel (botnet, scanner, TOR exit…). Hiệu quả cao cho T-02/T-03/T-08, gần như không false-positive | ✅ Bật Block ngay |
| AWSManagedRulesAnonymousIpList | Chặn VPN/TOR/hosting provider | ⚠️ Chỉ Count — sinh viên dùng VPN trường học nhiều |
| AWSManagedRulesBotControl *(trả phí)* | Phân loại bot tốt/bot xấu, CAPTCHA/Challenge tự động | ❌ v1 không dùng (tốn phí theo request); thay bằng Turnstile + rate-limit tự làm |
| AWSManagedRulesSQLi / Linux / Unix | Đã bao trong CRS/KnownBadInputs phần lớn | ❌ Không cần riêng |

**Thứ tự ưu tiên rule (WAF evaluates theo priority):** IP Reputation (0) → Rate-based shorten (1) → Rate-based redirect (2) → KnownBadInputs (3) → CRS (4) → custom blocklist/geo (5). Đặt rate-based trước CRS để cắt flood rẻ nhất trước khi chạy regex đắt.

### 1.4. Kiến trúc WAF + CloudFront & tối ưu chi phí

**Cơ chế tính phí WAF (khung — kiểm tra trang giá hiện hành):**

- Phí **Web ACL / tháng** (theo scope) + phí **mỗi rule / tháng** (managed rule group tính riêng, Bot Control/ Fraud Control đắt hơn hẳn) + phí **per-million-requests** được WAF đánh giá.
- Riêng với CloudFront: request đã qua CloudFront vẫn bị tính phí WAF request inspection; CloudFront tính phí request/bandwidth riêng.
- → **Tối ưu:** (1) ít rule nhưng trúng (4–6 rules như §1.2–1.3, không bật mọi managed group); (2) để CloudFront cache static (`/assets/*`, `/mock/*`) với TTL dài để request không vào origin (WAF vẫn inspect nhưng giảm tải origin/Lambda/Dynamo — nơi tốn tiền hơn); (3) **không cache** `/{code}` và `/api/*` (TTL 0, forward query) để analytics đúng; (4) bật compress + HTTP/2-3 ở distribution; (5) log WAF sampled vừa đủ, lifecycle S3 log sang Glacier sau 30 ngày.

**Checklist CloudFront cho TV5/TV2:**

- [ ] Behaviors: `/api/*` → HTTP API origin (cache disabled, origin request policy forward `CloudFront-Viewer-Country`, `X-Owner-Id`, query); `/{code}` → cùng origin, **cache disabled** (`Cache-Control: no-store` từ Lambda + `TTL=0`); `/assets|css|js|mock` → S3 origin, cache dài.
- [ ] Origin request policy **chỉ forward header cần thiết**; không forward `Cookie` vô tội vạ (làm vỡ cache + lộ).
- [ ] Custom error responses: 403/404/410 từ origin → trang `warning.html`/`error.html` của TV2 (cần thống nhất TV2/TV5 — TV1 §7).
- [ ] Bắt buộc HTTPS (redirect HTTP→HTTPS, TLS 1.2+), HSTS ở response; WAF Web ACL attach vào distribution.
- [ ] Khóa origin trực tiếp: API Gateway resource policy chỉ nhận từ CloudFront (kèm secret header `X-Origin-Verify` xoay định kỳ) để chống forge `CloudFront-Viewer-Country` (TV4 cảnh báo).

---

## 2. Amazon API Gateway — Throttling, Usage Plan, API Key

### 2.1. Thực tế với HTTP API (khung nhóm đang dùng)

| Tính năng | REST API | **HTTP API (nhóm dùng)** | Hệ quả & cách thay thế |
|---|---|---|---|
| Throttling stage/route (rate + burst) | ✅ | ✅ (cơ bản: stage default + route override) | Dùng ngay: stage `prod` rate ~100 rps, burst ~200; route `POST /shorten` siết 20 rps (số demo, hiệu chỉnh sau load test) |
| API key + Usage plan (quota theo client) | ✅ | ❌ | Thay bằng **token-bucket `rate_limits` trong DynamoDB** (PK `ip#<hash>`, SK `window`, TTL) + Turnstile; nâng lên REST API/Cognito khi có auth thật |
| WAF trực tiếp | ✅ | ❌ | WAF ở CloudFront (§1) |
| Request validation / API cache | ✅ | ❌/— | Validate trong Lambda (Joi/Zod-style, đã có `validate_url`); cache do CloudFront đảm nhiệm |
| JWT authorizer | ❌ (Cognito/Lambda authorizer) | ✅ | Lợi thế khi Week 3 thêm đăng nhập |

### 2.2. Throttling — cấu hình đề xuất

**Tầng Gateway (chặn rẻ nhất sau WAF):**

```yaml
# backend/template.yaml (SAM) — minh họa; số liệu demo, hiệu chỉnh sau đo
ApiGateway:
  StageName: prod
  DefaultRouteSettings:
    ThrottlingBurstLimit: 200
    ThrottlingRateLimit: 100
  RouteSettings:
    "POST /shorten": { ThrottlingBurstLimit: 20, ThrottlingRateLimit: 10 }
    "GET /{code}":    { ThrottlingBurstLimit: 300, ThrottlingRateLimit: 150 }
```

**Tầng ứng dụng (chính xác theo IP/owner, trả `429 + Retry-After` đúng spec):**

- Bảng `rate_limits`: PK `pk = IP#<sha256(ip+salt)>`, SK `sk = <endpoint>#<minute-bucket>`, `count` (atomic `ADD`), TTL 120s.
- Hạn mức hiển thị trên UI: **10 link/phút/IP** (`POST /shorten`); `GET /{code}` 120/phút/IP; `GET /stats*` 60/phút/IP.
- Vượt → `429 { error: { code: "rate_limited", retry_after: <s> } }` + header `Retry-After` (TV2 mock đã đọc `retry_after`).
- Dùng **DynamoDB atomic counter + TTL**, không dùng memory-local (Lambda scale nhiều instance).

**Khi nào đổi sang REST API:** khi cần quota theo người dùng/tháng (ví dụ gói Free 1000 link/tháng) hoặc gắn WAF trực tiếp không qua CloudFront. Chi phí REST cao hơn HTTP đáng kể ở traffic redirect lớn → giữ HTTP API cho đến khi có yêu cầu billing theo user.

---

## 3. Malicious URL Detection — Google Safe Browsing v4 vs URLhaus

### 3.1. So sánh

| Tiêu chí | **Google Safe Browsing API v4 (threatMatches)** | **abuse.ch URLhaus** |
|---|---|---|
| Phủ & độ chính xác | Rất rộng (Google crawl + Chrome/Firefox dùng chung); lists: `MALWARE`, `SOCIAL_ENGINEERING` (phishing), `UNWANTED_SOFTWARE`, `POTENTIALLY_HARMFUL_APPLICATION` | Chuyên sâu URL phân phối malware (payload, C2); cộng đồng + sandbox; tốt cho malware, yếu hơn về phishing đại trà |
| Đăng ký / Key | **Cần API key** (Google Cloud project, bật Safe Browsing API). Quota miễn phí hào phóng cho đồ án (kiểm tra console hiện hành; vượt thì nâng quota trả phí) | **Lookup (`https://urlhaus-api.abuse.ch/v1/url/`) không cần key**, không auth; giới hạn fair-use (không spam request, cache bắt buộc; key chỉ cần cho submit/danh sách bulk) |
| Rate limit / quota | Theo project (QPS + daily;```threatMatches:find``` nhẹ). Vượt → 429, phải backoff | Fair-use: **không quá vài request/giây**, bắt buộc User-Agent định danh + cache; bulk query dùng database download (CSV) thay vì lookup từng URL |
| Độ trễ | ~50–300 ms/lookup (giữ TLS warm, batch nhiều URL/lần) | ~100–400 ms/lookup |
| Tích hợp async | ✅ Khuyến nghị (xem §3.2) | ✅ Khuyến nghị |
| Chi phí | Miễn phí trong quota đồ án | Miễn phí (ghi công abuse.ch, tuân ToS) |
| Điểm yếu | Không phủ hết malware mới tinh (0-day), phụ thuộc Google verdict | Không phủ phishing đại trà; API có thể thay đổi; cần fallback |

**Kết luận:** dùng **cả hai, GSB làm chính (phishing+malware), URLhaus làm phụ (malware payload)**. Không tin tuyệt đối verdict nào — luôn cộng với blocklist nội bộ + heuristic (own-domain, IP-literal, từ khóa) và trạng thái `suspicious` cho biên.

### 3.2. Thiết kế tích hợp async + caching (không làm chậm redirect)

**Nguyên tắc vàng:** luồng redirect nóng (`GET /{code}`) **không bao giờ** gọi GSB/URLhaus đồng bộ. Mọi lookup mạng ra ngoài chỉ xảy ra ở **luồng tạo (async)** và **worker re-scan**, kết quả lưu cache → redirect chỉ đọc 1 item DynamoDB.

```
POST /shorten ─▶ validate nhanh (regex/host/own-domain/IP-literal/DNS) ─▶ ghi urls status=pending/active
      │                                                                              │
      └─▶ enqueue scan job (SQS hoặc DynamoDB Streams) ─▶ scanner Lambda ─┬─▶ GSB threatMatches (batch)
                                                                          ├─▶ URLhaus lookup
                                                                          └─▶ verdict → urls.status = active|suspicious|blocked + blocklist TTL + alert
GET /{code} ─▶ đọc urls (1 GetItem) ─▶ active→302 │ suspicious→403+confirm │ blocked→403 │ (không gọi API ngoài)
Worker định kỳ (EventBridge 6h) ─▶ re-scan top/active links ─▶ cập nhật verdict (chống domain đổi chủ)
```

**Chi tiết:**

1. **Tại `POST /shorten`:** chạy validate đồng bộ rẻ (< 20 ms, xem `threat_model.md` §4). Sau đó trả `201` ngay (UX nhanh), bắn event scan async (SQS `scan-queue` + DLQ, hoặc Streams). Nếu cần chặn cứng (ví dụ trùng blocklist nội bộ) → trả `blocked_domain` đồng bộ luôn.
2. **Scanner Lambda:** gom batch (GSB hỗ trợ nhiều `threatInfoEntries`/request), timeout 10s, retry exponential + jitter, circuit-breaker (ngắt 5 phút khi 429/5xx liên tục). Cache verdict theo **SHA256(canonical URL)** trong DynamoDB `blocklist`/`verdict_cache` với TTL (sạch: 24h; độc: 7–30 ngày) → lần sau không lookup lại.
3. **Hiển thị:** link `pending` vẫn redirect bình thường cho đến khi có verdict (hoặc chặn mềm `suspicious` nếu heuristic nghi). Quyết định Week 2: nhóm khuyến nghị **mặc định active + re-check 5–30s sau**, chỉ chặn đồng bộ khi blocklist nội bộ trúng (độ trễ < 5 ms).
4. **Re-scan:** EventBridge cron 6h quét link `active` + top-click; domain hết hạn/đổi IP → verdict mới. Ghi `updated_at`, giữ lịch sử verdict 30 ngày cho audit.
5. **Không để lộ key:** GSB key + Turnstile secret trong **SSM SecureString / Secrets Manager**, Lambda đọc qua env + IAM least-privilege; không log key/verdict thô.

**Pseudo-code Lambda (Python, khớp `backend/prototype.py` style):**

```python
import hashlib, json, os, time, urllib.request

GSB_KEY = os.environ["GSB_API_KEY"]  # từ SSM, không hard-code
VERDICT_TTL_OK, VERDICT_TTL_BAD = 24*3600, 7*24*3600

def canonical(u: str) -> str: ...
def verdict_cache_get(h: str): ...   # DynamoDB verdict_cache GetItem
def verdict_cache_put(h: str, bad: bool): ...  # PutItem + TTL

def gsb_lookup(urls: list[str]) -> set[str]:
    body = json.dumps({"threatInfo": {
        "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
        "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
        "threatEntries": [{"url": u} for u in urls]}}).encode()
    req = urllib.request.Request(
        f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={GSB_KEY}",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    return {m["threat"]["url"] for m in data.get("matches", [])}

def urlhaus_lookup(url: str) -> bool:
    req = urllib.request.Request("https://urlhaus-api.abuse.ch/v1/url/",
        data=f"url={url}".encode(),
        headers={"User-Agent": "LinkPulse-Research/1.0 (contact: team-linkpulse)"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r).get("query_status") == "ok"  # ok = thấy trong DB độc hại

def scan_url(url: str) -> str:  # "active" | "suspicious" | "blocked"
    h = hashlib.sha256(canonical(url).encode()).hexdigest()
    if (c := verdict_cache_get(h)) and c["exp"] > time.time():
        return c["status"]
    bad = url in gsb_lookup([url]) or urlhaus_lookup(url)
    status = "blocked" if bad else "active"
    verdict_cache_put(h, bad)
    return status
```

---

## 4. Bot Detection & CAPTCHA — Cloudflare Turnstile cho `POST /shorten`

### 4.1. Vì sao Turnstile (thay vì reCAPTCHA/hCaptcha)?

- **Miễn phí không giới hạn**, không đếm request như một số dịch vụ; widget nhẹ, không cần giải đố chữ/mê cung đa số phiên (managed/invisible mode), **riêng tư** (không dùng cookie quảng cáo như reCAPTCHA v2/v3).
- Phù hợp đồ án: 1 sitekey/site, verify 1 endpoint, không cần Enterprise trừ khi cần risk-score nâng cao.
- Thay thế drop-in cho reCAPTCHA ở frontend TV2 (đổi script + callback).

### 4.2. Frontend integration (TV2)

```html
<!-- Trong form tạo link (thay reCAPTCHA nếu có) -->
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<div class="cf-turnstile" data-sitekey="0x4AAAAAA..." data-callback="onTurnstile" data-action="shorten"></div>
<script>
  let turnstileToken = "";
  function onTurnstile(token) { turnstileToken = token; } // gửi kèm POST /api/shorten
  async function createLink(url, alias) {
    const res = await fetch("/api/shorten", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Owner-Id": ownerId },
      body: JSON.stringify({ url, alias, turnstile_token: turnstileToken, expires_in: 604800 })
    });
    if (res.status === 400) { /* captcha_failed → reset widget: turnstile.reset() */ }
  }
</script>
```

- Token **hết hạn sau ~5 phút**, dùng 1 lần → frontend lấy token mới mỗi lần submit (render lại widget sau mỗi lần tạo).
- Không disable nút submit khi chưa có token (bot gọi API trực tiếp vẫn bị server chặn) — nhưng UX nên chờ widget sẵn sàng.

### 4.3. Backend verification workflow (Lambda, bắt buộc)

```
POST /shorten { turnstile_token } ─▶ Lambda:
  1. Thiếu token → 400 captcha_failed (không ngoại lệ, kể cả dev)
  2. POST https://challenges.cloudflare.com/turnstile/v0/siteverify { secret, response: token, remoteip? }
  3. Kiểm tra: success==true AND hostname ∈ allowlist(ownDomains) AND action=="shorten" (nếu dùng) AND challenge_ts trong 5 phút
  4. Chống replay: token-id (response) cache đã-dùng 10 phút (DynamoDB rate_limits/TTL) → dùng lại → captcha_failed
  5. Fail (timeout/mạng) → chính sách "fail-closed" ở prod (trả captcha_failed), "fail-open + rate-limit chặt" chỉ khi demo khẩn (ghi log, bật alarm)
```

```python
import json, os, time, urllib.request
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
USED_TOKENS = {}  # prod: DynamoDB TTL thay cho dict

def verify_turnstile(token: str, remote_ip: str | None, allowed_hosts: set[str]) -> bool:
    if not token or USED_TOKENS.get(token):
        return False
    body = json.dumps({"secret": os.environ["TURNSTILE_SECRET"],
                       "response": token}).encode()
    req = urllib.request.Request(VERIFY_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            v = json.load(r)
    except Exception:
        return False  # fail-closed
    ok = (v.get("success") is True
          and v.get("hostname") in allowed_hosts
          and v.get("action", "shorten") == "shorten")
    if ok:
        USED_TOKENS[token] = time.time() + 600
    return ok
```

**Checklist review:** secret ở SSM; verify mọi request (không whitelist `localhost` ở prod); kiểm `hostname/action`; one-time token; log chỉ `success/false`, không log token.

---

## 5. Input Validation & Sanitization

### 5.1. Bảng quy tắc (đồng bộ Frontend + Lambda + spec)

| Trường | Quy tắc | Lỗi (`api_spec.yaml`) |
|---|---|---|
| `url` | trim; 1–**2048 ký tự**; `new URL()` parse được; scheme ∈ {`http:`, `https:`}; không `username:password@`; không whitespace/control; hostname ≠ own-domain (+ CloudFront domain); IP-literal + DNS-resolve-all đều không private (xem `threat_model.md` §4) | `invalid_url` (`scheme_not_allowed`, `host_not_allowed`, `own_domain`, …) |
| `url` (tiếp) | Chặn `data:`, `javascript:`, `vbscript:`, `file:`, `ftp:`, `blob:`; chặn `//host@evil` trick (parser xử lý); punycode chuẩn hóa trước khi so blocklist | `invalid_url` |
| `alias` | `^[A-Za-z0-9-]{3,30}$`, không trùng reserved (`api, assets, dashboard, error, warning, stats, links, shorten, admin, …`), không cấp lại kể cả đã xóa | `invalid_alias` / `alias_taken` (409) |
| `expires_in` | int 60–31.536.000 (giây) | `invalid_expires_in` |
| `max_clicks` | int ≥ 1 | `invalid_max_clicks` |
| `turnstile_token` | bắt buộc, verify server (§4.3) | `captcha_failed` |
| `code` (path) | `^[A-Za-z0-9-]{3,30}$`, case-sensitive | `not_found` (404, không lộ lý do) |
| `X-Owner-Id` | UUID v4 (validate định dạng, không tin là auth) | `unauthorized` (401) |
| `confirm` | chỉ `1` có nghĩa, còn lại bỏ qua | — |
| Output | Không phản chiếu URL vào HTML không escape; redirect chỉ qua `Location` header | — |

### 5.2. Mẫu Lambda validate (Python — khớp `backend/prototype.py`, mở rộng DNS)

`backend/prototype.py` đã có `validate_url()` đầy đủ lớp cú pháp. Bản production thêm **lớp DNS** (prototype chưa có) trước khi `PutItem`:

```python
import socket
import ipaddress

def dns_all_private(host: str) -> bool | None:
    """True: có ≥1 bản ghi private (chặn). False: sạch. None: DNS lỗi."""
    try:
        _, _, ips = socket.gethostbyname_ex(host)
    except socket.gaierror:
        return None
    for ip in ips:
        o = ipaddress.ip_address(ip)
        if o.is_private or o.is_loopback or o.is_link_local or o.is_reserved or o.is_multicast or o.is_unspecified:
            return True
    return False
# Trong shorten(): sau validate_url() → nếu hostname không phải IP literal:
#   r = dns_all_private(host); if r is not False: return invalid_url(host_not_allowed / dns_failed)
# + pin kết quả 60s (cache) để scanner dùng lại, chống DNS rebinding giữa validate và fetch.
```

---

## 6. Lộ trình triển khai Week 2 (đề xuất thứ tự)

1. **Foundation:** chạy `scripts/setup_aws_foundation.sh` (IAM least-privilege + MFA + Budget $5) → WAF Web ACL `us-east-1` + logging (Terraform `terraform/foundation.tf`).
2. **Lambda:** ghép `validate_url` 2 lớp + Turnstile verify + token-bucket `rate_limits` vào `POST /shorten`; header `302 + no-store` cho redirect.
3. **Async scan:** SQS + scanner (GSB + URLhaus) + `verdict_cache` + EventBridge re-scan 6h.
4. **CloudFront behaviors** (no-cache `/{code}` + `/api/*`, forward country header) + khóa origin trực tiếp.
5. **Alarms:** WAF-blocked, 5xx, throttle, billing; Count→Block cho CRS sau 1 tuần log.

---

## 7. Tài liệu tham khảo

- AWS WAF: rate-based rule statement, scope-down, managed rule groups, logging; Web ACL `CLOUDFRONT` scope ở `us-east-1`.
- CloudFront: cache policies, origin request policies, `CloudFront-Viewer-Country`, custom error responses.
- API Gateway: HTTP API vs REST API, throttling.
- Google Safe Browsing API v4 (`threatMatches:find`); abuse.ch URLhaus API (`/v1/url/`).
- Cloudflare Turnstile (client + `siteverify`).
- OWASP: Input Validation Cheat Sheet, SSRF Prevention, CAPTCHA guidance.
- Tài liệu nhóm: `docs/api_spec.yaml`, `backend/prototype.py`, `docs/threat_model.md`, `docs/architecture.md`.
