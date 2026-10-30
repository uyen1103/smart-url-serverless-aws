# Frontend TV2 

Tài liệu này mô tả trạng thái phần frontend web TV2, cách chạy thử và các điều kiện cần có trước khi nối backend/deploy. 

Tài liệu nghiên cứu và wireframe ban đầu: [frontend_research.md](./frontend_research.md), [gui_wireframe.md](./gui_wireframe.md). API chuẩn để đối chiếu: [api_spec.yaml](./api_spec.yaml).

## 1. Phạm vi đã triển khai

| Trang | File | Hành vi |
|---|---|---|
| Rút gọn link | `frontend/index.html` | Nhập URL và tùy chọn alias, thời hạn, số click tối đa; hiển thị kết quả, sao chép và trạng thái lỗi. |
| Thống kê | `frontend/dashboard.html` | KPI, click hợp lệ/bot, thiết bị, top link, quốc gia, nguồn giới thiệu và click gần nhất; tự làm mới định kỳ. |
| Link của tôi | `frontend/links.html` | Tìm kiếm, lọc, sắp xếp, phân trang, sao chép, xem thống kê và yêu cầu xóa sau xác nhận. |
| Chống lạm dụng | `frontend/protection.html` | Trang thông tin chỉ xem về các lớp bảo vệ và trạng thái cấu hình. |
| Cảnh báo | `frontend/warning.html` | Nội dung cho link bị chặn hoặc đáng ngờ theo `reason`. |
| Lỗi link | `frontend/error.html` | Nội dung cho `404`, `expired` và `max_clicks` theo `type`. |

Giao diện tuân theo các token trong `frontend/css/tokens.css`; bố cục được tách giữa HTML từng trang, CSS dùng chung và JavaScript ES modules. Các phần tử động được tạo bằng DOM APIs/text nodes thay vì chèn chuỗi HTML.

## 2. Cấu trúc frontend

| Đường dẫn | Trách nhiệm |
|---|---|
| `frontend/css/tokens.css` | Màu, typography, spacing và bo góc. |
| `frontend/css/style.css` | Kiểu dùng chung, bố cục trang chủ/dashboard và responsive. |
| `frontend/js/config.js` | API base URL, chế độ mock, domain public, liên hệ, Turnstile và chu kỳ polling. |
| `frontend/js/api.js` | API client, chuẩn hóa lỗi, timeout, owner header và mock handlers. |
| `frontend/js/owner.js` | Sinh UUID owner và lưu trong `localStorage`. |
| `frontend/js/dom.js` | Tạo phần tử an toàn, gán text, kiểm tra URL attribute và tiện ích DOM. |
| `frontend/js/shell.js` | Header/footer, toast, clipboard và trạng thái nút gửi. |
| `frontend/js/validate.js` | Kiểm tra URL, alias và giới hạn click ở client. |
| `frontend/js/home.js` | Form rút gọn link, xử lý kết quả/lỗi, sao chép và xác minh nếu được cấu hình. |
| `frontend/js/dashboard.js`, `charts.js`, `poller.js` | Dashboard, biểu đồ SVG và polling có backoff khi lỗi. |
| `frontend/js/links.js` | Danh sách, tìm kiếm, lọc, phân trang và xác nhận xóa. |
| `frontend/js/warning.js`, `error.js` | Hiển thị các trạng thái cảnh báo/lỗi từ query string. |
| `frontend/mock/` | Fixture link, thống kê và phản hồi mô phỏng; không phải dữ liệu backend. |
| `frontend/deploy.ps1` | Preview/sync S3 và invalidation CloudFront có kiểm soát. |

## 3. Hợp đồng tích hợp API

API client dùng đường dẫn tương đối `/api` và gắn `X-Owner-Id` cho các request. Owner ID là UUID lưu trong trình duyệt, **không phải đăng nhập hay cơ chế xác thực**.

| Màn hình/thao tác | Request theo `api_spec.yaml` | Ghi chú |
|---|---|---|
| Tạo link | `POST /api/shorten` | JSON gồm `url`, tùy chọn `alias`, `expires_in` (giây), `max_clicks`, `turnstile_token`. Hiển thị kết quả mới `201` hoặc mã cũ `200`. |
| Danh sách của tôi | `GET /api/links` | Query hỗ trợ `q`, `status`, `sort`, `limit`, `cursor`; trả `summary`, `items`, `next_cursor`. |
| Xóa link | `DELETE /api/links/{code}` | UI hỏi xác nhận trước; thành công là `204`. |
| Dashboard tổng | `GET /api/stats?from=...&to=...&granularity=...` | Polling 5 giây; `granularity` là `minute` hoặc `hour`. |
| Dashboard theo link | `GET /api/stats/{code}?from=...&to=...&granularity=...` | Query `code` trên URL trang dashboard chọn thống kê riêng của link. |
| Truy cập mã rút gọn | `GET /{code}` | Redirect và mã lỗi do backend/CloudFront quyết định; frontend không tự xác định link còn hoạt động hay không. |

Các lỗi được xử lý dựa trên `error.code`, không dựa vào nội dung `message`:

| HTTP / mã lỗi | Hiển thị |
|---|---|
| `400 invalid_url` | Thông báo dưới trường URL. |
| `400 blocked_domain` | Thông báo domain không được chấp nhận cạnh URL. |
| `400 captcha_failed` | Thông báo xác minh chống lạm dụng không thành công. |
| `400 invalid_expires_in` | Thông báo thời hạn liên kết không hợp lệ. |
| `400 invalid_request` | Thông báo yêu cầu không hợp lệ. |
| `409 alias_taken` | Thông báo cạnh trường alias. |
| `404 not_found` | Thông báo không tìm thấy liên kết. |
| `410 link_expired` | Thông báo link đã hết hạn. |
| `410 max_clicks_reached` | Thông báo link đã đạt giới hạn click. |
| `403 link_blocked` | Thông báo link đã bị chặn. |
| `403 link_suspicious` | Cảnh báo link cần được xem xét. |
| `429 rate_limited` | Cảnh báo vàng và đếm ngược từ header `Retry-After`. |
| `5xx internal_error` | Thông báo dịch vụ tạm thời không khả dụng. |
| `5xx`, timeout, mất mạng | Thông báo lỗi và nút thử lại; giữ dữ liệu người dùng. |
| Phản hồi không phải JSON | Chuẩn hóa thành lỗi phản hồi không hợp lệ; không giả làm kết quả thành công. |

**Cần phối hợp TV1 trước khi chuyển khỏi mock:** xác nhận API đã triển khai đúng base path `/api`, schema, header owner, CORS (nếu khác origin), phản hồi `Retry-After`, status redirect/error và dữ liệu thống kê. Không đổi frontend sang gọi production khi chưa có endpoint môi trường thử nghiệm.

Dashboard lấy danh sách lọc bằng nhiều request `limit: 50`, tối đa 4 trang và chống cursor lặp; nếu còn dữ liệu sẽ thông báo giới hạn 200 link.

**Cần phối hợp TV4/TV5:** TV4 xác nhận nghĩa của các chỉ số/timestamp và cách xử lý click bot; TV5 xác nhận CloudFront behaviors cho `/api/*`, trang tĩnh và `/{code}`. Không cache API hoặc redirect trừ khi nhóm thống nhất cấu hình cụ thể.

## 4. Mock và chạy thử giao diện

Mặc định hiện tại `USE_MOCK` đang bật trong `frontend/js/config.js`; các request trình duyệt vì vậy chưa gọi API thật. `?mock=1` chỉ có tác dụng trên localhost/127.0.0.1. Khi deploy, đổi `USE_MOCK=false` và chỉ điền `TURNSTILE_SITE_KEY` sau khi TV5 bật secret backend đồng thời.

Chạy từ thư mục gốc repository:

```powershell
python -m http.server 8000 --directory frontend
```

Mở `http://localhost:8000/index.html`. Dùng trình duyệt truy cập qua HTTP server thay vì `file://`, vì frontend sử dụng ES modules và mock JSON.

Các đường dẫn kiểm thử:

| Mục đích | URL |
|---|---|
| Trang chủ mặc định | `http://localhost:8000/index.html?scenario=ok` |
| Dashboard mock | `http://localhost:8000/dashboard.html?mock=1` |
| Thống kê theo mã | `http://localhost:8000/dashboard.html?code=khuyen-mai-tet&mock=1` |
| Hiện bộ chọn kịch bản demo | `http://localhost:8000/index.html?showDemo=1&scenario=ok` |
| Link bị chặn/đáng ngờ | `http://localhost:8000/warning.html?reason=blocked` hoặc `?reason=suspicious&code=promo88` |
| Link lỗi/hết hạn/hết lượt | `http://localhost:8000/error.html?type=404`, `?type=expired`, `?type=max_clicks` |

Kịch bản mock rút gọn: `ok`, `duplicate`, `invalid_url`, `blocked_domain`, `alias_taken`, `rate_limited`, `network`, `server_error`, `waf_html`. Kịch bản dashboard dùng `statsScenario=normal`, `empty`, `spike`, `suspicious` hoặc `network`.


## 5. Deploy và điều kiện còn chờ

Có script hỗ trợ triển khai frontend: `frontend/deploy.ps1` cho PowerShell và `frontend/deploy.sh` cho Bash. Đọc hướng dẫn ngắn tại [README_DEPLOY.md](../frontend/README_DEPLOY.md); PowerShell dùng đúng tham số `-Bucket`, `-DistributionId`, `-Execute`, `-Invalidate`.

Ví dụ PowerShell sau khi TV5 cung cấp bucket/distribution và AWS CLI đã cấu hình:

```powershell
$env:S3_BUCKET = "<bucket-frontend>"
$env:CLOUDFRONT_DISTRIBUTION_ID = "<distribution-id>"
.\frontend\deploy.ps1
.\frontend\deploy.ps1 -Execute -Invalidate
```

**Chưa deploy trong tài liệu này.** Cần TV5 cung cấp bucket private, CloudFront distribution/OAC, behaviors, domain và quyền AWS; cần xác nhận policy cache/invalidation. Cần TV1 cung cấp API thử nghiệm trước khi chuyển `USE_MOCK` sang `false`. Không lưu access key/secret trong repository hoặc script.

