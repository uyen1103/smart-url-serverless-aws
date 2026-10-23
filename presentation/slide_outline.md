# Khung slide thuyết trình — LinkPulse

## Quy ước dùng chung

- Template 16:9, nền sáng `#F8FAFC`, bề mặt trắng, chữ `#0F172A`, chữ phụ `#475569`.
- Màu nhấn `#4F46E5`/hover `#4338CA`; trạng thái success `#10B981`, warning `#F59E0B`, danger `#EF4444`; biểu đồ dùng palette đã định trong design tokens.
- Font Be Vietnam Pro cho nội dung/tiêu đề, JetBrains Mono cho mã link, metric và code; fallback sans/monospace nếu thiếu font.
- Mỗi slide một thông điệp; tối đa 4 gạch đầu dòng, hình/biểu đồ có nguồn và đơn vị, ghi rõ số đo là dữ liệu demo hay chạy thật. Không dùng số liệu/chi phí ước lượng như kết quả đo.
- Giữ lề, cỡ chữ và bố cục nhất quán; ưu tiên sơ đồ tự vẽ của nhóm, không dùng ảnh wireframe thay cho ảnh Figma export.

## Slide outline

| # | Tiêu đề | Ý chính (2–4 gạch đầu dòng) | Hình cần chèn | Phụ trách |
|---:|---|---|---|---|
| 1 | LinkPulse — Rút gọn liên kết thông minh | Đề tài; nhóm 5; môn Điện toán đám mây; kỳ báo cáo. | Logo/tên LinkPulse, thông tin nhóm. | TV2 |
| 2 | Nội dung trình bày | Bài toán và mục tiêu; kiến trúc; module; demo, kết quả, chi phí và hướng phát triển. | Mục lục 5 phần. | TV2 |
| 3 | Bài toán & bối cảnh | Link dài khó chia sẻ; cần số liệu lưu lượng; link có thể bị lạm dụng. | Minh họa vấn đề (không chứa dữ liệu cá nhân). | TV1 |
| 4 | Mục tiêu và phạm vi | Tạo alias an toàn; redirect; analytics gần thời gian thực; rate limit/blocklist. | Bảng mục tiêu ↔ tiêu chí kiểm chứng. | TV1 + TV4 |
| 5 | Kiến trúc Serverless trên AWS | CloudFront/WAF, S3, API Gateway, Lambda, DynamoDB; ranh giới module. | Sơ đồ kiến trúc tổng thể. | TV5 |
| 6 | Backend — tạo link và redirect | Validate HTTP(S), alias, owner; trả lỗi theo code; redirect active. | Sequence diagram request/response. | TV1 |
| 7 | Database — lưu link và click | Bảng links/clicks; owner_id; khóa/truy vấn và TTL nếu có. | Mô hình dữ liệu đã thống nhất. | TV3 |
| 8 | Analytics — xử lý click gần thời gian thực | DynamoDB Streams → Lambda; aggregate; dashboard polling. | Pipeline và độ trễ đo thực tế. | TV3 |
| 9 | Security & DevOps | WAF, blocklist, rate limit, IAM/OAC, deploy/cache/logs. | Trust boundaries / pipeline deploy. | TV4 + TV5 |
| 10 | Frontend — trải nghiệm LinkPulse | Tạo link; trạng thái lỗi; quản lý và dashboard; mobile/desktop. | Figma export chính thức và prototype. | TV2 |
| 11 | Demo luồng tạo link | Tạo thành công; duplicate; alias/URL lỗi; rate limit countdown. | Ảnh/chụp live demo, không dùng URL thật nhạy cảm. | TV2 + TV1 |
| 12 | Demo dashboard & bảo vệ link | Dashboard và trạng thái blocked/suspicious/expired; cập nhật số liệu. | Dashboard demo và cảnh báo Figma. | TV2 + TV3 + TV4 |
| 13 | Kết quả đo | Thời gian tạo/redirect; độ trễ analytics; tỷ lệ lỗi; điều kiện đo rõ ràng. | Bảng số liệu test/load test có nguồn. | TV1 + TV3 + TV5 |
| 14 | Chi phí AWS | Bóc tách dịch vụ; region, tải giả định và mức dùng; cách kiểm soát ngân sách. | Bảng calculator/estimate có ngày truy vấn. | TV5 |
| 15 | Hạn chế & hướng phát triển | Hạn chế prototype/quota/dữ liệu; cải thiện auth/admin/observability; bước tiếp theo. | Roadmap ngắn theo ưu tiên. | Cả nhóm |
| 16 | Q&A | Cảm ơn; câu hỏi; link repo/demo nếu được phép chia sẻ. | Slide tối giản theo template. | TV2 |

## Template / file khung

Template thống nhất: 16:9 widescreen, nền `#F8FAFC`, Be Vietnam Pro + JetBrains Mono, palette LinkPulse nêu trên. Khung PowerPoint với slide tiêu đề, mục lục và mẫu nội dung/sơ đồ/bảng số liệu/demo nằm tại `presentation/slides_skeleton.pptx`.
