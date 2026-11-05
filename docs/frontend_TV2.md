# Frontend TV2

Tài liệu này mô tả trạng thái frontend web TV2, cách chạy thử và triển khai.

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

```text
frontend/
  index.html
  dashboard.html
  links.html
  protection.html
  warning.html
  error.html
  css/
    style.css
    tokens.css
  js/
    config.js
    api.js
    owner.js
    validate.js
    dom.js
    shell.js
    poller.js
    charts.js
    home.js
    dashboard.js
    links.js
    protection.js
    warning.js
    error.js
  mock/
```

## 3. Hợp đồng tích hợp API

API client dùng đường dẫn tương đối `/api` và gắn `X-Owner-Id` cho các request. Owner ID là UUID lưu trong trình duyệt, **không phải đăng nhập hay cơ chế xác thực**. Hợp đồng API tham chiếu [api_spec.yaml](./api_spec.yaml).

| Màn hình/thao tác | Request theo `api_spec.yaml` | Ghi chú |
|---|---|---|
| Tạo link | `POST /api/shorten` | JSON gồm `url`, tùy chọn `alias`, `expires_in` (giây), `max_clicks`, `turnstile_token`. Hiển thị kết quả mới `201` hoặc mã cũ `200`. |
| Danh sách của tôi | `GET /api/links` | Query hỗ trợ `q`, `status`, `sort`, `limit`, `cursor`; trả `summary`, `items`, `next_cursor`. |
| Xóa link | `DELETE /api/links/{code}` | UI hỏi xác nhận trước; thành công là `204`. |
| Dashboard tổng | `GET /api/stats?from=...&to=...&granularity=...` | Polling 5 giây; `granularity` là `minute` hoặc `hour`. |
| Dashboard theo link | `GET /api/stats/{code}?from=...&to=...&granularity=...` | Query `code` trên URL trang dashboard chọn thống kê riêng của link. |
| Truy cập mã rút gọn | `GET /{code}` | Redirect và mã lỗi do backend/CloudFront quyết định; frontend không tự xác định link còn hoạt động hay không. |

Thông báo dưới đây lấy từ `getApiErrorMessage` trong `frontend/js/api.js`; lỗi API được chuẩn hóa dựa trên `error.code`:

| Mã lỗi / tình huống | Thông báo trên giao diện |
|---|---|
| `invalid_url` | “URL không hợp lệ hoặc không được hỗ trợ.” |
| `blocked_domain` | “Domain này không được phép rút gọn.” |
| `alias_taken` | “Alias đã được sử dụng. Hãy chọn tên khác.” |
| `rate_limited` | “Bạn thao tác quá nhanh. Vui lòng chờ rồi thử lại.”; luồng tạo link dùng `Retry-After` để hiển thị thời gian chờ. |
| `captcha_failed` | “Xác minh chống lạm dụng không thành công. Hãy thử lại.” |
| `internal_error`, `server_error` hoặc HTTP 5xx | “Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.” |
| `network_error` | “Không thể kết nối máy chủ. Kiểm tra mạng rồi thử lại.” |
| `timeout` | “Máy chủ phản hồi quá lâu. Hãy thử lại.” |
| `invalid_response` | “Máy chủ trả về nội dung không hợp lệ. Vui lòng thử lại sau.”; dùng cho response không phải JSON hoặc JSON sai định dạng. |
| `invalid_alias` | “Alias cần có 3–30 ký tự chữ, số hoặc dấu gạch ngang.” |
| `invalid_max_clicks` | “Số click tối đa phải là số nguyên từ 1 trở lên.” |
| `invalid_expires_in` | “Thời hạn liên kết không hợp lệ.” |
| `invalid_request` | “Yêu cầu không hợp lệ. Hãy kiểm tra lại thông tin.” |
| `not_found` | “Không tìm thấy liên kết.” |
| `unauthorized` | “Không thể xác thực mã chủ sở hữu của trình duyệt này.” |
| `forbidden` hoặc HTTP 403 | “Yêu cầu bị từ chối bởi lớp bảo vệ. Hãy kiểm tra thông tin và thử lại.” |
| `link_expired` | “Link đã hết hạn.” |
| `link_blocked` | “Link đã bị chặn.” |
| `link_suspicious` | “Link cần được xem xét trước khi tiếp tục.” |
| `max_clicks_reached` | “Link đã đạt giới hạn click.” |
| `mock_storage_invalid` | “Dữ liệu demo lưu trong trình duyệt bị lỗi. Hãy xóa dữ liệu demo rồi thử lại.” (mock) |
| `storage_unavailable` | “Không lưu được dữ liệu demo trong trình duyệt.” (mock) |
| HTTP 429 | Thông báo rate limit; `Retry-After` được đọc nếu có. |
| Mã lỗi khác | “Không thể hoàn tất yêu cầu. Vui lòng thử lại.” |

`ApiError` cũng đánh dấu HTTP 5xx và 429 là có thể thử lại; mã lỗi server khác không có ánh xạ riêng dùng thông báo chung theo status. Phản hồi không phải JSON hoặc JSON sai định dạng không được coi là thành công.

Dashboard lấy danh sách lọc bằng nhiều request `limit: 50`, tối đa 4 trang và chống cursor lặp; nếu còn dữ liệu sẽ thông báo giới hạn 200 link.

**Cần phối hợp TV4/TV5:** TV4 xác nhận nghĩa của các chỉ số/timestamp và cách xử lý click bot; TV5 xác nhận CloudFront behaviors cho `/api/*`, trang tĩnh và `/{code}`. Không cache API hoặc redirect trừ khi nhóm thống nhất cấu hình cụ thể.

## 4. Mock và chạy thử giao diện

Mock được bật/tắt bằng `USE_MOCK` trong `frontend/js/config.js`; hiện tại giá trị là `false`. `?mock=1` chỉ có tác dụng trên `localhost` hoặc `127.0.0.1`; domain deploy luôn tôn trọng `USE_MOCK`. `TURNSTILE_SITE_KEY` hiện để trống.

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


## 5. Deploy và kiểm thử

Frontend đã được deploy thật ngày 2026-11-05 từ CloudShell lên https://d3rsimgoxz85kx.cloudfront.net bằng `frontend/deploy.sh`. Script đọc `S3_BUCKET` và `CLOUDFRONT_DISTRIBUTION_ID`; chỉ ghi các giá trị thật trong biến môi trường và dùng placeholder trong tài liệu:

```bash
export S3_BUCKET="<tên-bucket>"
export CLOUDFRONT_DISTRIBUTION_ID="<distribution-id>"
bash frontend/deploy.sh
EXECUTE=true INVALIDATE=true bash frontend/deploy.sh
```

Lệnh đầu chỉ xem trước; lệnh thứ hai thực hiện sync và invalidation. Biến export sẽ mất khi phiên CloudShell đóng nên cần đặt lại ở phiên mới. Script loại `prototype/`, `deploy.ps1`, `deploy.sh` và `README_DEPLOY.md` khỏi sync; `mock/` vẫn được sync. Invalidation dùng danh sách khai báo gồm các trang HTML, `/css/*`, `/js/*` và `/mock/*`; script không tự so sánh file để chỉ tìm các đường dẫn đã thay đổi.

Kết quả kiểm thử giao diện/API và các ca chưa chạy được ghi trong [e2e_matrix.md](./e2e_matrix.md). Sáu quan sát chưa chặn merge:

1. Dashboard ghi “Tất cả link của tôi” nhưng số liệu là toàn hệ thống; khác số liệu trang Chống lạm dụng.
2. Ô alias hiển thị tiền tố cố định `linkpulse.vn/`.
3. Trục tung biểu đồ Dashboard lặp nhãn “2”.
4. Hộp thoại xác nhận xóa là hộp thoại mặc định của trình duyệt.
5. `deploy.sh` vẫn upload `mock/` lên S3 dù `USE_MOCK=false`.
6. Issue ghi 7 trang; frontend thực tế có 6 trang.

Các ca chưa chạy và lý do được liệt kê trong ma trận: trùng URL, URL sai và alias chưa chạy lại trên giao diện; domain bị chặn chưa có dữ liệu blocklist; Turnstile chưa bật ở backend; link hết hạn và `max_clicks` chưa có dữ liệu kiểm thử; lỗi mạng chưa thử bằng cách tắt Wi-Fi; lỗi 5xx chưa gây được; 403 HTML chưa kiểm tra.
