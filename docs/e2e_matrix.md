# Kiểm thử E2E — Frontend TV2

- Môi trường kiểm thử: `https://d3rsimgoxz85kx.cloudfront.net`, ngày 2026-11-05.
- Ảnh bằng chứng nằm trong `screenshots/e2e/`.
- Ảnh giao diện không thay thế bằng chứng HTTP.
- Các dòng kiểm thử lớp chống lạm dụng (TV5) cập nhật ngày 2026-11-10, bằng chứng ở
  `screenshots/aws/lan3/`, chi tiết lệnh và output ở [`security_test_week2.md`](security_test_week2.md).

## Giao diện

| Ca kiểm thử | Kết quả thực tế | Đánh giá | Ảnh |
|---|---|---|---|
| Mở trang HTTPS / Console | Đã mở 6 trang (index, dashboard, links, protection, warning, error); Console “No issues”, không có dòng đỏ (18:17–18:44). | Đạt | [01-console-home](screenshots/e2e/01-console-home.png), [02-console-links](screenshots/e2e/02-console-links.png), [03-console-protection](screenshots/e2e/03-console-protection.png) |
| Tạo link | Tạo thành công, trạng thái “Đang hoạt động”; `short_url=https://d3rsimgoxz85kx.cloudfront.net/RBe8QOi` (18:17–18:44). | Đạt | [18-links-active](screenshots/e2e/18-links-active.png) |
| Trùng URL trên giao diện | Giao diện báo link đã có trong tài khoản. | Đã quan sát trên giao diện | [06-url-duplicate](screenshots/e2e/06-url-duplicate.png) |
| URL `abc` trên giao diện | Giao diện báo URL không đúng định dạng. | Đã quan sát trên giao diện | [07-url-invalid-abc](screenshots/e2e/07-url-invalid-abc.png) |
| `https://bad.example/test` trên giao diện | Backend trả `invalid_url` vì DNS không phân giải; ảnh không phải bằng chứng blocklist. Kiểm thử blocklist thật đã chạy riêng với domain phân giải được `example.org` (xem dòng "Domain trong blocklist" ở mục API). | Đã quan sát trên giao diện | [11-blocked-domain-dns-rejected](screenshots/e2e/11-blocked-domain-dns-rejected.png) |
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
| Kiểm bản deploy thật | Kiểm tra ngày 09/11/2026 tại `https://d3rsimgoxz85kx.cloudfront.net/`: `USE_MOCK=false`; 6 trang (index, links, dashboard, protection, warning, error) tải đúng; S3 không còn `mock/`. Console chỉ có lỗi `Uncaught (in promise)` tại `onboarding.js:48`, không thuộc code dự án và nghi do extension trình duyệt. | Đạt | [01_index](screenshots/e2e/01_index.png), [02_links](screenshots/e2e/02_links.png), [03_dashboard](screenshots/e2e/03_dashboard.png), [04_protection](screenshots/e2e/04_protection.png), [05_warning](screenshots/e2e/05_warning.png), [06_error](screenshots/e2e/06_error.png) |

## API

| Ca kiểm thử | Kết quả thực tế | Đánh giá |
|---|---|---|
| URL sai | POST `/api/shorten` trả HTTP 400, `invalid_url`, `reason=scheme_not_allowed` (17:58 +07; CloudShell). | Đạt |
| Trùng URL cùng owner | Gửi lại URL và owner trả HTTP 200, `created=false`, code `LA8fvII` (17:50:01 +07). | Đạt |
| Alias dành riêng | API trả HTTP 409 cho `login` và `admin` (17:50:02 +07). | Đạt |
| Tạo alias mới rồi gửi lại | `e2e-10498` được tạo HTTP 201; gửi lại trả HTTP 409, `alias_taken` (17:58 +07; CloudShell). | Đạt |
| Domain trong blocklist | 2026-11-10: thêm domain thật `example.org` (DNS phân giải được) bằng `scripts/blocklist.sh add ... --execute`; POST `/api/shorten` với URL `https://example.org/tv5-block-test` trả HTTP 400, `error.code = blocked_domain`. Đã gỡ domain sau khi thử, `blocklist.sh list` trả `Count: 0`. Ảnh: [03-blocklist-list](screenshots/aws/lan3/03-blocklist-list.png), [04-blocked-domain-body](screenshots/aws/lan3/04-blocked-domain-body.png), [05-blocklist-empty](screenshots/aws/lan3/05-blocklist-empty.png). | Đạt |
| Rate limit | 2026-11-10 14:49 +07: 15 POST `/api/shorten` liên tiếp → 10 request đầu `201`, từ request 11 trả `429` kèm header `Retry-After` (41 → 38 giây); bảng `rate_limits` ghi `cnt = 10` cho khóa `shorten#<ip_hash>#<bucket>`. Lớp throttling API Gateway kiểm riêng bằng 120 request song song → 35 lần `429 {"message":"Too Many Requests"}` (không `Retry-After`) và 64 lần `429 {"code":"rate_limited"}` (có `Retry-After`). Ảnh: [01-ratelimit-output](screenshots/aws/lan3/01-ratelimit-output.png), [02-rate-limits-table](screenshots/aws/lan3/02-rate-limits-table.png), [06-apigateway-throttling](screenshots/aws/lan3/06-apigateway-throttling.png). | Đạt |
| Turnstile sai/thiếu | Không dùng, backend tắt (`TurnstileSecretParam` để trống khi deploy). | Không áp dụng |
| Hết hạn | 2026-11-13 (CloudShell, UTC+0 → +07): 09:10:26 +07 tạo link bằng `curl -s -X POST "https://$CF_DOMAIN/api/shorten" -H 'Content-Type: application/json' -H 'X-Owner-Id: 11111111-1111-4111-8111-111111111111' -d '{"url":"https://example.com/e2e-expire-<timestamp>","expires_in":60}'` → `created=true`, code `D8IYRNa`, `expires_at=2026-11-13T02:11:29Z` (09:11:29 +07). Chờ `sleep 75`, 09:12:13 +07 chạy `curl -s -i "https://$CF_DOMAIN/D8IYRNa"` → `HTTP/2 410`, `cache-control: no-store`, body `{"error": {"code": "link_expired", "message": "Link đã hết hạn."}}`. Trình duyệt (cửa sổ ẩn danh) mở cùng link → chuyển tới `/error.html?type=expired`, trang hiện "Liên kết đã hết hạn" cùng nút "Tạo liên kết mới" và "Xem link của tôi". Ảnh: [<img width="1919" height="1001" alt="Screenshot 2026-11-13 093504" src="https://github.com/user-attachments/assets/1e469ca6-5607-4c44-aca6-ccf057b3a20e" />); output curl dựng từ log CloudShell bằng `scripts/render_evidence.py`: [22b-expired-curl-410](<img width="1906" height="644" alt="22b expired curl 410" src="https://github.com/user-attachments/assets/bcd1f147-696d-4b92-8d0e-8f47d4f0a30a" />). | Đạt |
| Max clicks | Chưa mở link lần 3; ảnh chỉ cho thấy trạng thái “Đạt giới hạn” ở 2 click trong danh sách Link của tôi ([ảnh](screenshots/e2e/20-links-multiple-states.png)). | Đã quan sát trên giao diện; max clicks chưa chạy |
| Lỗi 5xx | Chưa chạy — không gây lỗi cố ý trên môi trường dùng chung. | Chưa chạy |
| Phản hồi 403 HTML | Chưa chạy — WAF thật không bật (giữ `EnableWaf=false` để chi phí $0; `infra/edge.yaml` bọc Web ACL trong `Condition`). Lớp biên đã kiểm thật là `X-Origin-Verify`: gọi thẳng API Gateway trả `403` (`reason: origin_not_allowed`), qua CloudFront trả `200` ([ảnh](screenshots/aws/lan2/smoke-direct-403.png)). Phần giao diện với mock `waf_html` vẫn giữ kết quả trước ([ảnh](screenshots/e2e/21-waf-html-mock.png)). | Chưa chạy (WAF) |

## Hạ tầng & phân quyền

| Ca kiểm thử | Kết quả thực tế | Đánh giá |
|---|---|---|
| AWS Budget $5/tháng | `linkpulse-monthly-ap-southeast-2-5usd` — giới hạn `5.0 USD`, lọc Region `ap-southeast-2`, `ActualSpend = 0.0 USD` (`aws budgets describe-budgets --account-id 567627324019 --region us-east-1`) | Đạt |
| Script phân quyền từng người | 2026-11-10: chạy thật cả `scripts/setup_aws_foundation.sh` và `.ps1`; cả hai **dừng ở bước preflight** với thông báo "KHÔNG ĐỦ QUYỀN — cần IAM admin" vì user `linkpulse-tv5` không có `iam:*` (`iam:GetGroup` → `AccessDenied`). Group `linkpulse-devs`, 4 policy theo vai trò, user riêng từng người và MFA **chưa tạo được**. Chi tiết: [security_test_week2.md](security_test_week2.md) mục 0.4 | Chưa chạy được (thiếu `iam:*`) |
| Console access cho `linkpulse-tv5` | Chưa có `LoginProfile` (user chỉ có access key) → không đăng nhập được AWS Console bằng user này. Script đã hỗ trợ `--console-password` / `-ConsolePassword` để admin cấp khi chạy được | Chưa chạy (thiếu `iam:*`) |

## Quan sát chưa chặn merge

1. `frontend/dashboard.html` dòng 32 đổi “Tất cả link của tôi” thành “Toàn hệ thống”. — Đã sửa.
2. `frontend/index.html` bỏ chữ cứng `linkpulse.vn/`, lấy domain từ `PUBLIC_DOMAIN` trong `config.js`; ô alias trên bản deploy hiện `d3rsimgoxz85kx.cloudfront.net/`. — Đã sửa.
3. Trục tung biểu đồ Dashboard không còn lặp nhãn “2”. — Đã sửa.
4. `deploy.sh` và `deploy.ps1` exclude `mock/*`, bỏ `/mock/*` khỏi invalidation. — Đã sửa.
5. Hộp thoại xác nhận xóa dùng hộp thoại mặc định của trình duyệt.
6. Issue ghi 7 trang; frontend hiện có 6 trang HTML.
