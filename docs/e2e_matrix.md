# E2E matrix — TV2

Kết quả thực tế chỉ được điền sau khi TV1/TV4/TV5 bàn giao API, CloudFront và dữ liệu test. Các dòng dưới đây hiện chưa chạy, không phải kết quả giả.

| Tình huống | Cách làm | Kết quả mong đợi | Kết quả thực tế | Đạt/Không | Gửi ai |
|---|---|---|---|---|---|
| Tạo link mới | POST URL hợp lệ | 201 | Chưa chạy — thiếu API thật | Chưa chạy | TV1 |
| Trùng URL cùng owner | Gửi lại cùng URL/owner | 200, created=false | Chưa chạy — thiếu API thật | Chưa chạy | TV1 |
| URL sai | Gửi URL không hợp lệ | 400 invalid_url | Mock đã có fixture; API thật chưa chạy | Chưa chạy | TV1 |
| Domain bị chặn | Gửi domain blocklist | 400 blocked_domain | Mock đã có fixture; API thật chưa chạy | Chưa chạy | TV1/TV5 |
| Alias trùng/dành riêng | Gửi alias đã dùng, `login`, `robots` | 409 alias_taken; alias reserved bị chặn client | Client đã kiểm tra `login`/`robots`; API thật chưa chạy | Chưa chạy | TV1 |
| Rate limit | Gửi liên tiếp | 429 và countdown đọc Retry-After | Mock fixture có; API thật chưa chạy | Chưa chạy | TV1/TV5 |
| Turnstile sai/thiếu | Gửi token sai hoặc thiếu khi bật | 400 captcha_failed | Chờ TV5 bật đồng thời | Chưa chạy | TV5/TV1 |
| Redirect active | Mở mã hợp lệ | 302 tới đích | Chưa chạy — thiếu domain CloudFront | Chưa chạy | TV1/TV5 |
| Mã không tồn tại | Mở mã không có | `/error.html?type=404` | Chưa chạy — thiếu CloudFront | Chưa chạy | TV5 |
| Hết hạn/max clicks | Mở link tương ứng | error page đúng `type` | Chưa chạy — thiếu dữ liệu test | Chưa chạy | TV1/TV4 |
| Suspicious/blocked | Mở link bị gắn cờ | warning đúng reason; blocked không vượt qua | Chưa chạy — thiếu dữ liệu test | Chưa chạy | TV4/TV5 |
| Link của tôi | Phân trang, lọc, q, sort, DELETE | Cursor đúng; 204 và mở lại 404 | Chưa chạy — thiếu API thật | Chưa chạy | TV1 |
| Dashboard | Tạo click rồi xem 15m/1h/24h | Cập nhật ≤10 giây; tab ẩn dừng polling | Chưa chạy — thiếu API/stats thật | Chưa chạy | TV1/TV4 |
| Protection chỉ xem | Gắn cờ link rồi mở trang | Hiện số lượng/trạng thái, không có nút quản trị | Client đã không có nút quản trị; API thật chưa chạy | Chưa chạy | TV4/TV5 |
| Lỗi mạng/5xx/403 HTML | Tắt mạng hoặc trả response biên | Thông báo thân thiện, không lộ raw body | Mock có network/server_error/waf_html; API thật chưa chạy | Chưa chạy | TV1/TV5 |

Mỗi dòng không đạt phải bổ sung nguyên văn mã lỗi, HTTP status, thời điểm và phân loại TV2 hoặc người nhận tương ứng.