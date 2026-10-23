# Nghiên cứu Frontend & Presentation — Tuần 1 (TV2)

## Mục lục

1. [Hosting](#1-hosting)
2. [Công nghệ](#2-công-nghệ)
3. [Wireframe](#3-wireframe)
4. [Luồng & trạng thái](#4-luồng--trạng-thái)
5. [Rủi ro & câu hỏi cần thống nhất với nhóm](#5-rủi-ro--câu-hỏi-cần-thống-nhất-với-tv1tv3tv4tv5)
6. [Nguồn tham khảo](#6-nguồn-tham-khảo)

## 1. Hosting

### Phương án lưu trữ

| Phương án | Cách hoạt động | Ưu / nhược điểm |
|---|---|---|
| S3 website endpoint công khai | Bật static website hosting; website endpoint phục vụ HTTP và bucket/object phải cho phép truy cập công khai. | Đơn giản để thử nghiệm, nhưng không tự cung cấp HTTPS; không thể dùng OAC để khóa origin website endpoint. Không chọn cho triển khai chính thức. |
| Bucket S3 private + CloudFront | Dùng S3 REST origin, bật Block Public Access, tạo CloudFront Origin Access Control (OAC), cho phép đúng distribution đọc object qua bucket policy. CloudFront phục vụ HTTPS ở edge. | Đề xuất cho đồ án: origin không công khai, HTTPS/CDN, cache và Response Headers Policy tập trung. Cần cấu hình distribution, certificate, DNS và cache. |

**Khuyến nghị:** bucket riêng tư + CloudFront + OAC; không kết hợp OAC với S3 *website endpoint*. Website endpoint là custom origin và không hỗ trợ OAC. S3 website hosting hỗ trợ static website, nhưng có các giới hạn bảo mật/HTTPS cần cân nhắc; dùng S3 REST endpoint cho phương án private origin.

OAC đặt chế độ ký request `Sign requests (recommended)` (`SigningBehavior: always`, `SigningProtocol: sigv4`). Bucket policy mẫu tối thiểu để CloudFront đọc object:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudFrontReadOnly",
      "Effect": "Allow",
      "Principal": { "Service": "cloudfront.amazonaws.com" },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::BUCKET_NAME/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::ACCOUNT_ID:distribution/DISTRIBUTION_ID"
        }
      }
    }
  ]
}
```

Thay ba giá trị mẫu bằng tài nguyên thực; không cấp `s3:ListBucket` nếu website không cần liệt kê object. Giữ Block Public Access bật và xác minh không còn policy/ACL công khai khác. Nếu object mã hóa SSE-KMS, cần cấp quyền giải mã cho CloudFront/OAC theo hướng dẫn AWS.

### HTTPS và cache

- Gắn alternate domain name (ví dụ `linkpulse.vn`) vào distribution và certificate ACM phù hợp. **Certificate dùng cho CloudFront phải được yêu cầu/nhập ở `us-east-1` (N. Virginia)**, kể cả khi origin/API ở region khác.
- Trên từng behavior, đặt Viewer Protocol Policy là `Redirect HTTP to HTTPS`. Với GET/HEAD CloudFront chuyển hướng HTTP sang HTTPS; phương thức khác có hành vi redirect riêng theo phiên bản giao thức, vì vậy client API nên gọi HTTPS ngay từ đầu.
- Phân tách cache theo loại nội dung:
  - Asset có fingerprint/hash trong tên file: `Cache-Control: public, max-age=31536000, immutable` có thể dùng khi tên đổi theo nội dung. TTL thực tế còn phụ thuộc Cache Policy và origin headers.
  - `index.html` và các HTML cấu hình: TTL ngắn (ví dụ `no-cache` hoặc TTL thấp) để bản phát hành mới nhận được ngay; không đặt minimum TTL lớn hơn ý định này.
  - API và redirect cá nhân hóa: dùng managed cache policy `CachingDisabled` (min/default/max TTL = 0) và forward các header, query/body cần thiết. Với `POST`, body được chuyển tới origin; không bật cache response cho endpoint API/redirect. Chọn Origin Request Policy riêng để forward header `X-Owner-Id`, `Retry-After` khi phù hợp và các thông tin cần cho API; không dùng allow-all thiếu cân nhắc.
- CloudFront tách Cache Policy (định nghĩa cache key) khỏi Origin Request Policy (thông tin thêm gửi origin). Không forward token/header cá nhân vào cache key hoặc bật cache API: có thể rò rỉ dữ liệu giữa người dùng. Đặt behavior `/api/*` về API Gateway, methods phù hợp (GET/HEAD/OPTIONS/POST/PUT/PATCH/DELETE theo API), cache disabled.
- CloudFront tạo `CloudFront-Viewer-Country` từ địa chỉ IP; đưa header này vào Origin Request Policy của API cần phân tích quốc gia, không đưa vào cache key khi không cần phân biệt nội dung. API Gateway/Lambda phải đọc đúng header được forward; dữ liệu quốc gia chỉ là ước lượng theo định vị IP.

### Invalidation và định tuyến

- Ưu tiên tên asset có hash để phát hành version mới mà không invalidation. Khi cần xóa object đang cache, ví dụ:

  ```powershell
  aws cloudfront create-invalidation --distribution-id DISTRIBUTION_ID --paths "/index.html" "/assets/*"
  ```

- Wildcard phải nằm cuối path và shell cần giữ dấu nháy. Mỗi path invalidation được tính riêng; path `/*` vẫn là một path, không phải một path cho từng file bị ảnh hưởng. AWS hiện nêu **1.000 path đầu tiên mỗi tháng miễn phí trên toàn bộ distribution của một account**; vượt mức sẽ tính phí theo bảng giá hiện hành. Kiểm tra lại giá theo account/thời điểm trước khi triển khai. Không có giới hạn “số file” tương ứng với wildcard; giới hạn request/đồng thời là quota khác và cần tra mục CloudFront quotas khi cần.
- Behavior `/api/*` trỏ đến API Gateway HTTP/REST API origin, đặt cache disabled, forward method/body/header/query mà API cần. Chọn Origin Request Policy cụ thể và đảm bảo CORS chỉ cấu hình nếu trình duyệt gọi khác origin; cùng domain qua CloudFront thường tránh CORS.
- Lưu ý định tuyến `/{code}`: CloudFront behavior chọn origin theo path pattern; không có wildcard “đúng một segment” tổng quát. Nếu dùng chung host, cách ít mơ hồ là đặt S3 cho các đường dẫn frontend đã biết (`/`, `/index.html`, `/css/*`, `/js/*`, `/assets/*`, các trang HTML), API Gateway làm default origin cho các đường còn lại; API Gateway định tuyến `/{code}` tới Lambda redirect và phải trả 404 cho code không hợp lệ/không tồn tại. Thử nghiệm behavior ưu tiên và đường dẫn asset trước khi phát hành. Một host riêng cho short link là phương án đơn giản hơn nhưng cần thống nhất DNS/UX.
- Không để Lambda redirect truy cập được trực tiếp theo URL công khai nếu mục tiêu là bắt buộc qua CloudFront/WAF; hạn chế API Gateway origin/authorizer phù hợp và kiểm tra cách bảo vệ origin. Cấu hình API Gateway regional/custom domain và forwarding Host cần được kiểm thử.
- Chạy prototype local từ repo bằng `python -m http.server 8000 --directory frontend/prototype`, rồi mở `http://localhost:8000`; không cần API hoặc bước build.

### Headers, lỗi và WAF

- Gắn Response Headers Policy vào behaviors HTML để phát `Strict-Transport-Security` (HSTS, chỉ sau khi HTTPS ổn định; cân nhắc `includeSubDomains`/`preload` trước khi bật), `Content-Security-Policy` theo nguồn thực tế, và `X-Content-Type-Options: nosniff`. CSP phải cho phép đúng Google Fonts nếu nhóm giữ font online; không bật `unsafe-inline`/`unsafe-eval` tùy tiện. Response Headers Policy thay đổi header trả viewer, không thay đổi cache key.
- Với private S3 REST origin, object không có thể sinh 403 tùy quyền/config; CloudFront custom error response có thể trả trang `/error.html?type=404` và mã 404 cho viewer. Lưu ý mapping mã lỗi được cấu hình ở distribution, không cô lập theo behavior: mapping 403 có thể ảnh hưởng cả 403 từ API. Ưu tiên để lỗi object không tồn tại phân biệt rõ thành 404 khi phù hợp; nếu không, không map 403 toàn cục khi API cũng dùng 403. Error page phải tồn tại, behavior phục vụ trang lỗi phải trỏ đúng S3 origin, TTL lỗi thấp; xác minh nguyên nhân permission trước khi ánh xạ.
- Gắn AWS WAF Web ACL với CloudFront distribution để lọc/chặn request ở edge (Web ACL scope CloudFront được quản lý ở `us-east-1`). Bắt đầu bằng Count/staging và quan sát false positive trước khi Block. WAF bổ trợ chứ không thay thế validate URL, rate limit/Retry-After, blocklist và phát hiện bất thường trong ứng dụng.

### Luồng đề xuất

```mermaid
flowchart LR
  B[Trình duyệt] -->|HTTPS; HTTP được redirect| CF[CloudFront + AWS WAF]
  CF -->|/, HTML, CSS, JS; OAC SigV4| S3[(S3 private REST origin)]
  CF -->|/api/*; cache disabled; headers cần thiết| APIGW[API Gateway]
  CF -->|/{code} qua default API behavior| APIGW
  APIGW --> L[Lambda: shorten / redirect / stats]
  L --> DDB[(DynamoDB)]
  DDB -->|clicks stream| ANA[Lambda analytics]
  ANA --> ST[(Bảng thống kê)]
  APIGW -->|CloudFront-Viewer-Country| L
```

### Rủi ro/lưu ý hosting

- OAC chỉ dùng với S3 REST origin, không dùng S3 website endpoint; policy cần khóa theo ARN distribution đúng.
- Cache sai có thể lưu trang HTML cũ, redirect 302 hoặc dữ liệu API dùng chung; giữ API/redirect `CachingDisabled`, kiểm tra method/header/cache key.
- CloudFront path behavior không biểu đạt trực tiếp “một segment duy nhất”; cần quy ước mapping `/{code}` và kiểm thử URL root, assets, trang lỗi, query string.
- Custom error mapping 403 là cấu hình distribution-wide, có thể che cả lỗi quyền S3 lẫn 403 của API; tránh dùng nếu API và S3 chia sẻ mã lỗi mà không có cách phân biệt.
- HSTS, CSP, CORS và WAF có thể làm ứng dụng hỏng nếu bật cấu hình quá chặt/quá rộng; rollout/test trên staging.
- Chi phí CloudFront, S3 request/storage/transfer, API Gateway, Lambda, WAF, logs, invalidation phụ thuộc vùng, mức dùng và thời điểm; nhóm phải tính từ AWS Pricing Calculator, không suy ra từ báo cáo này.

## 2. Công nghệ

### Framework giao diện

| Tiêu chí | HTML/CSS/JS thuần (ES modules) | React + Vite |
|---|---|---|
| Build/CI | Không cần build; lint/test có thể thêm riêng. Deploy `aws s3 sync` trực tiếp. | Cần Node/npm, cài dependency, build `vite` và publish thư mục `dist`; dễ tích hợp CI nhưng có thêm cấu hình. |
| Kích thước | Không có runtime framework; nhỏ nhất với vài trang và ít tương tác. | Tăng do runtime React và dependency; tối ưu phụ thuộc cách bundle/tree-shake. |
| Phù hợp S3 tĩnh | Rất phù hợp; HTML/CSS/JS tĩnh là object trực tiếp. | Phù hợp sau khi build; S3 phục vụ `dist` như static assets. |
| Thời gian 4 tuần | Ít bước setup, triển khai màn tạo link và trạng thái nhanh. | Tốt nếu UI lớn/chia component phức tạp; thời gian setup và học thêm có thể làm chậm prototype. |
| Kỹ năng nhóm | Đủ dùng nếu nhóm quen nền tảng web; không cần hệ sinh thái mới. | Phù hợp khi thành viên đã quen React và sẵn sàng duy trì component/state/tooling. |
| Khả năng test | Unit test logic JS và kiểm thử trình duyệt cần chọn/cấu hình công cụ; test DOM thủ công đơn giản. | Component/unit test có hệ sinh thái phong phú, nhưng vẫn cần cấu hình test/build. |

### Thư viện biểu đồ

| Thư viện | Kích thước tương đối | Line / bar / pie | Cập nhật mỗi 5 giây | Responsive | Tài liệu |
|---|---|---|---|---|---|
| Chart.js | Trung bình; bundle và gzip phụ thuộc phiên bản, module được import và cách build. | Có sẵn line, bar, doughnut/pie. | Đủ cho dashboard prototype; cập nhật dataset rồi gọi `update`, không cần vẽ lại trang. | Responsive container/canvas; cần đặt chiều cao container hợp lý. | Tài liệu chính thức rõ, nhiều mẫu cơ bản. |
| Recharts | Trung bình-lớn do phụ thuộc React; không phù hợp trang vanilla. | Có line, bar, pie. | Cập nhật theo React state; đủ cho 5 giây với bộ dữ liệu dashboard nhỏ. | `ResponsiveContainer` hỗ trợ co giãn. | Tài liệu và ví dụ tốt; gắn chặt với React. |
| Apache ECharts | Lớn hơn lựa chọn tối giản nếu đóng gói toàn bộ; có thể import module/chart cụ thể. | Line, bar, pie và nhiều dạng khác. | Khả năng xử lý chart giàu tính năng; 60 điểm và poll 5 giây không phải tải lớn đáng kể. | Có `resize`/responsive theo container, cần gọi resize theo layout. | Tài liệu chi tiết, nhiều ví dụ; nhiều tùy chọn cần học. |
| uPlot | Nhỏ, tập trung vào hiệu năng đồ thị thời gian. | Line/area và series thời gian rất tốt; bar cần cấu hình/custom; pie không phải mục tiêu tích hợp sẵn. | Hiệu năng cao cho chuỗi dữ liệu lớn, dư sức với 60 điểm/5 giây. | Hỗ trợ kích thước nhưng cần chủ động xử lý resize/layout. | Tài liệu/API thiên kỹ thuật, ít tiện ích dashboard tổng quát hơn. |

**Kết luận:** chọn **HTML/CSS/JS thuần + Chart.js** làm mặc định. Đây là cách ít setup và nhanh nhất cho mốc bốn tuần, deploy trực tiếp lên S3, trong khi dashboard dự kiến chỉ cần line/bar/pie và polling 5 giây. Prototype tuần này chưa tải thư viện biểu đồ/CDN; khi tuần dashboard bắt đầu, đóng gói Chart.js cùng frontend và đo bundle thực tế (không dựa vào con số kích thước suy đoán). Nếu nhóm đã có nền React và muốn xây UI component phức tạp trong nhiều tuần, React + Vite là lựa chọn thay thế hợp lý.

## 3. Wireframe

Thiết kế nguồn đã có trong Figma (LinkPulse, `linkpulse.vn`), vì vậy không dựng lại giao diện bằng hình tự vẽ. Môi trường hiện tại không có công cụ Figma MCP để đọc frame/xuất ảnh và trang chia sẻ không cung cấp nội dung frame có thể tải; file `docs/gui_wireframe.md` ghi hướng dẫn xuất/chèn ảnh thủ công. Bốn màn bắt buộc:

| Màn Figma | Mục đích | Thành phần cần thể hiện theo thiết kế nguồn | Hành động | API liên quan (đề xuất, cần TV1 xác nhận contract) |
|---|---|---|---|---|
| 01 — Trang chủ | Tạo link ngắn. | Ô URL, tùy chọn alias/thời hạn/số click, nút rút gọn, vùng kết quả và lỗi. | Nhập URL, submit, copy kết quả. | `POST` tạo link; `X-Owner-Id`; 201 tạo mới, 200 link trùng cùng owner, 400/409/429/5xx lỗi. |
| 04 — Dashboard | Theo dõi lưu lượng gần thời gian thực. | Thẻ/thành phần dashboard theo frame Figma; biểu đồ và danh sách thống kê. | Chọn link/khoảng thời gian, refresh/poll 5 giây. | `GET` thống kê (toàn bộ/theo code); schema và query chưa chốt. |
| 08/09 — Cảnh báo | Giải thích vì sao đích đến bị chặn hoặc đáng ngờ. | Màn `/warning.html?reason=blocked` và `?reason=suspicious`; nội dung theo thiết kế nguồn. | Đọc cảnh báo, quay lại/đóng trang; không tự tiếp tục redirect. | API redirect kiểm tra policy, trả trạng thái/mã lỗi đã thống nhất với TV4. |
| 10/11 — 404/hết hạn | Thông báo link không tồn tại hoặc đã hết hạn. | `/error.html?type=404` và `?type=expired`; màn `max_clicks` dùng biến thể liên quan. | Quay lại trang trước hoặc trang chủ. | `GET /{code}` trả 404, 410 hoặc error code đã chốt. |

Chi tiết xuất ảnh và placeholder: [docs/gui_wireframe.md](./gui_wireframe.md). Chưa có ảnh PNG trong repo vì không thể truy cập frame Figma từ phiên này; không sử dụng wireframe giả.

## 4. Luồng & trạng thái

### Luồng người dùng

```mermaid
flowchart TD
  A[Mở trang chủ] --> B[Nhập URL và tùy chọn]
  B --> C{Client validate}
  C -->|Sai| E[Hiện lỗi tại trường]
  E --> B
  C -->|Đúng| D[POST tạo link + X-Owner-Id]
  D -->|201| F[Hiện link mới]
  D -->|200 trùng URL cùng owner| G[Hiện mã link cũ]
  D -->|400 / 409 / 429| H[Hiện lỗi theo error.code]
  D -->|5xx / mất mạng| I[Thông báo lỗi + Thử lại]
  F --> J[Sao chép]
  G --> J
  K[Truy cập /{code}] --> L{Kiểm tra link/policy}
  L -->|Active| M[302 tới URL đích]
  L -->|Không tồn tại| N[404]
  L -->|Hết hạn / hết lượt| O[410: expired / max_clicks]
  L -->|Bị chặn| P[/warning.html?reason=blocked]
  L -->|Đáng ngờ| Q[/warning.html?reason=suspicious]
  R[Mở dashboard] --> S[Loading]
  S --> T[GET stats; polling mỗi 5 giây]
  T --> U{Kết quả}
  U -->|Có dữ liệu| V[Dashboard; hiển thị thời điểm cập nhật]
  U -->|Rỗng| W[Empty state]
  U -->|Mất mạng| X[Giữ dữ liệu cũ + cảnh báo stale/retry]
  R --> Y[Quản lý link của tôi]
  Y --> Z[GET danh sách theo owner_id; chỉnh sửa/disable theo API đã chốt]
  R --> AA[Quản trị]
  AA --> AB{Có admin key?}
  AB -->|Không| AC[Khóa trang/403]
  AB -->|Có| AD[Admin API]
```

### Bảng trạng thái giao diện

| Tên trạng thái | Điều kiện kích hoạt (HTTP/error.code) | Giao diện hiển thị | Hành động người dùng |
|---|---|---|---|
| Loading | Đang gửi request hoặc tải dashboard/list. | Trạng thái đang xử lý; khóa submit lặp và thông báo qua vùng `aria-live`. | Chờ; không gửi request trùng. |
| Lỗi mạng | Fetch thất bại/timeout hoặc không nhận response. | Thông báo đỏ, nút **Thử lại**; dashboard giữ dữ liệu cuối và đánh dấu đã cũ. | Thử lại khi kết nối ổn định. |
| URL không hợp lệ | Client validation hoặc HTTP 400 `invalid_url`. | Lỗi đỏ dưới ô URL; giữ giá trị để sửa. | Sửa URL thành HTTP(S), tối đa 2048 ký tự. |
| Domain bị chặn | HTTP 400 `blocked_domain`. | Thông báo đỏ dưới URL hoặc cảnh báo tương ứng. | Nhập đích hợp lệ khác. |
| Alias trùng | HTTP 409 `alias_taken`. | Lỗi tại trường alias. | Đổi alias. |
| Rate limit | HTTP 429 `rate_limited`; đọc `Retry-After` (giây). | Thông báo vàng, bộ đếm lùi; khóa submit đến khi hết thời gian. | Chờ bộ đếm về 0 rồi thử lại. |
| Lỗi server | HTTP 5xx. | Thông báo đỏ và nút **Thử lại**; không hiển thị stack/error raw. | Thử lại sau. |
| Tạo thành công | HTTP 201. | Vùng kết quả với URL rút gọn. | Sao chép/mở link. |
| Trùng link cùng chủ sở hữu | HTTP 200; response có mã cũ. | Kết quả hiện mã cũ, thông tin rõ đây là link đã tồn tại. | Sao chép/mở mã cũ. |
| Alias sai định dạng | Client validation; contract API cần trả code tương ứng nếu gửi trực tiếp. | Lỗi cạnh alias (3–30 ký tự chữ/số/gạch ngang). | Sửa alias hoặc để trống. |
| Link không tồn tại | Redirect API HTTP 404. | `/error.html?type=404`. | Trở lại/trang chủ. |
| Link hết hạn | HTTP 410, mã `expired` (cần TV1 xác nhận). | `/error.html?type=expired`. | Trở lại/trang chủ. |
| Hết lượt click | HTTP 410, mã `max_clicks` (cần TV1 xác nhận). | `/error.html?type=max_clicks`. | Trở lại/trang chủ. |
| Link bị chặn | Mã policy `blocked`; status HTTP cần TV4/TV1 chốt. | `/warning.html?reason=blocked`. | Đọc lý do, rời trang; không redirect. |
| Link đáng ngờ | Mã policy `suspicious`; status HTTP cần TV4/TV1 chốt. | `/warning.html?reason=suspicious`. | Đọc cảnh báo, rời trang; không redirect. |
| Link active | Redirect API trả HTTP 302. | Trình duyệt theo redirect đến đích. | Không cần thêm thao tác. |
| Dashboard rỗng | Stats API trả 200 nhưng dữ liệu rỗng. | Empty state, không vẽ dữ liệu giả. | Tạo lượt truy cập/chọn link/khoảng thời gian khác. |
| Dashboard dữ liệu cũ | Poll 5 giây thất bại nhưng đã có dữ liệu trước đó. | Giữ số liệu cuối, nhãn “cập nhật lúc …” và cảnh báo kết nối. | Thử tải lại. |
| Admin bị khóa | Thiếu/sai admin key hoặc HTTP 403. | Trang quản trị khóa; không lộ chi tiết quyền. | TV5/admin cấu hình quyền; người dùng quay lại. |

Giao diện xử lý bằng `error.code`, không phụ thuộc câu chữ response. Mọi dữ liệu user/API hiển thị bằng `textContent`/DOM APIs, không chèn chuỗi động qua `innerHTML`. Polling dừng khi rời trang/ẩn tab để tránh request không cần thiết; chu kỳ 5 giây theo kiến trúc chung, cần API stats sẵn sàng.

## 5. Rủi ro & câu hỏi cần thống nhất với TV1/TV3/TV4/TV5

| Nhóm | Câu hỏi/rủi ro cần thống nhất |
|---|---|
| TV1 — API/backend | Chốt URL/method/schema cho shorten, duplicate 200, stats, list/manage và redirect; danh sách `error.code`; header/body `Retry-After`; status 404/410 và mã `expired`/`max_clicks`; CORS và `X-Owner-Id`. |
| TV1 — định tuyến | Với link rút gọn dạng `linkpulse.vn/{code}`, xác nhận CloudFront default API + behaviors S3 tĩnh, hay chọn host riêng/prefix. Kiểm thử cache redirect và query string. |
| TV3 — database/analytics | Chốt schema stats, timezone, thời gian cập nhật, trường country/device/top links và xử lý dữ liệu rỗng; dashboard poll 5 giây có phù hợp tải API không. |
| TV4 — security | Chốt status/error code và nội dung cảnh báo blocked/suspicious; CSP nguồn font; admin authentication/key custody. `owner_id` tạo ở trình duyệt và `X-Owner-Id` có thể bị sửa/giả mạo nên **không phải bằng chứng xác thực danh tính**; thống nhất cách giới hạn rủi ro, dữ liệu có thể xem/sửa và quyền admin. |
| TV5 — infra/DevOps | Chốt region, domain/DNS, ACM tại `us-east-1`, bucket/OAC policy, Response Headers Policy, WAF Web ACL scope, deployment/invalidation, logging và cost estimation. |
| Cả nhóm | Cấp quyền xem/export Figma hoặc TV2 tự xuất frame; quyết định file ảnh (PNG export và `docs/gui_wireframe.png` khi đủ quyền), chốt ai phụ trách slide từng module. |

**Cần xác minh trước khi production:** exact API contract và status code; CloudFront behavior thực tế cho `/{code}`; cache TTL; ACM/DNS region/ownership; CSP; WAF rules/false positives; quota/giá theo account và region; các kích thước bundle thực đo.

## 6. Nguồn tham khảo

Tài liệu AWS là nguồn chính cho mô tả hạ tầng. Giá và quota có thể cập nhật; kiểm tra lại trước khi triển khai thật.

1. Amazon S3 — [Hosting a static website](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html)
2. CloudFront — [Restrict access to an Amazon S3 origin (OAC/OAI)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
3. CloudFront — [Require HTTPS for communication between viewers and CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-https-viewers-to-cloudfront.html)
4. AWS Certificate Manager — [Regions and AWS managed certificates](https://docs.aws.amazon.com/acm/latest/userguide/acm-regions.html)
5. CloudFront — [Cache behavior settings](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesCacheBehavior.html)
6. CloudFront — [Control the cache key with a policy](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/controlling-the-cache-key.html)
7. CloudFront — [Control origin requests with a policy](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/controlling-origin-requests.html)
8. CloudFront — [Add CloudFront request headers](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-cloudfront-headers.html)
9. CloudFront — [Add or remove HTTP headers with a response headers policy](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/modifying-response-headers.html)
10. CloudFront — [Custom error pages and error caching](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesErrorPages.html)
11. CloudFront — [Invalidate files](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Invalidation_Requests.html)
12. CloudFront — [Pay for file invalidation](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PayingForInvalidation.html)
13. AWS WAF — [Configuring protection in AWS WAF / Web ACL](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl.html)
14. Amazon CloudFront — [Pricing](https://aws.amazon.com/cloudfront/pricing/)
15. Chart.js — [Documentation](https://www.chartjs.org/docs/latest/)
16. Recharts — [Documentation](https://recharts.org/en-US/)
17. Apache ECharts — [Documentation](https://echarts.apache.org/en/index.html)
18. uPlot — [Documentation and examples](https://github.com/leeoniya/uPlot)
19. Thiết kế sản phẩm (nguồn nhóm cung cấp) — [Figma: URL Shortener — Giao diện TV2](https://www.figma.com/design/uZxwjbnDQeqpGBqXQbuwVc/URL-Shortener-%E2%80%94-Giao-di%E1%BB%87n-TV2--Serverless-AWS-?node-id=5-18&m=dev)
20. CloudFront — [Use managed cache policies (`CachingDisabled`)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html)
21. CloudFront — [Create a custom error page](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/creating-custom-error-pages.html)
22. CloudFront — [Quotas](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cloudfront-limits.html)
