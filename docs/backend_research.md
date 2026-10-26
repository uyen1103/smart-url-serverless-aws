# Nghiên cứu Backend Core: Serverless API rút gọn link

> **Người thực hiện:** TV1 (Backend Core) · **Issue:** #1 · **Trạng thái:** hoàn thành tuần 1 (các điểm cần thống nhất với nhóm ở mục 7)

## Kết luận

Backend dùng **API Gateway HTTP API + Lambda (Python 3.11) + DynamoDB**, đặt **CloudFront + WAF** phía trước. Các quyết định chính:

- **API Gateway:** chọn HTTP API vì rẻ hơn, độ trễ thấp hơn và đủ cho các endpoint của hệ thống. HTTP API không gắn trực tiếp WAF và không có API key/usage plan, nên WAF gắn vào CloudFront. Chỉ đổi sang REST API nếu nhóm cần usage plan hoặc gắn WAF trực tiếp.
- **Sinh mã:** random 7 ký tự Base62 bằng `secrets`, kiểm tra trùng bằng conditional write `attribute_not_exists(short_code)`, trùng thì sinh lại (tối đa 5 lần). Alias dùng chung khóa với mã tự sinh; cùng chủ sở hữu rút gọn lại đúng URL thì trả link cũ (HTTP 200).
- **Redirect:** dùng 302 kèm `Cache-Control: no-store` để đếm được click. Hết hạn hoặc hết lượt click trả 410; không tồn tại hoặc đã xóa trả 404; bị chặn hoặc đáng ngờ trả 403.
- **Lambda:** Python 3.11, 128 MB, timeout 5 giây là mức khởi điểm; khởi tạo client ngoài handler; đo thực tế rồi mới chỉnh.
- **Chủ sở hữu link:** header `X-Owner-Id` (UUID theo trình duyệt). Đây không phải xác thực thật.

**Trạng thái thực hiện:** đặc tả OpenAPI hợp lệ (`docs/api_spec.yaml`); prototype Python có 31 test đạt; SAM hello-world đã deploy và gọi thành công (mục 6.2).

---

## 1. AWS Lambda

### 1.1 Lambda là gì, vì sao hợp với hệ thống này
Lambda chạy một hàm code khi có sự kiện (ở đây là request từ API Gateway), không cần quản lý server, tính tiền theo số lần gọi và thời gian chạy. Hệ thống rút gọn link có tải thất thường (có lúc ít, có lúc dồn) và mỗi request rất nhẹ (đọc/ghi một item DynamoDB), nên rất hợp với Lambda.

### 1.2 Cold start
- **Cold start** là khi Lambda phải tạo môi trường chạy mới: tải code, khởi động runtime, chạy phần code ngoài hàm handler. Việc này xảy ra ở lần gọi đầu, khi sau một thời gian không dùng, hoặc khi lượng request tăng và cần thêm môi trường mới.
- **Warm start** là khi tái sử dụng môi trường có sẵn, nhanh hơn nhiều.
- Với hàm redirect (người dùng chờ trực tiếp), cold start làm chậm lần truy cập đầu tiên.

Cách giảm ảnh hưởng:
1. Khởi tạo client `boto3` và đọc biến môi trường **ngoài** hàm `lambda_handler` để được tái sử dụng ở các lần gọi sau.
2. Giữ gói code nhỏ, chỉ import thư viện cần thiết.
3. Tăng memory một chút (CPU tăng theo), thường làm khởi động nhanh hơn.
4. Nếu sau này cần: dùng provisioned concurrency (giữ sẵn môi trường, nhưng tốn phí).

### 1.3 Memory và timeout
| Thiết lập | Giá trị theo tài liệu AWS | Đề xuất cho dự án |
|-----------|---------------------------|-------------------|
| Memory | 128 MB đến 10.240 MB; CPU tăng tỷ lệ theo memory, đạt tương đương 1 vCPU ở 1.769 MB | 128 MB để bắt đầu, đo rồi mới tăng |
| Timeout | Tối đa 900 giây (15 phút) | 3 đến 5 giây (các hàm chỉ gọi DynamoDB nên rất nhanh) |

Đặt timeout nhỏ giúp lỗi bị phát hiện sớm và không tốn tiền khi hàm bị treo. Cần đo thực tế: xem dòng `REPORT` trong CloudWatch Logs (có `Duration` và `Max Memory Used`).

### 1.4 Concurrency
- Là số bản sao của hàm chạy **cùng lúc**. Giới hạn mặc định là **1.000 mỗi region cho cả tài khoản** (có thể xin tăng). Tài khoản AWS mới có thể bị giới hạn thấp hơn lúc đầu.
- **Reserved concurrency**: dành riêng một phần cho một hàm, đồng thời cũng là mức trần của hàm đó. Hữu ích để hàm redirect không bị hàm khác chiếm hết, hoặc để chặn một hàm "ăn" hết quota khi bị tấn công.
- **Provisioned concurrency**: giữ sẵn môi trường đã khởi động (không cold start) nhưng tính phí. Chỉ áp dụng cho một phiên bản (version) hoặc alias của hàm, không áp dụng cho `$LATEST`. Reserved concurrency thì không tính phí thêm.

### 1.5 Biến môi trường
- Dùng để cấu hình mà không cần sửa code, ví dụ: `URLS_TABLE`, `CLICKS_TABLE`, `BASE_URL`, `CODE_LENGTH`.
- Tổng dung lượng tất cả biến môi trường của một hàm tối đa **4 KB**.
- Không lưu bí mật (mật khẩu, API key) dạng chữ thường trong biến môi trường. Dùng Secrets Manager hoặc SSM Parameter Store.
- Trong `template.yaml` khai báo ở mục `Environment: Variables:`; trong code đọc bằng `os.environ["URLS_TABLE"]`.

---

## 2. API Gateway: REST API và HTTP API

### 2.1 So sánh (theo tài liệu AWS "Choose between REST APIs and HTTP APIs")
| Tiêu chí | REST API | HTTP API |
|----------|----------|----------|
| Giá | Cao hơn | Thấp hơn (thiết kế tối giản để rẻ hơn) |
| Độ trễ | Cao hơn | Thường thấp hơn |
| API key, usage plan, giới hạn theo từng client | **Có** | **Không** |
| Gắn trực tiếp AWS WAF | **Có** | **Không** |
| Request validation, cache tích hợp | Có | Không |
| Private endpoint, resource policy | Có | Không |
| JWT authorizer sẵn có | Không (dùng Cognito user pool authorizer hoặc Lambda authorizer) | **Có** |
| Xác thực IAM, Lambda authorizer | Có | Có |
| Custom domain | Có | Có |

> Giá và tính năng có thể thay đổi; cần số liệu cụ thể thì xem trang giá của API Gateway trên aws.amazon.com.

### 2.2 Hệ thống cần gì
1. **Redirect phải nhanh và rẻ.** Đây là endpoint có lượng truy cập lớn nhất.
2. **Chống lạm dụng** (TV5): WAF rate-based rule, throttling, blocklist.
3. **Xác thực đơn giản** cho `DELETE` và danh sách link: dùng header `X-Owner-Id` (UUID theo trình duyệt) như giao diện của TV2 đang làm; chưa cần đăng nhập thật.
4. Không cần request/response transformation phức tạp, không cần cache ở API Gateway.

### 2.3 Đề xuất: HTTP API + CloudFront + WAF
- HTTP API rẻ và nhanh hơn, có JWT authorizer sẵn (dùng được nếu sau này thêm đăng nhập), đáp ứng đủ các endpoint của hệ thống.
- HTTP API **không gắn trực tiếp WAF**, nên đặt **CloudFront phía trước** và gắn WAF vào CloudFront. Hướng này khớp với issue của TV2 (S3 + CloudFront, trỏ `/api/*` sang API Gateway) và TV5 (WAF cho CloudFront tạo ở `us-east-1`, có phí).
- Giới hạn tốc độ theo IP làm bằng WAF rate-based rule và/hoặc bảng `rate_limits` trong DynamoDB (TV3 đã thiết kế).

**Khi nào nên đổi sang REST API:** nếu nhóm muốn API key / usage plan theo từng người dùng, hoặc muốn gắn WAF trực tiếp vào API Gateway mà không qua CloudFront.

**Cần chốt với TV5** trước khi viết kiến trúc cuối cùng.

---

## 3. Thuật toán sinh mã rút gọn

Mã dùng bảng chữ Base62 (`a-z`, `A-Z`, `0-9`). Độ dài 7 ký tự cho 62⁷ = **3.521.614.606.208** (khoảng 3,5 nghìn tỷ) tổ hợp.

### 3.1 Ba phương án
| | A. Base62 từ bộ đếm | B. Hash (MD5/SHA) rồi cắt | C. Random + kiểm tra trùng |
|---|---|---|---|
| Cách làm | Tăng một bộ đếm toàn cục, đổi số sang Base62 | Hash URL, lấy N ký tự đầu | Chọn ngẫu nhiên N ký tự |
| **Va chạm** | Không bao giờ trùng | Có: cắt ngắn làm mất thông tin, hai URL khác nhau có thể ra cùng mã | Có nhưng rất hiếm, và phát hiện được |
| **Đoán được mã** | **Dễ**: mã tăng dần, kẻ xấu duyệt tuần tự (enumeration) | Trung bình: cùng URL luôn ra cùng mã, nếu biết thuật toán thì tính được | **Khó** (nếu dùng bộ sinh ngẫu nhiên an toàn) |
| **Hiệu năng** | Mỗi lần tạo cần thêm 1 thao tác ghi để tăng bộ đếm; item bộ đếm là điểm nghẽn | Nhanh, không cần trạng thái chung | Nhanh; hiếm khi phải thử lại |
| Cùng URL tạo 2 lần | 2 mã khác nhau | **Cùng 1 mã** (khó gán chủ sở hữu, hạn dùng, thống kê riêng) | 2 mã khác nhau (muốn trả lại link cũ cho cùng người dùng thì phải tra cứu thêm, xem mục 3.4) |

### 3.2 Tính xác suất trùng (phương án C, 7 ký tự)
Khi đã có `n` link, xác suất một mã mới ngẫu nhiên trùng mã cũ là `n / 62⁷`:

| Số link đã có | Xác suất trùng ở mỗi lần sinh |
|---|---|
| 1 triệu | khoảng 2,8 × 10⁻⁷ |
| 1 tỷ | khoảng 2,8 × 10⁻⁴ (0,03%) |

Nếu trùng thì sinh lại. Thử tối đa 5 lần thì xác suất cả 5 lần đều trùng là không đáng kể.

Với phương án B nếu chỉ lấy 7 ký tự hex của MD5 thì chỉ có 16⁷ ≈ 268 triệu tổ hợp, nên với 1 triệu link xác suất trùng mỗi lần đã khoảng 0,37%.

### 3.3 Lựa chọn: **C. Random 7 ký tự Base62 + kiểm tra trùng**
Lý do:
1. **Khó đoán**, giảm nguy cơ dò mã (TV5 liệt kê "dò mã (enumeration)" là một mối đe dọa).
2. **Đơn giản và nhanh**, không cần bộ đếm dùng chung.
3. **Kiểm tra trùng miễn phí** nhờ DynamoDB: ghi item bằng `ConditionExpression: attribute_not_exists(short_code)`. Nếu lỗi `ConditionalCheckFailedException` thì sinh mã mới và thử lại (đây chính là phần TV3 nghiên cứu).
4. Mỗi lần tạo link là một mã riêng, nên gán được `owner`, `expires_at`, `max_clicks`, thống kê riêng cho từng link (ngoại lệ: trả lại link cũ cho cùng chủ sở hữu, xem mục 3.4).

Lưu ý khi cài đặt: dùng module `secrets` (không dùng `random`) vì `random` có thể bị đoán trước.

### 3.4 Alias và link trùng (theo yêu cầu của giao diện TV2)
Giao diện có ô **Alias** (3-30 ký tự chữ, số, gạch ngang) và có trạng thái "URL đã được rút gọn trước đó", nên API cần thêm:

1. **Alias.** Người dùng chọn tên thì dùng luôn tên đó làm `short_code`. Ghi bằng cùng một conditional write; trùng thì trả **409 `alias_taken`** (không tự sinh lại như mã ngẫu nhiên). Mã tự sinh và alias dùng chung một không gian khóa nên không thể trùng nhau.
2. **Tên dành riêng.** Alias không được trùng đường dẫn của hệ thống (`api`, `assets`, `dashboard`, `error`, `warning`...), nếu không `GET /{code}` sẽ lẫn với trang web. Các tên này cũng trả `alias_taken`.
3. **Phân biệt chữ hoa/thường.** `Abc` và `abc` là hai mã khác nhau. Bản prototype giữ cách này cho đơn giản; có thể đổi sang không phân biệt nếu nhóm muốn tránh nhầm lẫn.
4. **Link trùng.** Nếu **không đặt alias** và cùng chủ sở hữu (`X-Owner-Id`) đã có link **còn hiệu lực** cho đúng URL đó, trả lại link cũ với HTTP 200 và `created: false`. Link đã hết hạn, hết lượt click, bị chặn hoặc đã xóa thì không được dùng lại. Khác chủ sở hữu thì vẫn tạo mã mới (mỗi người có thống kê riêng).
5. **Việc cho TV3.** Để tra cứu "cùng chủ sở hữu và cùng URL" mà không phải quét cả bảng, bảng `urls` cần một chỉ mục phụ theo `owner` (GSI, sort key theo thời gian tạo); bước kiểm tra trùng lọc theo `long_url` trong kết quả. Mã đã xóa nên giữ lại dạng "đã xóa" để không cấp lại cho người khác.

---

## 4. Redirect: 301, 302, 307

| Mã | Ý nghĩa | Trình duyệt cache? | Đếm click? |
|----|---------|--------------------|------------|
| **301** Moved Permanently | Chuyển vĩnh viễn | **Có**, lần sau đi thẳng, không qua server | **Không đếm được** |
| **302** Found | Chuyển tạm thời | Không (mặc định) | **Đếm được** |
| **307** Temporary Redirect | Chuyển tạm thời, giữ nguyên phương thức HTTP | Không (mặc định) | Đếm được |
| 308 Permanent Redirect | Như 301 nhưng giữ nguyên phương thức | Có | Không đếm được |

### Lựa chọn: **302**
- Hệ thống cần đếm click (TV4 làm analytics, issue yêu cầu "tổng click, click/phút...") nên mỗi lượt truy cập phải đi qua server. Loại 301 và 308.
- Giữa 302 và 307: với link người dùng mở bằng trình duyệt (phương thức GET), hai mã hoạt động như nhau. Chọn 302 vì phổ biến nhất. Có thể dùng 307 nếu sau này cần giữ nguyên phương thức POST.
- Thêm header `Cache-Control: no-store` vào response redirect để chắc chắn không bị cache.
- Link hết hạn hoặc hết lượt click trả **410 Gone**; mã không tồn tại hoặc link đã xóa trả **404**.

### Kết quả theo trạng thái link (khớp các trang của TV2)
| Trạng thái | HTTP | `error.code` | Trang giao diện |
|---|---:|---|---|
| Đang hoạt động | 302 | - | chuyển đến URL đích, ghi click event |
| Không tồn tại / đã xóa | 404 | `not_found` | `/error.html?type=404` |
| Hết hạn | 410 | `link_expired` | `/error.html?type=expired` |
| Hết lượt click | 410 | `max_clicks_reached` | `/error.html?type=max_clicks` |
| Bị chặn | 403 | `link_blocked` | `/warning.html?reason=blocked` (không bao giờ chuyển tiếp) |
| Đáng ngờ | 403 | `link_suspicious` | `/warning.html?reason=suspicious`; người dùng xác nhận thì gọi lại `/{code}?confirm=1` để được 302 |

Thứ tự kiểm tra: bị chặn, hết hạn, hết lượt click, đáng ngờ. `confirm=1` **không** vượt qua được trạng thái bị chặn, để cảnh báo không thành đường vòng bỏ qua chặn (TV2 cũng lo điểm này).

Link không tồn tại hoặc đã xóa dùng chung 404 vì giao diện chưa có trang riêng cho "đã xóa".

---

## 5. Prototype Python

File: `backend/prototype.py` (code), `tests/test_backend_prototype.py` (test). Chạy local, dữ liệu giả là một dict trong bộ nhớ. Tên trường và mã lỗi bám theo `docs/api_spec.yaml` và mock của TV2.

**Chạy (từ thư mục gốc repo):**
```bash
python backend/prototype.py      # demo
python -m pytest tests -v        # test (pytest có trong requirements.txt)
```

**Hàm trong prototype:** `shorten()` và `redirect()` (hai hàm theo yêu cầu issue), thêm `delete_link()` vì giao diện cần xóa link.

**Những gì đã xử lý:**
- Kiểm tra URL: chỉ `http`/`https`, tối đa 2048 ký tự, có host, không có `user:pass@`, không chứa khoảng trắng, không thuộc chính domain `linkpulse.vn`.
- Chặn địa chỉ nội bộ (SSRF) như TV5 đề cập: `localhost`, `127.0.0.1`, `10.x`, `192.168.x`, `169.254.169.254`, cả dạng viết tắt (`127.1`) và dạng số (`2130706433`). Tất cả trả `invalid_url` (giao diện coi đây là "URL không hợp lệ").
- Domain trong blocklist trả `blocked_domain`.
- Alias, tên dành riêng, trả lại link cũ khi trùng URL (mục 3.4).
- Xử lý trùng mã ngẫu nhiên: sinh lại tối đa 5 lần, quá 5 lần trả 500.
- `expires_in` tính bằng giây (giao diện gửi 3600, 86400, 604800), `max_clicks`.
- Trạng thái link: bị chặn, hết hạn, hết lượt click, đáng ngờ (cần `confirm`), đã xóa.
- Xóa link chỉ cho đúng chủ sở hữu (401/403/404).

**Kết quả test (đã chạy thực tế):**
```
31 passed
```

**Giới hạn của prototype (cần làm ở các tuần sau):**
- Chỉ kiểm tra URL dạng chữ, chưa phân giải DNS. Một tên miền công khai vẫn có thể trỏ về IP nội bộ, nên bản chính thức cần xử lý thêm.
- Chưa có: xác minh Turnstile, rate limit, kiểm tra Safe Browsing/URLhaus, ghi click event, danh sách link và thống kê (phần của TV3, TV4, TV5 khi ghép vào Lambda).
- Dữ liệu mất khi tắt chương trình; bản thật sẽ ghi vào DynamoDB.

---

## 6. Cài SAM CLI và deploy hello-world

File: `backend/template.yaml`, `backend/hello/app.py`. Repo đã có `.gitignore` (đã bỏ qua `.aws-sam/` và `__pycache__/`), không cần thêm.

### 6.1 Các bước
1. Cài **AWS CLI** và **AWS SAM CLI** theo hướng dẫn chính thức cho hệ điều hành đang dùng; kiểm tra:
   ```bash
   aws --version
   sam --version
   ```
2. Cấu hình tài khoản (dùng IAM user riêng theo việc dựng nền tảng của TV5, không dùng tài khoản root):
   ```bash
   aws configure        # nhập Access Key, Secret, region, output: json
   ```
   Region: dùng `ap-southeast-1` nếu tài khoản cho phép chọn Region. Với tài khoản Free plan kiểu mới ("Sign up for AWS (new)"), Region bị cố định theo project, xem ở https://settings.aws.com, mục Project, dòng Region. Khi đó phải dùng đúng Region đó, nếu không `sam deploy` bị `AccessDenied` do service control policy.
3. Build và deploy trong thư mục `backend/`:
   ```bash
   cd backend
   sam build
   sam deploy --guided
   ```
   Khi được hỏi: đặt Stack Name (ví dụ `smart-url`), region đúng như đã cấu hình ở bước 2, chấp nhận tạo IAM role (`y`), lưu cấu hình (`y`). Những câu còn lại nhấn Enter. Câu hỏi về việc không có authorization cho route `/hello` trả lời `y`, vì đây chỉ là bản thử.
4. Cuối quá trình deploy, phần **Outputs** có `HelloApiUrl`. Mở URL đó hoặc chạy:
   ```bash
   curl <HelloApiUrl>
   ```
   Kết quả đúng: `{"message": "hello from smart-url"}`.
5. **Xóa tài nguyên để khỏi tốn phí** sau khi chụp kết quả:
   ```bash
   sam delete
   ```

### 6.2 Kết quả deploy
- Ngày deploy: 25/10/2026
- Stack: `smart-url`, Region `ap-southeast-2` (Sydney)
- `HelloApiUrl`: `https://vxoj3bxoyj.execute-api.ap-southeast-2.amazonaws.com/hello` (đã xóa bằng `sam delete` sau khi chụp ảnh nên không còn truy cập được)
- Kết quả `curl.exe`: `{"message": "hello from smart-url"}`
- Ảnh chụp kết quả (lưu trong `docs/images/`):

![Kết quả curl](images/deploy-curl.png)

![Kết quả deploy](images/deploy-outputs.png)

- Tài nguyên tạo ra (đều `CREATE_COMPLETE`): 1 Lambda (`python3.11`), 1 HTTP API, 1 stage mặc định, 1 IAM role, 1 quyền cho API Gateway gọi Lambda
- **Lỗi gặp phải:** lần `sam deploy` đầu ở `ap-southeast-1` bị `AccessDenied` (`cloudformation:CreateChangeSet`, "explicit deny in a service control policy"). Nguyên nhân: tài khoản Free plan kiểu mới có Region cố định theo project (ở đây là Sydney `ap-southeast-2`) và AWS tự quản lý SCP giới hạn Region, người dùng không sửa được. Sau khi đổi Region của CLI sang `ap-southeast-2` (`aws configure set region ap-southeast-2`) thì deploy thành công.
- **Lưu ý cho nhóm:** kiến trúc dự kiến dùng `ap-southeast-1`. Thành viên nào dùng tài khoản Free plan kiểu mới sẽ không deploy được ở Singapore. Hello-world chỉ để chứng minh SAM deploy chạy được; Region deploy thật cần thống nhất với TV5.

### 6.3 Lỗi thường gặp
| Lỗi | Nguyên nhân thường gặp | Cách xử lý |
|-----|------------------------|------------|
| `Unable to locate credentials` | Chưa chạy `aws configure` | Chạy `aws configure` |
| `AccessDenied` khi deploy | IAM user thiếu quyền (CloudFormation, Lambda, API Gateway, IAM, S3) | Nhờ TV5 cấp quyền |
| `AccessDenied ... service control policy` khi `sam deploy` | Region của CLI khác Region cố định của project (tài khoản Free plan kiểu mới) | Xem Region ở settings.aws.com, mục Project, rồi `aws configure set region <Region đó>` |
| `sam build` không thấy đúng phiên bản Python | Máy chưa cài đúng phiên bản | Cài đúng phiên bản hoặc đổi `Runtime` trong `template.yaml` cho khớp, hoặc dùng `sam build --use-container` (cần Docker) |
| Gọi URL ra `Message: Forbidden` | Sai đường dẫn (thiếu `/hello`) | Dùng đúng URL trong Outputs |

---

## 7. Bàn giao liên nhóm

### Hợp đồng API đã đối chiếu
Spec (`docs/api_spec.yaml`) được đối chiếu với `frontend/prototype/` (mock JSON, `app.js`), `docs/frontend_research.md`, `docs/gui_wireframe.md` của TV2 và `docs/click_event_schema.json`, `analytics/prototype/aggregate.py` của TV4. Các quyết định chính:

| Chủ đề | Quyết định trong spec | Theo |
|---|---|---|
| Body `POST /shorten` | `url`, `alias`, `expires_in` (giây), `max_clicks`, `turnstile_token` | TV2 |
| Response tạo link | `code`, `short_url`, `created`; link mới trả 201, link cũ trả 200 | TV2 |
| Domain bị chặn | 400 `blocked_domain` | TV2 |
| Alias bị trùng | 409 `alias_taken` | TV2 |
| Chủ sở hữu link | header `X-Owner-Id` | TV2 |
| Rate limit | header `Retry-After` và `error.retry_after` trong body | TV2 (mock đọc thời gian chờ) |
| Dashboard | `GET /stats` (có `top_links`), gọi định kỳ 5 giây | TV2, TV4 |
| Thống kê theo link | `GET /stats/{code}` kèm `link`, `recent_clicks`, `bot_clicks`, `updated_at` | màn 04, 04c của TV2 |
| Danh sách link | `GET /links`, phân trang bằng cursor | màn "Link của tôi" của TV2 |
| Trạng thái link | `active`, `suspicious`, `blocked`, `max_clicks`, `expired` | nhãn ở màn 05 của TV2 |
| Link đáng ngờ | 403 `link_suspicious`, tiếp tục bằng `?confirm=1` | TV2 |
| Trường thời gian của `timeline` | `bucket` (ISO 8601 có giây); lớp API đổi từ `clicks_per_minute[].minute` của TV4 | TV4 |

### Gửi TV2 – Giao diện
* Dùng `docs/api_spec.yaml` làm hợp đồng cho mock: request `url`, `alias`, `expires_in` (giây), `max_clicks`, `turnstile_token`; response `code`, `short_url`, `created`; lỗi `invalid_url`, `blocked_domain` (400), `alias_taken` (409), `rate_limited` (429, kèm `Retry-After`).
* Danh sách "Link của tôi" phân trang bằng cursor (`next_cursor`), nút "Tải thêm" thay cho số trang, vì DynamoDB phân trang theo `LastEvaluatedKey`.
* Prototype hiện chưa gửi `turnstile_token`; cần thêm khi bật Turnstile.
* Các trạng thái redirect và trang tương ứng ở mục 4. `?confirm=1` chỉ giúp tiếp tục link đáng ngờ, không vượt được link bị chặn.
* Cần thống nhất: trang lỗi/cảnh báo do Lambda trả 302 sang `error.html`/`warning.html`, hay CloudFront custom error response.

### Gửi TV3 – Database
* Bảng `urls` lưu: `short_code`, `long_url`, `owner`, `status` (`active`, `suspicious`, `blocked`, `deleted`), `expires_at`, `max_clicks`, `click_count`, `created_at`.
* Ghi link mới bằng conditional write `attribute_not_exists(short_code)`. Alias và mã tự sinh dùng chung khóa: trùng alias trả 409, trùng mã tự sinh thì sinh lại.
* Cần GSI theo `owner` (sort key theo thời gian tạo) để liệt kê link của người dùng và tra "cùng chủ sở hữu, cùng URL" (mục 3.4).
* Mã đã xóa giữ ở trạng thái `deleted` để không cấp lại cho người khác.

### Gửi TV4 – Analytics
* `GET /stats` và `GET /stats/{code}` trả số liệu theo schema click event: `country` là mã 2 chữ hoặc `XX`, `device` thuộc 5 giá trị trong schema, `referrer` là domain hoặc `direct`. API không trả `ip_hash` hay `user_agent`.
* `timeline[].bucket` là ISO 8601 có giây; lớp API đổi tên từ `clicks_per_minute[].minute` và thêm `:00`.
* Giao diện cần thêm: `bot_clicks` (trong `timeline` và tổng), `recent_clicks`, `avg_clicks_per_minute`, `flagged_links`. `total_clicks` hiện tính cả bot, giống `aggregate.py`.
* Cần chốt: `ip_hash` dùng salt cố định hay đổi theo ngày, vì ảnh hưởng độ chính xác của `unique_visitors`.

### Gửi TV5 – Security/DevOps
* Cần chốt HTTP API hay REST API (mục 2): HTTP API không gắn WAF trực tiếp và không có usage plan.
* `X-Owner-Id` chỉ là định danh theo trình duyệt. API quản trị (chặn/gỡ chặn link, màn 07 của TV2) cần xác thực thật và chưa có trong spec.
* Cần thống nhất: nơi xác minh Turnstile; rate limit 10 link/phút/IP làm ở WAF hay Lambda; cách tách `/{code}` và `/api/*` trong CloudFront (TV2 nêu CloudFront không có pattern khớp "một đoạn đường dẫn bất kỳ").
* Region: tài khoản Free plan kiểu mới bị cố định Region theo project (project của TV1 là `ap-southeast-2`), nên hello-world được deploy ở đó. Cần thống nhất Region chung cho cả nhóm.

### Câu hỏi còn mở
1. `GET /stats` và `GET /stats/{code}` hiện công khai (ai có mã đều xem được). Có cần giới hạn theo chủ sở hữu không?
2. Link đã xóa trả 404 vì giao diện chưa có trang riêng cho "đã xóa". Có cần trang riêng không?
3. Người dùng có đổi được alias sau khi tạo không? Hiện chưa hỗ trợ.

---

## 8. Tài liệu tham khảo

Thông tin được đối chiếu với tài liệu AWS trong tháng 10/2026. Giá, quota và tính năng có thể thay đổi theo Region, loại tài khoản; trước khi triển khai cần kiểm tra lại tài liệu và trang giá hiện hành.

* [API Gateway – chọn giữa REST API và HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html)
* [API Gateway – pricing](https://aws.amazon.com/api-gateway/pricing/)
* [Lambda – quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
* [Lambda – vòng đời môi trường chạy (cold start, warm start)](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-context.html)
* [Lambda – reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html)
* [Lambda – provisioned concurrency](https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html)
* [Lambda – biến môi trường](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html)
* [DynamoDB – condition expressions (conditional write)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.SpecifyingConditions.html)
* [RFC 9110 – HTTP Semantics, mục 15.4 Redirection 3xx (301, 302, 307, 308)](https://www.rfc-editor.org/rfc/rfc9110.html)
* [OpenAPI Specification 3.0.3](https://spec.openapis.org/oas/v3.0.3)
* [AWS SAM – cài đặt SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
* [AWS CLI – cài đặt](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
* [AWS Account – Region của project (tài khoản Free plan kiểu mới)](https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html)
* [Python – `secrets`](https://docs.python.org/3/library/secrets.html)
* [Python – `ipaddress`](https://docs.python.org/3/library/ipaddress.html)
* [Python – `urllib.parse`](https://docs.python.org/3/library/urllib.parse.html)
* Tài liệu của nhóm: `docs/frontend_research.md`, `docs/gui_wireframe.md` (TV2); `docs/analytics_research.md`, `docs/click_event_schema.json` (TV4)
