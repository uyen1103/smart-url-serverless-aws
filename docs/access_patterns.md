# Access Patterns – LinkPulse

Tài liệu mô tả các access pattern chính của hệ thống LinkPulse, bảng DynamoDB được sử dụng và thao tác truy vấn tương ứng.

## 1. Các access patterns

| Access pattern | Bảng / Index | Thao tác + điều kiện | Hàm trong code |
|---|---|---|---|
| Lấy URL theo mã rút gọn khi redirect | `urls` | `GetItem` theo Partition Key `short_code` | `get_link(code)` |
| Kiểm tra mã rút gọn đã tồn tại | `urls` | `PutItem` với điều kiện `attribute_not_exists(short_code)` để tránh ghi đè mã đã tồn tại | `create_link(item)` |
| Tìm URL trùng của cùng chủ sở hữu | `urls` / `owner-index` | `Query` theo `owner_id`, lọc theo `long_url` và trạng thái không phải `deleted` | `find_existing(owner_id, long_url)` |
| Liệt kê URL của chủ sở hữu | `urls` / `owner-index` | `Query` theo `owner_id`, lọc URL đã xóa mềm, hỗ trợ phân trang | `list_owner_links(owner_id)` |
| Tăng số lượt click của URL | `urls` | `UpdateItem` sử dụng `ADD` cho `click_count`, có điều kiện kiểm tra `max_clicks` | `register_click(code, max_clicks)` |
| Truy vấn lịch sử click của một URL | `clicks` | `Query` theo `short_code`, sắp xếp theo sort key giảm dần | `recent_for_link(code, limit)` |
| Tổng hợp thống kê click theo thời gian | `stats` | `Query` theo `scope`, giới hạn khoảng thời gian bằng sort key `sk` | `_query_range(scope, frm, to)`, `get_stats(...)` |
| Xếp hạng link theo lượt click | `stats` | Lấy thống kê từ scope `GLOBAL`, sử dụng bộ đếm `l:<code>` để tạo danh sách link và sắp xếp giảm dần | `get_stats(...)`, `top_links(counter, n)` |
| Xem các click gần đây trên toàn hệ thống | `stats` | `GetItem` với khóa `scope=META`, `sk=recent_clicks` | `recent_global()` |
| Xóa dữ liệu click và thống kê của một URL | `clicks`, `stats` | `Query` dữ liệu theo `short_code` và `scope=LINK#<code>`, sau đó xóa theo batch | `purge_link_data(code)` |
| Đánh dấu URL đáng ngờ | `urls` | Cập nhật trạng thái và lý do | `flag_link(code, reason, new_status)` |
| Tăng số URL bị gắn cờ | `stats` | `UpdateItem` với khóa `scope=META`, `sk=flagged_links`, sử dụng `ADD` | `incr_flagged(n)` |
| Đọc số URL bị gắn cờ | `stats` | `GetItem` theo khóa `scope=META`, `sk=flagged_links` | `get_flagged()` |
| Kiểm tra blocklist | `blocklist` | `batch_get_item` theo domain hiện tại và các domain cha | `is_blocklisted(url)` trong `reputation.py`; `is_blocked(url)` kết hợp blocklist và Google Safe Browsing |
| Kiểm soát số request theo IP | `rate_limits` | `UpdateItem` với `ADD cnt`, khóa `pk` theo dạng `key#bucket`, dùng `ConditionExpression` để giới hạn số request trong cửa sổ thời gian | `hit(key, limit, window, now_ts)` trong `ratelimit.py` |

## 2. Quy ước khóa trong bảng stats

Bảng `stats` sử dụng:

- Partition Key: `scope`
- Sort Key: `sk`

Quy ước giá trị:

| Loại dữ liệu | `scope` | `sk` |
|---|---|---|
| Thống kê toàn hệ thống | `GLOBAL` | `M#<minute>` |
| Thống kê từng URL | `LINK#<code>` | `M#<minute>` |
| Metadata hệ thống | `META` | `flagged_links` hoặc `recent_clicks` |

Các trường thống kê trong một bản ghi theo phút gồm:

- `clicks`: tổng lượt click.
- `bot_clicks`: lượt click được xác định là bot.
- `c:<country>`: số lượt click theo quốc gia.
- `d:<device>`: số lượt click theo thiết bị.
- `b:<browser>`: số lượt click theo trình duyệt.
- `r:<referrer>`: số lượt click theo nguồn truy cập.
- `l:<code>`: số lượt click của từng URL, được dùng trong thống kê toàn hệ thống.
- `ips`: tập hợp IP đã được xử lý để thống kê visitor duy nhất.

## 3. Luồng xử lý click và cập nhật thống kê

Khi có click mới, dữ liệu click được ghi vào bảng `clicks`. DynamoDB Streams theo dõi thay đổi của bảng với chế độ `NEW_IMAGE`. Lambda xử lý sự kiện Stream và cập nhật bảng `stats`.

```text
Người dùng truy cập URL
         |
         v
      Redirect
         |
         v
    DynamoDB clicks
         |
         v
  DynamoDB Streams
     NEW_IMAGE
         |
         v
 Lambda process_clicks
         |
         v
    analytics.py
         |
         v
    DynamoDB stats
         |
         v
 Dashboard thống kê
```

Trong `analytics.py`:

1. `aggregate(events)` nhóm các click theo scope và phút.
2. `apply_group(scope, minute, group)` cập nhật các bộ đếm trong bảng `stats`.
3. `update_recent(events)` cập nhật danh sách click gần đây.
4. `_query_range(scope, frm, to)` truy vấn dữ liệu thống kê theo khoảng thời gian.
5. `get_stats(...)` tổng hợp kết quả thống kê.
6. `top_links(counter, n)` sắp xếp danh sách link theo số lượt click.

## 4. Ghi chú kỹ thuật

- Các thao tác truy vấn được mô tả trong tài liệu dựa trên các module backend đã kiểm tra.
- Không sử dụng `Scan` trong các hàm đã kiểm tra; các thao tác đọc chính sử dụng `GetItem` hoặc `Query`.
- `owner-index` hỗ trợ truy vấn URL theo `owner_id`.
- `clicks` và `stats` sử dụng TTL thông qua thuộc tính `expires_at`.
- DynamoDB Streams được cấu hình trên bảng `clicks` với `StreamViewType: NEW_IMAGE`.
- DynamoDB Streams có cơ chế xử lý ít nhất một lần (at-least-once). Vì vậy, cần lưu ý khả năng xử lý trùng sự kiện khi cập nhật thống kê.
- Bảng `stats` có giới hạn kích thước tối đa 400 KB cho mỗi item. Việc lưu nhiều tập hợp IP hoặc bộ đếm theo chiều có thể làm item tăng kích thước đáng kể.
- Rate limit sử dụng cửa sổ thời gian cố định và cập nhật bộ đếm nguyên tử bằng DynamoDB. Khi DynamoDB bị throttle, cơ chế này fail-open; AWS WAF và API Gateway throttling vẫn là các lớp bảo vệ bổ sung.