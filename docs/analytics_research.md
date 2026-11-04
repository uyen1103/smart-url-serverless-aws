# Nghiên cứu Analytics

## Pipeline đang triển khai

Redirect ghi click event vào bảng DynamoDB `clicks` theo chế độ best-effort; lỗi ghi analytics không chặn redirect. `ClicksTable` bật DynamoDB Streams với `NEW_IMAGE`. Event source mapping gọi Lambda `process_clicks`, chỉ nhận record `INSERT`.

Lambda gộp event theo phút và theo phạm vi (`GLOBAL` hoặc từng link), sau đó dùng thao tác DynamoDB `ADD` để cộng dồn bộ đếm vào bảng `stats`. `GET /api/stats` và `GET /api/stats/{code}` đọc các bucket này cho dashboard. Mỗi item thống kê giữ bộ đếm theo chiều, referrer và tập hash IP để ước tính visitor duy nhất.

Event source mapping cấu hình retry, tách batch lỗi và gửi record không xử lý được vào SQS DLQ; CloudWatch Alarm cảnh báo khi DLQ có message. Lambda xử lý theo cơ chế at-least-once và hiện chưa khử trùng lặp, vì vậy retry có thể làm số đếm tăng lặp.

Mục tiêu thiết kế là độ trễ từ click tới dashboard **không quá 10 giây**, gồm cả chu kỳ polling API của dashboard. Đây là mục tiêu, không phải SLA hay số đo đã xác nhận; độ trễ thực tế phụ thuộc tải, xử lý và tần suất polling.

## Chỉ số analytics cần theo dõi

| Chỉ số | Cách hiểu/nhóm dữ liệu | Dùng trên dashboard |
|---|---|---|
| **Tổng lượt click** | Số event click trong khoảng thời gian được chọn; có thể lọc theo `short_code`. Đây là số lượt, không phải số người. | Thẻ tổng quan cho toàn hệ thống hoặc một link. |
| **Click/phút** | Số event theo bucket UTC một phút; hiển thị thành chuỗi thời gian. | Biểu đồ xu hướng và nhận biết bất thường. |
| **Top link** | Xếp hạng `short_code` theo lượt click trong cùng khoảng thời gian. | Bảng/xếp hạng link có nhiều lượt click. |
| **Phân bố quốc gia** | Đếm click theo `country`; dùng `XX` khi thiếu hoặc không xác định được. | Bảng hoặc biểu đồ phân bố theo quốc gia. |
| **Thiết bị** | Đếm click theo `device`: `desktop`, `mobile`, `tablet`, `bot`, `other`. | Biểu đồ thiết bị và traffic bot. |
| **Trình duyệt** | Đếm click theo `browser` đã parse, ví dụ Chrome, Safari, Firefox, Edge. | Bảng/biểu đồ tương thích trình duyệt. |
| **Nguồn giới thiệu** | Đếm click theo domain `referrer`; dùng `direct` nếu không có referrer hợp lệ. | Top nguồn giới thiệu. |
| **Người truy cập duy nhất (ước tính)** | Đếm distinct `ip_hash` trong khoảng thời gian xác định; đây là ước tính theo IP, không phải định danh chính xác một người. | Thẻ tổng quan có ghi rõ kỳ thống kê và cách tính. |

Mọi biểu đồ nên cho biết khoảng thời gian và múi giờ; thống kê trong hệ thống dùng bucket UTC.

## Phương án không chọn và lý do

| Phương án | Lý do không chọn cho phiên bản hiện tại |
|---|---|
| **Kinesis Data Streams + Managed Service for Apache Flink** | Phù hợp hơn khi cần nhiều consumer độc lập, xử lý stream phức tạp hoặc throughput cao. Thêm stream, consumer, cấu hình và chi phí; Kinesis Data Streams không có free tier nên không phù hợp với mục tiêu $0 và phạm vi nhỏ của đồ án. |
| **SQS làm hàng đợi chính** | Cần producer/queue và thêm đường ghi sau click. Không cần cho luồng đơn giản hiện tại; SQS chỉ được dùng làm DLQ cho lỗi của `process_clicks`. |
| **EventBridge** | Có ích khi cần định tuyến event tới nhiều dịch vụ, nhưng tạo thêm bus/rule và cấu hình retry. Chưa cần cho một consumer analytics. |
| **API Gateway WebSocket** | Đẩy dữ liệu tới client đang kết nối nhưng cần quản lý vòng đời connection và broadcast. Dashboard polling đơn giản hơn. |

Các phương án trên có thể phát sinh chi phí AWS; phải kiểm tra giá theo cấu hình và region trước khi triển khai, không giả định miễn phí.

## Thu thập dữ liệu và bảo vệ quyền riêng tư

### Quốc gia

Nếu dùng `CloudFront-Viewer-Country`, chỉ tin header này khi request đi qua CloudFront được kiểm soát. Nếu origin/API vẫn truy cập trực tiếp, caller có thể tự gửi header cùng tên; cần giới hạn đường vào origin. Khi thiếu hoặc không hợp lệ, dùng `XX`. Không đưa IP vào log khi debug.

### Thiết bị, trình duyệt và User-Agent

`events.record_click` chỉ dùng User-Agent đầu vào để suy ra `device`, `browser` và kết quả `valid`/`bot`; chuỗi User-Agent gốc không được ghi vào item `clicks`. Thiết bị theo enum `desktop`, `mobile`, `tablet`, `bot`, `other`. User-Agent do client gửi nên không dùng làm bằng chứng xác thực.

### Hash IP và unique visitors

1. Chỉ lấy địa chỉ client từ nguồn request đáng tin cậy; không tin tùy tiện header do caller tự đặt.
2. `ratelimit.ip_hash` tính HMAC-SHA-256 từ salt cấu hình và IP, rồi cắt digest còn **16 ký tự hex**. Salt không hard-code, không commit và không in ra log.
3. Chỉ lưu `ip_hash`, không lưu hoặc log IP gốc. Hạn chế quyền truy cập và thời gian lưu event theo TTL của bảng.

Hash IP vẫn là dữ liệu giả danh có thể liên kết click, không nên mô tả là ẩn danh tuyệt đối. Unique visitors là số ước tính theo distinct hash trong kỳ thống kê.

## Dashboard và giám sát vận hành

Dashboard sản phẩm dùng polling `GET /api/stats` hoặc `GET /api/stats/{code}`; chọn chu kỳ polling để hướng tới mục tiêu độ trễ tối đa 10 giây. Polling tạo request kể cả khi số liệu không đổi, vì vậy cần theo dõi tải và chi phí thực tế.

CloudWatch dùng cho vận hành: theo dõi lỗi Lambda và alarm cho SQS DLQ. CloudWatch Dashboard không thay cho dashboard sản phẩm.

## Hướng phát triển

Chỉ cân nhắc **OpenSearch** khi cần tìm kiếm/phân tích tương tác trên lượng event lớn; **Athena** khi cần truy vấn dữ liệu lịch sử dạng batch; hoặc **QuickSight** khi cần báo cáo BI. Đây không phải thành phần của pipeline hiện tại và có thể phát sinh chi phí, nên cần đánh giá riêng trước khi triển khai.

## Bàn giao liên nhóm

### Gửi TV2 – Dashboard

- Các số liệu gồm tổng click, click/phút, top link, quốc gia, thiết bị, trình duyệt, referrer và unique visitors ước tính.
- Polling API stats cho dashboard sản phẩm; ghi rõ khoảng thời gian, múi giờ và tính chất ước tính của `unique_visitors`.
- CloudWatch dành cho giám sát vận hành, không thay dashboard sản phẩm.

### Gửi TV3 – Bảng clicks

- Dùng schema [click_event_schema.json](./click_event_schema.json) với 8 trường bắt buộc: `short_code`, `timestamp`, `ip_hash`, `country`, `device`, `browser`, `referrer`, `result`.
- `timestamp` là ISO 8601 UTC; `ip_hash` là 16 ký tự hex; `result` là `valid` hoặc `bot`; `device` theo enum trong schema.
- Không lưu/log IP gốc hoặc User-Agent nguyên bản. Consumer nhận stream `NEW_IMAGE` và chỉ xử lý record `INSERT`.
- Schema event mô tả thuộc tính ứng dụng, không thay đổi PK/SK, TTL hoặc cấu hình Streams của bảng.

### Tài liệu tham khảo

Thông tin được đối chiếu ngày **22/10/2026**. Giá/quota có thể thay đổi theo region và cấu hình; cần kiểm tra lại trước khi triển khai.

- [DynamoDB Streams – change data capture](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)
- [Lambda với DynamoDB Streams – polling, batching và retry](https://docs.aws.amazon.com/lambda/latest/dg/with-ddb.html)
- [Kinesis Data Streams – giới thiệu](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Kinesis Data Streams – pricing](https://aws.amazon.com/kinesis/data-streams/pricing/)
- [Apache Flink – documentation](https://flink.apache.org/)
- [SQS – giới thiệu](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html)
- [EventBridge – event bus và Pipes](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [CloudFront – request headers và country](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-cloudfront-headers.html)
- [CloudFront – origin request policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/controlling-origin-requests.html)
- [Python `hmac` – HMAC keyed hashing](https://docs.python.org/3/library/hmac.html)
- [AWS Systems Manager Parameter Store – SecureString](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
- [CloudWatch – dashboards](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Dashboards.html)
- [CloudWatch – pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [API Gateway – pricing](https://aws.amazon.com/api-gateway/pricing/)
