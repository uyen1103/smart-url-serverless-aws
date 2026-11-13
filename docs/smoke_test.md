# Smoke test backend (TV1)

Mỗi lần deploy ghi một mục: ngày giờ, tham số đã deploy, lệnh `curl`/PowerShell và kết quả rút gọn.
Ảnh chụp AWS Console của từng lần nằm trong `docs/screenshots/aws/lan1/` và `docs/screenshots/aws/lan2/`; ảnh lần 3 nằm trong `docs/screenshots/e2e/`.

## Lần 1 (BaseUrl tạm, gọi thẳng API Gateway)

- Ngày: 2026-11-04 (khoảng 16:33 giờ Việt Nam)
- Stack: `linkpulse-backend`, Region `ap-southeast-2`
- API: `https://q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com`
- Tham số (từ `backend/samconfig.toml`): `BillingMode=PROVISIONED`, `EnablePitr=false`, `BaseUrl=https://linkpulse.vn` (tạm), `OwnDomains=linkpulse.vn`,
  `TurnstileSecretParam=` (trống), `SafeBrowsingKeyParam=` (trống), `OriginVerifySecretParam=` (trống, tắt), `CorsOrigin=*`, `ErrorPageMode=redirect`,
  `RedirectRateLimit=300`, `SpikeClicksPerMinute=300`, `BotMinClicks=50`, `IpHashSalt=***` (không ghi vào tài liệu).
  Lệnh deploy: `sam deploy --guided` (stack `linkpulse-backend`, Region `ap-southeast-2`).

```powershell
$api = "https://q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com"
$owner = [guid]::NewGuid().ToString()
```

| # | Lệnh | Lambda | Kết quả | Đạt |
|---|---|---|---|---|
| 1 | `curl.exe -s "$api/api/health"` | Health | `{"status": "ok"}` | Có |
| 2 | `POST /api/shorten` với `{"url":"https://example.com"}` và `X-Owner-Id` | Shorten | `created: True`, `code: gVvU73C`, `short_url: https://linkpulse.vn/gVvU73C` | Có |
| 3 | `GET /gVvU73C` (3 lần) | Redirect | 3 lần `HTTP/1.1 302 Found`, `location: https://example.com` | Có |
| 4 | `GET /api/links` với `X-Owner-Id` | Links | `total_links=1`, `active_links=1`, `total_clicks=3` | Có |
| 5 | `GET /api/stats` | Stats | `total_clicks=3`, `bot_clicks=3`, `unique_visitors=1`, `top_links: gVvU73C (3)` | Có |
| 6 | (tự động) DynamoDB Stream sang `process_clicks` | ProcessClicks | `stats` đã cộng đủ 3 click (xem dòng 5), `flagged_links=0` | Có |

### Thống kê theo link và các phép thử lỗi

Link thử `OvZcd9S` (owner là một UUID ngẫu nhiên, 3 lần redirect, chờ 10 giây).

| # | Lệnh | Kết quả | Đạt |
|---|---|---|---|
| 7 | `GET /api/stats/OvZcd9S` | `200`, `total_clicks=3`, `bot_clicks=3`, `link.status=active`, `recent_clicks` có 3 dòng | Có |
| 8 | `POST /api/shorten` với `{"url":"khong-phai-url"}` | `400` | Có |
| 9 | `POST /api/shorten` với `alias=smoke-test-1` | `201`, `code: smoke-test-1` | Có |
| 10 | `POST /api/shorten` lại với `alias=smoke-test-1` | `409` | Có |
| 11 | `POST /api/shorten` với `alias=admin` (alias dành riêng) | `409` | Có |
| 12 | `GET /api/links` không có `X-Owner-Id` | `401` | Có |
| 13 | `GET /zzzzzzz` (mã không tồn tại) | `HTTP/1.1 404 Not Found` | Có |

Nhận xét:
- `short_url` hiện `linkpulse.vn` vì lần 1 dùng `BaseUrl` tạm; lần 2 truyền domain CloudFront sẽ đổi.
- 3 click đều bị tính là `bot` (`device=bot`) vì `curl` không gửi User-Agent của trình duyệt. Đúng thiết kế, và là lý do khi demo chỉ cần khoảng 10 lệnh `curl` với `BotMinClicks=10`.
- CloudWatch có đủ log group của 6 Lambda (xem `docs/screenshots/aws/lan1/cloudwatch.png`).

### Xóa link (kiểm tra quyền IAM của Links)

```powershell
Invoke-RestMethod -Method Delete -Uri "$api/api/links/gVvU73C" -Headers @{"X-Owner-Id"=$owner}
curl.exe -s -i "$api/gVvU73C" | Select-String "HTTP/"
```

Kết quả (chạy cho link `OvZcd9S` và alias `smoke-test-1`, cùng một `X-Owner-Id`):

| # | Lệnh | Kết quả | Đạt |
|---|---|---|---|
| 14 | `DELETE /api/links/OvZcd9S` | `204` | Có |
| 15 | `GET /OvZcd9S` sau khi xóa | `HTTP/1.1 404 Not Found` | Có |
| 16 | `DELETE /api/links/smoke-test-1` | `204` | Có |
| 17 | `GET /smoke-test-1` sau khi xóa | `HTTP/1.1 404 Not Found` | Có |

Quyền IAM đã thu hẹp của `LinksFunction` (xóa mềm link, dọn click và thống kê) hoạt động trên AWS thật, không có lỗi 500.

### Độ trễ lần 1 (gọi thẳng API Gateway)

Đo từ máy phát triển ở TP. Hồ Chí Minh tới Region `ap-southeast-2`, bằng `scripts/measure_latency.py` (50 yêu cầu mỗi đích, tuần tự, cách nhau 250 ms).
Kết quả đầy đủ: `docs/latency_lan1.json`. Đơn vị: mili giây. Yêu cầu đầu tiên có thể dính cold start nên tách riêng.

| Đích | ok/tổng | Đầu tiên | min | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| `GET /api/health` | 50/50 | 1393 | 337 | 341 | 351 | 364 | 364 |
| `GET /api/stats` | 50/50 | 2933 | 388 | 409 | 425 | 475 | 475 |
| `GET /v2x560i` (redirect, link thử riêng) | 50/50 | 1229 | 382 | 410 | 426 | 456 | 456 |

Nhận xét:
- Số đo là thời gian trọn vòng từ máy đo (gồm mạng tới Sydney), không phải thời gian chạy bên trong Lambda. Chưa đo riêng thời gian trong Lambda; cần chạy truy vấn CloudWatch Logs Insights trong phần mô tả của `scripts/measure_latency.py`.
- Yêu cầu đầu tiên chậm hơn rõ (1,2 đến 2,9 giây), khớp với cold start của Lambda.
- Lần 2 đo lại qua CloudFront để so sánh.


## Lần 2 (BaseUrl là domain CloudFront, gọi qua CloudFront)

- Ngày chạy smoke test: 2026-11-04 18:33 (giờ Việt Nam). Deploy lần 2 xong lúc khoảng 17:44 ngày 2026-11-04.
- Stack: `linkpulse-backend`, Region `ap-southeast-2`, cập nhật stack cũ (`UPDATE_COMPLETE`), `CAPABILITY_IAM`.
- Tham số đổi so với lần 1: `BaseUrl=https://d3rsimgoxz85kx.cloudfront.net`, `OwnDomains=d3rsimgoxz85kx.cloudfront.net`, `OriginVerifySecretParam=/linkpulse/origin-verify`. `ErrorPageMode=redirect` giữ nguyên; các tham số còn lại giữ như lần 1.
- Changeset: thêm `OriginSecretReadPolicy` (IAM ManagedPolicy), sửa 6 Lambda, 5 IAM Role và `HttpApi`. Không có resource bị thay thế, không đụng DynamoDB.
- CloudFront: `https://d3rsimgoxz85kx.cloudfront.net` (TV5: DistributionId E240XHWY20B7CL). API Gateway: `https://q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com`.
- Lệnh deploy: `sam deploy --stack-name linkpulse-backend --region ap-southeast-2 --capabilities CAPABILITY_IAM --resolve-s3 --confirm-changeset --parameter-overrides BaseUrl=... OwnDomains=... ErrorPageMode=redirect OriginVerifySecretParam=/linkpulse/origin-verify`.
- Kiểm tra trước deploy: `aws ssm get-parameter --name /linkpulse/origin-verify` trả `SecureString` ở `ap-southeast-2`.

| # | Lệnh | Kết quả | Đạt |
|---|---|---|---|
| 1 | curl.exe -s "$CF/api/health" | 200, {"status": "ok"} | Có |
| 2 | curl.exe -s "$API/api/health" (gọi thẳng, không qua CloudFront) | 403 | Có |
| 3 | POST /api/shorten {"url":"https://example.com"} + X-Owner-Id | 201, code=mwQZoFv, short_url=https://d3rsimgoxz85kx.cloudfront.net/mwQZoFv | Có |
| 4 | GET /mwQZoFv (lần 1) | HTTP/1.1 302 Found, location: https://example.com | Có |
| 5 | GET /mwQZoFv (lần 2) | HTTP/1.1 302 Found, location: https://example.com | Có |
| 6 | GET /mwQZoFv (lần 3) | HTTP/1.1 302 Found, location: https://example.com | Có |
| 7 | GET /api/links + X-Owner-Id | 200 | Có |
| 8 | GET /api/stats/mwQZoFv | 200, total_clicks=3 | Có |
| 9 | GET /api/stats | 200, total_clicks=3 | Có |
| 10 | POST /api/shorten với url không hợp lệ | 400 | Có |
| 11 | POST /api/shorten với alias=smoke-l2-43884 | 201 | Có |
| 12 | POST /api/shorten lại cùng alias | 409 | Có |
| 13 | POST /api/shorten với alias=admin (alias dành riêng) | 409 | Có |
| 14 | GET /api/links không có X-Owner-Id | 401 | Có |
| 15 | GET /zzzzzzz (mã không tồn tại) | HTTP/1.1 404 Not Found | Có |
| 16 | DELETE /api/links/mwQZoFv | 204 | Có |
| 17 | GET /mwQZoFv sau khi xóa | HTTP/1.1 404 Not Found | Có |
| 18 | DELETE /api/links/smoke-l2-43884 | 204 | Có |
| 19 | GET /smoke-l2-43884 sau khi xóa | HTTP/1.1 404 Not Found | Có |

Tổng: 19 phép thử, 0 không đạt.

Nhận xét:
- `short_url` đã đổi sang domain CloudFront (lần 1 là `linkpulse.vn`).
- Gọi thẳng API Gateway bị từ chối (dòng 2, `reason: origin_not_allowed`) còn qua CloudFront thì chạy: cơ chế `X-Origin-Verify` hoạt động.
- Độ trễ qua CloudFront chưa đo trong đợt này.

Ảnh chụp lần 2 (`docs/screenshots/aws/lan2/`):
- `smoke-health.png`: `/api/health` qua CloudFront trả `200`.
- `smoke-direct-403.png`: gọi thẳng API Gateway trả `403`.
- `deploy-success-and-curl.png`: deploy lần 2 thành công và hai lệnh `curl` đầu tiên.
- `lambda.png`: 6 hàm Lambda của stack.
- `api-gateway.png`, `api-gateway-routes.png`, `api-gateway-routes-2.png`: API `linkpulse-backend` và các route.
- `dynamodb.png`: 5 bảng DynamoDB của stack.
- `cloudwatch.png`: 6 log group Lambda, cột lưu giữ là 1 tuần (7 ngày).

## Lần 3 — 13/11/2026

**Mục đích:** deploy với ngưỡng demo để kiểm tra cờ suspicious (spike và bot).

**Lệnh:** như lần 2, thêm `SpikeClicksPerMinute=30` và `BotMinClicks=10`. Tạo changeset bằng `sam deploy --no-execute-changeset`, xem trước, rồi chạy bằng `aws cloudformation execute-change-set`.

**Tham số:** `IpHashSalt=*****` (giữ nguyên lần 1), `BaseUrl=https://d3rsimgoxz85kx.cloudfront.net`, `OwnDomains=d3rsimgoxz85kx.cloudfront.net`, `ErrorPageMode=redirect`, `OriginVerifySecretParam=/linkpulse/origin-verify`, `SpikeClicksPerMinute=30`, `BotMinClicks=10`.

**Deploy:** 14:58 (UTC+7) ngày 13/11/2026. Changeset `samcli-deploy1794541173`, thao tác `UPDATE_STACK` ID `97f59d87-3b1d-4258-84e4-28188368a0f8`. Stack `linkpulse-backend` ở trạng thái `UPDATE_COMPLETE`. `ProcessClicksFunction` có `SPIKE_CLICKS_PER_MINUTE=30`, `BOT_MIN_CLICKS=10`. Độ dài salt vẫn là 32 ký tự (không đổi).

**Kết quả smoke test**

| Bước | Kết quả |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `POST /api/shorten` | Tạo link `gLvW9pX` thành công (`created: true`) |
| Cờ bot (curl, 40 lần) | Link `gLvW9pX`: 10 lần `302`, sau đó `403 link_suspicious`; stats: 10 click, `bot_clicks=10`; status `suspicious` |
| Cờ spike (UA trình duyệt, 40 lần) | Link `8j9KaKl`: 31 lần `302`, sau đó `403`; 31 click, `bot_clicks=0`; status `suspicious`. Chạy lại với link `xfgamwh`: 30 lần `302`, sau đó 10 lần `403` |
| Link suspicious trên trình duyệt | Chuyển sang `/warning.html?reason=suspicious&code=8j9KaKl` |
| Link hết lượt (`max_clicks=1`) | Link `jCkvxmk`: lần 1 `302`, lần 2 `410 max_clicks_reached`; trình duyệt chuyển sang `/error.html?type=max_clicks` |

**Ảnh** (trong `docs/screenshots/e2e/`):

- `23-lan3-env-processclicks.png`: biến môi trường ProcessClicksFunction (đã che salt)
- `24-lan3-stack-update-complete.png`: stack `UPDATE_COMPLETE`
- `25-lan3-stack-events.png`: sự kiện cập nhật stack
- `26-lan3-terminal-302-403.png`: terminal cờ spike, link `xfgamwh` (30 lần `302`, 10 lần `403`)
- `27-lan3-warning-page.png`: trang `warning.html`
- `28-lan3-expired-error.png`: trang `error.html?type=max_clicks`
- `29-lan3-terminal-410.png`: terminal `410 max_clicks_reached`

**Việc sau demo:** deploy lại với `SpikeClicksPerMinute=300`, `BotMinClicks=50` để link bình thường không bị gắn cờ nhầm.

## Kiểm bản deploy so với main — 13/11/2026 15:51

Đã kiểm, khớp main (13/11/2026 15:51). Bản deploy trên AWS (stack `linkpulse-backend`, deploy lần 3) build từ commit `9f541aa`; `main` hiện ở commit `7a04352`. Từ `9f541aa` đến nay các PR đã merge chỉ sửa `docs/` (ảnh và `docs/smoke_test.md`), không có thay đổi nào trong `backend/` (`git diff --stat 9f541aa HEAD -- backend` không có kết quả), nên không cần deploy lại và không cần chạy lại smoke test.
