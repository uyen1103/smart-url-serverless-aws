# Đo độ trễ click → thống kê

## Thông tin lần đo

- Môi trường: `https://d3rsimgoxz85kx.cloudfront.net` (bản deploy lần 2), đo ngày 2026-11-05.
- Nơi đo: AWS CloudShell, region `ap-southeast-2`.
- Link thử: tạo riêng cho lần đo này (owner id là UUID ngẫu nhiên), đích `https://example.com/tv4-analytics`.

## Cách đo

1. Đọc `total_clicks` hiện tại của `GET /api/stats/{code}`.
2. Gửi 1 click bằng `curl` với User-Agent trình duyệt (tính là click hợp lệ, không dùng `-L`).
3. Hỏi lại `GET /api/stats/{code}` mỗi 0,5 giây cho đến khi `total_clicks` tăng.
4. Độ trễ = thời điểm thấy số tăng trừ thời điểm bắt đầu gửi click.
5. Lặp 30 lần, tuần tự, trên cùng một link.

## Kết quả

| Chỉ số | Giá trị |
|---|---|
| Số lần đo (n) | 30 |
| Nhỏ nhất | 1,20 s |
| Trung bình | 1,58 s |
| Lớn nhất | 2,88 s |
| Lần không thấy số tăng (timeout) | 0 |

Giá trị từng lần (giây): 2,88; 1,20; 1,48; 1,24; 2,36; 1,22; 1,24; 1,50; 2,34; 1,22; 1,22; 1,20; 2,36; 1,22; 1,22; 1,46; 1,48; 1,22; 1,48; 1,22; 2,34; 1,22; 1,20; 1,22; 2,28; 1,24; 1,22; 2,34; 1,26; 2,30.

**Mục tiêu < 10 giây: Đạt.** Cả 30 lần đều thấy số click tăng, lần chậm nhất là 2,88 s.

## Hạn chế

- Sai số khoảng 0,5–1 giây do chu kỳ hỏi lại 0,5 s và thời gian mỗi lần gọi `curl`. Vì vậy các giá trị tập trung quanh 1,2 s, 1,5 s và 2,3 s; độ trễ thật nhiều khả năng nhỏ hơn hoặc bằng số đã đo.
- Đo từ CloudShell trong cùng khu vực AWS, không phải từ trình duyệt của người dùng, nên không gồm độ trễ mạng của người dùng.
- Chỉ đo 30 lần tuần tự, không đo khi có tải đồng thời (không chạy tải lớn lên AWS theo quyết định tuần 2).
- Đoạn kiểm tra timeout 60 giây của script không chạy do lỗi mở rộng `!` của shell; vòng đo vẫn hoàn tất cả 30 lần và không có lần nào treo.
- `GET /api/stats/{code}` trả `total_clicks` gồm cả click của bot; script chỉ gửi click hợp lệ nên mỗi lần chạy số này tăng đúng 1.
