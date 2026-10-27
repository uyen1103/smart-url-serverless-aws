# Threat Model — Smart URL Serverless (LinkPulse)

> **Module:** TV5 — Security, Anti-abuse & DevOps · **Issue:** Week 1 / #5
> **Phạm vi:** Hệ thống rút gọn liên kết serverless trên AWS
> (`CloudFront + WAF → API Gateway HTTP API → Lambda (Python 3.11) → DynamoDB`,
> redirect `302 + Cache-Control: no-store`, analytics qua `DynamoDB Streams → click_processor → stats_agg`).
> **Tài liệu liên quan:** `docs/api_spec.yaml`, `docs/backend_research.md` (TV1),
> `docs/analytics_research.md` + `docs/click_event_schema.json` (TV4), `backend/prototype.py`.
> **Phương pháp:** STRIDE (Microsoft) + OWASP Top 10:2021 / OWASP API Security Top 10:2023.
> **Ngày:** 27/10/2026 · **Trạng thái:** v1.0 — dùng cho review nhóm & triển khai Week 2.

---

## 1. Tổng quan hệ thống & ranh giới tin cậy (Trust Boundaries)

### 1.1. Tài sản cần bảo vệ (Assets)

| # | Tài sản | Tác động nếu bị xâm phạm |
|---|---------|--------------------------|
| A1 | Tính toàn vẹn redirect (người dùng đến đúng URL đích an toàn) | Phishing/malware phát tán qua domain uy tín của hệ thống → mất niềm tin, bị blocklist, bị trình duyệt cảnh báo |
| A2 | Dữ liệu `urls` (DynamoDB): `short_code → long_url`, `owner`, `status`, `expires_at`, `max_clicks` | Lộ/quá ghi dữ liệu người khác, chiếm alias, resurrect mã đã xóa |
| A3 | Dữ liệu `clicks` + `stats_agg` (analytics) | Số liệu sai → dashboard sai, quyết định sai; lộ `ip_hash`/hành vi |
| A4 | Quyền riêng tư: IP (qua `ip_hash` + salt), `User-Agent`, `country`, `referrer` | Rò rỉ PII/giả danh, vi phạm chính sách |
| A5 | Ngân sách AWS & quota (Lambda concurrency, DynamoDB WCU/RCU, API Gateway, WAF) | Bị đốt tiền (bill shock), DoS ví (economic DoS), hết quota → sập dịch vụ |
| A6 | Uy tín domain `linkpulse.vn` + distribution CloudFront | Bị Safe Browsing/URLhaus/Meta đánh dấu → toàn bộ link bị chặn |
| A7 | Khóa bí mật: Turnstile secret, GSB API key, IP-hash salt, IAM credentials | Giả mạo CAPTCHA verdict, đọc brute-force, leo thang quyền |

### 1.2. Sơ đồ ranh giới tin cậy

```
[Attacker / Bot / User] ──(1)──▶ [CloudFront + WAF] ──(2)──▶ [API Gateway HTTP API]
      │                                  │                           │
      │                           TLS terminate,              Throttle cơ bản,
      │                           country header,              route /shorten, /{code},
      │                           cache behavior               /stats, /links
      │                                                              │
      │──(0) DNS / TLS / CDN edge (không tin client IP/header)───────▼
                                                              [Lambda Backend]
                                                              validate → Turnstile verify
                                                              → GSB/URLhaus (async+cache)
                                                              → DynamoDB conditional write
                                                                     │
                                                                     ▼
                                                     [DynamoDB: urls | clicks | stats_agg | rate_limits | blocklist]
                                                                     │ (Streams NEW_IMAGE, INSERT only)
                                                                     ▼
                                                     [Lambda click_processor → stats_agg] ──▶ [GET /stats(/:code)]
```

**Ranh giới:**

- **TB-0 (Untrusted):** mọi thứ từ client — URL, `X-Owner-Id`, `User-Agent`, `Referer`, `confirm=1`, Turnstile token. Không bao giờ tin trực tiếp.
- **TB-1 (Edge):** CloudFront là điểm duy nhất được tin cho `CloudFront-Viewer-Country` và IP nguồn (qua `X-Forwarded-For` do AWS chèn). Origin (API Gateway/Lambda) **phải** chặn truy cập trực tiếp (resource policy / custom header bí mật / Security Groups logic) — nếu không attacker tự forge country header (TV4 đã cảnh báo).
- **TB-2 (App):** Lambda là nơi thực thi mọi kiểm tra (validate, auth owner, Turnstile, verdict cache). Không đẩy kiểm tra bảo mật ra frontend.
- **TB-3 (Data):** DynamoDB + Streams là nguồn sự thật. Mọi ghi cạnh tranh phải qua conditional write; analytics chỉ cộng từ `INSERT`.

### 1.3. Giả định & ngoài phạm vi

- **Giả định:** TLS đầy đủ (CloudFront + ACM); IAM least-privilege + MFA bắt buộc (xem `scripts/setup_aws_foundation.sh`); salt băm IP lưu ở SSM SecureString/KMS, không hard-code; `X-Owner-Id` chỉ là định danh trình duyệt, **không phải xác thực** (đã chốt với TV1/TV2 — API quản trị chặn/gỡ chặn cần auth thật ở Week 2+).
- **Ngoài phạm vi v1:** đăng nhập người dùng (Cognito/JWT), kiểm duyệt nội dung trang đích sau khi tạo (chỉ check tại thời điểm tạo + re-check định kỳ), WAF Bot Control bản trả phí.

---

## 2. Phương pháp chấm rủi ro

- **STRIDE:** S-Spoofing, T-Tampering, R-Repudiation, I-Information disclosure, D-DoS, E-Elevation of privilege. Mỗi mối đe dọa gắn 1 nhãn chính (+ nhãn phụ nếu có).
- **Mức rủi ro:** kết hợp **Impact** (H/M/L đối với A1–A7) × **Likelihood** (H/M/L trong bối cảnh đồ án public internet) → **Critical / High / Medium / Low**. Cột `CVSS/Impact` ghi vector CVSS 3.1 minh họa (tính cho kịch bản điển hình, không thay cho pentest) + impact nghiệp vụ.
- **Ưu tiên sửa:** Critical/High phải có mitigation trong v1 (Week 1–2); Medium có tối thiểu ở Lambda/WAF; Low ghi nhận residual risk + monitoring.

---

## 3. Bảng Threat Model (STRIDE)

> Quy ước mã lỗi theo `docs/api_spec.yaml`: `invalid_url`, `blocked_domain`, `alias_taken`, `captcha_failed`, `rate_limited` (429 + `Retry-After`), `link_blocked/link_suspicious` (403), `not_found` (404), `link_expired/max_clicks_reached` (410).

| ID | Mối đe dọa | Vector tấn công | Phân loại STRIDE | Mức độ rủi ro (CVSS/Impact) | Kịch bản khai thác | Biện pháp giảm thiểu (Mitigation) |
|----|-----------|-----------------|------------------|------------------------------|---------------------|-----------------------------------|
| **T-01** | **Phishing / Malware hosting qua link rút gọn** | Attacker rút gọn URL phishing (`https://evil.example/login-vcb`) thành `https://linkpulse.vn/aB3kLm9`, phát tán qua SMS/Facebook; nạn nhân tin domain chính thống | **S** (giả mạo uy tín domain) + T | **Critical** · CVSS 8.2 (AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:N) · Impact H (A1, A6) | Tạo 100 link phishing với alias giống thương hiệu (`vcb-secure`, `shopee-sale`); dùng `?confirm=1`-style social engineering để vượt cảnh báo `suspicious` | 1) Validate + blocklist + **GSB v4 / URLhaus check lúc tạo** (async + cache verdict, chặn `blocked_domain`) — xem `security_research.md` §4. 2) Trạng thái `suspicious → warning.html?reason=suspicious`, `blocked → 403` không bao giờ redirect. 3) Re-scan định kỳ + API quản trị block. 4) Report-abuse + TTL blocklist. 5) CSP/`Referrer-Policy` ở frontend, không phản chiếu URL đích vào HTML mà không escape |
| **T-02** | **Spam hàng loạt / tạo link ồ ạt (link farming)** | Script gọi `POST /api/shorten` hàng nghìn lần (xoay IP/proxy, bỏ qua UI) | **D** + T | **High** · CVSS 7.5 · Impact H (A5 chi phí/quota, A6 uy tín) | Botnet tạo 50k link rác trong 1 giờ → DynamoDB WCU爆, bảng `urls` phình, domain bị đánh dấu spam | 1) **WAF rate-based rule** trên `/api/shorten` (ví dụ 100 req/5 phút/IP → block 5–30 phút) + AWS Managed Rules IP Reputation. 2) **Turnstile bắt buộc** cho `/shorten` (thiếu/sai → `captcha_failed`). 3) Throttle API Gateway + token-bucket `rate_limits` trong DynamoDB (10 link/phút/IP hiển thị trên UI). 4) Giới hạn `MAX_URL_LENGTH=2048`, alias 3–30, `expires_in` 60–31.536.000s. 5) Alarm CloudWatch + Budget $5 (TV5 foundation) |
| **T-03** | **Bot enumeration / brute-force short-code** | Duyệt không gian mã: `GET /a000001…`, dictionary alias phổ biến; mã Base62 tuần tự nếu dùng counter | **I** (thu thập URL riêng tư) + S | **High** · CVSS 6.5 · Impact H (A2 riêng tư) | Attacker quét 10M mã/ngày tìm link nội bộ (`/hr-luong-t13`), tống tiền hoặc SEO spam | 1) **Mã random 7 ký tự Base62 bằng `secrets`** (62⁷ ≈ 3.5 nghìn tỷ, không dùng counter tăng dần — TV1 đã chốt). 2) WAF rate-based cho `GET /{code}` (ví dụ 1000 req/5 phút/IP) + Managed Common Rule Set. 3) Redirect 404/410 đồng nhất, không lộ lý do chi tiết (chỉ `not_found`). 4) CloudFront cache `no-store` cho redirect để không lộ qua cache. 5) Rate-limit theo IP-hash ở Lambda + exponential backoff 429. 6) Cân nhắc không phân biệt hoa/thường ở alias? — giữ phân biệt như spec để tăng không gian |
| **T-04** | **Redirect loop (vòng lặp chuyển hướng)** | `long_url` trỏ vòng quanh: `A→B→A`, hoặc self-chain `linkpulse.vn/x → linkpulse.vn/y → … → linkpulse.vn/x` | **D** (treo trình duyệt/lambda) + T | **Medium** · CVSS 5.3 · Impact M (A1 UX, A5 tài nguyên) | Attacker tạo `A→B`, `B→A`; nạn nhân mở → trình duyệt báo `ERR_TOO_MANY_REDIRECTS`; bot redirect-follower của hệ thống (nếu có preview) treo/timeout | 1) **Chặn own-domain** (`linkpulse.vn` + CloudFront domain + custom domain, gồm subdomain — `validate_url` reason `own_domain`). 2) Trình preview/unfurl (nếu có) giới hạn redirect-hop ≤ 5 + timeout 5s, không follow loop. 3) Frontend mở link ngoài với `rel=noopener`. 4) Test-case loop trong `tests/` |
| **T-05** | **Chuyển hướng trỏ ngược về chính hệ thống (self-reference / open-redirect dây chuyền)** | `long_url = https://linkpulse.vn/{code-khác}` hoặc `https://linkpulse.vn/api/...`, `/warning.html`, `//linkpulse.vn@evil` | **S** + T | **High** · CVSS 6.8 · Impact H (A1 trust, bypass `blocked`) | Attacker tạo link `X → /warning.html?reason=blocked` giả trang cảnh báo thật để lừa “xác minh”; hoặc `X → /api/shorten` gây hành vi lạ; hoặc dùng `https://linkpulse.vn%2e.evil.example/` né check chuỗi | 1) Chuẩn hóa URL bằng `URL` parser (không check chuỗi thô): so sánh `hostname` lowercase, strip trailing dot, decode punycode; chặn `OWN_DOMAINS` + CloudFront domain + mọi custom domain (config, không hard-code). 2) Chặn `username:password@` (`credentials_not_allowed`). 3) Chặn khoảng trắng/ký tự điều khiển. 4) Alias trùng route hệ thống (`api, assets, dashboard, error, warning, stats, links, shorten, admin`) → `alias_taken` |
| **T-06** | **SSRF vào metadata / private network** | `long_url` là IP nội bộ hoặc domain phân giải về IP nội bộ: `127.0.0.1`, `localhost`, `169.254.169.254/latest/meta-data/iam/security-credentials/`, `10/8`, `172.16/12`, `192.168/16`, dạng né `2130706433`, `127.1`, `0x7f.0.0.1`, `[::ffff:127.0.0.1]`, DNS rebinding | **E** (đọc credential IMDSv1, quét VPC) + I | **Critical** · CVSS 9.1 (AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:L) · Impact H (toàn bộ AWS account) | Attacker tạo link `http://169.254.169.254/latest/meta-data/` rồi dụ **server-side fetcher** (preview/screenshot/GSB-enrichment) fetch → lộ IAM credential; hoặc quét `http://10.0.1.5:8080/admin` trong VPC | 1) **Validate 2 lớp** (mẫu TS §4): lớp cú pháp (scheme/host) + lớp phân giải (xem 3). 2) Chặn mọi IP literal thuộc `is_private/is_loopback/is_link_local/is_reserved/is_multicast/is_unspecified` — **bao gồm cả dạng thập phân/octal/hex** (`inet_aton`-equivalent) và IPv6-mapped. 3) **Resolve DNS ra mọi A/AAAA rồi kiểm tra từng IP** (chống DNS rebinding: resolve tại validate + resolve lại ngay trước fetch với cùng kết quả, pin IP, timeout ngắn). 4) Mọi fetch server-side chạy trong egress bị giới hạn (no VPC route tới metadata nếu không cần; dùng IMDSv2 + hop-limit 1). 5) Không bao giờ fetch URL người dùng ở Lambda redirect nóng — chỉ fetch ở worker cách ly (nếu cần preview) với allowlist egress. 6) Log `host_not_allowed`, không phản chiếu IP nội bộ cho client |
| **T-07** | **SSRF qua redirect phía server (server-follows-redirect)** | URL ban đầu công khai nhưng redirect (301/302/meta-refresh) về IP nội bộ; fetcher đi theo mà không re-validate | **E** + I | **High** · CVSS 8.0 · Impact H | `https://evil.example/r` (200 → 302 `http://10.0.0.10/`) — worker preview đi theo → SSRF như T-06 | 1) Re-validate **mỗi hop** (tối đa 3–5 hop), áp cùng chính sách IP/host như URL gốc. 2) Tắt follow-redirect mặc định của HTTP client; tự xử lý thủ công. 3) Chặn redirect tới scheme khác (`file:`, `gopher:`, `dict:`). 4) Timeout tổng ≤ 8s, giới hạn body (ví dụ 1 MB) |
| **T-08** | **Bot tăng click ảo (click fraud / analytics poisoning)** | Botnet/cron `curl /{code}` hàng nghìn lần, xoay UA/IP; hoặc `<img src=/code>` nhúng vào site traffic cao | **T** (làm sai số liệu) + D | **Medium** · CVSS 5.8 · Impact M (A3, A5) | Đối thủ bơm 100k click giả vào link đối thủ → `max_clicks` cạn, dashboard sai, `top_links` bị thao túng; hoặc bơm vào link mình để “làm đẹp” KPI | 1) Phân loại bot bằng UA (`user-agents` lib) + heuristic (tốc độ/IP burst, `referrer` bất thường) → `device=bot`, tách `bot_clicks` khỏi click hợp lệ (`total - bot`). 2) WAF rate-based + API throttle cho `/{code}`. 3) Không tin `ip_hash` cho billing; `unique_visitors` ghi rõ là ước tính. 4) CloudWatch anomaly alarm (spike click/phút). 5) Tùy chọn: `max_clicks` không đếm bot (quyết định Week 2, hiện spec đếm mọi 302 — cần chốt TV4) |
| **T-09** | **Cạn kiệt tài nguyên / Bill shock (economic DoS)** | Flood cả 2 endpoint nặng nhất: `POST /shorten` (ghi DB + GSB lookup) và `GET /{code}` (đọc DB + ghi click + Streams + processor) | **D** | **High** · CVSS 7.0 · Impact H (A5) | 10k rps trong 1 giờ → Lambda concurrency 1000, DynamoDB on-demand爆, WAF request charge, Streams→Lambda loop | 1) WAF block + CloudFront (cache static, shield edge). 2) Reserved concurrency cho redirect fn + throttling. 3) DynamoDB on-demand + auto-scale + TTL `clicks`; CloudWatch billing alarm + **Budget $5** gửi mail nhóm. 4) `sam delete`/stack tách môi trường demo. 5) Kill-switch: chuyển `status=blocked` hoặc tắt behavior CloudFront |
| **T-10** | **Open-redirect + XSS/malware qua scheme nguy hiểm** | `javascript:alert(1)`, `data:text/html,<script>…`, `vbscript:`, `file:///etc/passwd`, `ftp://…` | **S** + T (XSS) | **High** · CVSS 7.4 · Impact H (A1) | Link `javascript:` mở trong WebView cũ thực thi JS; `data:` HTML chứa form phishing không cần host | 1) **Whitelist scheme `http/https` duy nhất** (`scheme_not_allowed` → `invalid_url`). 2) Từ chối URL có `username/password@`, backtick/whitespace/control chars. 3) Redirect chỉ dùng `Location` header + `no-store`, không render URL vào HTML. 4) Warning page escape mọi tham số |
| **T-11** | **Chiếm alias / typosquatting / reserved-route hijack** | Đăng ký `vietcombank`, `login`, `dashboard`, `api` trước; hoặc `faceb00k-sale` nhái thương hiệu | **S** | **Medium** · CVSS 5.4 · Impact M (A1, A2) | Attacker giữ alias `hotline` rồi đổi đích? (hiện không cho đổi đích — giảm rủi ro); giữ tên gây nhầm lẫn để phishing | 1) Alias regex `^[A-Za-z0-9-]{3,30}$` + `RESERVED_ALIASES` (đồng bộ frontend/backend). 2) Conditional write `attribute_not_exists(short_code)`; alias đã dùng (kể cả `deleted`) **không cấp lại**. 3) Blocklist từ khóa thương hiệu/nhạy cảm (cấu hình được). 4) Admin duyệt `suspicious` trước khi public (Week 2) |
| **T-12** | **Vượt xác thực chủ sở hữu (`X-Owner-Id`) / IDOR** | `X-Owner-Id` là UUID do client tự sinh — ai biết UUID là xóa/list được link người khác; không có auth thật | **E** + I | **High** · CVSS 7.1 · Impact H (A2) | Attacker brute-force/log-steal UUID → `DELETE /links/{code}` link nạn nhân; `GET /links` lộ `long_url` riêng tư | 1) Ghi rõ trong spec/UI: đây là **định danh trình duyệt, không phải bảo mật**. 2) Không trả dữ liệu nhạy cảm ở `/stats` public (đã ẩn `ip_hash`/UA). 3) Week 2: Cognito/JWT cho API quản trị (`block/unblock`, `list all`); hiện tại giới hạn CORS, audit log `owner` + IP-hash. 4) Xoay UUID khi khả nghi; hướng dẫn không chia sẻ UUID |
| **T-13** | **Bỏ qua CAPTCHA (Turnstile bypass)** | Reuse token cũ, dùng token của site khác, gọi API trực tiếp không qua UI, tắt JS | **E** | **Medium** · CVSS 6.0 · Impact M (mở đường cho T-02) | Attacker sniff 1 token hợp lệ rồi replay 1000 lần `POST /shorten` | 1) **Verify mọi token ở server** (`siteverify`, check `success + hostname + action + cdata`, timeout 10s, one-time). 2) Token dùng 1 lần (cache `token-id` đã dùng 5–10 phút). 3) Không tin `turnstile_token` từ query/log; thiếu/sai → `captcha_failed`. 4) Rate-limit theo IP độc lập với CAPTCHA |
| **T-14** | **Đầu độc cache / cache deception (CloudFront)** | `GET /{code}?x=…`, `GET /ABC` vs `/abc` (case), `GET /code%2f…` khiến edge cache nhầm; hoặc ép cache 301 cũ | **T** + I | **Medium** · CVSS 5.0 · Impact M | Attacker dụ nạn nhân mở URL có query lạ → cache redirect sai cho người sau; hoặc 301 cũ (nếu từng dùng) cache vĩnh viễn | 1) Redirect **302 + `Cache-Control: no-store, private`** (TV1 đã chốt — không dùng 301/308). 2) Cache policy: **không cache** `/{code}` và `/api/*` ở CloudFront (TTL 0, forward query-string + `confirm`). 3) Chuẩn hóa `code` case-sensitive đúng spec; trả 404 cho path lạ. 4) Disable range/odd-method cache |
| **T-15** | **Rò rỉ quyền riêng tư qua analytics/logs** | `ip_hash` với salt yếu/cố định vĩnh viễn, log IP/UA gốc vào CloudWatch, `recent_clicks` lộ pattern, salt xoay làm vỡ `unique_visitors` | **I** | **Medium** · CVSS 5.5 · Impact M (A4) | Dev bật debug log in IP thật; salt hard-code trong repo → attacker có DB sẽ brute-force IP không gian nhỏ (IPv4) | 1) `ip_hash = SHA256(ip + salt)` với salt 256-bit từ SSM SecureString/KMS, không log IP/UA (cắt UA 512 ký tự chỉ lưu field, không log). 2) API không trả `ip_hash`/UA (TV4 đã chốt). 3) TTL `clicks` + retention log ngắn; IAM least-privilege đọc logs. 4) Ghi rõ `unique_visitors` là ước tính; xoay salt theo quý + chia kỳ thống kê (TV4 §unique visitors) |

---

## 4. Logic validate URL & chặn IP nội bộ (TypeScript/Node.js — production-grade)

> Tương đương logic Python trong `backend/prototype.py` (`validate_url`, `_parse_ip_literal`, `_is_internal_ip`)
> nhưng bổ sung **bước phân giải DNS** mà prototype chưa có (TV1 §5 giới hạn đã nêu).
> Dùng cho Lambda Backend (Node 20) hoặc middleware Express. Không cần dependency ngoài `node:dns/promises`
> (khuyến nghị thêm `ipaddr.js` nếu muốn parse `inet_aton`-style đầy đủ — code dưới tự xử lý các dạng phổ biến).

```typescript
// safe-url.ts — Validate URL rút gọn + chặn SSRF (self-domain, private IP, DNS rebinding-aware).
// Tương thích ESM + CommonJS (Node 18+). Không log URL/IP ở caller.

import { lookup } from 'node:dns/promises';
import net from 'node:net';

export const MAX_URL_LENGTH = 2048;
export const ALLOWED_SCHEMES = new Set(['http:', 'https:']);
export const RESERVED_ALIASES = new Set([
  'api', 'assets', 'vendor', 'css', 'js', 'mock', 'index', 'dashboard',
  'error', 'warning', 'stats', 'links', 'shorten', 'admin', 'favicon',
]);
export const ALIAS_RE = /^[A-Za-z0-9-]{3,30}$/;
export const BLOCKED_HOSTNAMES = new Set(['localhost']);

export type UrlRejectReason =
  | 'url_empty' | 'url_too_long' | 'url_has_whitespace' | 'url_malformed'
  | 'scheme_not_allowed' | 'credentials_not_allowed' | 'host_missing'
  | 'host_not_allowed' | 'own_domain' | 'dns_failed';

export type AliasRejectReason = 'invalid_alias' | 'alias_taken';

/** IPv4 dạng số nguyên ("2130706433"), octal ("0177.0.0.1"), hex ("0x7f.0.0.1") → dotted quad. */
export function normalizeNumericIPv4(host: string): string | null {
  const h = host.trim();
  if (/^\d+$/.test(h)) {
    // "2130706433" → 127.0.0.1 (inet_aton semantics)
    try {
      const n = BigInt(h);
      if (n < 0n || n > 4294967295n) return null;
      const b = Number(n);
      return `${(b >>> 24) & 255}.${(b >>> 16) & 255}.${(b >>> 8) & 255}.${b & 255}`;
    } catch { return null; }
  }
  const parts = h.split('.');
  if (parts.length > 1 && parts.length <= 4) {
    const nums: number[] = [];
    for (const p of parts) {
      if (!/^(0[xX][0-9a-fA-F]+|0[0-7]*|[0-9]+)$/.test(p)) return null;
      let v: number;
      if (/^0[xX]/.test(p)) v = parseInt(p, 16);
      else if (/^0[0-9]+$/.test(p) && p !== '0') v = parseInt(p, 8); // octal né lọc
      else v = parseInt(p, 10);
      if (!Number.isSafeInteger(v) || v < 0 || v > 4294967295) return null;
      nums.push(v);
    }
    // inet_aton: phần cuối chiếm các byte còn lại
    if (nums.some((v) => v > 255) && !(nums.length === 2 && nums[1] <= 16777215)
        && !(nums.length === 3 && nums[2] <= 65535)) return h; // để URL parser báo lỗi
    let n = 0;
    if (nums.length === 2) n = nums[0] * 16777216 + nums[1];
    else if (nums.length === 3) n = nums[0] * 16777216 + nums[1] * 256 + nums[2];
    else if (nums.length === 4 && nums.every((v) => v <= 255)) {
      return nums.join('.');
    } else return null;
    n >>>= 0;
    return `${(n >>> 24) & 255}.${(n >>> 16) & 255}.${(n >>> 8) & 255}.${n & 255}`;
  }
  return null;
}

/** true nếu IP thuộc dải cấm (loopback, private 10/8–172.16/12–192.168/16, link-local 169.254/16 incl. IMDS, reserved/multicast/unspecified, IPv6 ULA/link-local/loopback/mapped). */
export function isBlockedIp(ip: string): boolean {
  const v = net.isIP(ip);
  if (v === 4) {
    const o = ip.split('.').map(Number);
    if (o[0] === 127) return true;                                    // 127.0.0.0/8
    if (o[0] === 10) return true;                                     // 10.0.0.0/8
    if (o[0] === 172 && o[1] >= 16 && o[1] <= 31) return true;        // 172.16.0.0/12
    if (o[0] === 192 && o[1] === 168) return true;                    // 192.168.0.0/16
    if (o[0] === 169 && o[1] === 254) return true;                    // 169.254.0.0/16 (IMDS)
    if (o[0] === 0) return true;                                      // 0.0.0.0/8
    if (o[0] >= 224) return true;                                     // multicast + reserved 240/4
    if (o[0] === 192 && o[1] === 0 && o[2] === 2) return true;         // TEST-NET-1 (docs)
    if (o[0] === 198 && o[1] === 51 && o[2] === 100) return true;     // TEST-NET-2
    if (o[0] === 203 && o[1] === 0 && o[2] === 113) return true;      // TEST-NET-3
    if (o[0] === 192 && o[1] === 88 && o[2] === 99) return true;      // 6to4 relay (historic)
    return false;
  }
  if (v === 6) {
    const low = ip.toLowerCase();
    if (low === '::1' || low === '::') return true;
    if (low.startsWith('fe80:') || low.startsWith('fec0:') || low.startsWith('fc00:') || low.startsWith('fd')) return true; // link-local/site-local/ULA
    if (low.startsWith('ff')) return true;                            // multicast
    if (low.startsWith('::ffff:')) {                                  // IPv4-mapped → đệ quy
      const tail = ip.slice(7);
      const dotted = normalizeNumericIPv4(tail) ?? tail;
      if (net.isIP(dotted) === 4) return isBlockedIp(dotted);
      return true;
    }
    return false;
  }
  return true; // không parse được → chặn an toàn
}

export interface ValidateOptions {
  ownDomains: string[];          // ví dụ ['linkpulse.vn', 'd123.cloudfront.net']
  blockedDomains?: string[];    // blocklist TV3/TV5
  resolveDns?: boolean;          // true ở Lambda (khuyến nghị), false ở unit-test
}

function hostMatches(host: string, list: string[]): boolean {
  return list.some((d) => {
    const dd = d.toLowerCase().trim().replace(/\.$/, '');
    return host === dd || host.endsWith('.' + dd);
  });
}

/** Bước 1 — kiểm tra cú pháp (đồng bộ, rẻ, chạy ở mọi nơi kể cả edge). */
export function validateUrlSyntax(raw: string, opts: ValidateOptions): { ok: true; url: URL } | { ok: false; reason: UrlRejectReason } {
  if (typeof raw !== 'string' || !raw.trim()) return { ok: false, reason: 'url_empty' };
  if (raw !== raw.trim() || /\s/.test(raw)) return { ok: false, reason: 'url_has_whitespace' };
  if (raw.length > MAX_URL_LENGTH) return { ok: false, reason: 'url_too_long' };
  let url: URL;
  try { url = new URL(raw); } catch { return { ok: false, reason: 'url_malformed' }; }
  // URL parser chấp nhận cổng rác? new URL('http://h:abc/') ném lỗi → đã bắt ở trên.
  if (!ALLOWED_SCHEMES.has(url.protocol)) return { ok: false, reason: 'scheme_not_allowed' }; // chặn javascript:, data:, file:, ftp:, vbscript:
  if (url.username || url.password) return { ok: false, reason: 'credentials_not_allowed' };
  let host = (url.hostname || '').toLowerCase().replace(/\.$/, '');
  if (!host) return { ok: false, reason: 'host_missing' };
  if (BLOCKED_HOSTNAMES.has(host) || host.endsWith('.localhost')) return { ok: false, reason: 'host_not_allowed' };
  if (hostMatches(host, opts.ownDomains)) return { ok: false, reason: 'own_domain' }; // chống loop/self-ref (T-04/T-05)
  // Ghi chú: blocklist nội bộ KHÔNG kiểm tra ở đây mà ở validateLongUrl (bước sau),
  // để caller map đúng mã lỗi api_spec.yaml: trúng blocklist → blocked_domain,
  // còn lại → invalid_url. Không gộp hai mã này lại.
  // IP literal (kể cả dạng né) → kiểm tra ngay không cần DNS
  const asDotted = normalizeNumericIPv4(host);
  const literal = asDotted ?? host;
  if (net.isIP(literal)) {
    if (isBlockedIp(literal)) return { ok: false, reason: 'host_not_allowed' };
    return { ok: true, url };
  }
  // Tên miền thường: cấm ký tự lạ còn sót (URL parser đã chuẩn hóa punycode xn--)
  if (/[\\\s]/.test(host)) return { ok: false, reason: 'url_malformed' };
  return { ok: true, url };
}

/** Bước 2 — kiểm tra DNS (bắt buộc trước khi lưu + trước mỗi fetch server-side; chống DNS rebinding). */
export async function assertDnsSafe(hostname: string): Promise<{ ok: true; ips: string[] } | { ok: false; reason: UrlRejectReason }> {
  const host = hostname.toLowerCase().replace(/\.$/, '');
  const literal = normalizeNumericIPv4(host) ?? host;
  if (net.isIP(literal)) {
    return isBlockedIp(literal) ? { ok: false, reason: 'host_not_allowed' } : { ok: true, ips: [literal] };
  }
  let records: string[];
  try {
    records = await lookup(host, { all: true }).then((rs) => rs.map((r) => r.address));
  } catch {
    return { ok: false, reason: 'dns_failed' };
  }
  if (records.length === 0) return { ok: false, reason: 'dns_failed' };
  // CHẶN nếu BẤT KỲ bản ghi nào là IP nội bộ (kẻ tấn công hay gài 1 A public + 1 A private)
  for (const ip of records) {
    const norm = normalizeNumericIPv4(ip) ?? ip;
    if (isBlockedIp(norm)) return { ok: false, reason: 'host_not_allowed' };
  }
  return { ok: true, ips: records };
}

/** Hàm tổng: dùng ở Lambda POST /shorten. Ném lỗi có `code` khớp api_spec.yaml. */
export async function validateLongUrl(raw: string, opts: ValidateOptions): Promise<URL> {
  const s = validateUrlSyntax(raw, opts);
  // Mọi lỗi cú pháp/host đều map về `invalid_url` + giữ `reason` chi tiết để debug
  // (đúng hợp đồng api_spec.yaml: invalid_url bao gồm URL nội bộ, sai scheme, own-domain...).
  if (!s.ok) throw Object.assign(new Error(`URL rejected: ${s.reason}`), { status: 400, code: 'invalid_url', reason: s.reason });
  if (opts.blockedDomains && hostMatches(s.url.hostname.toLowerCase(), opts.blockedDomains)) {
    throw Object.assign(new Error('Domain blocked'), { status: 400, code: 'blocked_domain' });
  }
  if (opts.resolveDns !== false) {
    const d = await assertDnsSafe(s.url.hostname);
    if (!d.ok) throw Object.assign(new Error(`DNS rejected: ${d.reason}`), { status: 400, code: 'invalid_url', reason: d.reason });
  }
  return s.url;
}

/** Validate alias + tên dành riêng (đồng bộ với TV2/TV1). */
export function validateAlias(alias: string | undefined): { ok: true } | { ok: false; reason: AliasRejectReason } {
  if (alias === undefined) return { ok: true };
  if (typeof alias !== 'string' || !ALIAS_RE.test(alias)) return { ok: false, reason: 'invalid_alias' };
  if (RESERVED_ALIASES.has(alias.toLowerCase())) return { ok: false, reason: 'alias_taken' };
  return { ok: true };
}

// Ví dụ dùng trong Lambda (Node 20):
// import { validateLongUrl } from './safe-url.js';
// try {
//   await validateLongUrl(body.url, {
// //   ownDomains: [process.env.OWN_DOMAIN!, process.env.CLOUDFRONT_DOMAIN!].filter(Boolean),
// //   blockedDomains: await loadBlocklist(), // từ DynamoDB blocklist (cache 60s)
// //   resolveDns: true,
// // });
// // } catch (e: any) {
// //   return { statusCode: e.status ?? 400, body: JSON.stringify({ error: { code: e.code ?? 'invalid_url', reason: e.reason } }) };
// // }
```

**Regex chủ chốt:**

| Mục đích | Pattern | Ghi chú |
|----------|---------|---------|
| Alias | `^[A-Za-z0-9-]{3,30}$` | Khớp `api_spec.yaml` + prototype TV1; case-sensitive |
| Short-code tự sinh | Base62 `^[A-Za-z0-9]{7}$` | Sinh bằng `crypto.randomBytes`/`secrets`, không dùng `Math.random` |
| ISO-8601 UTC | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$` | Khớp `click_event_schema.json` |
| Scheme | whitelist `http:`/`https:` sau `new URL()` | Không dùng regex đen (dễ bypass `JaVaScRiPt:`) |
| Country | `^[A-Z]{2}$` | `XX` khi thiếu |

**Checklist SSRF cho reviewer (paste vào PR):**

- [ ] Mọi IP literal (kể cả `2130706433`, `127.1`, `0x7f.1`, `::ffff:127.0.0.1`) đều bị chặn ở `validateUrlSyntax`.
- [ ] Mọi hostname đều qua `assertDnsSafe` và chặn nếu **bất kỳ** A/AAAA nào là private.
- [ ] Fetcher server-side (nếu có) tắt auto-redirect, re-validate mỗi hop, pin IP đã resolve, timeout ≤ 8s, giới hạn 1 MB.
- [ ] Không log URL/IP; lỗi trả về chỉ có `code` + `reason` an toàn (`host_not_allowed`, `own_domain`).

---

## 5. Ma trận truy vết Mitigation → Nơi triển khai

| Mitigation | WAF/CloudFront | API GW | Lambda | DynamoDB | Frontend | Week |
|------------|----------------|--------|--------|----------|----------|------|
| Rate-based rule `/shorten` + `/​{code}` | ✅ | — | — | — | — | 1–2 |
| Managed Rules (Common, KnownBadInputs, IP Reputation) | ✅ | — | — | — | — | 2 |
| Throttle + token bucket `rate_limits` | — | ✅ | ✅ | ✅ | hiển thị 429/`Retry-After` | 2 |
| Validate URL 2 lớp + own-domain + reserved alias | — | — | ✅ | — | ✅ (UX sớm) | 1 ✅ (prototype) |
| Turnstile verify server-side | — | — | ✅ | cache token | ✅ widget | 2 |
| GSB/URLhaus async + cache verdict | — | — | ✅ worker | ✅ `blocklist` + TTL | warning page | 2 |
| 302 + `no-store`, không cache `/{code}` | ✅ behavior | — | ✅ header | — | `rel=noopener` | 1 ✅ |
| Conditional write + alias không cấp lại | — | — | ✅ | ✅ | — | 1 ✅ |
| Bot tách `bot_clicks`, alarm spike | — | — | ✅ | ✅ `stats_agg` | dashboard tách bot | 2 |
| IP-hash salt KMS + TTL +最小 log | — | — | ✅ | ✅ TTL | — | 2 |
| Budget $5 + billing alarm + kill-switch | — | — | — | — | — | 1 (foundation script) |

---

## 6. Rủi ro còn lại (Residual) & giám sát

1. **Re-scan URL sau khi tạo:** URL sạch lúc tạo có thể bị đổi thành phishing sau đó (domain hết hạn → attacker mua lại). → Worker re-check GSB/URLhaus mỗi 6–24h + chuyển `active → suspicious/blocked` (Week 3).
2. **`X-Owner-Id` yếu:** chấp nhận cho đồ án; mọi API destructive phải có audit log + xác nhận UI; nâng lên Cognito khi có auth thật.
3. **DNS rebinding giữa validate và fetch:** giảm bằng resolve-lại + pin IP + TTL cache ngắn (60s); không fetch ở request nóng.
4. **WAF false-positive:** Managed Rules có thể chặn traffic hợp lệ (đặc biệt Common Rule Set với query lạ) → bật Count mode trước, xem log 3–7 ngày rồi chuyển Block.
5. **Giám sát tối thiểu (CloudWatch):** `4xx/5xx` theo route, `WAFBlockedRequests`, `Lambda Throttles/Errors/Duration`, `DynamoDB ThrottledRequests`, `IteratorAge` (Streams), billing alarm. Dashboard vận hành riêng với dashboard sản phẩm của TV2.

---

## 7. Tài liệu tham khảo

- OWASP Top 10:2021 · OWASP API Security Top 10:2023 · OWASP Cheat Sheets (SSRF Prevention, Input Validation, CAPTCHA).
- Microsoft STRIDE · CVSS v3.1 Specification.
- AWS: WAF rate-based rules, Managed Rules, CloudFront cache policies/origin request policies, IMDSv2, SSM SecureString/KMS.
- Google Safe Browsing API v4 · abuse.ch URLhaus API.
- Cloudflare Turnstile (siteverify).
- Tài liệu nhóm: `docs/backend_research.md`, `docs/api_spec.yaml`, `docs/analytics_research.md`, `backend/prototype.py`.
