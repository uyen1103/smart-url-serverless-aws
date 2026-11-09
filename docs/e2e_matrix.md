# Kiểm thử E2E — Frontend TV2

- Môi trường kiểm thử: `https://d3rsimgoxz85kx.cloudfront.net`, ngày 2026-11-05.
- Ảnh bằng chứng nằm trong `screenshots/e2e/`.
- Ảnh giao diện không thay thế bằng chứng HTTP.

## Giao diện

| Ca kiểm thử | Kết quả thực tế | Đánh giá | Ảnh |
|---|---|---|---|
| Mở trang HTTPS / Console | Đã mở 6 trang (index, dashboard, links, protection, warning, error); Console “No issues”, không có dòng đỏ (18:17–18:44). | Đạt | [01-console-home](screenshots/e2e/01-console-home.png), [02-console-links](screenshots/e2e/02-console-links.png), [03-console-protection](screenshots/e2e/03-console-protection.png) |
| Tạo link | Tạo thành công, trạng thái “Đang hoạt động”; `short_url=https://d3rsimgoxz85kx.cloudfront.net/RBe8QOi` (18:17–18:44). | Đạt | [18-links-active](screenshots/e2e/18-links-active.png) |
| Trùng URL trên giao diện | Giao diện báo link đã có trong tài khoản. | Đã quan sát trên giao diện | [06-url-duplicate](screenshots/e2e/06-url-duplicate.png) |
| URL `abc` trên giao diện | Giao diện báo URL không đúng định dạng. | Đã quan sát trên giao diện | [07-url-invalid-abc](screenshots/e2e/07-url-invalid-abc.png) |
| `https://bad.example/test` trên giao diện | Backend trả `invalid_url` vì DNS không phân giải; ảnh không phải bằng chứng blocklist. | Đã quan sát trên giao diện; blocklist API chưa chạy | [11-blocked-domain-dns-rejected](screenshots/e2e/11-blocked-domain-dns-rejected.png) |
| Alias dành riêng, tạo mới và trùng trên giao diện | Giao diện báo `login` dành riêng, tạo được `tv2-test-01` và báo alias đã dùng. | Đã quan sát trên giao diện | [08-alias-reserved-login](screenshots/e2e/08-alias-reserved-login.png), [09-alias-created](screenshots/e2e/09-alias-created.png), [10-alias-taken](screenshots/e2e/10-alias-taken.png) |
| Mở link và sau khi xóa | Mở `RBe8QOi` 3 lần, Click = 3; sau khi xóa, mở lại chuyển tới `/error.html?type=404` (18:17–18:44). | Đạt theo quan sát trình duyệt | [16-404-after-delete](screenshots/e2e/16-404-after-delete.png) |
| Mã không tồn tại | Trang `/error.html?type=404` hiện “Không tìm thấy liên kết” cùng nút tạo link và xem link của tôi (18:17–18:44). | Đạt | [17-error-404-page](screenshots/e2e/17-error-404-page.png) |
| Trang cảnh báo suspicious | `/warning.html?reason=suspicious` hiện cảnh báo đáng ngờ và nút “Quay lại nơi an toàn”. | Đạt phần giao diện | [19-warning-suspicious](screenshots/e2e/19-warning-suspicious.png) |
| Link của tôi và xóa link | Hiện `RBe8QOi`, đích `https://example.com`, Click = 3, hết hạn 12/11/2026; xóa xong hiện thông báo và danh sách trống (18:17–18:44). | Đạt các thao tác đã kiểm tra | [14-delete-confirm](screenshots/e2e/14-delete-confirm.png), [15-delete-toast](screenshots/e2e/15-delete-toast.png) |
| Danh sách link nhiều trạng thái | Ảnh hiển thị 2 link: một link đạt giới hạn với 2 click và một link đang hoạt động với 4 click. | Đã quan sát trên giao diện | [20-links-multiple-states](screenshots/e2e/20-links-multiple-states.png) |
| Dashboard | Tổng 9 click (3 hợp lệ, 6 bot); biểu đồ cập nhật trong vài giây sau click lúc 18:17 (18:17–18:44). | Đạt | [04-dashboard-system-wide](screenshots/e2e/04-dashboard-system-wide.png) |
| Chống lạm dụng chỉ xem | Có 4 số liệu (1 / 1 / 0 / 3), danh sách gắn cờ trống, không có nút quản trị (18:17–18:44). | Đạt | [05-protection-readonly](screenshots/e2e/05-protection-readonly.png) |
| Lỗi mạng mô phỏng | DevTools Offline làm yêu cầu `shorten` thất bại; giao diện báo không thể kết nối máy chủ. | Đạt mô phỏng Offline; chưa thử ngắt Wi-Fi | [12-offline-devtools](screenshots/e2e/12-offline-devtools.png), [13-offline-friendly-error](screenshots/e2e/13-offline-friendly-error.png) |
| Frontend trên S3 | Ảnh hiển thị 6 trang HTML, `favicon.svg`, `css/`, `js/` và thư mục `mock/` (2026-11-05). | Đạt | [01-s3-bucket](screenshots/aws/01-s3-bucket.png) |
| CloudFront | Ảnh hiển thị 1 distribution ở trạng thái Enabled và domain `d3rsimgoxz85kx.cloudfront.net`; distribution ID bị che (2026-11-05). | Đạt | [02-cloudfront-enabled-domain](screenshots/aws/02-cloudfront-enabled-domain.png) |

## API

| Ca kiểm thử | Kết quả thực tế | Đánh giá |
|---|---|---|
| URL sai | POST `/api/shorten` trả HTTP 400, `invalid_url`, `reason=scheme_not_allowed` (17:58 +07; CloudShell). | Đạt |
| Trùng URL cùng owner | Gửi lại URL và owner trả HTTP 200, `created=false`, code `LA8fvII` (17:50:01 +07). | Đạt |
| Alias dành riêng | API trả HTTP 409 cho `login` và `admin` (17:50:02 +07). | Đạt |
| Tạo alias mới rồi gửi lại | `e2e-10498` được tạo HTTP 201; gửi lại trả HTTP 409, `alias_taken` (17:58 +07; CloudShell). | Đạt |
| Domain trong blocklist | Chưa chạy — chưa có domain thật trong blocklist; `bad.example` bị backend loại ở bước DNS trước blocklist. | Chưa chạy |
| Rate limit | Chưa chạy — rate limit không được kiểm tra. | Chưa chạy |
| Turnstile sai/thiếu | Chưa chạy — backend chưa bật Turnstile. | Chưa chạy |
| Hết hạn / max clicks | Chưa mở link lần 3; ảnh chỉ cho thấy trạng thái “Đạt giới hạn” ở 2 click trong danh sách Link của tôi ([ảnh](screenshots/e2e/20-links-multiple-states.png)); hết hạn chưa kiểm tra. | Đã quan sát trên giao diện; hết hạn chưa chạy |
| Lỗi 5xx | Chưa chạy — không gây lỗi cố ý trên môi trường dùng chung. | Chưa chạy |
| Phản hồi 403 HTML | 2026-11-09 20:41, localhost:8000, mock `waf_html`: giao diện hiện “Chưa thể tạo liên kết. Máy chủ trả về nội dung không hợp lệ. Vui lòng thử lại sau.” kèm nút “Thử lại”; trang không vỡ, không lộ chữ thô ([ảnh](screenshots/e2e/21-waf-html-mock.png)). WAF thật chưa kiểm tra. | Đạt phần giao diện (mock) |

## Quan sát chưa chặn merge

1. Ô alias trên `index.html`: đã sửa trong code, cần xác nhận sau khi deploy lại.
2. Trục tung biểu đồ Dashboard: mock normal có nhãn 0, 8, 16, 24, 32; mock spike có nhãn 0, 70, 140, 210, 280; spike sửa còn 0–2: chưa kiểm. Đã sửa trong code, cần xác nhận sau khi deploy lại.
3. Hộp thoại xác nhận xóa dùng hộp thoại mặc định của trình duyệt.
4. `deploy.sh` và `deploy.ps1` loại `mock/` khỏi nội dung deploy; đã sửa trong code, cần xác nhận sau khi deploy lại. Ảnh S3 ngày 2026-11-05 vẫn hiển thị thư mục `mock/`.
5. Dashboard dùng nhãn “Toàn hệ thống” trong code; cần xác nhận sau khi deploy lại.
6. Issue ghi 7 trang; frontend hiện có 6 trang HTML.
