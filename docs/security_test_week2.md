# Kiểm chứng lớp chống lạm dụng — tuần 2

> **Module:** TV5 · **Issue:** #27 (chi tiết) · **Issue:** #11 (tổng hợp tuần 2)
> **Người thực hiện:** `piupear206-oss` — `liamnguyen.piupear206@gmail.com`
> **Ngày chạy:** 2026-11-10 (giờ Việt Nam) · **Tài khoản AWS:** `567627324019`
> **Trạng thái:** đã chạy thật trên môi trường đã deploy. Riêng WAF **chưa chạy** (giữ `EnableWaf=false` để chi phí $0) — mục 1 trình bày bằng thiết kế.

Lớp phòng thủ theo thứ tự request đi qua:

```
Client → CloudFront → [WAF] → [API Gateway throttling] → [Lambda rate limit theo IP]
       → [X-Origin-Verify] → [validate URL + blocklist] → [Turnstile] → DynamoDB
```

Mỗi lớp chặn ở một chỗ khác nhau nên phải kiểm từng lớp, không gộp.

---

## 0. Triển khai và phân quyền thực tế

> Đây là 3 ô còn trống ở issue #11. Ghi lại trạng thái thật, không suy đoán.

### 0.1 Deploy thử edge

| Mục | Giá trị thực tế |
|---|---|
| Ngày giờ deploy edge | 2026-11-04 07:59:22 UTC (14:59 giờ Việt Nam) |
| Region stack edge | `ap-southeast-2` (**không phải** `us-east-1`) |
| Lý do chọn region này | SCP của tổ chức chặn `us-east-1` cho user `linkpulse-tv5` (xem mục 0.3). Vì `EnableWaf=false` và không dùng domain riêng nên edge **không bắt buộc** ở `us-east-1` (chỉ WAF phạm vi `CLOUDFRONT` và chứng chỉ ACM mới cần). |
| Tên stack edge | `linkpulse-edge` |
| Domain CloudFront | `d3rsimgoxz85kx.cloudfront.net` |
| Distribution ID | `E240XHWY20B7CL` |
| Bucket giao diện (output `FrontendBucketName`) | `linkpulse-edge-frontendbucket-dkefldigoegt` |
| Tham số edge | `ApiDomain=q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com`, `EnableWaf=false`, `DomainName=` (trống), `CertificateArn=` (trống), `ShortenRateLimitPer5Min=50`, `RateLimitPer5Min=1000`, `OriginVerifySecret=/linkpulse/origin-verify` |
| Tài nguyên trong stack | `Distribution`, `FrontendBucket`, `FrontendBucketPolicy`, `FrontendOac`, `RootRedirectFunction`, `ApiOriginRequestPolicy`, `SecurityHeadersPolicy`, `StaticCachePolicy` — tất cả `CREATE_COMPLETE` |

Ảnh bằng chứng: [01-s3-bucket](screenshots/aws/01-s3-bucket.png),
[02-cloudfront-enabled-domain](screenshots/aws/02-cloudfront-enabled-domain.png).

### 0.2 Deploy edge đúng thứ tự

Thứ tự đã chạy thật (quyết định 3 trong `docs/QUYET_DINH_CHOT_TUAN_2.md`):

| Bước | Thời điểm (UTC) | Nội dung |
|---|---|---|
| 1. Backend lần 1 | 2026-11-04 06:44:33 | `sam deploy` stack `linkpulse-backend` ở `ap-southeast-2`, `BaseUrl` tạm `https://linkpulse.vn`, `OriginVerifySecretParam=` (tắt) |
| 2. Bí mật origin vào SSM | trước 07:59 UTC | `aws ssm put-parameter --name /linkpulse/origin-verify --type SecureString` ở `ap-southeast-2` (kiểm bằng `aws ssm get-parameter` trả `SecureString`) |
| 3. Edge | 2026-11-04 07:59:22 | `sam deploy` stack `linkpulse-edge` ở `ap-southeast-2` với `ApiDomain` lấy từ output `ApiDomain` của backend lần 1 và `OriginVerifySecret` trỏ vào SSM |
| 4. Backend lần 2 | 2026-11-04 10:44:17 | Cập nhật `BaseUrl=https://d3rsimgoxz85kx.cloudfront.net`, `OwnDomains=d3rsimgoxz85kx.cloudfront.net`, bật `OriginVerifySecretParam=/linkpulse/origin-verify` |

Chi tiết từng lần deploy, changeset và bảng lệnh `curl` nằm ở [`docs/smoke_test.md`](smoke_test.md) (mục "Lần 1" và "Lần 2").
Ảnh: `docs/screenshots/aws/lan2/deploy-success-and-curl.png`.

### 0.3 IAM — cách nhóm đang cấp quyền thật

**Sự thật đang diễn ra (không phải đề xuất):**

1. Nhóm **chưa** chạy `scripts/setup_aws_foundation.sh` để cấp quyền từng người. Script có sẵn trong repo (`scripts/setup_aws_foundation.sh` và `.ps1`, quyền theo vai trò `deployer` / `frontend` / `reader` theo quyết định 17) nhưng **chưa chạy được** — user đang dùng không có `iam:*` (xem bằng chứng chạy thật ở mục 0.4).
2. Trong thời gian chờ đó, nhóm dùng **một user IAM dùng chung** do TV5 tạo: `arn:aws:iam::567627324019:user/linkpulse-tv5`. Key nằm trong `~/.aws/credentials` dưới profile `[default]`.
3. Người chạy test là chính user đó nên **không có** console access (không có `LoginProfile`), và các API quản trị IAM bị chặn:

   ```text
   $ aws iam list-users
   aws: [ERROR]: An error occurred (AccessDenied) when calling the ListUsers operation:
   User: arn:aws:iam::567627324019:user/linkpulse-tv5 is not authorized to perform: iam:ListUsers

   $ aws iam get-group --group-name linkpulse-devs
   aws: [ERROR]: An error occurred (AccessDenied) when calling the GetGroup operation: ...

   $ aws iam list-policies --scope Local
   aws: [ERROR]: An error occurred (AccessDenied) when calling the ListPolicies operation: ...
   ```

   Bằng chứng cho phần này là output lỗi trên. Riêng mục **chi phí $0** đã có thêm ảnh chụp trực tiếp
   từ AWS Console (mục 7.2): đăng nhập bằng **root user** của tài khoản `567627324019` rồi mở
   **Billing and Cost Management → Cost Explorer** — `Total cost -$0.00` cho kỳ `2026-11-01 — 2026-11-10`.
4. User này bị SCP của tổ chức chặn `us-east-1` cho CloudFormation:

   ```text
   $ aws cloudformation describe-stacks --stack-name linkpulse-edge --region us-east-1
   aws: [ERROR]: An error occurred (AccessDenied) ... with an explicit deny in a service control policy:
   arn:aws:organizations::331545064122:policy/o-gum3yrtvzo/service_control_policy/p-tbg8xbnv
   ```

   Đây chính là lý do edge deploy ở `ap-southeast-2` (mục 0.1).
5. IAM **trong CloudFormation** thì đã đúng: stack `linkpulse-backend` tạo 4 Lambda Role (`ShortenFunctionRole`, `RedirectFunctionRole`, `LinksFunctionRole`, `ProcessClicksFunctionRole`, `HealthFunctionRole`, `StatsFunctionRole`) và 1 ManagedPolicy `OriginSecretReadPolicy`. Không cấp `iam:*` cho Lambda — mỗi Lambda chỉ có đúng quyền cần dùng.

**Kết luận:** phần "phân quyền từng người" **chưa chạy được**; mọi kiểm thử dưới đây chạy bằng user chung `linkpulse-tv5`. Xem [`scripts/setup_aws_foundation.sh`](../scripts/setup_aws_foundation.sh) để biết cách cấp quyền đúng khi có `iam:*`.

### 0.4 Chạy thật script phân quyền — dừng ở bước preflight (bằng chứng)

Ngày 2026-11-10, TV5 đã chạy thật cả hai bản script trên tài khoản `567627324019`. Cả hai **dừng
ở bước preflight** với thông báo rõ ràng thay vì lỗi `AccessDenied` xen giữa quá trình
(bản `.ps1` trước đây crash vì PowerShell coi stderr của AWS CLI là exception — đã sửa).

**PowerShell (`scripts/setup_aws_foundation.ps1`):**

```text
==> Account: 567627324019 | Region workload: ap-southeast-2 | Region edge: us-east-1 | Budget: $5/mo

!! KHÔNG ĐỦ QUYỀN — script cần quyền IAM admin (iam:*) và budgets:*.
   Caller hiện tại: arn:aws:iam::567627324019:user/linkpulse-tv5
   Lỗi: aws: [ERROR]: An error occurred (AccessDenied) when calling the GetGroup operation: User:
   arn:aws:iam::567627324019:user/linkpulse-tv5 is not authorized to perform: iam:GetGroup on resource:
   group linkpulse-devs because no identity-based policy allows the iam:GetGroup action.

   Cách xử lý:
   1) Chạy script này bằng root user hoặc IAM admin của tài khoản 567627324019.
   2) Hoặc admin gán cho user hiện tại: iam:CreateUser, iam:CreateGroup, iam:CreatePolicy,
      iam:AttachUserPolicy, iam:AttachGroupPolicy, iam:PutUserPolicy, iam:CreateLoginProfile,
      iam:UpdateAccountPasswordPolicy, budgets:CreateBudget, budgets:UpdateBudget.
```

**Bash (`scripts/setup_aws_foundation.sh`)** cho ra cùng kết luận:

```text
==> Account: 567627324019 | Region workload: ap-southeast-2 | Region edge: us-east-1 | Budget: $5/mo

!! KHÔNG ĐỦ QUYỀN — script cần quyền IAM admin (iam:*) và budgets:*.
   Caller hiện tại: arn:aws:iam::567627324019:user/linkpulse-tv5
   Lỗi: aws: [ERROR]: An error occurred (AccessDenied) when calling the GetGroup operation: ...
```

**Điều đã chạy được và còn lại trong account:**

| Hạng mục | Trạng thái | Cách kiểm chứng |
|---|---|---|
| AWS Budget `linkpulse-monthly-ap-southeast-2-5usd` | ✅ **Đã có** — giới hạn `5.0 USD`/tháng, lọc Region `ap-southeast-2`, `ActualSpend = 0.0 USD` | `aws budgets describe-budgets --account-id 567627324019 --region us-east-1` |
| Group `linkpulse-devs` + 4 policy theo vai trò | ❌ **Chưa tạo** — cần `iam:*` | `aws iam get-group --group-name linkpulse-devs` → `AccessDenied` |
| IAM user riêng cho từng thành viên + MFA | ❌ **Chưa tạo** | `aws iam list-users` → `AccessDenied` |
| LoginProfile (console access) cho `linkpulse-tv5` | ❌ **Chưa có** — user chỉ có access key | `aws iam get-login-profile --user-name linkpulse-tv5` → `AccessDenied` |

> **Cách admin chạy được:** đăng nhập AWS Console bằng **root user** của `567627324019`, rồi chạy
> `scripts/setup_aws_foundation.ps1` (hoặc `.sh`) với danh sách thành viên. Budget đã tạo nên
> script chỉ cần phần IAM. Cần `iam:*` + `budgets:*`.

---

## 0.5 Chuẩn bị

```bash
# Domain CloudFront và domain API Gateway (lấy từ output của stack)
CF_DOMAIN="d3rsimgoxz85kx.cloudfront.net"
API_DOMAIN="q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com"

# Kiểm tra tài khoản đã bật MFA
aws sts get-caller-identity
```

| Ký hiệu | Ý nghĩa |
|---|---|
| `CF_DOMAIN` | domain `*.cloudfront.net` của stack edge |
| `API_DOMAIN` | domain `*.execute-api.ap-southeast-2.amazonaws.com` |

Tạo link để có mã hợp lệ dùng trong các bước sau:

```bash
curl -s -X POST "https://$CF_DOMAIN/api/shorten" \
  -H 'Content-Type: application/json' \
  -H 'X-Owner-Id: 11111111-1111-4111-8111-111111111111' \
  -d '{"url":"https://example.com"}'
```

Lấy `code` trong kết quả, thay cho `<code>` bên dưới.

---

## 1. WAF — chặn theo ngưỡng

> **Chưa chạy — trình bày bằng thiết kế (`infra/edge.yaml`, `EnableWaf=false`).**
>
> Lý do: giữ chi phí $0. AWS WAF (phạm vi `CLOUDFRONT`) có phí theo Web ACL + request + rule, bật lên sẽ phá vỡ yêu cầu "chi phí $0" của TV5. Ngoài ra SCP của tổ chức chặn `us-east-1`, mà WAF phạm vi `CLOUDFRONT` chỉ deploy được ở `us-east-1` — tức là bật WAF còn bị chặn bởi chính sách tài khoản.
>
> Tham số `EnableWaf` (mặc định `false`) đã có trong `infra/edge.yaml`; Web ACL, association, logging và bucket `waf_logs` đều được bọc trong `Condition` nên khi `EnableWaf=false` thì **không** tạo tài nguyên nào — xem output stack edge ở mục 0.1: không có resource WAF nào trong danh sách.

Cách bật/tắt (để dùng khi có điều kiện phù hợp — region được mở và ngân sách cho phép):

```bash
cd backend
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=$API_DOMAIN OriginVerifySecret="$SECRET" EnableWaf=true
```

Vượt ngưỡng rate-based của `POST /api/shorten` (mặc định 50 request / 5 phút / IP):

```bash
for i in $(seq 1 60); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "https://$CF_DOMAIN/api/shorten" \
    -H 'Content-Type: application/json' \
    -H 'X-Owner-Id: 11111111-1111-4111-8111-111111111111' \
    -d '{"url":"https://example.com/waf-test"}'
done
```

- Kết quả mong đợi: các request đầu trả `201`, các request sau vượt ngưỡng trả `403` (WAF chặn ở edge,
  không vào API Gateway nên không có lượt gọi Lambda).
- Chụp ảnh CloudWatch → WAF → `BlockedRequests` theo rule.

Tắt WAF ngay sau khi kiểm thử và xác nhận Web ACL đã bị xoá:

```bash
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=$API_DOMAIN OriginVerifySecret="$SECRET" EnableWaf=false

aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1
```

- Kết quả mong đợi: danh sách không còn Web ACL của stack edge.

**Bằng chứng:** ☐ lệnh + output · ☐ ảnh BlockedRequests · ☐ ảnh Web ACL đã xoá
→ **Chưa chạy** (xem lý do trên). Mục 4 (403 khi gọi thẳng origin) đã chạy thật và cho thấy lớp
biên có tác dụng, nhưng đó là `X-Origin-Verify`, **không phải** WAF.

---

## 2. API Gateway throttling

Route `POST /api/shorten` giới hạn 10 request/giây, burst 20. Toàn API giới hạn 100/giây, burst 200.

> **Đã chạy.** Ngày 2026-11-10, dùng `scripts/test_throttling.py` (Python + thread, `Barrier` để đẩy
> đồng thời thật sự). Lý do không dùng `xargs -P 30` như gợi ý: mỗi request của `xargs -P` phải spawn
> một tiến trình `bash` + `curl`, độ trễ spawn làm các request tới lệch nhau vài trăm ms nên **tốc độ
> thực tế không vượt quá 10 rps** → API Gateway không kịp trả 429, chỉ thấy lớp rate limit của
> Lambda. Script Python giữ lại `--par`/`--conc` để chỉnh độ song song.

```bash
python scripts/test_throttling.py --par 120 --conc 60
```

Output thực tế (rút gọn):

```text
Bắt đầu lúc 2026-11-10T08:03:00Z UTC
Gửi 120 request, 60 chạy song song

--- thời gian gửi: 4.39s (tốc độ 27.4 rps) ---
--- tổng hợp mã trả về ---
    99  HTTP 429
    11  HTTP 503
    10  HTTP 201

--- phân loại hai lớp 429 ---
  API Gateway 429 (body message/Too Many Requests, không có Retry-After): 35
  Lambda rate limit 429 (body error.code/rate_limited, có Retry-After):   64
  429 khác:                                                                    0

--- 12 request 429 đầu tiên ---
    2  HTTP 429  2.166s  Retry-After=none  {"message":"Too Many Requests"}
    4  HTTP 429  2.897s  Retry-After=none  {"message":"Too Many Requests"}
    6  HTTP 429  2.163s  Retry-After=none  {"message":"Too Many Requests"}
    7  HTTP 429  2.505s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
    9  HTTP 429  2.678s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   12  HTTP 429  2.913s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   13  HTTP 429  3.581s  Retry-After=54  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 54}}
   14  HTTP 429  2.552s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   20  HTTP 429  2.503s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   21  HTTP 429  2.016s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   23  HTTP 429  1.841s  Retry-After=56  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}
   26  HTTP 429  2.101s  Retry-After=none  {"message":"Too Many Requests"}

--- 6 request lỗi khác ---
    3  HTTP 503  2.445s  {"message":"Service Unavailable"}
    5  HTTP 503  2.346s  {"message":"Service Unavailable"}
    8  HTTP 503  3.120s  {"message":"Service Unavailable"}
   11  HTTP 503  2.480s  {"message":"Service Unavailable"}
   22  HTTP 503  1.826s  {"message":"Service Unavailable"}
   24  HTTP 503  2.311s  {"message":"Service Unavailable"}
```

**Hai lớp 429 đã phân biệt được:**

| Lớp | Mã | Body | Header `Retry-After` | Số lần (lần chạy này) |
|---|---|---|---|---|
| API Gateway throttling | `429` | `{"message":"Too Many Requests"}` | **không có** | 35 |
| Rate limit trong Lambda (theo IP) | `429` | `{"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 56}}` | có (56 → 40 giây) | 64 |

> Ghi chú: 11 request trả `503 {"message":"Service Unavailable"}` — đây là lớp quota của API Gateway
> (HTTP API trả `503` khi đã vượt mức throttle hoặc hết quota), **không phải** 429 nên không tính
> vào hai lớp trên. Header của 429/503 đã kiểm tra: không có `x-amzn-ErrorType`, không có
> `x-amzn-RequestId` (CloudFront đã bỏ header định danh request của API Gateway trước khi trả về),
> nên phân biệt dựa vào **body** — đúng như yêu cầu của issue #27.

Ảnh bằng chứng: [06-apigateway-throttling](screenshots/aws/lan3/06-apigateway-throttling.png)
(text gốc: `docs/screenshots/aws/lan3/06-apigateway-throttling.png`).

**Bằng chứng:** ☑ output 429 của cả hai lớp (có body và header `Retry-After`)

---

## 3. Rate limit theo IP trong Lambda

Bảng `rate_limits` giới hạn 10 lần/phút cho `POST /api/shorten` (tham số `SHORTEN_RATE_LIMIT`).

> **Đã chạy.** Ngày 2026-11-10, dùng `scripts/test_ratelimit.sh` (chạy đúng đầu phút UTC vì giới hạn
> tính theo cửa sổ 60 giây dùng mốc `now // 60`).

```bash
bash scripts/test_ratelimit.sh
```

Output thực tế:

```text
Bắt đầu lúc 2026-11-10T07:49:01Z UTC
CF_DOMAIN=d3rsimgoxz85kx.cloudfront.net  OWNER=33333333-3333-4333-8333-333333333333

 1  HTTP 201  Retry-After=<khong co>  {"code": "b5iFeoZ", ... "created": true, "long_url": "https://example.com/rl-test-1", ...}
 2  HTTP 201  Retry-After=<khong co>  {"code": "IOKcuQG", ...}
 3  HTTP 201  Retry-After=<khong co>  {"code": "hYvp04m", ...}
 4  HTTP 201  Retry-After=<khong co>  {"code": "LWLSjck", ...}
 5  HTTP 201  Retry-After=<khong co>  {"code": "NcNvOA0", ...}
 6  HTTP 201  Retry-After=<khong co>  {"code": "e1BWklO", ...}
 7  HTTP 201  Retry-After=<khong co>  {"code": "Ql3PE4y", ...}
 8  HTTP 201  Retry-After=<khong co>  {"code": "szpRX3X", ...}
 9  HTTP 201  Retry-After=<khong co>  {"code": "WXu3s5v", ...}
10  HTTP 201  Retry-After=<khong co>  {"code": "3gh0X4p", ...}
11  HTTP 429  Retry-After=41  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 41}}
12  HTTP 429  Retry-After=40  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 40}}
13  HTTP 429  Retry-After=39  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 39}}
14  HTTP 429  Retry-After=39  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 39}}
15  HTTP 429  Retry-After=38  {"error": {"code": "rate_limited", "message": "Bạn thao tác quá nhanh.", "retry_after": 38}}

Kết thúc lúc 2026-11-10T07:49:21Z UTC
```

**Kết quả đúng như yêu cầu:** 10 request đầu thành công (`201`), từ request thứ 11 trả `429` kèm
header `Retry-After` (41 → 38 giây, đếm ngược về hết cửa sổ 60 giây).

Kiểm tra bảng `rate_limits`:

```bash
aws dynamodb scan --table-name linkpulse-backend-RateLimitsTable-M1Q1J64G9Q1 --region ap-southeast-2
```

Bản ghi sau lần chạy (khóa `pk = shorten#<ip_hash>#<bucket>`):

```json
{
    "cnt": { "N": "10" },
    "expires_at": { "N": "1794297060" },
    "pk": { "S": "shorten#0cff739176b21ff8#29904949" }
}
```

`cnt = 10` đúng bằng số request cho phép trong cửa sổ; `expires_at` là epoch giây hết hạn bản ghi.

Ảnh bằng chứng:
[01-ratelimit-output](screenshots/aws/lan3/01-ratelimit-output.png) ·
[02-rate-limits-table](screenshots/aws/lan3/02-rate-limits-table.png)

**Bằng chứng:** ☑ output 429 + `Retry-After` · ☑ ảnh bảng `rate_limits`

---

## 4. Gọi thẳng API Gateway bị 403

Khi `OriginVerifySecretParam` đã bật, backend chỉ nhận request có header `X-Origin-Verify` đúng giá trị
mà CloudFront gắn vào (`backend/src/linkpulse/origin.py`).

> **Đã chạy** trong smoke test lần 2 (2026-11-04) — không cần chạy lại.

```bash
# Gọi thẳng API Gateway, không qua CloudFront
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://$API_DOMAIN/api/health"

# Gọi qua CloudFront — phải qua được
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://$CF_DOMAIN/api/health"
```

- Kết quả mong đợi: gọi thẳng → `403`; qua CloudFront → `200`.
- Giả lập thêm header sai:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H 'X-Origin-Verify: sai-gia-tri' "https://$API_DOMAIN/api/health"
```

Ảnh và kết quả đã có sẵn:
- [`docs/screenshots/aws/lan2/smoke-direct-403.png`](screenshots/aws/lan2/smoke-direct-403.png) — gọi thẳng API Gateway trả `403`.
- [`docs/smoke_test.md`](smoke_test.md) — mục "Lần 2 (BaseUrl là domain CloudFront, gọi qua CloudFront)",
  dòng 2 của bảng: `curl.exe -s "$API/api/health"` (gọi thẳng, không qua CloudFront) → `403`.
  Ghi chú cùng file: lý do là `reason: origin_not_allowed`, còn qua CloudFront thì chạy — cơ chế
  `X-Origin-Verify` hoạt động.

**Bằng chứng:** ☑ output 403 và 200 (ảnh `smoke-direct-403.png` + dòng 2 của `smoke_test.md`)

---

## 5. Link vượt ngưỡng thành suspicious

Phát hiện lạm dụng chạy trong `process_clicks` (DynamoDB Stream của bảng `clicks`):
`SpikeClicksPerMinute` (mặc định 300) và `BotMinClicks` (mặc định 50) + `BotRatio` (mặc định 0.8).
Khi demo, deploy với ngưỡng thấp để chỉ cần khoảng 30 lệnh curl.

> **Đã chạy** — do TV4 chạy, TV5 chỉ đọc kết quả. Không chạy lại để không làm bẩn số liệu của TV4.

```bash
# Bot: User-Agent giống crawler
for i in $(seq 1 60); do
  curl -s -o /dev/null "https://$CF_DOMAIN/<code>" \
    -H 'User-Agent: Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
done

# Đợi stream xử lý rồi kiểm tra trạng thái link
sleep 15
aws dynamodb get-item --table-name <UrlsTableName> --region ap-southeast-2 \
  --key '{"short_code":{"S":"<code>"}}'
```

Kết quả thực tế (code do TV4 gửi: `0R4b1nm`, đích `https://example.com/tv4-flag`):

```text
$ scripts/dyn_urls.sh get 0R4b1nm
{
    "Item": {
        "click_count":  { "N": "113" },
        "created_at":   { "S": "2026-11-09T14:19:14Z" },
        "expires_at":   { "S": "2026-11-16T14:19:14Z" },
        "flag_reason":  { "S": "bot_traffic" },
        "flagged_at":   { "N": "1794234453" },
        "long_url":     { "S": "https://example.com/tv4-flag" },
        "owner_id":     { "S": "969b778c-deb4-4c0a-88bc-4bdad1f6bda7" },
        "short_code":   { "S": "0R4b1nm" },
        "status":       { "S": "suspicious" }
    }
}
```

→ `status = suspicious`, `flag_reason = bot_traffic`. ✔

Ảnh bằng chứng:
- [08-suspicious-flagged-link](screenshots/aws/lan3/08-suspicious-flagged-link.png) — `get-item` bảng `urls` (ảnh do TV5 chụp lại).
- Dashboard và biểu đồ bot clicks của TV4: `01-dashboard-flagged.png`, `02-protection-flagged.png`,
  `03-stats-bot-clicks.png` trong `docs/screenshots/` — PR #31:
  https://github.com/uyen1103/smart-url-serverless-aws/pull/31

> **Link `0R4b1nm` được giữ nguyên** (không gỡ cờ, không xóa) theo yêu cầu của TV4 trong PR #31 —
  cần giữ nguyên để đối chiếu số liệu dashboard.

Gỡ cờ về `active` bằng script của TV5 (khi TV4 cho phép):

```bash
./scripts/blocklist.sh activate <code> --execute
```

**Bằng chứng:** ☑ output `get-item` có `suspicious` · ☑ ảnh dashboard TV4 (PR #31)

---

## 6. Blocklist domain

> **Đã chạy.** Ngày 2026-11-10. Domain dùng để thử: `example.org` — là domain **thật**, DNS phân giải
> được (`103.102.166.224`), vì backend kiểm tra DNS **trước** khi tra blocklist nên domain không phân
> giải sẽ bị loại ở bước `invalid_url` chứ không tới được `blocked_domain`.

```bash
STACK_NAME=linkpulse-backend ./scripts/blocklist.sh add example.org --reason phishing --execute
STACK_NAME=linkpulse-backend ./scripts/blocklist.sh list

curl -s -X POST "https://$CF_DOMAIN/api/shorten" \
  -H 'Content-Type: application/json' \
  -H 'X-Owner-Id: 44444444-4444-4444-8444-444444444444' \
  -d '{"url":"https://example.org/tv5-block-test"}'

STACK_NAME=linkpulse-backend ./scripts/blocklist.sh remove example.org --execute
STACK_NAME=linkpulse-backend ./scripts/blocklist.sh list
```

Output thực tế:

```text
=== add example.org ===
Đang chặn domain: example.org (lý do: phishing)
Đã chặn example.org.

=== blocklist.sh list ===
{
    "Items": [
        {
            "added_at": { "S": "2026-11-10T07:46:09Z" },
            "domain":   { "S": "example.org" },
            "reason":   { "S": "phishing" }
        }
    ],
    "Count": 1,
    "ScannedCount": 1
}

-- tao link tro toi domain bi chan --
HTTP 400
{"error": {"code": "blocked_domain", "message": "Domain này đang bị chặn."}}

=== remove example.org ===
Đang gỡ chặn domain: example.org
Đã gỡ chặn example.org.

=== blocklist.sh list sau khi go ===
{
    "Items": [],
    "Count": 0,
    "ScannedCount": 0
}
```

→ Đúng `400` với `error.code = blocked_domain`. ✔
Domain đã được **gỡ khỏi** blocklist sau khi thử; bảng về lại rỗng.

> **Sửa lỗi script sau khi kiểm thử (2026-11-10):** lần chạy đầu tiên trên Windows, cả
> `blocklist.sh` lẫn `blocklist.ps1` **không tìm được tên bảng** vì mặc định tra stack
> `smart-url` (stack của tuần 1) trong khi stack thật là `linkpulse-backend`. Bản PowerShell
> còn hỏng thêm ở chỗ PowerShell 5.1 bỏ dấu nháy của native command, khiến các tham số
> JSON của DynamoDB (`--item`, `--key`, `--expression-attribute-names`) không parse được.
> Đã sửa cả hai bản và kiểm thử lại vòng add → list → remove; cả hai đều trả `Count: 0`
> sau khi gỡ. Xem mục 9.

Ảnh bằng chứng:
[03-blocklist-list](screenshots/aws/lan3/03-blocklist-list.png) ·
[04-blocked-domain-body](screenshots/aws/lan3/04-blocked-domain-body.png) ·
[05-blocklist-empty](screenshots/aws/lan3/05-blocklist-empty.png)

**Bằng chứng:** ☑ output `blocked_domain` · ☑ output `blocklist.sh list`

---

## 7. Chi phí $0

> **Đã kiểm tra** bằng Cost Explorer API (ngày 2026-11-10) **và chụp thêm trang Cost Explorer
> trên AWS Console** (ngày 2026-11-10) — bằng chứng console đã có, xem mục "Ảnh bằng chứng" bên dưới.

### 7.1. Cost Explorer API

```bash
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-11-11 \
  --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE
```

| Kỳ | Dịch vụ | UnblendedCost |
|---|---|---|
| 2026-10-01 → 2026-11-01 | Lambda, API Gateway, DynamoDB, S3, CloudFront, KMS, Secrets Manager, CloudFormation, Glue, SNS, SQS, CloudWatch, Tax | `0` USD (S3: `-0.0000000006` USD) |
| 2026-11-01 → 2026-11-11 | Lambda, API Gateway, DynamoDB, S3, CloudFront, KMS, Secrets Manager, CloudFormation, Glue, SQS, CloudWatch, Tax | `0` USD (CloudShell `0.0000015082`, CloudFront `-0.0000000011`, S3 `-0.0000000004`, Data Transfer `-0.0000015082`) |

Tổng chi phí thực = **0 USD** (các con số ở mức 10⁻⁹ USD là phần credit/thuế cân bằng, không phải chi phí thật).

- **AWS Budget** đã có: `linkpulse-monthly-ap-southeast-2-5usd`, giới hạn `5.0 USD` / tháng, lọc
  theo Region `ap-southeast-2`.
- **Không có phí phát sinh** vì: `BillingMode=PROVISIONED` (không trả theo số lần gọi Lambda),
  `EnablePitr=false`, WAF tắt (`EnableWaf=false`), CloudWatch log retention 7 ngày, DynamoDB on-demand
  dưới ngưỡng miễn phí.

### 7.2. Trang Cost Explorer trên AWS Console

Đăng nhập console bằng **root user** của tài khoản `567627324019` (user `linkpulse-tv5` không có
`LoginProfile` nên không đăng nhập được console), mở **Billing and Cost Management → Cost Explorer**:

| Thông số trên màn hình | Giá trị |
|---|---|
| Account | `567627324019` |
| Date range | `2026-11-01 — 2026-11-10` (tháng 11/2026, đúng kỳ chạy test) |
| Granularity | `Monthly` |
| Group by | `Service` |
| **Total cost** | **`-$0.00`** |
| Số dịch vụ có phát sinh | `13` (CloudWatch, CloudFront, AWS Key Management Service, Amazon S3, AWS Glue, AWS Lambda, AWS Secrets Manager, Amazon DynamoDB, Amazon API Gateway, AWS CloudFormation, Amazon SNS, Amazon SQS, AWS Tax) |

`-$0.00` nghĩa là **$0**: các phần âm ở mức 10⁻⁹ USD là credit/thuế cân bằng, khớp đúng với kết quả
Cost Explorer API ở mục 7.1 (cùng một nguồn dữ liệu).

Ảnh bằng chứng:
[07-billing-cost-zero](screenshots/aws/lan3/07-billing-cost-zero.png) (API) ·
[09-cost-explorer-console](screenshots/aws/lan3/09-cost-explorer-console.png) (AWS Console)

### 7.3. Kiểm `architecture.png` đã có ghi chú `verdict_cache` chưa

☑ **Đã có.** `docs/architecture.png` sinh bằng `python scripts/gen_arch_png.py` (commit `456f035`)
ghi rõ trong khối DynamoDB:

```text
blocklist: PK domain (no verdict_cache)
```

Kiểm tra: `docs/architecture.png` và `docs/architecture.md` đều đã đồng bộ với `backend/template.yaml`
(bảng `blocklist` chỉ có khoá `domain`, không có bảng cache verdict riêng).

---

## 8. Tổng hợp

| # | Lớp | Lệnh kiểm | Kết quả mong đợi | Kết quả thực tế | Bằng chứng |
|---|---|---|---|---|---|
| 0 | Triển khai & phân quyền | `describe-stacks`, `sts get-caller-identity` | Ghi rõ stack/region/thời điểm/IAM | Edge ở `ap-southeast-2` (SCP chặn `us-east-1`); Budget $5/tháng đã tạo; script phân quyền từng người **chạy thật nhưng dừng ở preflight** vì user không có `iam:*` | mục 0.1–0.4 |
| 1 | WAF rate-based | 60 × POST `/api/shorten` | `403` khi vượt ngưỡng | **Chưa chạy** — trình bày bằng thiết kế (`infra/edge.yaml`, `EnableWaf=false`) để giữ chi phí $0 | mục 1 |
| 2 | API Gateway throttling | 120 request song song | `429` `{"message":"Too Many Requests"}` | ☑ 35 lần 429 của API Gateway (không `Retry-After`) + 64 lần 429 của Lambda (có `Retry-After`) | [06](screenshots/aws/lan3/06-apigateway-throttling.png) |
| 3 | Rate limit theo IP | 15 × POST `/api/shorten` | 10 thành công rồi `429` + `Retry-After` | ☑ 10× `201`, 5× `429` + `Retry-After` (41→38) | [01](screenshots/aws/lan3/01-ratelimit-output.png), [02](screenshots/aws/lan3/02-rate-limits-table.png) |
| 4 | Chặn gọi thẳng origin | GET API domain không có header | `403` | ☑ `403` (`reason: origin_not_allowed`) | [smoke-direct-403](screenshots/aws/lan2/smoke-direct-403.png) |
| 5 | Gắn cờ suspicious | `get-item` bảng `urls` | `status = suspicious` | ☑ `suspicious` / `bot_traffic` (link `0R4b1nm` của TV4, giữ nguyên) | [08](screenshots/aws/lan3/08-suspicious-flagged-link.png), PR #31 |
| 6 | Blocklist domain | POST URL domain bị chặn | `400 blocked_domain` | ☑ `400` `blocked_domain` với domain thật `example.org`, đã gỡ sau khi thử | [03](screenshots/aws/lan3/03-blocklist-list.png), [04](screenshots/aws/lan3/04-blocked-domain-body.png) |
| 7 | Chi phí $0 | Cost Explorer | `$0` | ☑ API cho mọi dịch vụ `0 USD` **và** trang Cost Explorer trên Console cho `Total cost -$0.00` (13 dịch vụ) | [07](screenshots/aws/lan3/07-billing-cost-zero.png), [09](screenshots/aws/lan3/09-cost-explorer-console.png) |

Ảnh chụp AWS Console cần chụp cho: WAF `BlockedRequests` theo rule (mục 1 — **chưa chạy**),
CloudWatch throttling của API Gateway (đã có bằng chứng bằng output HTTP ở mục 2),
bảng `rate_limits` (mục 3) và bảng `urls` (link `suspicious`, mục 5).

---

## 9. Script dùng để chạy lại

| Script | Công dụng |
|---|---|
| [`scripts/test_ratelimit.sh`](../scripts/test_ratelimit.sh) | 15 POST liên tiếp, canh đầu phút, in mã + `Retry-After`, tự xoá link test |
| [`scripts/test_throttling.py`](../scripts/test_throttling.py) | N request song song (thread + `Barrier`), phân loại 2 lớp 429, tự xoá link test |
| [`scripts/blocklist.sh`](../scripts/blocklist.sh) / [`.ps1`](../scripts/blocklist.ps1) | Thêm/xoá domain trong bảng blocklist, gỡ cờ link về `active` |
| [`scripts/dyn_urls.sh`](../scripts/dyn_urls.sh) | Truy vấn nhanh bảng `urls` |
| [`scripts/render_evidence.py`](../scripts/render_evidence.py) | Dựng ảnh PNG từ output kiểm thử để dán vào tài liệu |

> **Lưu ý khi chạy lại (đã sửa ngày 2026-11-10):** `blocklist.sh` / `blocklist.ps1` giờ tự dò
> tên bảng qua các stack `linkpulse-backend` (stack thật) rồi `smart-url` (stack tuần 1), nên
> không cần đặt `STACK_NAME` khi chạy trên môi trường hiện tại. Bản `.ps1` đã sửa lỗi PowerShell
> 5.1 làm mất dấu nháy của tham số JSON DynamoDB, và cả hai bản đều **báo lỗi khi lệnh `aws`
> thất bại** thay vì in "đã xong" sai. Script `setup_aws_foundation.*` cũng không còn nội suy mật
> khẩu console vào chuỗi lệnh (bị `Invoke-Expression`/`eval` diễn giải sai với ký tự đặc biệt).

Trên Windows, chạy script Python với `PYTHONUTF8=1` và `PYTHONIOENCODING=utf-8` để không lỗi
`UnicodeEncodeError` khi in tiếng Việt.
