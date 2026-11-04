# AWS Deployment & Performance Benchmark - HealthFunction (Issue #7)

## 1. Thông tin tổng quan
- **Backend URL:** `https://q7ldh9h6g9.execute-api.ap-southeast-2.amazonaws.com`
- **Region:** `ap-southeast-2` (Sydney)
- **Function Name:** `linkpulse-backend-HealthFunction-bCMQTEPN5Ml7`
- **Mục tiêu:** Đo lường độ trễ thực thi (Duration) ở mức p50 và p95 để nghiệm thu Issue #7.

## 2. Quá trình xử lý & Kết quả
### 2.1. Lỗi Origin / CORS
- **Sự cố:** Truy cập trực tiếp qua browser/công cụ ngoài gặp lỗi `origin_not_allowed` do chính sách CORS/Origin validation.
- **Khắc phục:** Sử dụng chức năng **Test** trực tiếp trong AWS Lambda Console để kích hoạt traffic và ghi nhận log/metrics thực tế.

### 2.2. Kết quả đo lường CloudWatch Metrics (`Duration`)
- **p50 (Median Latency):** **~1.1 ms** (Trạng thái Warm Start - xử lý cực nhanh khi container đã khởi động).
- **p95 (95th Percentile Latency):** **~2.5 s** (Trạng thái Cold Start - lần khởi tạo container đầu tiên).

## 3. Kết luận
- Hàm Lambda `HealthFunction` hoạt động ổn định trên môi trường AWS.
- Cấu hình theo dõi CloudWatch Metrics đáp ứng đầy đủ tiêu chuẩn vận hành và giám sát hệ thống.
