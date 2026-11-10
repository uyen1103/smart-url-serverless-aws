# LinkPulse — hệ thống rút gọn liên kết thông minh

LinkPulse rút gọn URL, ghi lại lưu lượng truy cập gần thời gian thực và chống lạm dụng. Toàn bộ
hạ tầng chạy trên AWS theo mô hình serverless: không có server, không cần quản lý máy.

| Tính năng | Mô tả |
|---|---|
| Rút gọn link | Đặt alias tùy chọn, hạn dùng, giới hạn số click |
| Phân tích | Số click theo phút/giờ, tỉ lệ bot, xu hướng bất thường |
| Chống lạm dụng | Rate limit, WAF, chặn domain, đánh dấu link đáng ngờ |
| Giao diện | Trang tĩnh trên S3, phân phối qua CloudFront |

## Kiến trúc

```
                        ┌──────────────────────────────┐
   Người dùng ────────► │ CloudFront (+ WAF tùy chọn)   │
                        └──────┬──────────────┬────────┘
                     /api/*, /{code}       tệp tĩnh
                               │              │
                               ▼              ▼
                    ┌─────────────────┐   ┌──────────┐
                    │ API Gateway     │   │ S3       │  giao diện
                    │ (HTTP API)      │   └──────────┘
                    └──────┬──────────┘
                           │
        ┌──────────────────┼──────────────────┬───────────────┐
        ▼                  ▼                  ▼               ▼
    shorten            redirect              links           stats
        │                  │                  │               │
        │                  ├─► urls ◄─────────┘               │
        │                  ├─► rate_limits                    │
        │                  └─► clicks ──► DynamoDB Stream     │
        │                                     │               │
        │                                     ▼               │
        │                          process_clicks ──► stats    │
        │                                     │               │
        │                                     └─► gắn cờ     │
        ├─► blocklist                          link đáng ngờ  │
        └─► Turnstile / Safe Browsing (tùy chọn)              │
                                                            ▼
                                              CloudWatch alarm (DLQ, ngưỡng)
```

Mỗi lần truy cập `/{code}` ghi một item vào bảng `clicks`. DynamoDB Stream kích hoạt `process_clicks`
cộng dồn số liệu theo phút vào bảng `stats`, nên dashboard có dữ liệu sau vài giây mà đường redirect
không phải chờ.

Tài liệu chi tiết: [`docs/architecture.md`](docs/architecture.md), [`docs/threat_model.md`](docs/threat_model.md),
[`docs/security_research.md`](docs/security_research.md).

## Cấu trúc thư mục

| Đường dẫn | Nội dung |
|---|---|
| `backend/` | Lambda, HTTP API, DynamoDB (SAM). Template: `backend/template.yaml` |
| `infra/edge.yaml` | Stack biên: CloudFront, S3 giao diện, WAF (bật/tắt bằng tham số) |
| `frontend/` | Giao diện tĩnh, script nạp lên S3 |
| `database/` | Script tạo bảng DynamoDB và tài liệu schema |
| `scripts/` | Script vận hành: kiểm tra tài khoản, IAM nền tảng, quản lý blocklist, kiểm thử rate limit |
| `terraform/` | AWS Budget |
| `docs/` | Tài liệu kiến trúc, bảo mật, quyết định chung của nhóm |
| `tests/` | Test dùng chung (pytest + moto) |

## Chạy test

Cần Python 3.11. Test dùng `moto` nên không gọi AWS thật và không cần thông tin đăng nhập.

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests -q
```

Lint CloudFormation (không cần AWS):

```bash
cfn-lint backend/template.yaml
cfn-lint infra/edge.yaml
```

Kiểm tra template bằng SAM (chạy tay trên máy có AWS CLI):

```bash
cd backend && sam validate --lint
```

CI chạy tự động `pytest` và `cfn-lint` mỗi khi có pull request: `.github/workflows/ci.yml`.

## Deploy

Toàn bộ hạ tầng nằm trên **một tài khoản AWS chung**. Không ai dùng tài khoản root; mỗi người có
IAM user riêng (`linkpulse-<tên>`) và bắt buộc MFA.

### Bước 0 — Chuẩn bị tài khoản (chỉ làm một lần)

Region workload đã chốt là `ap-southeast-2`. Mọi thành viên chạy:

```bash
aws configure set region ap-southeast-2
```

#### 0.0. Loại tài khoản: bắt buộc là "Sign up for AWS (advanced)"

AWS có hai luồng đăng ký. Nhóm **phải dùng tài khoản advanced**, không dùng tài khoản kiểu
"new" (Builder ID + project):

| Nhu cầu của nhóm | Advanced | Kiểu "new" |
|---|---|---|
| IAM user / group / managed policy tùy chỉnh, bắt buộc MFA | Có | Không |
| AWS WAF gắn với CloudFront (scope CLOUDFRONT, `us-east-1`) | Có | Không |
| Tự chọn Region | Có | Không — bị ghim theo nước |
| AWS Organizations, IAM Access Analyzer | Có | Không |

Lý do kỹ thuật: tài khoản kiểu "new" ghim region theo nước (Việt Nam → `ap-southeast-2`) và chặn
những tính năng tạo tài nguyên ngoài region đó — trong đó có AWS WAF đi kèm CloudFront. Kiến trúc
LinkPulse cần cả WAF+CloudFront lẫn IAM group `linkpulse-devs`, nên tài khoản advanced là bắt buộc.

Nếu tài khoản đã tạo theo kiểu "new", vào AWS Settings → Projects → **Explore advanced features**
để kích hoạt (không hoàn tác được, và phải nâng lên Paid Plan trước).

Về việc đăng ký từ Việt Nam: AWS có hỗ trợ (`VN` thuộc nhóm region `ap-southeast-2`), nhưng bước
xác minh số điện thoại ở một số luồng đăng ký có thể từ chối mã quốc gia `+84`. Khi bị từ chối,
mở support case tại https://support.console.aws.amazon.com/support/home → **Create case** →
Service: *Account and billing* → Category: *Account activation* → Severity: *Urgent business
impacting question* → **Contact us → Chat**, nêu rõ email root user và số điện thoại đã nhập.
AWS có thể kích hoạt thủ công kể cả khi tài khoản chưa kích hoạt được.

#### 0.1. Tạo IAM user quản trị tạm

Cần một user có quyền `iam:*` và `budgets:*` để chạy script cấp quyền. Tạo user tạm, dùng xong
xoá — không dùng key của root.

Trên AWS Console ([IAM Users](https://console.aws.amazon.com/iam/home#/users)):

1. **Create user** → tên `linkpulse-setup` → không bật console access → Next
2. **Permissions** → **Attach policies** → tìm `AdministratorAccess` → **Next**
3. **Tags** → `Key=Project, Value=LinkPulse`, `Key=Owner, Value=tv5` → Next → Create
4. Vào user `linkpulse-setup` → **Security credentials** → **Create access key** → copy key

Nhập vào CLI:

```bash
aws configure
# AWS Access Key ID: AKIA...
# AWS Secret Access Key: ...
# Default region name: ap-southeast-2
# Default output format: json
```

Kiểm tra:

```bash
aws sts get-caller-identity
```

Ra `Account` và `Arn` là được. Nếu báo `Unable to locate credentials` thì key sai hoặc chưa
`aws configure`.

#### 0.2. Kiểm tra tài khoản trước khi làm gì

```bash
./scripts/preflight.sh
```

Trên Windows:

```powershell
.\scripts\preflight.ps1
```

Lệnh này cho biết trước Region nào bị chặn bởi service control policy, CloudFront/WAF có dùng
được không, và budget đã tồn tại chưa — tránh mất thời gian deploy rồi mới biết bị chặn.

#### 0.3. Cấp quyền cho 5 thành viên

Cách gắn email trực tiếp theo từng người, không phải nhớ thứ tự:

```bash
./scripts/setup_aws_foundation.sh \
  --member tv1=kinkit784@gmail.com \
  --member tv2=nguyenuyen2017tn@gmail.com \
  --member tv3=lamvanhau202101@gmail.com \
  --member tv4=yendoan20062020@gmail.com \
  --member tv5=liemnt0773@ut.edu.vn \
  --region ap-southeast-2 --budget 5
```

Trên Windows:

```powershell
.\scripts\setup_aws_foundation.ps1 `
  -Member @("tv1=kinkit784@gmail.com", "tv2=nguyenuyen2017tn@gmail.com", "tv3=lamvanhau202101@gmail.com", "tv4=yendoan20062020@gmail.com", "tv5=liemnt0773@ut.edu.vn") `
  -Region ap-southeast-2 -Budget 5
```

Xem trước thay đổi mà không thực thi: thêm `--dry-run` (bash) hoặc `-DryRun` (PowerShell).

Bảng ánh xạ:

| Thành viên | Module | Email | IAM user | Vai trò |
|---|---|---|---|---|
| Trần Hữu Nam | TV1 Backend | kinkit784@gmail.com | `linkpulse-tv1` | deployer |
| Nguyễn Thảo Uyên | TV2 Frontend | nguyenuyen2017tn@gmail.com | `linkpulse-tv2` | frontend |
| Lâm Văn Hậu | TV3 Database | lamvanhau202101@gmail.com | `linkpulse-tv3` | reader |
| Đoàn Lê Hồng Yến | TV4 Analytics | yendoan20062020@gmail.com | `linkpulse-tv4` | reader |
| Liam Nguyễn | TV5 Security & DevOps | liemnt0773@ut.edu.vn | `linkpulse-tv5` | deployer |

Kiểm tra kết quả:

```bash
aws iam get-group --group-name linkpulse-devs
aws iam list-attached-user-policies --user-name linkpulse-tv1
aws iam list-attached-user-policies --user-name linkpulse-tv3
```

#### 0.4. Xoá user quản trị tạm

```bash
aws iam delete-access-key --user-name linkpulse-setup --access-key-id <ACCESS_KEY_ID>
aws iam detach-user-policy --user-name linkpulse-setup --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam delete-user --user-name linkpulse-setup
```

Sau bước này không còn user nào có `AdministratorAccess` trong nhóm.

#### 0.5. Gửi thông tin cho 5 người

Gửi cho mỗi người một tin nhắn, mẫu:

> Chào bạn, tài khoản AWS chung của nhóm đã sẵn sàng cho bạn.
>
> 1. AWS Console → IAM → Users → `linkpulse-tv<N>` → **Security credentials** → **Assign MFA device**
>    (bắt buộc, chọn TOTP với app Google Authenticator)
> 2. Sau khi bật MFA xong mới tạo **Access key** (Create access key)
> 3. Trên máy chạy:
>    ```
>    aws configure set region ap-southeast-2
>    aws configure
>    ```
> 4. Kiểm tra email budget đã về hộp thư của bạn chưa (kiểm tra cả Spam)

Mỗi người tự bật MFA và tự tạo key của mình — không chia sẻ key.

### Bước 1 — Deploy backend (lần 1)

```bash
cd backend
sam build
sam deploy --guided
```

Nhập `IpHashSalt` (tối thiểu 16 ký tự, giữ kín). Các tham số khác để mặc định. Lấy output
`ApiDomain` để dùng cho bước 2.

### Bước 2 — Deploy lớp biên

Stack edge dùng CloudFront nên phải deploy ở `us-east-1`:

```bash
SECRET=$(openssl rand -hex 24)
aws ssm put-parameter --name /linkpulse/origin-verify --type SecureString --value "$SECRET"

cd backend
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=<ApiDomain> OriginVerifySecret="$SECRET"
```

Lấy output `DistributionDomain`, `FrontendBucketName` và `DistributionId` rồi gửi cho TV1 và TV2.

### Bước 3 — Deploy backend (lần 2)

Bật kiểm tra origin để API chỉ nhận request đi qua CloudFront:

```bash
cd backend
sam deploy --parameter-overrides OriginVerifySecretParam=/linkpulse/origin-verify
```

Kèm các tham số đã nhập ở lần 1. `BaseUrl` đặt thành `https://<DistributionDomain>` và `OwnDomains`
đặt thành `<DistributionDomain>` để chặn vòng lặp redirect.

### Bước 4 — Đưa giao diện lên S3

```bash
cd frontend
S3_BUCKET=<FrontendBucketName> CLOUDFRONT_DISTRIBUTION_ID=<DistributionId> \
  ./deploy.sh --execute --invalidate
```

Trên Windows dùng `deploy.ps1` với tham số `-Bucket`, `-DistributionId`, `-Execute -Invalidate`.

### Bước 5 — Kiểm thử WAF (tùy chọn, có phí)

WAF có phí nên mặc định tắt (`EnableWaf=false`). Chỉ bật khi cần chụp bằng chứng cho báo cáo, rồi
tắt lại ngay:

```bash
cd backend
sam deploy -t ../infra/edge.yaml --region us-east-1 --stack-name linkpulse-edge \
  --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides ApiDomain=<ApiDomain> OriginVerifySecret="$SECRET" EnableWaf=true
```

Kiểm thử xong thì deploy lại với `EnableWaf=false` để xoá Web ACL.

## Quản lý blocklist

Hệ thống không có giao diện quản trị; link bị chặn hoặc gỡ chặn bằng script. Backend tra blocklist
theo host và các domain cha, nên chặn `bad.com` cũng chặn `a.b.bad.com`.

```bash
./scripts/blocklist.sh add bad.com --reason phishing
./scripts/blocklist.sh remove bad.com
./scripts/blocklist.sh list
./scripts/blocklist.sh activate abc1234
```

Trên Windows:

```powershell
.\scripts\blocklist.ps1 add bad.com -Reason phishing
.\scripts\blocklist.ps1 remove bad.com
.\scripts\blocklist.ps1 list
.\scripts\blocklist.ps1 activate abc1234
```

Mặc định script chỉ in lệnh để xem trước. Thêm `--execute` (bash) hoặc `-Execute` (PowerShell) để
chạy thật. Tên bảng được tra tự động từ output của stack backend; đặt `BLOCKLIST_TABLE` và
`URLS_TABLE` nếu cần chỉ định tay.

## Kiểm thử lớp chống lạm dụng

| Script | Công dụng |
|---|---|
| `scripts/test_ratelimit.sh` | Gửi 15 POST `/api/shorten` liên tiếp, in mã trả về + header `Retry-After`, tự xoá link test. Kỳ vọng: 10 request đầu `201`, từ request 11 là `429`. |
| `scripts/test_throttling.py` | Gửi N request song song (thread + `Barrier`) để vượt ngưỡng 10 rps của API Gateway, phân loại 2 lớp `429`, tự xoá link test. |
| `scripts/dyn_urls.sh` | Truy vấn nhanh bảng `urls` (trạng thái link, `flag_reason`). |
| `scripts/render_evidence.py` | Dựng ảnh PNG từ output kiểm thử để dán vào tài liệu. |

```bash
# Lớp rate limit theo IP (10 lần/phút)
bash scripts/test_ratelimit.sh

# Lớp throttling của API Gateway (10 rps, burst 20)
python scripts/test_throttling.py --par 120 --conc 60
```

Trên Windows, chạy script Python với `PYTHONUTF8=1` và `PYTHONIOENCODING=utf-8` để không lỗi
`UnicodeEncodeError` khi in tiếng Việt. Kết quả và ảnh bằng chứng ghi ở
[`docs/security_test_week2.md`](docs/security_test_week2.md).

## Phân công

| Module | Phạm vi | Hạ tầng do module quản lý |
|---|---|---|
| TV1 — Backend | Lambda, HTTP API, DynamoDB, SQS DLQ, CloudWatch | Stack backend (`backend/template.yaml`) |
| TV2 — Frontend | Giao diện tĩnh | Nạp lên S3 của stack edge (`frontend/deploy.sh`) |
| TV3 — Database | Dung lượng, TTL, GSI của DynamoDB | Cấu hình trong `backend/template.yaml` |
| TV4 — Analytics | Pipeline Streams → `process_clicks`, alarm | Kiểm chứng bằng click thật |
| TV5 — Security & DevOps | CloudFront, WAF, SSM, IAM, CI | Stack edge (`infra/edge.yaml`), script IAM, GitHub Actions |

Vai trò trong nhóm:

| Module | Người phụ trách | GitHub |
|---|---|---|
| TV1 — Backend | Trần Hữu Nam | `namth0411-netizen` |
| TV2 — Frontend | Nguyễn Thảo Uyên | `uyen1103` |
| TV3 — Database | Lâm Văn Hậu | `lamvanhau202101-a11y` |
| TV4 — Analytics | Đoàn Lê Hồng Yến | `doanlehongyen` |
| TV5 — Security & DevOps | Liam Nguyễn | `piupear206-oss` |

Tài khoản AWS chung: một tài khoản cho cả nhóm, mỗi người có IAM user riêng theo bảng ở Bước 0.
Quyền theo vai trò: TV1 và TV5 được `PowerUserAccess` cộng quyền tạo IAM role/policy cho SAM và
deploy edge; TV2 chỉ ghi bucket giao diện và tạo invalidation CloudFront; TV3 và TV4 chỉ đọc.

Quyết định chung của nhóm (Region, thứ tự deploy, ngưỡng chống lạm dụng, quyền IAM) nằm ở
[`docs/QUYET_DINH_CHOT_TUAN_2.md`](docs/QUYET_DINH_CHOT_TUAN_2.md). Đóng góp theo
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Link AWS Console

| Việc | Đường dẫn | Region trong console |
|---|---|---|
| Tạo access key | [Security credentials](https://console.aws.amazon.com/iam/home#/security_credentials) | — |
| IAM user, gán quyền, bật MFA | [IAM Users](https://console.aws.amazon.com/iam/home#/users) | — |
| Region cố định của tài khoản | [settings.aws.com](https://settings.aws.com) → mục Project | — |
| CloudFront | [CloudFront distributions](https://console.aws.amazon.com/cloudfront/v4/home) | toàn cục |
| WAF Web ACL | [WAF web ACLs](https://console.aws.amazon.com/wafv2/homev2/web-acls) | **N. Virginia** |
| CloudWatch metrics | [CloudWatch metrics](https://console.aws.amazon.com/cloudwatch/home) → Metrics | `ap-southeast-2` |
| DynamoDB | [DynamoDB tables](https://console.aws.amazon.com/dynamodbv2/home) | `ap-southeast-2` |
| Budget | [Budgets](https://console.aws.amazon.com/billing/home#/budgets) | toàn cục |

CloudFront và WAF luôn nằm ở `us-east-1` (N. Virginia) — đó là lý do stack edge deploy riêng ở
Region đó. Metric của Lambda/DynamoDB thì ở `ap-southeast-2`.

> **Thực tế đã deploy (2026-11-04):** SCP của tổ chức chặn `us-east-1` cho user của nhóm, nên stack
> `linkpulse-edge` đã deploy ở `ap-southeast-2` cùng Region với backend. Vì `EnableWaf=false` và
> không dùng domain riêng thì edge không bắt buộc ở `us-east-1`; chỉ khi bật WAF phạm vi
> `CLOUDFRONT` hoặc dùng certificate ACM riêng thì mới cần quay lại `us-east-1`.
> Chi tiết: [`docs/security_test_week2.md`](docs/security_test_week2.md) mục 0.
