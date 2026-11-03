# Backend - Smart URL Shortener (serverless trên AWS)

Khung backend hoàn chỉnh bám theo `docs/api_spec.yaml`: rút gọn link, redirect, thống kê gần thời gian
thực và chống lạm dụng. Chạy toàn bộ bằng HTTP API + Lambda + DynamoDB, không có server.
Chi phí và thứ tự deploy theo `docs/QUYET_DINH_CHOT_TUAN_2.md` (nguyên tắc $0); tham số xem mục "Tham số của template".

## Kiến trúc

```
Người dùng ──> [CloudFront + WAF] (infra/edge.yaml) ── /index.html, /assets/*... ──> S3 (giao diện TV2)
                    │  /api/* và /{code}  (kèm header bí mật X-Origin-Verify)
                    ▼
              API Gateway HTTP API  (throttling toàn API và riêng POST /api/shorten)
   ┌───────────┬────┴─────┬─────────────┬───────────┐
 shorten     redirect    links         stats       health        <- Lambda (src/handlers)
   │            │          │             │
   │            ├─ urls ◄──┤             │ đọc
   │            ├─ rate_limits            ▼
   │            └─ clicks ──► DynamoDB Stream ──► process_clicks ──► stats (cộng dồn theo phút)
   ├─ blocklist                               │                      └─► gắn cờ link bất thường
   └─ Turnstile / Safe Browsing (SSM)         └─ lỗi ──► SQS DLQ ──► CloudWatch Alarm
```

Luồng click gần thời gian thực: `redirect` ghi 1 item vào `clicks`; DynamoDB Stream kích hoạt
`process_clicks` (gom tối đa 100 event hoặc 2 giây) để `ADD` nguyên tử vào `stats` theo phút. Dashboard
đọc `stats`, nên độ trễ chỉ vài giây. Lambda này cũng phát hiện lạm dụng và đổi link sang `suspicious`.

## API (đường dẫn có tiền tố `/api` để CloudFront chuyển thẳng, không cần rewrite)

| Route | Lambda | Ghi chú |
|---|---|---|
| `POST /api/shorten` | shorten | 201 tạo mới, 200 trả link cũ (cùng owner, cùng URL, không alias) |
| `GET /{code}` | redirect | 302 + `Cache-Control: no-store`; `?confirm=1` để đi tiếp link `suspicious`. Với `ErrorPageMode=redirect`, trình duyệt (`Accept: text/html`) nhận 302 sang `/error.html` hoặc `/warning.html` (link đáng ngờ kèm `&code=<mã>`) thay vì JSON |
| `GET /api/links` | links | cần `X-Owner-Id`; lọc `status`, `q`, sắp xếp `sort`, phân trang `cursor` |
| `DELETE /api/links/{code}` | links | 204; xóa mềm (giữ mã, không cấp lại) và dọn click + thống kê của link |
| `GET /api/stats`, `/api/stats/{code}` | stats | `from`, `to`, `granularity=minute\|hour` (tối đa 1440 mốc) |
| `GET /api/health` | health | `{"status":"ok"}`, không đọc DynamoDB; dùng để kiểm tra nhanh sau mỗi lần deploy |

Mã lỗi đúng spec: 400 (`invalid_url`, `blocked_domain`, `invalid_alias`, `invalid_expires_in`,
`invalid_max_clicks`, `captcha_failed`, `invalid_request`), 401, 403 (`forbidden`, `link_blocked`,
`link_suspicious`), 404, 409 `alias_taken`, 410 (`link_expired`, `max_clicks_reached`), 429 (kèm `Retry-After`).
Thứ tự kiểm tra trạng thái khi redirect: bị chặn, hết hạn, hết lượt click, đáng ngờ.

**Alias dành riêng** (19 tên, so khớp không phân biệt hoa/thường, trả 409 `alias_taken`): `api`, `assets`, `vendor`,
`css`, `js`, `mock`, `index`, `dashboard`, `error`, `warning`, `stats`, `links`, `shorten`, `admin`, `favicon`,
`health`, `static`, `login`, `robots` (`js` chỉ 2 ký tự nên bị 400 `invalid_alias` trước). Danh sách chuẩn là
`RESERVED_ALIASES` trong `src/linkpulse/validation.py`; `tests/test_handlers_spec_contract.py` kiểm tra spec khớp danh sách này.

## Mô hình dữ liệu

| Bảng | Khóa | Ghi chú |
|---|---|---|
| `urls` | `short_code` | GSI `owner-index` (`owner_id`, `created_at`); `click_count` tăng nguyên tử có điều kiện `< max_clicks` |
| `clicks` | `short_code` + `sk` (`ts#id`) | TTL 30 ngày; **Stream NEW_IMAGE** là nguồn của pipeline. Chỉ lưu `ip_hash`, không lưu IP/UA thô |
| `stats` | `scope` (`GLOBAL`, `LINK#code`, `META`) + `sk` (`M#<phút>`) | TTL 8 ngày; bộ đếm phẳng `c:`, `d:`, `b:`, `r:`, `l:` và tập `ips` |
| `rate_limits` | `pk` (`<loại>#<ip_hash>#<cửa sổ>`) | cửa sổ cố định, TTL tự dọn |
| `blocklist` | `domain` | khớp cả domain cha (`a.b.bad.com` khớp `bad.com`) |

## Chống lạm dụng (nhiều lớp)

1. **WAF** (`infra/edge.yaml`): rate-based theo IP, riêng cho `/api/shorten`, IP reputation, Common rule set.
   Kèm **header bí mật `X-Origin-Verify`**: CloudFront gắn vào mọi request tới API, backend (`origin.py`) từ chối
   request thiếu/sai. Nhờ vậy không ai gọi thẳng `*.execute-api.amazonaws.com` để né WAF, và header IP/quốc gia
   của CloudFront mới đáng tin. Bật bằng tham số `OriginVerifySecretParam`; để trống thì tắt (dev).
2. **API Gateway**: throttling toàn API và riêng route tạo link.
3. **Trong code**: rate limit theo IP băm cho `shorten` (mặc định 10/phút) và `redirect` (300/phút, 0 = tắt).
4. **Cloudflare Turnstile**: xác minh phía server, bí mật đọc từ SSM; để trống tham số = tắt (dev).
5. **Kiểm tra URL**: chỉ http/https, chặn IP nội bộ (kể cả dạng rút gọn `127.1`), chặn domain của chính hệ thống,
   phân giải DNS và từ chối domain trỏ về IP nội bộ.
6. **Blocklist** + **Google Safe Browsing** (tùy chọn, fail-open) -> 400 `blocked_domain`.
7. **Heuristic khi tạo link** -> cho tạo nhưng gắn `suspicious`: IP làm host, punycode, quá nhiều subdomain,
   TLD rủi ro, link rút gọn lồng nhau.
8. **Phát hiện theo thời gian thực**: link vượt `SPIKE_CLICKS_PER_MINUTE` (300) hoặc tỷ lệ bot >= 80% (từ 50 click/phút)
   bị chuyển `suspicious`; người dùng phải bấm xác nhận (`?confirm=1`).

## Chạy test

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests -q          # dùng moto (DynamoDB, SSM giả) nên không cần tài khoản AWS và không tốn phí
```

Fixture dùng chung nằm ở `tests/conftest.py` (5 bảng dựng thẳng từ `template.yaml`, nên template đổi schema thì test tự theo).
Test handler: `tests/test_handlers_*.py`; kiểm tra spec khớp backend: `tests/test_handlers_spec_contract.py`.

## Tham số của template

| Tham số | Mặc định | Lần 1 | Lần 2 | Ghi chú |
|---|---|---|---|---|
| `BillingMode` | `PROVISIONED` | mặc định | mặc định | Bảng tạo ở chế độ provisioned để nằm trong 25 WCU/RCU miễn phí (tổng 23/23, xem bên dưới). Chỉ đổi sang `PAY_PER_REQUEST` khi demo bị throttle, và chỉ **TV1** chạy deploy này |
| `EnablePitr` | `false` | mặc định | mặc định | Point-in-Time Recovery tính phí, nên tắt |
| `IpHashSalt` | không có (bắt buộc, >= 16 ký tự) | nhập | **cùng giá trị** | Đổi salt làm đếm khách duy nhất đứt đoạn. Không đưa vào Git |
| `BaseUrl` | `https://linkpulse.vn` | mặc định (tạm) | `https://<domain>.cloudfront.net` | Dựng `short_url`; không có `/` cuối |
| `OwnDomains` | `linkpulse.vn` | mặc định (tạm) | `<domain>.cloudfront.net` | URL trỏ về các domain này bị từ chối (chống vòng lặp); nhiều domain cách nhau dấu phẩy |
| `ErrorPageMode` | `json` | `json` | `redirect` | `redirect` = trình duyệt được 302 sang `error.html`/`warning.html`. Quyết định tuần 2 mục 3 sẽ đổi mặc định thành `redirect` trong PR sửa template |
| `OriginVerifySecretParam` | trống (tắt) | trống | `/linkpulse/origin-verify` | Bật kiểm tra `X-Origin-Verify`. Chỉ bật khi CloudFront đã tồn tại, nếu không mọi request bị 403 |
| `TurnstileSecretParam` | trống (tắt) | tùy chọn | tùy chọn | Tên SSM SecureString chứa secret Turnstile. Không phải dịch vụ AWS, không tính là lớp bảo vệ chính |
| `SafeBrowsingKeyParam` | trống (tắt) | tùy chọn | tùy chọn | Tương tự (Google Safe Browsing) |
| `CorsOrigin` | `*` | | | Chạy cùng domain sau CloudFront thì không cần CORS |
| `RedirectRateLimit` | 300 | | | Lượt redirect tối đa mỗi IP mỗi phút (0 = tắt) |

**Sắp thêm (chưa có trong `template.yaml` cho tới khi PR template của TV1 merge, cập nhật bảng này sau đó):**
`SpikeClicksPerMinute` (300) và `BotMinClicks` (50) theo quyết định #7, khi demo deploy với 30 và 10; đổi mặc định `ErrorPageMode` thành `redirect`.

### Dung lượng DynamoDB (`BillingMode=PROVISIONED`, quyết định #2)

| Bảng / index | WCU | RCU |
|---|---|---|
| `urls` | 5 | 6 |
| `urls` / `owner-index` | 4 | 2 |
| `clicks` | 4 | 1 |
| `stats` | 4 | 10 |
| `rate_limits` | 5 | 1 |
| `blocklist` | 1 | 3 |
| **Tổng** | **23** | **23** |

Không tự tăng quá tổng 25. AWS chỉ cho đổi chế độ tính phí **một lần mỗi 24 giờ** (bị từ chối thì chờ đủ 24 giờ rồi deploy lại). Nếu demo bị throttle: TV3 đề nghị, TV1 chạy `sam deploy --parameter-overrides IpHashSalt="$SALT" BaseUrl=https://<DistributionDomain> OwnDomains=<DistributionDomain> ErrorPageMode=redirect OriginVerifySecretParam=/linkpulse/origin-verify BillingMode=PAY_PER_REQUEST` (tốn vài cent), xong buổi demo đổi lại `PROVISIONED`. On-demand là cấu hình khi chạy thật, phải ghi rõ trong báo cáo.

## Deploy: 2 lần, đúng thứ tự

`BaseUrl`/`OwnDomains` phụ thuộc domain CloudFront, mà CloudFront cần domain của API, nên backend phải deploy **hai lần**.
Chạy `sam deploy` **một lần một người** cho mỗi stack (không deploy chồng lên nhau), và đặt tên stack bắt đầu bằng `linkpulse-`
nếu chính sách IAM vẫn là bản cũ.

```bash
# 0. Region: tài khoản Free plan kiểu mới bị cố định Region theo project (xem settings.aws.com, mục Project).
#    TV1 và TV5 chốt MỘT Region cho backend; mọi thành viên `aws configure` đúng Region đó.

# 1. Sinh bí mật dùng chung với CloudFront, lưu vào SSM (loại Standard SecureString, miễn phí)
SECRET=$(openssl rand -hex 24)
aws ssm put-parameter --name /linkpulse/origin-verify --type SecureString --value "$SECRET"
SALT=$(openssl rand -hex 16)                 # IpHashSalt (32 ký tự). Lưu lại: lần 2 phải dùng đúng giá trị này

# 2. LẦN 1: deploy backend với BaseUrl/OwnDomains mặc định, chưa bật kiểm tra origin. Lấy output ApiDomain gửi TV5
cd backend
sam validate --lint
sam build
sam deploy --guided                          # Stack Name: linkpulse-backend; IpHashSalt nhập giá trị $SALT

# 3. TV5 deploy lớp biên (infra/edge.yaml); lấy DistributionDomain và FrontendBucketName
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=<ApiDomain> OriginVerifySecret="$SECRET"
#    Region của stack edge và việc bật WAF do TV5 chốt (quyết định tuần 2 mục 16, 19); thêm DomainName + CertificateArn nếu có tên miền riêng

# 4. LẦN 2: deploy lại backend với domain CloudFront. Truyền đủ mọi tham số, IpHashSalt PHẢI giống lần 1
sam deploy --parameter-overrides \
  IpHashSalt="$SALT" BaseUrl=https://<DistributionDomain> OwnDomains=<DistributionDomain> \
  ErrorPageMode=redirect OriginVerifySecretParam=/linkpulse/origin-verify

# 5. Đưa giao diện lên S3 (TV2) và kiểm tra
aws s3 sync <thư mục giao diện> s3://<FrontendBucketName>
curl https://<DistributionDomain>/api/health                  # phải ra {"status":"ok"}
```

Bật Turnstile: `aws ssm put-parameter --name /linkpulse/turnstile-secret --type SecureString --value <secret>` rồi deploy với
`TurnstileSecretParam=/linkpulse/turnstile-secret` (Safe Browsing tương tự).
Chặn một domain: `aws dynamodb put-item --table-name <BlocklistTableName> --item '{"domain":{"S":"bad.example"}}'`.
Xoay vòng bí mật: đổi giá trị SSM và tham số `OriginVerifySecret` của stack edge gần như cùng lúc (có khoảng ngắn bị 403).

**Dọn sau mỗi đợt thử:** khi không dùng stack nữa thì `sam delete --stack-name linkpulse-backend` (và stack edge) để không
tốn credit. Chỉ chạy tải lớn trên moto hoặc DynamoDB Local, không chạy lên AWS.

## Giới hạn đã biết và điểm cần chốt

- **Đếm có thể dư khi retry**: stream là at-least-once, nên một batch bị retry sẽ cộng lại. Chấp nhận được cho
  dashboard; muốn chính xác tuyệt đối cần khử trùng lặp theo `sk` của click.
- **Kích thước item**: tập `ips` và `r:*` trong 1 phút/1 scope bị giới hạn 400 KB. Lưu lượng rất lớn thì chuyển sang
  ước lượng HyperLogLog hoặc Kinesis + Flink.
- **Rate limit cửa sổ cố định** cho phép bùng nổ ở ranh giới cửa sổ (tối đa ~2 lần giới hạn); WAF bổ sung cho điểm này.
- **DNS rebinding** chưa chống được hoàn toàn: DNS có thể đổi sau khi tạo link. Hệ thống không tự fetch URL nên rủi ro
  chủ yếu là chuyển hướng người dùng, không phải SSRF.
- **`flagged_links`** là bộ đếm tăng dần; chưa giảm khi link được gỡ cờ (chưa có API quản trị).
- **Danh tính** hiện là `X-Owner-Id` (UUID do frontend sinh) đúng theo spec, nên không phải xác thực thật.
  Cần Cognito/JWT authorizer nếu có tài khoản.
- **Lỗi redirect trên trình duyệt**: mặc định trong template hiện là JSON đúng spec; khi chạy cùng giao diện qua
  CloudFront dùng `ErrorPageMode=redirect` (đã chốt ở quyết định tuần 2 mục 3) để trình duyệt được 302 sang
  `/error.html` hoặc `/warning.html`. Lỗi 429 luôn là JSON.
- **DynamoDB bị throttle** (bảng provisioned hết WCU/RCU): rate limit, đếm click và ghi click event **fail-open**,
  ghi cảnh báo `DYNAMODB_THROTTLED` rồi cho request đi tiếp thay vì 500 (mất vài lượt đếm, có thể vượt rate limit
  đôi chút). Đọc/ghi link vẫn lỗi thật. Các thao tác này chỉ thử lại 2 lần (chờ ~0,15 giây) thay vì mặc định 10 lần
  (chờ ~25 giây, vượt timeout 5 giây của Lambda). Nên đặt CloudWatch metric filter trên từ khóa `DYNAMODB_THROTTLED`.
- **Salt băm IP**: cố định cho phép đếm khách duy nhất xuyên ngày; `IP_HASH_DAILY=true` tăng riêng tư nhưng
  mỗi ngày đếm lại từ đầu.
- **Tên miền riêng**: cần chứng chỉ ACM ở us-east-1 và tự tạo bản ghi DNS trỏ về `DistributionDomain`; `BaseUrl` của backend
  phải khớp domain này. Chưa có log WAF/CloudFront và chưa đặt CSP (phụ thuộc giao diện, nhớ cho phép script Turnstile).
- **Ngưỡng WAF** (1000 và 50 request/5 phút/IP) là số chọn tạm; mạng dùng chung một IP (trường, công ty) có thể bị chặn nhầm.
- Trang chủ `/` được CloudFront chuyển 302 sang `/index.html`; giao diện phải có file này, nếu chưa upload thì người dùng thấy lỗi S3.
