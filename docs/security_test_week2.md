# Kiểm chứng lớp chống lạm dụng — tuần 2

> **Module:** TV5 · **Issue:** #11
> **Trạng thái:** khung kiểm thử đã sẵn sàng; các mục đánh dấu ☐ cần chạy khi có stack đã deploy
> (TV1 deploy backend lần 2, TV5 deploy edge) rồi dán lệnh + kết quả + ảnh chụp.

Lớp phòng thủ theo thứ tự request đi qua:

```
Client → CloudFront → [WAF] → [API Gateway throttling] → [Lambda rate limit theo IP]
       → [X-Origin-Verify] → [validate URL + blocklist] → [Turnstile] → DynamoDB
```

Mỗi lớp chặn ở một chỗ khác nhau nên phải kiểm từng lớp, không gộp.

---

## 0. Chuẩn bị

```bash
# Domain CloudFront và domain API Gateway (lấy từ output của stack)
CF_DOMAIN="<DistributionDomain>"
API_DOMAIN="<ApiDomain>"

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

> WAF mặc định tắt (`EnableWaf=false`) vì có phí. Bật, kiểm thử, tắt lại trong cùng buời.

Bật WAF (stack edge phải ở `us-east-1`):

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

---

## 2. API Gateway throttling

Route `POST /api/shorten` giới hạn 10 request/giây, burst 20. Toàn API giới hạn 100/giây, burst 200.

Vượt ngưỡng route tạo link:

```bash
for i in $(seq 1 40); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "https://$CF_DOMAIN/api/shorten" \
    -H 'Content-Type: application/json' \
    -H 'X-Owner-Id: 22222222-2222-4222-8222-222222222222' \
    -d '{"url":"https://example.com/agw-test"}'
done
```

- Kết quả mong đợi: `201`/`200` cho các request đầu, sau đó `429 Too Many Requests`.

**Bằng chứng:** ☐ output 429

---

## 3. Rate limit theo IP trong Lambda

Bảng `rate_limits` giới hạn 10 lần/phút cho `POST /api/shorten` (tham số `SHORTEN_RATE_LIMIT`).

```bash
for i in $(seq 1 15); do
  curl -s -D - -o /dev/null \
    -X POST "https://$CF_DOMAIN/api/shorten" \
    -H 'Content-Type: application/json' \
    -H 'X-Owner-Id: 33333333-3333-4333-8333-333333333333' \
    -d '{"url":"https://example.com/rl-test"}' | grep -iE "^HTTP|retry-after"
done
```

- Kết quả mong đợi: `429` và header `Retry-After` khi vượt 10 lần/phút.
- Kiểm tra bảng:

```bash
aws dynamodb scan --table-name <RateLimitsTableName> --region ap-southeast-2
```

**Bằng chứng:** ☐ output 429 + `Retry-After` · ☐ ảnh bảng `rate_limits`

---

## 4. Gọi thẳng API Gateway bị 403

Khi `OriginVerifySecretParam` đã bật, backend chỉ nhận request có header `X-Origin-Verify` đúng giá trị
mà CloudFront gắn vào (`backend/src/linkpulse/origin.py`).

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

**Bằng chứng:** ☐ output 403 và 200

---

## 5. Link vượt ngưỡng thành suspicious

Phát hiện lạm dụng chạy trong `process_clicks` (DynamoDB Stream của bảng `clicks`):
`SpikeClicksPerMinute` (mặc định 300) và `BotMinClicks` (mặc định 50) + `BotRatio` (mặc định 0.8).
Khi demo, deploy với ngưỡng thấp để chỉ cần khoảng 30 lệnh curl.

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

- Kết quả mong đợi: `status` = `suspicious`, có `flag_reason` (ví dụ `bot_traffic` hoặc `click_spike`).
- Phối hợp với TV4 để đối chiếu số liệu ở dashboard.

Gỡ cờ về `active` bằng script của TV5:

```bash
./scripts/blocklist.sh activate <code> --execute
```

**Bằng chứng:** ☐ output `get-item` có `suspicious` · ☐ ảnh dashboard TV4

---

## 6. Blocklist domain

Chặn domain rồi thử tạo link trỏ tới domain đó:

```bash
./scripts/blocklist.sh add bad.example --reason phishing --execute

curl -s -X POST "https://$CF_DOMAIN/api/shorten" \
  -H 'Content-Type: application/json' \
  -H 'X-Owner-Id: 44444444-4444-4444-8444-444444444444' \
  -d '{"url":"https://bad.example/x"}'
```

- Kết quả mong đợi: `400` với `error.code = blocked_domain`.
- Gỡ chặn: `./scripts/blocklist.sh remove bad.example --execute`.

**Bằng chứng:** ☐ output `blocked_domain` · ☐ output `blocklist.sh list`

---

## 7. Tổng hợp

| # | Lớp | Lệnh kiểm | Kết quả mong đợi | Bằng chứng |
|---|---|---|---|---|
| 1 | WAF rate-based | 60 × POST `/api/shorten` | `403` khi vượt ngưỡng | ☐ |
| 2 | API Gateway throttling | 40 × POST `/api/shorten` | `429` | ☐ |
| 3 | Rate limit theo IP | 15 × POST `/api/shorten` | `429` + `Retry-After` | ☐ |
| 4 | Chặn gọi thẳng origin | GET API domain không có header | `403` | ☐ |
| 5 | Gắn cờ suspicious | 60 click bot + `get-item` | `status = suspicious` | ☐ |
| 6 | Blocklist domain | POST URL domain bị chặn | `400 blocked_domain` | ☐ |

Ảnh chụp AWS Console cần chụp cho: WAF `BlockedRequests` theo rule, CloudWatch throttling của API
Gateway, bảng `rate_limits` và bảng `urls` (link `suspicious`).
