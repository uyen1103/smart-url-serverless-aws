# Hướng dẫn xuất ảnh wireframe Figma

File Figma nguồn: [URL Shortener — Giao diện TV2](https://www.figma.com/design/uZxwjbnDQeqpGBqXQbuwVc/URL-Shortener-%E2%80%94-Giao-di%E1%BB%87n-TV2--Serverless-AWS-?node-id=5-18&m=dev).

Phiên làm việc không có quyền/công cụ đọc frame và xuất ảnh Figma. Vì vậy file PNG chưa được tạo và không có hình minh họa giả. Nhờ thành viên có quyền Figma thực hiện:

1. Mở file, chọn đúng frame desktop: `01`, `04`, `08`, `09`, `10`, `11` (có thể thêm `12` cho max clicks).
2. Dùng bảng **Export** xuất PNG, scale 1x hoặc 2x, giữ nguyên frame và nội dung thiết kế.
3. Lưu ảnh vào `docs/screenshots/` với tên `01-home.png`, `04-dashboard.png`, `08-warning-blocked.png`, `09-warning-suspicious.png`, `10-error-404.png`, `11-error-expired.png`.
4. Chèn ảnh vào mục tương ứng bên dưới bằng Markdown; nếu muốn giao nộp ảnh ghép, dùng công cụ thiết kế/ảnh của nhóm để ghép thành `docs/gui_wireframe.png`. Không chỉnh sửa giao diện ngoài thiết kế gốc.

## 01 — Trang chủ rút gọn link

Mục đích: cho phép người dùng tạo link ngắn. Thành phần/hành động/API được mô tả trong [báo cáo mục 3](./frontend_research.md#3-wireframe).

_Chèn export `01-home.png` tại đây._

## 04 — Dashboard thống kê

Mục đích: xem thống kê link/lưu lượng gần thời gian thực.

_Chèn export `04-dashboard.png` tại đây._

## 08/09 — Cảnh báo blocked/suspicious

Mục đích: ngăn người dùng tiếp tục tới link bị chặn hoặc đáng ngờ.

_Chèn exports `08-warning-blocked.png` và `09-warning-suspicious.png` tại đây._

## 10/11 — 404 / link hết hạn

Mục đích: giải thích link không tồn tại hoặc đã hết hạn; frame 12 có thể đại diện hết lượt click.

_Chèn exports `10-error-404.png` và `11-error-expired.png` tại đây._

Khi đã có đủ quyền/ảnh, cập nhật báo cáo và lưu bản ghép tại `docs/gui_wireframe.png` nếu nhóm cần đúng định dạng ảnh ghép của issue.
