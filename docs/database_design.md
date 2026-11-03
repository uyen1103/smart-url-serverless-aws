# DATABASE DESIGN

## 1. Mục tiêu

Thiết kế các bảng Amazon DynamoDB cho hệ thống LinkPulse – dịch vụ rút gọn URL có chức năng lưu trữ URL, ghi nhận lịch sử click, tổng hợp thống kê, giới hạn request và quản lý domain bị chặn.

Hệ thống sử dụng 5 bảng DynamoDB:

- `urls`: Lưu thông tin URL rút gọn.
- `clicks`: Lưu lịch sử các sự kiện click.
- `stats`: Lưu dữ liệu thống kê tổng hợp.
- `rate_limits`: Lưu thông tin giới hạn request.
- `blocklist`: Lưu danh sách domain bị chặn.

Cấu hình tính phí mặc định là `PROVISIONED`. Hệ thống vẫn hỗ trợ chuyển sang `PAY_PER_REQUEST` thông qua Parameter `BillingMode`.

Nguồn cấu hình chuẩn: `backend/template.yaml`.

## 2. Thiết kế bảng `urls`

Bảng `urls` lưu thông tin các đường dẫn rút gọn.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `short_code` | Partition Key (PK) | Mã rút gọn duy nhất của URL |
| `long_url` | Attribute | Đường dẫn gốc |
| `created_at` | Attribute | Thời điểm tạo URL |
| `expires_at` | Attribute | Thời điểm URL hết hạn nếu được sử dụng |
| `owner_id` | Attribute | Định danh chủ sở hữu URL |
| `status` | Attribute | Trạng thái URL |
| `max_clicks` | Attribute | Số lượt click tối đa nếu có giới hạn |
| `click_count` | Attribute | Số lượt click hiện tại |

### Global Secondary Index (GSI)

Bảng `urls` có GSI tên `owner-index`.

| Thuộc tính | Giá trị |
|---|---|
| Index name | `owner-index` |
| Partition Key | `owner_id` |
| Sort Key | `created_at` |
| Projection | `ALL` |

GSI hỗ trợ truy vấn danh sách URL theo chủ sở hữu và sắp xếp theo thời gian tạo.

### Access patterns

- Lấy URL theo mã rút gọn: `GetItem` bằng `short_code`.
- Kiểm tra mã rút gọn đã tồn tại: `PutItem` với điều kiện `attribute_not_exists(short_code)`.
- Liệt kê URL theo chủ sở hữu: `Query` trên GSI `owner-index`.

## 3. Thiết kế bảng `clicks`

Bảng `clicks` lưu các sự kiện click của từng URL.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `short_code` | Partition Key (PK) | Mã rút gọn được click |
| `sk` | Sort Key (SK) | Khóa sắp xếp của sự kiện click |
| `ip_hash` | Attribute | Giá trị băm IP, không lưu IP gốc |
| `country` | Attribute | Mã quốc gia |
| `device` | Attribute | Nhóm thiết bị |
| `browser` | Attribute | Tên trình duyệt |
| `referrer` | Attribute | Nguồn giới thiệu |
| `user_agent` | Attribute | Thông tin User-Agent |
| `expires_at` | TTL attribute | Unix timestamp tính bằng giây để xác định thời điểm hết hạn |

### Access patterns

- Lấy lịch sử click theo URL: `Query` bằng `short_code`.
- Truy vấn click theo khoảng thời gian: sử dụng điều kiện trên Sort Key `sk`.

### TTL

Bảng `clicks` được cấu hình TTL tự động thông qua thuộc tính `expires_at`.

Giá trị TTL phải là kiểu Number chứa Unix timestamp tính bằng giây. DynamoDB không bảo đảm xóa bản ghi ngay tại thời điểm hết hạn.

### DynamoDB Streams

Bảng `clicks` được bật DynamoDB Streams với cấu hình:

- `StreamViewType: NEW_IMAGE`

Cấu hình này cho phép các thành phần xử lý sự kiện nhận dữ liệu ảnh mới của bản ghi khi có sự kiện ghi mới vào bảng.

## 4. Thiết kế bảng `stats`

Bảng `stats` lưu dữ liệu thống kê tổng hợp theo phạm vi và khoảng thời gian.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `scope` | Partition Key (PK) | Phạm vi thống kê |
| `sk` | Sort Key (SK) | Khóa sắp xếp của dữ liệu thống kê |
| `click_count` | Attribute | Tổng số click được ghi nhận |
| `updated_at` | Attribute | Thời điểm cập nhật dữ liệu |
| `expires_at` | TTL attribute | Unix timestamp tính bằng giây để xác định thời điểm hết hạn |

### Access patterns

- Truy vấn dữ liệu thống kê theo phạm vi: `Query` bằng `scope`.
- Lọc dữ liệu theo khóa sắp xếp: sử dụng điều kiện trên `sk`.

Bảng `stats` có thể phục vụ việc lưu trữ các số liệu tổng hợp theo URL hoặc phạm vi thời gian tùy theo quy ước dữ liệu của ứng dụng.

### TTL

Bảng `stats` được bật TTL bằng thuộc tính `expires_at`.

Giá trị TTL phải là Number chứa Unix timestamp tính bằng giây.

## 5. Thiết kế bảng `rate_limits`

Bảng `rate_limits` lưu thông tin bộ đếm request nhằm hỗ trợ giới hạn tốc độ truy cập.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `pk` | Partition Key (PK) | Khóa định danh nguồn request |
| `request_count` | Attribute | Số request trong cửa sổ hiện tại |
| `window_start` | Attribute | Thời điểm bắt đầu cửa sổ đếm |
| `expires_at` | TTL attribute | Unix timestamp tính bằng giây để xác định thời điểm hết hạn |

### Access patterns

- Lấy thông tin giới hạn request: `GetItem` bằng `pk`.
- Cập nhật bộ đếm request: `UpdateItem` bằng `pk`.

### TTL

Bảng `rate_limits` được bật TTL tự động thông qua thuộc tính `expires_at`, phục vụ việc loại bỏ các bản ghi giới hạn request đã hết hạn.

## 6. Thiết kế bảng `blocklist`

Bảng `blocklist` lưu danh sách các domain bị chặn.

| Thuộc tính | Vai trò | Mô tả |
|---|---|---|
| `domain` | Partition Key (PK) | Tên miền cần kiểm tra |
| `reason` | Attribute | Lý do domain bị chặn |
| `created_at` | Attribute | Thời điểm domain được thêm vào danh sách |

### Access patterns

- Kiểm tra domain có nằm trong danh sách chặn hay không: `GetItem` bằng `domain`.
- Thêm domain vào danh sách: `PutItem`.
- Xóa domain khỏi danh sách: `DeleteItem`.

## 7. Bảng tổng hợp Access Patterns

| Access pattern | Bảng / Index | Thao tác |
|---|---|---|
| Lấy URL theo mã rút gọn | `urls`, PK `short_code` | `GetItem` |
| Kiểm tra mã rút gọn trùng | `urls`, PK `short_code` | `PutItem` có điều kiện |
| Liệt kê URL theo chủ sở hữu | `urls`, GSI `owner-index` | `Query` |
| Lấy lịch sử click theo URL | `clicks`, PK `short_code` | `Query` |
| Lọc click theo thời gian | `clicks`, SK `sk` | `Query` |
| Truy vấn thống kê theo phạm vi | `stats`, PK `scope` | `Query` |
| Lấy thông tin giới hạn request | `rate_limits`, PK `pk` | `GetItem` |
| Cập nhật bộ đếm request | `rate_limits`, PK `pk` | `UpdateItem` |
| Kiểm tra domain bị chặn | `blocklist`, PK `domain` | `GetItem` |

Lưu ý: Bảng `stats` hiện được mô tả theo khóa `scope` và `sk`. Cách tổ chức dữ liệu cụ thể và logic tổng hợp phụ thuộc vào phần triển khai ứng dụng.

## 8. TTL và DynamoDB Streams

### 8.1. TTL

Theo `backend/template.yaml`, TTL được bật cho 3 bảng:

| Bảng | TTL attribute | Trạng thái |
|---|---|---|
| `clicks` | `expires_at` | Enabled |
| `stats` | `expires_at` | Enabled |
| `rate_limits` | `expires_at` | Enabled |

Các giá trị TTL sử dụng kiểu Number và Unix timestamp tính bằng giây.

DynamoDB thực hiện xóa dữ liệu hết hạn theo cơ chế nền. Vì vậy, bản ghi có thể vẫn tồn tại một khoảng thời gian sau khi đạt thời điểm hết hạn.

### 8.2. DynamoDB Streams

Bảng `clicks` được cấu hình DynamoDB Streams với `NEW_IMAGE`.

Streams cung cấp dữ liệu mới của bản ghi cho các thành phần xử lý sự kiện. Đây là cơ sở để tích hợp các chức năng xử lý click và cập nhật thống kê.

Việc xử lý sự kiện cần lưu ý khả năng một sự kiện được gửi hoặc xử lý lại, do đó logic ứng dụng nên cân nhắc cơ chế idempotency.

## 9. Chi phí và dung lượng DynamoDB

### 9.1. Billing Mode

Parameter `BillingMode` trong `backend/template.yaml` có hai giá trị:

| Parameter | Giá trị |
|---|---|
| Default | `PROVISIONED` |
| AllowedValues | `PROVISIONED`, `PAY_PER_REQUEST` |

Chế độ mặc định `PROVISIONED` được lựa chọn để kiểm soát dung lượng đọc và ghi, phù hợp với mục tiêu sử dụng giới hạn tài nguyên miễn phí của dự án.

### 9.2. Provisioned Throughput

Dung lượng đọc và ghi được cấu hình như sau:

| Bảng / Index | Read Capacity Units (RCU) | Write Capacity Units (WCU) |
|---|---:|---:|
| `urls` | 6 | 5 |
| `owner-index` | 2 | 4 |
| `clicks` | 1 | 4 |
| `stats` | 10 | 4 |
| `rate_limits` | 1 | 5 |
| `blocklist` | 3 | 1 |
| **Tổng cộng** | **23** | **23** |

Tổng dung lượng provisioned:

- 23 RCU.
- 23 WCU.

Cấu hình nằm trong giới hạn mục tiêu 25 RCU và 25 WCU của dự án.

Lưu ý: Dung lượng của GSI `owner-index` được tính riêng vào tổng dung lượng provisioned.

### 9.3. Point-in-Time Recovery (PITR)

Parameter `EnablePitr` điều khiển chức năng Point-in-Time Recovery của bảng `urls`.

- Giá trị mặc định: `false`.
- Chỉ bật khi có nhu cầu và được nhóm thống nhất.
- Cấu hình được thực hiện thông qua điều kiện `PitrEnabled` trong CloudFormation.

Mục tiêu là tránh phát sinh chi phí lưu trữ sao lưu ngoài nhu cầu triển khai hiện tại.

## 10. Trạng thái triển khai và nguồn cấu hình

`backend/template.yaml` là nguồn cấu hình chuẩn cho cấu trúc DynamoDB trong dự án.

Các thông tin được xác định trực tiếp từ template:

- Có 5 bảng DynamoDB: `urls`, `clicks`, `stats`, `rate_limits`, `blocklist`.
- GSI `owner-index` được khai báo trên bảng `urls`.
- TTL được bật trên `clicks`, `stats`, `rate_limits`.
- DynamoDB Streams được bật trên `clicks` với `NEW_IMAGE`.
- Billing Mode mặc định là `PROVISIONED`.
- Tổng dung lượng provisioned là 23 RCU và 23 WCU.
- PITR của bảng `urls` mặc định tắt.

Các logic xử lý dữ liệu, truy vấn thực tế, pipeline tổng hợp thống kê và kết quả kiểm thử cần được xác nhận từ mã nguồn ứng dụng và quá trình kiểm thử riêng.