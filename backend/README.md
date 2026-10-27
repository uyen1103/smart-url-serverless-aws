# Backend - Smart URL Shortener (serverless trên AWS)

Khung backend hoàn chỉnh bám theo `docs/api_spec.yaml`: rút gọn link, redirect, thống kê gần thời gian
thực và chống lạm dụng. Chạy toàn bộ bằng HTTP API + Lambda + DynamoDB (on-demand), không có server.

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
| `GET /{code}` | redirect | 302 + `Cache-Control: no-store`; `?confirm=1` để đi tiếp link `suspicious` |
| `GET /api/links` | links | cần `X-Owner-Id`; lọc `status`, `q`, sắp xếp `sort`, phân trang `cursor` |
| `DELETE /api/links/{code}` | links | 204; xóa mềm (giữ mã, không cấp lại) và dọn click + thống kê của link |
| `GET /api/stats`, `/api/stats/{code}` | stats | `from`, `to`, `granularity=minute\|hour` (tối đa 1440 mốc) |
| `GET /api/health` | health | |

Mã lỗi đúng spec: 400 (`invalid_url`, `blocked_domain`, `invalid_alias`, `invalid_expires_in`,
`invalid_max_clicks`, `captcha_failed`, `invalid_request`), 401, 403 (`forbidden`, `link_blocked`,
`link_suspicious`), 404, 409 `alias_taken`, 410 (`link_expired`, `max_clicks_reached`), 429 (kèm `Retry-After`).
Thứ tự kiểm tra trạng thái khi redirect: bị chặn, hết hạn, hết lượt click, đáng ngờ.

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

## Chạy test, kiểm tra, deploy

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests -q                    # 82 test, dùng moto nên không cần tài khoản AWS

cd backend
sam validate --lint
sam build
sam deploy --guided                          # nhập IpHashSalt (>= 16 ký tự); các tham số khác có mặc định
```

Bật Turnstile: `aws ssm put-parameter --name /linkpulse/turnstile-secret --type SecureString --value <secret>`
rồi deploy với `TurnstileSecretParam=/linkpulse/turnstile-secret` (Safe Browsing tương tự).
Chặn một domain: `aws dynamodb put-item --table-name <BlocklistTableName> --item '{"domain":{"S":"bad.example"}}'`.
### Triển khai lớp biên (CloudFront + WAF + S3), đúng thứ tự

Bật kiểm tra origin trước khi CloudFront tồn tại thì mọi request đều bị 403, nên làm theo thứ tự này:

```bash
# 1. Sinh bí mật và lưu vào SSM (region của backend)
SECRET=$(openssl rand -hex 24)
aws ssm put-parameter --name /linkpulse/origin-verify --type SecureString --value "$SECRET"

# 2. Deploy backend CHƯA bật kiểm tra origin (OriginVerifySecretParam để trống), lấy output ApiDomain
sam deploy --guided

# 3. Deploy lớp biên ở us-east-1 với CÙNG bí mật (thêm DomainName + CertificateArn nếu có tên miền riêng)
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=<ApiDomain> OriginVerifySecret="$SECRET"

# 4. Deploy lại backend với OriginVerifySecretParam=/linkpulse/origin-verify -> API chỉ nhận request qua CloudFront
sam deploy --parameter-overrides OriginVerifySecretParam=/linkpulse/origin-verify  # kèm các tham số cũ

# 5. Đưa giao diện lên S3 (bucket lấy từ output FrontendBucketName của stack edge)
aws s3 sync <thư mục giao diện> s3://<FrontendBucketName>
```

Xoay vòng bí mật: đổi giá trị SSM và tham số `OriginVerifySecret` của stack edge gần như cùng lúc (có khoảng ngắn bị 403).

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
- **Lỗi redirect trên trình duyệt**: mặc định trả JSON đúng spec. `ErrorPageMode=redirect` sẽ 302 sang
  `/error.html` hoặc `/warning.html` (cần thống nhất với TV2/TV5).
- **Salt băm IP**: cố định cho phép đếm khách duy nhất xuyên ngày; `IP_HASH_DAILY=true` tăng riêng tư nhưng
  mỗi ngày đếm lại từ đầu.
- **Tên miền riêng**: cần chứng chỉ ACM ở us-east-1 và tự tạo bản ghi DNS trỏ về `DistributionDomain`; `BaseUrl` của backend
  phải khớp domain này. Chưa có log WAF/CloudFront và chưa đặt CSP (phụ thuộc giao diện, nhớ cho phép script Turnstile).
- **Ngưỡng WAF** (1000 và 50 request/5 phút/IP) là số chọn tạm; mạng dùng chung một IP (trường, công ty) có thể bị chặn nhầm.
- Trang chủ `/` được CloudFront chuyển 302 sang `/index.html`; giao diện phải có file này, nếu chưa upload thì người dùng thấy lỗi S3.
- `backend/hello/` là hello-world tuần 1, không còn được `template.yaml` dùng, có thể xóa.
