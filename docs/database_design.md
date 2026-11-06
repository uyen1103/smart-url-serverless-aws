# DATABASE DESIGN

## 1. Tổng quan

LinkPulse sử dụng Amazon DynamoDB làm cơ sở dữ liệu NoSQL để lưu trữ URL rút gọn, dữ liệu lượt truy cập, thống kê lưu lượng, giới hạn tần suất truy cập và danh sách domain bị chặn.

Hệ thống gồm 5 bảng:

1. `urls`
2. `clicks`
3. `stats`
4. `rate_limits`
5. `blocklist`

Các bảng được tạo và cấu hình thông qua AWS CloudFormation trong `backend/template.yaml`.

## 2. Thiết kế các bảng

### 2.1. Bảng `urls`

**Mục đích:** Lưu thông tin URL gốc và URL rút gọn.

| Thuộc tính | Mô tả |
|---|---|
| `short_code` (PK) | Mã URL rút gọn |
| `long_url` | URL gốc |
| `created_at` | Thời điểm tạo |
| `expires_at` | Thời điểm hết hạn |
| `owner_id` | Chủ sở hữu URL |
| `status` | Trạng thái URL |
| `max_clicks` | Giới hạn lượt truy cập |
| `click_count` | Số lượt truy cập |
| Các thuộc tính khác | Theo dữ liệu nghiệp vụ của URL |

**Global Secondary Index: `owner-index`**

- Partition key: `owner_id`.
- Sort key: `created_at`.
- Projection: `ALL`.

Index hỗ trợ truy vấn danh sách URL theo chủ sở hữu và sắp xếp theo thời gian tạo.

### 2.2. Bảng `clicks`

**Mục đích:** Lưu lịch sử từng lượt truy cập URL. Bảng này đồng thời kích hoạt DynamoDB Streams để xử lý thống kê gần thời gian thực.

| Thuộc tính | Mô tả |
|---|---|
| `short_code` (PK) | Mã URL được truy cập |
| `sk` (SK) | Khóa sắp xếp của sự kiện click |
| `timestamp` | Thời điểm truy cập |
| `ip_hash` | IP đã được băm bằng HMAC-SHA256 |
| `country` | Quốc gia |
| `device` | Thiết bị |
| `browser` | Trình duyệt |
| `referrer` | Nguồn giới thiệu |
| `result` | Kết quả xử lý lượt truy cập |
| `expires_at` | Thời điểm dữ liệu hết hạn |

**Cấu hình:**

- DynamoDB Streams: `NEW_IMAGE`.
- TTL: bật trên thuộc tính `expires_at`.
- Thời gian lưu dữ liệu theo cấu hình hiện tại: 30 ngày.

IP thật không được lưu trực tiếp; hệ thống sử dụng `ip_hash` để hỗ trợ ước tính số người truy cập duy nhất.

### 2.3. Bảng `stats`

**Mục đích:** Lưu dữ liệu thống kê đã tổng hợp từ các sự kiện click.

| Thuộc tính | Mô tả |
|---|---|
| `scope` (PK) | Phạm vi thống kê |
| `sk` (SK) | Khóa xác định nhóm dữ liệu |
| `clicks` | Tổng lượt click |
| `bot_clicks` | Số lượt click từ bot |
| `c:<country>` | Bộ đếm theo quốc gia |
| `d:<device>` | Bộ đếm theo thiết bị |
| `b:<browser>` | Bộ đếm theo trình duyệt |
| `r:<referrer>` | Bộ đếm theo nguồn giới thiệu |
| `l:<code>` | Bộ đếm theo mã URL, chỉ áp dụng cho scope GLOBAL |
| `ips` | Tập hợp các `ip_hash` |
| `items` | Danh sách các lượt click gần đây phục vụ dashboard |
| `expires_at` | Thời điểm dữ liệu hết hạn |

**Quy ước dữ liệu:**

- `scope = GLOBAL`: thống kê toàn hệ thống.
- `scope = LINK#<code>`: thống kê cho một URL cụ thể.
- `sk = M#<minute>`: dữ liệu tổng hợp theo từng phút.
- `scope = META`, `sk = recent_clicks`: lưu danh sách các lượt click gần đây.
- `scope = META`, `sk = flagged_links`: lưu số lượng URL bị gắn cờ.

Các bộ đếm được cập nhật bằng thao tác `ADD` nguyên tử của DynamoDB.

**Cấu hình:**

- TTL: bật trên thuộc tính `expires_at`.
- Thời gian lưu dữ liệu theo cấu hình hiện tại: 8 ngày.

### 2.4. Bảng `rate_limits`

**Mục đích:** Giới hạn số request trong một cửa sổ thời gian cố định.

| Thuộc tính | Mô tả |
|---|---|
| `pk` (PK) | Khóa định danh gồm key và bucket thời gian |
| `cnt` | Số request trong bucket |
| `expires_at` | Thời điểm dữ liệu hết hạn |

**Cơ chế hoạt động:**

- Xác định bucket bằng cách chia timestamp hiện tại cho thời lượng cửa sổ.
- Khóa được tạo theo dạng `key#bucket`.
- Sử dụng `UpdateItem` với `ADD cnt` và `ConditionExpression` để cập nhật bộ đếm nguyên tử.
- Khi số request vượt giới hạn, hệ thống trả về HTTP 429.
- Khi DynamoDB bị throttle, cơ chế rate limit này hoạt động theo hướng fail-open để tránh làm hỏng request; AWS WAF và API Gateway throttling vẫn là các lớp bảo vệ bổ sung.

**Cấu hình:**

- TTL: bật trên thuộc tính `expires_at`.
- Thời điểm hết hạn được tính bằng `(bucket + 2) * window`, tức là sau khi bucket hiện tại kết thúc thêm một cửa sổ thời gian.

### 2.5. Bảng `blocklist`

**Mục đích:** Lưu danh sách domain bị chặn để kiểm tra URL trước khi tạo hoặc xử lý liên kết.

| Thuộc tính | Mô tả |
|---|---|
| `domain` (PK) | Tên domain |
| `reason` | Lý do bị chặn |
| `created_at` | Thời điểm thêm vào danh sách |

## 3. Cấu hình DynamoDB

### 3.1. Billing Mode

CloudFormation hỗ trợ hai chế độ:

- `PROVISIONED`: cấp phát trước năng lực đọc và ghi.
- `PAY_PER_REQUEST`: thanh toán theo số request thực tế.

Giá trị mặc định của tham số `BillingMode` là `PROVISIONED`.

### 3.2. Provisioned Capacity

Cấu hình năng lực đọc và ghi trong `backend/template.yaml`:

| Bảng / Index | Read Capacity (RCU) | Write Capacity (WCU) |
|---|---:|---:|
| `urls` | 6 | 5 |
| `owner-index` | 2 | 4 |
| `clicks` | 1 | 4 |
| `stats` | 10 | 4 |
| `rate_limits` | 1 | 5 |
| `blocklist` | 3 | 1 |
| **Tổng cộng** | **23** | **23** |

Các giá trị trên là cấu hình Provisioned Capacity trong template, không phải số liệu sử dụng thực tế.
### 3.2.1. Capacity và chi phí tham chiếu

Tổng Provisioned Capacity của hệ thống:

- Read Capacity: 23 RCU.
- Write Capacity: 23 WCU.

Theo mức Free Tier DynamoDB được sử dụng làm giả định đối chiếu trong thiết kế (25 RCU và 25 WCU):

| Chỉ số | Hệ thống | Mức tham chiếu | Còn lại |
|---|---:|---:|---:|
| Read Capacity | 23 RCU | 25 RCU | 2 RCU |
| Write Capacity | 23 WCU | 25 WCU | 2 WCU |

Như vậy, cấu hình hiện tại nằm trong mức capacity tham chiếu 25 RCU và 25 WCU.

**Lưu ý:** Đây là phép đối chiếu capacity, không phải cam kết toàn bộ chi phí AWS bằng 0. Chi phí thực tế còn phụ thuộc vào điều kiện Free Tier, thời hạn ưu đãi, Region, lưu trữ, Streams, backup và các dịch vụ AWS khác.

### 3.3. Time to Live (TTL)

TTL được bật trên các bảng:

| Bảng | Thuộc tính TTL | Thời gian lưu theo cấu hình |
|---|---|---|
| `clicks` | `expires_at` | 30 ngày |
| `stats` | `expires_at` | 8 ngày |
| `rate_limits` | `expires_at` | Theo bucket thời gian |

DynamoDB sử dụng thuộc tính `expires_at` để xác định các item hết hạn và xóa chúng tự động. Việc xóa không nhất thiết diễn ra ngay tại thời điểm hết hạn.

### 3.4. DynamoDB Streams

Bảng `clicks` bật DynamoDB Streams với chế độ `NEW_IMAGE`.

Luồng xử lý:

1. Người dùng truy cập URL rút gọn.
2. Hệ thống ghi sự kiện vào bảng `clicks`.
3. DynamoDB Streams phát sinh sự kiện.
4. Lambda `process_clicks` nhận sự kiện.
5. Lambda tổng hợp dữ liệu và cập nhật bảng `stats`.

### 3.5. Point-in-Time Recovery (PITR)

PITR được điều khiển thông qua tham số `EnablePitr`, mặc định là `false`.

Cấu hình PITR áp dụng cho bảng `urls` theo điều kiện trong CloudFormation template.

## 4. Nhận xét thiết kế

- Sử dụng khóa chính phù hợp với các access pattern của từng bảng.
- GSI `owner-index` hỗ trợ truy vấn URL theo chủ sở hữu.
- DynamoDB Streams kết hợp Lambda giúp cập nhật thống kê gần thời gian thực.
- TTL giúp tự động dọn dẹp dữ liệu click, thống kê và rate limit hết hạn.
- Cập nhật bộ đếm bằng `ADD` nguyên tử giúp tránh thao tác đọc rồi ghi lại thủ công.
- IP được băm trước khi lưu nhằm hạn chế lưu trữ thông tin IP thật.
- PITR của bảng `urls` được điều khiển bằng tham số `EnablePitr` và mặc định tắt.

## 5. Giới hạn đã biết

- DynamoDB Streams có cơ chế xử lý at-least-once, do đó khi sự kiện được retry, số liệu tổng hợp có thể bị đếm dư.
- Một item DynamoDB không được vượt quá 400 KB. Tập `ips` hoặc các bộ đếm referrer có thể tăng kích thước lớn khi lưu lượng cao.
- Khi hệ thống đạt lưu lượng rất lớn, có thể cân nhắc HyperLogLog hoặc Kinesis kết hợp Flink để xử lý thống kê ở quy mô cao hơn.