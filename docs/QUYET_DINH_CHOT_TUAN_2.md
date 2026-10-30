# LinkPulse — Quyết định đã chốt (áp dụng cho cả nhóm)


**Đề tài:** hệ thống rút gọn liên kết thông minh với phân tích lưu lượng thời gian thực và chống lạm dụng trên AWS, kiến trúc serverless (CloudFront, S3, API Gateway, Lambda, DynamoDB, CloudWatch).

**Nguyên tắc:** chi phí $0 và vẫn phải chứng minh được các thành phần AWS của đề tài. Thấy dịch vụ nào tính phí ngoài ngoại lệ đã ghi dưới đây thì dừng và hỏi cả nhóm.

---
1. **Không dùng thường xuyên:** tên miền riêng (dùng `*.cloudfront.net`), Secrets Manager (dùng SSM Parameter loại Standard), Point-in-Time Recovery (tham số `EnablePitr`, mặc định `false`). Safe Browsing để trống. AWS WAF là lớp chống lạm dụng của AWS nên vẫn giữ trong hạ tầng dưới dạng tham số `EnableWaf` (mặc định `false`): TV5 bật đúng một lần, 1–2 giờ để kiểm thử và chụp bằng chứng cho báo cáo (khoảng vài cent), rồi tắt ngay. Đây là ngoại lệ duy nhất được phép.
2. **DynamoDB:** mặc định chế độ provisioned để nằm trong 25 WCU/25 RCU miễn phí (chỉ chế độ này mới được miễn phí). Dung lượng cố định cho mỗi bảng:
   | Bảng / index | WCU | RCU |
   |---|---|---|
   | urls | 5 | 6 |
   | urls / owner-index | 4 | 2 |
   | clicks | 4 | 1 |
   | stats | 4 | 10 |
   | rate_limits | 5 | 1 |
   | blocklist | 1 | 3 |
   | **Tổng** | **23** | **23** |
   **Thứ tự để không bị khóa đổi chế độ:** PR `BillingMode`/`EnablePitr` của TV3 phải merge TRƯỚC khi TV1 deploy lần 1 để bảng được tạo ngay ở chế độ provisioned. Nếu không kịp thì deploy lần 1 như hiện tại và đổi ở lần 2; AWS chỉ cho đổi chế độ tính phí một lần mỗi 24 giờ, nếu bị từ chối thì chờ đủ 24 giờ rồi deploy lại.
   Nếu demo bị throttle: TV3 đề nghị, TV1 là người chạy `sam deploy` với `BillingMode=PAY_PER_REQUEST` (TV3 chỉ có quyền đọc theo mục 17; chỉ đổi được một lần mỗi 24 giờ, tốn vài cent), xong buổi demo đổi lại. Không tự ý tăng dung lượng quá 25 tổng. Đây vẫn là DynamoDB do AWS quản lý (không có máy chủ); mặc định provisioned chỉ để giữ $0, còn on-demand là cấu hình khi chạy thật và phải ghi rõ trong báo cáo (kiến trúc serverless co giãn nằm ở Lambda, API Gateway, CloudFront).
3. **Thứ tự deploy (vòng phụ thuộc domain):** TV1 deploy backend lần 1 (`BaseUrl` tạm) → TV5 deploy edge (lấy domain CloudFront) → TV1 deploy lần 2 với `BaseUrl=https://<domain>.cloudfront.net`, `OwnDomains=<domain>.cloudfront.net`, `ErrorPageMode=redirect`. Mặc định của `ErrorPageMode` trong template đổi thành `redirect`.
4. **Schema click event** (sửa tài liệu theo code, không sửa code): `ip_hash` 16 ký tự hex; không lưu `user_agent`; có trường `result` (`valid` hoặc `bot`).
5. **Nguồn sự thật của schema DB là `backend/template.yaml`.** Tài liệu, sơ đồ và `create_tables.sh` của tuần 1 (`stats_agg`, `click_key`, `ip`, `owner`) phải sửa theo template, không sửa ngược lại.
6. **Frontend:** gọi `GET /links` với `limit ≤ 50`. Danh sách alias dành riêng chuẩn là danh sách của backend (19 mục): `api, assets, vendor, css, js, mock, index, dashboard, error, warning, stats, links, shorten, admin, favicon, health, static, login, robots`.
7. **Ngưỡng phát hiện lạm dụng:** TV1 thêm tham số template `SpikeClicksPerMinute` (mặc định 300) và `BotMinClicks` (mặc định 50) truyền vào Lambda `process_clicks`. Khi demo deploy với 30 và 10 để chỉ cần khoảng 30 lệnh curl.
8. **Lớp chống lạm dụng của đề tài (ưu tiên dịch vụ AWS):**
   - (a) API Gateway throttling (toàn API 100/200, `POST /api/shorten` 10/20 đã có trong template);
   - (b) rate limit theo IP bằng DynamoDB trong Lambda;
   - (c) CloudFront + OAC + header `X-Origin-Verify` để chặn gọi thẳng API Gateway;
   - (d) AWS WAF (bật khi test);
   - (e) tự động gắn cờ suspicious từ pipeline analytics;
   - (f) CloudWatch alarm.
   Turnstile (Cloudflare) và Safe Browsing (Google) không phải dịch vụ AWS nên chỉ là tùy chọn bổ sung, không được xem là lớp bảo vệ chính khi viết báo cáo.
9. **Không có giao diện quản trị.** Trang Chống lạm dụng chỉ để xem. Link bị chặn do tự động hoặc do script `scripts/blocklist` của TV5; gỡ chặn cũng bằng script này.
10. **Test dùng chung:** TV1 đẩy `tests/conftest.py` (moto tạo đúng 5 bảng, GSI, TTL như template; đặt biến môi trường tên bảng và `IP_HASH_SALT` ≥ 16 ký tự) sớm nhất có thể, vì TV3 và TV4 cần dùng để viết test. TV3 và TV4 dùng lại fixture này, không tự tạo fixture riêng. Tên file: `test_handlers_*.py` (TV1), `test_repo.py` (TV3), `test_analytics*.py` (TV4).
11. **CI:** GitHub Actions chạy `pytest` và `cfn-lint` (không cần thông tin đăng nhập AWS). `sam validate --lint` chạy tay trên máy có AWS CLI.
12. **Git:** nhánh `feature/<số issue>-<việc>` hoặc `bugfix/<số issue>-<việc>`; commit `type(scope): mô tả` ≤ 72 ký tự; Pull Request có `Closes #<số issue>`, ít nhất 1 người ở module khác review. Mỗi việc trong PR phải kèm bằng chứng (lệnh đã chạy và đầu ra rút gọn, và ảnh chụp AWS Console của tài nguyên liên quan khi có deploy); không có bằng chứng thì xem như chưa làm.
13. **Thứ tự làm việc (không chia ngày).** Việc không chờ ai thì làm ngay, tự chọn thứ tự, xong việc nào báo nhóm việc đó. Chỉ chuỗi dưới đây phải đúng thứ tự: bước sau bắt đầu khi bước trước báo xong.
    1. TV5 sửa quyền IAM và chốt Region cùng TV1; TV3 mở PR `BillingMode`/`EnablePitr`; TV1 đẩy `conftest.py` và xóa test cũ; TV5 deploy thử edge ở `us-east-1` (chưa có `ApiDomain` thật thì điền tạm một giá trị giả, chỉ để biết tài khoản có cho tạo CloudFront và S3 không; thử xong xóa stack thử). (Bốn việc này người khác đang chờ nên làm trước.)
    2. TV1 merge PR của TV3, deploy backend lần 1, gửi `ApiDomain`.
    3. TV5 deploy edge thật, gửi domain CloudFront, tên bucket, distribution ID.
    4. TV1 deploy backend lần 2 với domain CloudFront.
    5. TV2 deploy giao diện; TV4 kiểm chứng và đo độ trễ; TV5 kiểm thử WAF và lớp chống lạm dụng; TV3 kiểm tra throttle.
    6. Cả nhóm chạy ma trận đầu-cuối, sửa lỗi, PR, review.
    7. Họp demo, tick checklist.
    Bị kẹt ở bước nào thì báo cả nhóm ngay khi biết, để người sau không phải chờ trong im lặng. Muốn họp ngắn giữa chừng thì cả nhóm tự hẹn, không bắt buộc.
14. **Lưu ý free:** HTTP API chỉ miễn phí 1 triệu lượt gọi/tháng trong 12 tháng đầu (hoặc bằng credit tài khoản mới); nếu quá thì vài nghìn request chỉ vài cent. Không chạy tải lớn lên AWS: tải lớn chạy trên moto hoặc DynamoDB Local. Xong mỗi đợt thử không dùng nữa thì `sam delete`. Giữ tối đa 10 CloudWatch alarm và 2 AWS Budget.
15. **Hosting trên AWS: cả nhóm cùng làm, mỗi người một phần, trên MỘT tài khoản AWS chung.** TV5 là người cấp quyền: chạy `scripts/setup_aws_foundation.sh` để tạo IAM user riêng (quyền tối thiểu, bắt buộc MFA) cho từng thành viên; không ai dùng tài khoản root. Phân công hạ tầng:
    - TV1 = stack backend (API Gateway, Lambda, DynamoDB, SQS DLQ, CloudWatch) bằng SAM;
    - TV5 = stack edge (S3 riêng tư, CloudFront, WAF tùy chọn), SSM, IAM, CI;
    - TV2 = đưa giao diện lên S3 bằng `deploy.ps1` và kiểm tra trên CloudFront;
    - TV3 = cấu hình DynamoDB (dung lượng, TTL, GSI) trong template;
    - TV4 = pipeline Streams → `process_clicks` và alarm, kiểm chứng bằng click thật.
    Người nào deploy phần nào thì chụp ảnh AWS Console của phần đó làm bằng chứng cho báo cáo.
16. **Tài khoản kiểu Free plan mới bị cố định Region theo project** (xem `docs/backend_research.md` mục 6.2: hello-world của TV1 phải deploy ở `ap-southeast-2`, không phải `ap-southeast-1`). Chốt ở bước 1 của mục 13: TV5 và TV1 xem Region tại settings.aws.com (mục Project) của tài khoản dùng chung và thống nhất MỘT Region cho backend; mọi thành viên `aws configure` đúng Region đó. Stack edge của CloudFront/WAF ở `us-east-1` có thể bị tài khoản Free plan chặn: TV5 deploy thử edge sớm; nếu bị chặn thì báo cả nhóm để quyết định (ví dụ bỏ WAF và trình bày WAF bằng thiết kế và tài liệu, hoặc nâng cấp tài khoản sang gói trả phí chỉ khi cả nhóm đồng ý).
17. **Quyền IAM để deploy được:** chính sách dev trong `scripts/setup_aws_foundation.sh` hiện chỉ cho CloudFormation (stack `linkpulse-*`), Lambda, API Gateway, DynamoDB, S3 `linkpulse-*`, log và `iam:PassRole`; **chưa có** CloudFront, SSM, SQS, tạo IAM role cho Lambda (SAM cần), `cloudwatch:PutMetricAlarm`, WAF. Nên cả nhóm dùng IAM user theo script sẽ bị `AccessDenied` khi deploy. **Chốt:** TV5 cập nhật chính sách ở bước 1 của mục 13, trước khi ai deploy:
    - TV1 và TV5 (người chạy `sam deploy` và deploy edge) có `PowerUserAccess` cộng quyền tạo/xóa IAM role mà SAM cần (hoặc `AdministratorAccess` có MFA cho hai người này);
    - TV2 chỉ cần ghi vào bucket giao diện và tạo invalidation CloudFront;
    - TV3 và TV4 chỉ cần quyền đọc (`ReadOnlyAccess` cộng CloudWatch và DynamoDB đọc).
    Đặt tên stack bắt đầu bằng `linkpulse-` nếu vẫn giữ chính sách cũ. Không dùng root.
18. **Thứ tự sửa `backend/template.yaml`:** TV3 mở PR `BillingMode`/`EnablePitr` trước, TV1 review và merge; sau đó TV1 sửa `ErrorPageMode`, tham số ngưỡng, LogGroup sau đó và rebase. Không ai khác sửa file này trong tuần 2. Mỗi tài liệu và thư mục có một chủ (xem `KE_HOACH_TUAN_2.md`, mục "Quy tắc tránh xung đột file").
19. **Region của stack edge:** Web ACL của CloudFront chỉ tạo được ở `us-east-1`, và đổi Region của stack edge sẽ tạo distribution mới với domain mới (kéo theo TV1 deploy lần 2 lại và TV2 deploy lại giao diện). Vì vậy TV5 thử deploy edge ở `us-east-1` ngay ở bước 1 của mục 13: chạy được thì dùng luôn `us-east-1` cho stack edge thật; bị chặn thì deploy edge ở Region backend, bỏ phần kiểm thử WAF và trình bày WAF bằng thiết kế và tài liệu (theo mục 16).

