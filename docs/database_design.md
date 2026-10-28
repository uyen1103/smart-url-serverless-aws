# DATABASE DESIGN

## 1. Mục tiêu

Thiết kế các bảng DynamoDB cho dịch vụ rút gọn URL, lưu lịch sử click, tổng hợp thống kê, giới hạn request và quản lý domain bị chặn. Các bảng sử dụng chế độ tính phí `PAY_PER_REQUEST` trong script tạo bảng hiện tại.

## 2. Thiết kế bảng `urls`

Bảng `urls` lưu thông tin các đường dẫn rút gọn.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `short_code` (PK) | Partition key | Mã rút gọn duy nhất của URL |
| `long_url` | Attribute | Đường dẫn gốc |
| `created_at` | Attribute | Thời điểm tạo URL, nên dùng ISO 8601 UTC |
| `expires_at` | Attribute | Thời điểm URL hết hạn nếu hệ thống hỗ trợ thời hạn |
| `owner` | Attribute | Chủ sở hữu URL |
| `status` | Attribute | Trạng thái URL, ví dụ `active` hoặc `blocked` |
| `max_clicks` | Attribute | Số lượt click tối đa nếu có giới hạn |
| `click_count` | Attribute | Số lượt click hiện tại |

**Access patterns:**
- Lấy URL theo mã rút gọn: `GetItem` bằng `short_code`.
- Kiểm tra mã đã tồn tại khi tạo mới: `PutItem` với điều kiện `attribute_not_exists(short_code)`.
- Liệt kê URL theo chủ sở hữu: cần GSI đề xuất `owner-index` với partition key `owner` và sort key `created_at`. GSI này chưa được tạo trong script hiện tại.

## 3. Thiết kế bảng `clicks`

Bảng `clicks` lưu các sự kiện click của từng URL.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `short_code` (PK) | Partition key | Mã rút gọn được click |
| `click_key` (SK) | Sort key | Chuỗi kết hợp thời gian và ID duy nhất của click, ví dụ `2026-10-28T06:00:00Z#001` |
| `ip_hash` | Attribute | Mã băm IP; không lưu IP gốc |
| `country` | Attribute | Mã quốc gia ISO alpha-2, ví dụ `VN`; dùng `XX` nếu không xác định |
| `device` | Attribute | Nhóm thiết bị, ví dụ `desktop`, `mobile`, `tablet`, `bot`, `other` |
| `browser` | Attribute tùy chọn theo event schema | Tên trình duyệt suy ra từ User-Agent |
| `referrer` | Attribute | Nguồn giới thiệu hoặc `direct` |
| `user_agent` | Attribute tùy chọn theo event schema | User-Agent, tối đa 512 ký tự theo `click_event_schema.json` |
| `expires_at` | TTL attribute | Unix timestamp tính bằng giây, dùng làm thời điểm hết hạn |

`click_event_schema.json` mô tả sự kiện đầu vào gồm 8 trường bắt buộc: `short_code`, `timestamp`, `ip_hash`, `country`, `device`, `browser`, `referrer`, `user_agent`. Khi lưu vào DynamoDB, `timestamp` được ghép cùng ID để tạo giá trị `click_key`; vì vậy cần bảo đảm pipeline xử lý sự kiện thực hiện ánh xạ này.

**Access patterns:**
- Lấy lịch sử click của một URL: `Query` với `short_code` và tùy chọn điều kiện trên `click_key` để giới hạn khoảng thời gian.
- Dữ liệu click được dự kiến lưu tối đa 30 ngày. TTL được bật trên bảng `clicks` với thuộc tính `expires_at`; thuộc tính này phải là kiểu Number chứa Unix timestamp tính bằng giây.

**Lưu ý triển khai:** script `database/scripts/create_tables.sh` hiện tạo khóa `click_key`, nhưng chưa tự bật TTL. TTL đã được bật thủ công trên môi trường DynamoDB Local trong quá trình kiểm thử. Cơ chế xóa TTL có thể không diễn ra ngay lập tức; việc bản ghi hết hạn còn đọc được không nhất thiết có nghĩa cấu hình TTL sai.

## 4. Thiết kế bảng `stats_agg`

Bảng `stats_agg` lưu số liệu click đã tổng hợp theo từng URL và khoảng thời gian.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `short_code` (PK) | Partition key | Mã rút gọn |
| `time_bucket` (SK) | Sort key | Mốc thời gian thống kê theo phút hoặc giờ |
| `click_count` | Attribute | Tổng số click trong khoảng thời gian |
| `updated_at` | Attribute | Thời điểm cập nhật số liệu |

**Access pattern:** lấy số liệu thống kê của một URL bằng `Query` trên `short_code`, có thể lọc theo khoảng `time_bucket`.

**Top link:** schema hiện tại chưa hỗ trợ trực tiếp việc xếp hạng tất cả URL theo tổng số click. Cần thống nhất thiết kế bổ sung (ví dụ một bảng tổng hợp theo phạm vi thời gian hoặc một index phù hợp) trước khi coi access pattern Top link là đã triển khai. Không nên xem GSI Top link là đã tồn tại khi chưa được định nghĩa và tạo trong script.

## 5. Thiết kế bảng `rate_limits`

Bảng `rate_limits` lưu bộ đếm request theo IP để hỗ trợ giới hạn tốc độ truy cập.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `ip` (PK) | Partition key | Định danh nguồn request; nên cân nhắc dùng giá trị đã băm nếu không cần lưu IP gốc |
| `request_count` | Attribute | Số request trong cửa sổ hiện tại |
| `window_start` | Attribute | Thời điểm bắt đầu cửa sổ đếm |
| `expires_at` | TTL attribute dự kiến | Unix timestamp tính bằng giây để dữ liệu giới hạn request hết hạn |

TTL được dự kiến dùng cho dữ liệu ngắn hạn. Trong script hiện tại, bảng `rate_limits` chưa được bật TTL tự động; cần thêm cấu hình TTL nếu đây là yêu cầu triển khai.

## 6. Thiết kế bảng `blocklist`

Bảng `blocklist` lưu danh sách domain bị chặn.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `domain` (PK) | Partition key | Tên miền cần kiểm tra |
| `reason` | Attribute | Lý do chặn domain |
| `created_at` | Attribute | Thời điểm thêm domain vào danh sách |

**Access pattern:** kiểm tra domain có bị chặn không bằng `GetItem` theo `domain`.

## 7. Ánh xạ access pattern sang bảng và thao tác

| Access pattern | Bảng / index | Thao tác | Trạng thái |
|---|---|---|---|
| Lấy URL theo mã rút gọn khi redirect | `urls`, PK `short_code` | `GetItem` | Đã kiểm thử trên DynamoDB Local |
| Kiểm tra mã rút gọn trùng | `urls`, PK `short_code` | `PutItem` với `attribute_not_exists(short_code)` | Đã kiểm thử trên DynamoDB Local |
| Đếm hoặc truy vấn click theo URL và thời gian | `clicks`, PK `short_code`, SK `click_key`; hoặc `stats_agg` | `Query` | Đã kiểm thử `Query` trên `clicks`; chưa kiểm thử pipeline tổng hợp |
| Xem thống kê theo URL và khoảng thời gian | `stats_agg`, PK `short_code`, SK `time_bucket` | `Query` | Schema đã thiết kế; cần kiểm thử riêng |
| Xếp hạng Top link | Chưa chốt bảng/index tổng hợp | Cần thiết kế | Chưa hoàn thiện |
| Liệt kê URL theo chủ sở hữu | GSI đề xuất `owner-index` trên `urls` | `Query` | Chưa tạo GSI trong script hiện tại |
| Kiểm tra domain trong blocklist | `blocklist`, PK `domain` | `GetItem` | Schema đã tạo; cần kiểm thử riêng |
| Đếm request theo IP | `rate_limits`, PK `ip` | `GetItem` / `UpdateItem` | Schema đã tạo; cần kiểm thử riêng |

## 8. TTL và DynamoDB Streams

### TTL

- `clicks`: TTL attribute `expires_at`, dự kiến lưu click tối đa 30 ngày.
- `rate_limits`: TTL attribute `expires_at`, dự kiến dùng thời hạn ngắn.
- Giá trị TTL phải là Number chứa Unix timestamp tính bằng giây.
- Trạng thái TTL được xác nhận bằng `describe-time-to-live`. Việc bật TTL không bảo đảm bản ghi bị xóa ngay tại thời điểm hết hạn.

### DynamoDB Streams

Luồng xử lý analytics có thể sử dụng DynamoDB Streams trên bảng `clicks` để kích hoạt Lambda xử lý click và cập nhật `stats_agg`. Đây là phương án kiến trúc đề xuất; script tạo bảng hiện tại chưa bật Streams và chưa triển khai Lambda xử lý sự kiện. Nếu triển khai, cần xử lý idempotency vì sự kiện có thể được xử lý lại.

## 9. Trạng thái triển khai hiện tại

Script `database/scripts/create_tables.sh` hiện tạo 5 bảng `urls`, `clicks`, `stats_agg`, `rate_limits`, `blocklist` với chế độ `PAY_PER_REQUEST`. Các khóa chính và khóa sắp xếp được khai báo trong script. GSI `owner-index`, cấu hình TTL tự động trong script, DynamoDB Streams và pipeline tổng hợp chưa được script hiện tại tạo hoặc cấu hình.
