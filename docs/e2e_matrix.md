# E2E matrix — TV2

Đã kiểm thử API qua CloudFront ngày 2026-11-05; các dòng chưa chạy có ghi rõ lý do.

| Tình huống | Cách làm | Kết quả mong đợi | Kết quả thực tế | Đạt/Không | Gửi ai |
|---|---|---|---|---|---|
| Tạo link mới | POST URL hợp lệ | 201 | Tạo link thành công, trạng thái “Đang hoạt động”; `short_url=https://d3rsimgoxz85kx.cloudfront.net/RBe8QOi` (2026-11-05 18:17–18:44). | Đạt | TV1 |
| Mở trang HTTPS / Console | Mở từng trang HTTPS và kiểm tra Console | 6 trang mở được, không có lỗi Console | Đã mở 6 trang (index, dashboard, links, protection, warning, error); Console “No issues”, không có dòng đỏ (2026-11-05 18:17–18:44, Cốc Cốc, cửa sổ ẩn danh). | Đạt | TV2 |
| Trùng URL cùng owner | Gửi lại cùng URL/owner | 200, created=false | API: HTTP 200, `created=false`, code `LA8fvII` (2026-11-05 17:50:01 +07). | Đạt (qua API, chưa chạy lại trên giao diện) | TV1 |
| URL sai | Gửi URL không hợp lệ | 400 invalid_url | API: HTTP 400, `invalid_url`, `reason=scheme_not_allowed` (2026-11-05 17:58 +07, chạy trong CloudShell). | Đạt (qua API, chưa chạy lại trên giao diện) | TV1 |
| Domain bị chặn | Gửi domain blocklist | 400 blocked_domain | Chưa chạy — chưa có domain trong blocklist | Chưa chạy | TV1/TV5 |
| Alias trùng/dành riêng | Gửi alias đã dùng, `login`, `admin` | Alias mới 201 rồi trùng 409; alias dành riêng 409 hoặc 400 | API: alias mới `e2e-10498` HTTP 201, `short_url=https://d3rsimgoxz85kx.cloudfront.net/e2e-10498`; gửi lại alias HTTP 409, `alias_taken` (2026-11-05 17:58 +07, chạy trong CloudShell). `login` và `admin`: HTTP 409 (2026-11-05 17:50:02 +07). | Đạt (qua API, chưa chạy lại trên giao diện) | TV1 |
| Rate limit | Gửi liên tiếp | 429 và countdown đọc Retry-After | Chưa chạy — không kiểm tra rate limit trong lượt này | Chưa chạy | TV1/TV5 |
| Turnstile sai/thiếu | Gửi token sai hoặc thiếu khi bật | 400 captcha_failed | Chưa chạy — backend chưa bật Turnstile | Chưa chạy | TV5/TV1 |
| Redirect active | Mở mã hợp lệ | 302 tới đích | Mở `RBe8QOi` 3 lần; danh sách hiển thị Click = 3. Sau khi xóa, mở lại chuyển tới `/error.html?type=404` (2026-11-05 18:17–18:44). | Đạt | TV1/TV5 |
| Mã không tồn tại | Mở mã không có | `/error.html?type=404` | Trang `/error.html?type=404` hiển thị “Không tìm thấy liên kết” cùng nút “Tạo liên kết mới” và “Xem link của tôi” (2026-11-05 18:17–18:44). | Đạt | TV5 |
| Hết hạn/max clicks | Mở link tương ứng | error page đúng `type` | Chưa chạy — link hết hạn và dữ liệu kiểm thử `max_clicks` chưa có | Chưa chạy | TV1/TV4 |
| Suspicious/blocked | Mở link bị gắn cờ | warning đúng reason; blocked không vượt qua | `/warning.html?reason=suspicious` hiển thị “Liên kết này có dấu hiệu đáng ngờ” và nút “Quay lại nơi an toàn” (2026-11-05 18:17–18:44). Chỉ xác minh giao diện warning, chưa kiểm tra bypass ở backend. | Đạt (giao diện warning) | TV4/TV5 |
| Link của tôi | Phân trang, lọc, q, sort, DELETE | Cursor đúng; 204 và mở lại 404 | Hiển thị `RBe8QOi`, đích `https://example.com`, Click = 3, hết hạn 12/11/2026; có Sao chép/Thống kê/Xóa. Xóa qua hộp thoại xác nhận mặc định; thông báo “Đã xóa liên kết.” và danh sách trống (2026-11-05 18:17–18:44). Phân trang/lọc/q/sort chưa kiểm tra. | Đạt (các thao tác đã kiểm tra) | TV1 |
| Dashboard | Tạo click rồi xem 15m/1h/24h | Cập nhật ≤10 giây; tab ẩn dừng polling | Sau 3 lần mở link, biểu đồ có cột click hợp lệ lúc 18:17 và cập nhật trong vài giây; tổng 9 click (3 hợp lệ, 6 bot) (2026-11-05 18:17–18:44). | Đạt | TV1/TV4 |
| Protection chỉ xem | Gắn cờ link rồi mở trang | Hiện số lượng/trạng thái, không có nút quản trị | Có dòng “Trang chỉ xem...”, 4 số liệu (1 / 1 / 0 / 3), danh sách gắn cờ trống, không có nút quản trị (2026-11-05 18:17–18:44). | Đạt | TV4/TV5 |
| Lỗi mạng/5xx/403 HTML | Tắt mạng hoặc trả response biên | Thông báo thân thiện, không lộ raw body | Chưa chạy — chưa tắt Wi-Fi để thử lỗi mạng; chưa gây được lỗi 5xx; chưa kiểm tra 403 HTML | Chưa chạy | TV1/TV5 |

Mỗi dòng không đạt phải bổ sung nguyên văn mã lỗi, HTTP status, thời điểm và phân loại TV2 hoặc người nhận tương ứng.

## Quan sát

1. Dashboard hiển thị “Tất cả link của tôi”, nhưng `/api/stats` đang trả số liệu toàn hệ thống (9 click, 1 link gắn cờ), khác trang Chống lạm dụng (3 click, 0 link gắn cờ). TV1/TV2 quyết định đổi nhãn hay lọc theo owner.
2. Ô alias trên `index.html` hiển thị tiền tố cố định `linkpulse.vn/`. Việc của TV2.
3. Trục tung biểu đồ Dashboard lặp hai nhãn “2” liên tiếp. Việc của TV2.
4. Hộp thoại xác nhận xóa là hộp thoại mặc định của trình duyệt, khác thiết kế Figma. Việc của TV2.
5. `deploy.sh` vẫn đẩy thư mục `mock/` lên S3 dù `USE_MOCK=false`. TV5/TV1 quyết định có sửa `deploy.sh` không.
6. Issue ghi 7 trang; thực tế frontend có 6 trang: index, dashboard, links, protection, warning và error.