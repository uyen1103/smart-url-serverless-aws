# Nghiên cứu Analytics

## So sánh phương án truyền sự kiện click

**Bối cảnh:** Mỗi lượt click đã được ghi thành một item mới trong bảng `clicks`. Pipeline cần chuyển thay đổi đó tới Lambda xử lý để cập nhật `stats_agg`. So sánh dưới đây xét luồng này, không giả định lưu lượng lớn hay cần nhiều hệ thống tiêu thụ độc lập.

| Phương án | Độ trễ | Chi phí | Độ phức tạp | Giới hạn và lưu ý |
|---|---|---|---|---|
| **DynamoDB Streams** | Gần thời gian thực. Lambda mặc định gọi hàm khi có record; event source mapping poll shard ở mức cơ sở 4 lần/giây. Độ trễ thực tế còn phụ thuộc batch, tải và thời gian xử lý; AWS không bảo đảm một độ trễ end-to-end cố định ở đây. | Tận dụng bảng `clicks` đã cần cho redirect, không cần thêm lần gửi sự kiện từ ứng dụng. Vẫn phát sinh chi phí của thao tác ghi DynamoDB, xử lý Lambda và các phần DynamoDB liên quan; cần tính theo giá hiện hành và cấu hình thực tế. | **Thấp nhất cho kiến trúc hiện tại:** bật stream, cấu hình Lambda event source mapping và xử lý `INSERT`. Không phải duy trì thêm producer/queue riêng. Cần làm handler idempotent vì Lambda có thể xử lý lại record. | Stream giữ record tối đa **24 giờ**. Có thể chọn `NEW_IMAGE` để Lambda nhận click event vừa ghi. DynamoDB Streams ghi nhận thay đổi gần thời gian thực; mỗi record xuất hiện một lần trong stream, nhưng không đồng nghĩa Lambda chỉ chạy đúng một lần. |
| **Kinesis Data Streams** | Độ trễ put-to-get thường **dưới 1 giây** theo tài liệu Kinesis; độ trễ toàn pipeline vẫn phụ thuộc consumer và xử lý. | Tính phí theo chế độ capacity và lượng ghi/đọc/retention; nếu phát CDC từ DynamoDB sang Kinesis còn có thể có chi phí CDC của DynamoDB. **Kinesis Data Streams không có free tier**; kiểm tra lại trang giá hiện hành theo region trước khi triển khai. | **Cao:** cần stream riêng, producer hoặc tích hợp CDC, consumer, cấu hình throughput/retention và theo dõi lag. Hợp lý hơn khi cần nhiều consumer độc lập hoặc stream dữ liệu lớn. | Provisioned: mỗi shard hỗ trợ tối đa 1 MB/s hoặc 1.000 record/s ghi và 2 MB/s đọc; on-demand có mức khởi đầu và khả năng scale theo region. Payload tối đa 10 MiB/record theo tài liệu quota hiện hành. Quota và capacity cần đối chiếu region/account. |
| **Amazon SQS** | Gần thời gian thực nhưng phụ thuộc polling, batch, backlog và visibility timeout; không có thời hạn xử lý cố định cho từng message. | Tính phí theo request; gửi/nhận/xóa theo batch giúp giảm số request. Có thể phát sinh thêm chi phí Lambda và DLQ. Giá và điều kiện free tier phải kiểm tra theo region/tài khoản hiện hành. | **Trung bình:** cần gửi message riêng sau khi ghi click, cấu hình queue và Lambda event source mapping, visibility timeout, retry/DLQ và partial batch failure. Standard queue có thể giao trùng và không đảm bảo thứ tự tuyệt đối, nên consumer phải idempotent. | Message tối đa 1 MiB; retention mặc định 4 ngày, cấu hình tối đa 14 ngày. Standard queue có throughput rất cao; FIFO có giới hạn throughput theo mode và region. |
| **Amazon EventBridge** | Gần thời gian thực khi event được nhận và target sẵn sàng; khi target lỗi, retry có thể kéo dài đáng kể. Không nên diễn giải “near-real-time” thành SLA cố định. | Tính theo events ingested/processed và tính năng sử dụng; target Lambda, DLQ, archive/replay có thể ảnh hưởng tổng chi phí. Cần dùng AWS Pricing Calculator/trang giá hiện hành cho tải dự kiến. | **Trung bình đến cao:** cần publish event, event bus, rules/targets, quyền truy cập, retry/DLQ và quản lý schema/transform nếu dùng. Có lợi khi cần định tuyến một event tới nhiều target hoặc tích hợp nhiều dịch vụ. | Với Custom Event Bus, quota mặc định công bố là 500.000 events/giây mỗi bus; mức thực tế phụ thuộc loại bus và region. Retry mặc định tối đa 24 giờ hoặc 185 lần; nên cấu hình DLQ để không mất event sau khi hết retry. Quota có thể thay đổi theo loại bus. |

### Đề xuất

Chọn **DynamoDB Streams → Lambda `click_processor` → `stats_agg`** cho đề tài. Bảng `clicks` đã là nguồn lưu click theo kiến trúc chung, nên Streams chuyển chính thay đổi vừa ghi mà không buộc API redirect phải gửi thêm một bản tin qua dịch vụ trung gian. Phương án này phù hợp với mục tiêu học DynamoDB Streams/Lambda, giảm số thành phần phải cấu hình, và dễ mô phỏng bằng dữ liệu giả hoặc mock khi phát triển local.

Đặt stream view type là `NEW_IMAGE` để consumer đọc được click event mới; chỉ xử lý record `INSERT`, không tăng số đếm khi item bị `MODIFY`/`REMOVE`. Lambda cần xử lý idempotent và bật partial batch failure phù hợp để retry một record lỗi không làm xử lý lại cả batch thành công. Giới hạn lưu stream 24 giờ có nghĩa là consumer bị gián đoạn quá lâu có nguy cơ không còn đọc được record cũ; cần theo dõi tuổi record chưa xử lý và có kế hoạch xử lý lỗi.

Chỉ cân nhắc **SQS** nếu nhóm cần hàng đợi độc lập để đệm tải, retry/DLQ tách biệt hoặc tách producer khỏi consumer. Chọn **EventBridge** khi yêu cầu định tuyến/phân phối một event tới nhiều dịch vụ là trọng tâm. Chọn **Kinesis Data Streams** khi cần stream throughput cao, nhiều consumer đọc độc lập hoặc khả năng replay/stream processing nâng cao và nhóm chấp nhận chi phí, quota cùng vận hành bổ sung. Với phạm vi đồ án hiện tại, các lợi ích này chưa bù được độ phức tạp và chi phí tăng thêm.

## Chỉ số analytics cần theo dõi

| Chỉ số | Cách hiểu/nhóm dữ liệu | Dùng trên dashboard |
|---|---|---|
| **Tổng lượt click** | Số event click trong khoảng thời gian được chọn; có thể lọc theo `short_code`. Đây là số lượt, không phải số người. | Thẻ tổng quan cho toàn hệ thống hoặc một link. |
| **Click/phút** | Số event theo bucket UTC một phút; hiển thị thành chuỗi thời gian. | Biểu đồ xu hướng, nhận biết giờ cao điểm hoặc bất thường. |
| **Top link** | Xếp hạng `short_code` theo lượt click trong cùng khoảng thời gian. | Bảng/xếp hạng link có nhiều lượt click. |
| **Phân bố quốc gia** | Đếm click theo `country`; dùng `XX` khi thiếu hoặc không xác định được. | Bảng hoặc biểu đồ phân bố theo quốc gia. |
| **Thiết bị** | Đếm click theo `device`: `desktop`, `mobile`, `tablet`, `bot`, `other`. | Biểu đồ thiết bị; có thể lọc/nhận diện traffic bot. |
| **Trình duyệt** | Đếm click theo `browser` đã parse, ví dụ Chrome, Safari, Firefox, Edge. | Bảng/biểu đồ tương thích trình duyệt. |
| **Nguồn giới thiệu** | Đếm click theo domain `referrer`; dùng `direct` nếu không có referrer hợp lệ. | Top nguồn giới thiệu, giúp biết kênh nào đưa traffic tới link. |
| **Người truy cập duy nhất (ước tính)** | Đếm distinct `ip_hash` trong khoảng thời gian xác định, toàn hệ thống hoặc theo link. Đây là ước tính theo IP đã băm, không phải định danh chính xác một người. | Thẻ tổng quan; phải ghi rõ kỳ thống kê và cách tính. |

Mọi biểu đồ nên cho biết khoảng thời gian và múi giờ; lưu bucket theo UTC để nhất quán giữa Lambda và API. Click total và unique visitors là hai chỉ số khác nhau. IP động, NAT, VPN, thiết bị dùng chung, bot và việc đổi salt đều ảnh hưởng độ chính xác của unique visitors.

## Thu thập dữ liệu và bảo vệ quyền riêng tư

### Quốc gia

CloudFront có thể thêm header `CloudFront-Viewer-Country` chứa mã quốc gia ISO 3166-1 alpha-2 suy ra từ IP viewer. Cấu hình origin request policy của distribution để chuyển header này tới origin/API; Lambda đọc header không phân biệt chữ hoa/thường và chuẩn hóa mã về chữ hoa. Nếu header vắng mặt hoặc không hợp lệ, ghi `XX`. Không cần tự suy ra quốc gia từ IP trong ứng dụng.

Chỉ tin header này khi request đi qua CloudFront được kiểm soát. Nếu origin/API vẫn truy cập trực tiếp, caller có thể tự gửi header cùng tên; cần giới hạn đường vào origin để không ghi dữ liệu quốc gia giả. Không đưa IP vào log khi debug phần này.

### Thiết bị, trình duyệt và User-Agent

Đề xuất thư viện Python **`user-agents`** (dựa trên `ua-parser`) để parse chuỗi User-Agent: thư viện cung cấp các thuộc tính thiết bị, browser và cờ nhận biết bot. Ánh xạ kết quả vào enum trong schema: tablet trước mobile nếu cả hai cờ cùng đúng; tiếp theo desktop; bot khi được nhận diện; trường hợp không rõ là `other`. Lấy `browser.family` làm tên browser; nếu không nhận diện được, ghi `Other`.

User-Agent do client gửi, có thể thiếu hoặc giả mạo nên chỉ dùng cho analytics, không dùng như bằng chứng xác thực. Lưu tối đa **512 ký tự** theo giới hạn schema, và không ghi nguyên chuỗi này vào log ứng dụng. Trong pipeline production, chỉ cần đưa User-Agent tới bước parse nếu chính sách lưu dữ liệu yêu cầu; schema hiện tại vẫn giữ trường `user_agent` theo hợp đồng đã chốt.

### Ẩn danh IP và unique visitors

1. Lấy địa chỉ client chỉ từ nguồn request đã được tin cậy (ví dụ request đã đi qua CloudFront/API Gateway); không lấy tùy tiện từ header do caller tự đặt.
2. Dùng salt/secret ngẫu nhiên, đủ mạnh, lấy từ cấu hình môi trường được bảo vệ hoặc SSM Parameter Store `SecureString`; không hard-code, không commit và không in giá trị ra log. Tài liệu AWS lưu ý `SecureString` được mã hóa bằng KMS; cấp quyền đọc tối thiểu cho Lambda.
3. Theo đúng hợp đồng hiện tại, tạo `ip_hash = SHA256(ip_bytes + salt_bytes).hexdigest()` trước khi ghi item; dùng salt bí mật, ngẫu nhiên và đủ mạnh. HMAC-SHA-256 là một thiết kế keyed-hash mạnh hơn, nhưng sẽ đổi công thức băm đã chốt; chỉ chuyển sang HMAC nếu cả nhóm đồng ý, dù tên trường và dạng digest không đổi.
4. Chỉ ghi `ip_hash`; không lưu hoặc log IP gốc, kể cả trong exception/debug. Hạn chế quyền truy cập và thời gian lưu event theo TTL đã thống nhất cho bảng.

Salt ổn định trong cùng kỳ phân tích cho phép đếm distinct hash, nhưng kết quả chỉ là ước tính visitor theo IP. Khi xoay salt, các hash cũ và mới không đối chiếu được; unique visitors qua thời điểm xoay vì thế bị chia kỳ. Hash IP vẫn là dữ liệu giả danh có khả năng liên kết click, không nên mô tả là ẩn danh tuyệt đối.

## Hiển thị gần thời gian thực

| Phương án | Độ mới dữ liệu | Ưu điểm | Chi phí/độ phức tạp và phù hợp |
|---|---|---|---|
| **Polling stats_api (đề xuất cho dashboard TV2)** | Gần thời gian thực theo chu kỳ frontend gọi API; số liệu mới có sau khi `click_processor` cập nhật `stats_agg`. | Dễ xây dựng và kiểm thử với dashboard web; frontend chỉ cần gọi lại endpoint và render JSON. Dễ chịu lỗi mất mạng vì lần polling tiếp theo lấy lại snapshot mới nhất. | Đơn giản nhất, nhưng tạo request định kỳ kể cả khi số liệu không đổi. Tần suất polling ảnh hưởng độ mới và request/chi phí API Gateway/Lambda; chọn chu kỳ vừa phải theo demo, đo tải thực tế và không cam kết SLA. |
| **API Gateway WebSocket** | Server có thể đẩy cập nhật tới client đang kết nối mà không cần client hỏi lặp lại. | Hai chiều, thích hợp khi cần cập nhật đẩy tức thời hoặc tương tác hai chiều. | Phức tạp hơn: quản lý `$connect`/`$disconnect`, connection ID, lưu connection đang hoạt động, broadcast và dọn connection hết hạn; backend phải gọi callback `@connections`. Phát sinh chi phí theo connection/message và vận hành bổ sung; chưa cần cho dashboard polling đơn giản. |
| **CloudWatch Dashboard** | Hiển thị metric/log đã gửi tới CloudWatch; không phải kênh push trực tiếp vào giao diện ứng dụng. Độ mới phụ thuộc metric, chu kỳ refresh dashboard và dịch vụ nguồn. | Tốt cho nhóm vận hành: xem sức khỏe Lambda/Streams, số liệu EMF, alarm và lỗi trong một màn hình AWS. Không cần xây trang dashboard sản phẩm riêng để theo dõi hệ thống. | Cần phát metric/log, tạo dashboard và quản lý quyền. CloudWatch tính phí logs ingestion/storage và custom metrics theo cách sử dụng; EMF có thể tạo nhiều custom metrics nếu dùng dimension cardinality cao. Không dùng `ip_hash`, request ID hay từng visitor làm dimension. |

**Kết luận hiển thị:** TV2 nên dùng dashboard web **polling stats_api** làm bản đầu tiên, dựa trên `stats_agg`/JSON response thống nhất. TV4 dùng **CloudWatch Dashboard** cho giám sát vận hành (Lambda errors/throttles, stream iterator age và metric tổng hợp). Chỉ chuyển sang WebSocket nếu polling không đáp ứng yêu cầu độ mới hoặc có yêu cầu push rõ ràng; cần ước tính chi phí và thiết kế vòng đời connection trước.

## Bàn giao liên nhóm

### Gửi TV2 – Dashboard

- Chỉ số đề xuất: tổng click; click/phút; top link; phân bố quốc gia; thiết bị; trình duyệt; referrer; unique visitors (ước tính theo distinct `ip_hash`, ghi rõ kỳ thống kê).
- Bản đầu nên polling `stats_api`; hiển thị rõ khoảng thời gian/múi giờ. CloudWatch Dashboard dành cho vận hành, không thay dashboard sản phẩm.
- JSON response thống nhất ở giai đoạn tích hợp; các field gợi ý đã có trong hợp đồng kiến trúc chung. `unique_visitors` là số ước tính, không phải định danh người dùng chính xác.

### Gửi TV3 – Bảng clicks

- Dùng schema [click_event_schema.json](./click_event_schema.json), gồm đúng 8 trường bắt buộc: `short_code`, `timestamp`, `ip_hash`, `country`, `device`, `browser`, `referrer`, `user_agent`.
- `timestamp` là ISO 8601 UTC; `ip_hash` là SHA-256 dạng hex 64 ký tự; `country` dùng mã 2 chữ cái hoặc `XX`; `device` theo enum trong schema; `user_agent` tối đa 512 ký tự.
- Không lưu/log IP gốc. Analytics đề xuất Streams `NEW_IMAGE` và chỉ tăng số liệu từ record `INSERT`.
- Giữ khóa/TTL/Streams theo thiết kế database đã thống nhất; schema event này mô tả thuộc tính ứng dụng, không thay đổi PK/SK.

### Tài liệu tham khảo

Thông tin được đối chiếu ngày **22/10/2026**. Các mức giá/quota có thể thay đổi theo region, loại bus/capacity mode và tài khoản; trước khi triển khai cần kiểm tra lại tài liệu AWS và trang giá hiện hành cho `ap-southeast-1`.

- [DynamoDB Streams – change data capture](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)
- [Lambda với DynamoDB Streams – polling, batching và retry](https://docs.aws.amazon.com/lambda/latest/dg/with-ddb.html)
- [Kinesis Data Streams – giới thiệu và độ trễ put-to-get](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Kinesis Data Streams – quotas and limits](https://docs.aws.amazon.com/streams/latest/dev/service-sizes-and-limits.html)
- [Kinesis Data Streams – pricing](https://aws.amazon.com/kinesis/data-streams/pricing/)
- [DynamoDB – pricing, gồm CDC sang Kinesis](https://aws.amazon.com/dynamodb/pricing/)
- [SQS – giới thiệu, độ bền và retention](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html)
- [SQS – quotas và giới hạn message](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)
- [Lambda với SQS – polling, batching và at-least-once](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)
- [EventBridge – khái niệm event bus và Pipes](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [EventBridge – quotas](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-quota.html)
- [EventBridge – retry policy và DLQ](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-retry-policy.html)
- [CloudFront – request headers, country và device type](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-cloudfront-headers.html)
- [CloudFront – origin request policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/controlling-origin-requests.html)
- [Python `user-agents` – thuộc tính browser, device và bot](https://pypi.org/project/user-agents/)
- [Python `hmac` – HMAC keyed hashing](https://docs.python.org/3/library/hmac.html)
- [AWS Systems Manager Parameter Store – SecureString](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
- [API Gateway – WebSocket APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api-overview.html)
- [API Gateway – gọi kết nối WebSocket bằng `@connections`](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-how-to-call-websocket-api-connections.html)
- [CloudWatch – dashboards](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Dashboards.html)
- [CloudWatch – Embedded Metric Format và cardinality](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html)
- [CloudWatch – pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [API Gateway – pricing](https://aws.amazon.com/api-gateway/pricing/)