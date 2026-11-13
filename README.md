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

Toàn bộ hạ tầng nằm trên **một tài khoản AWS chung** của nhóm. Năm thành viên cùng được thêm vào
project **"Do the Thing"** của tài khoản này. Không dùng root user cho việc thường ngày.

### Bước 0 — Chuẩn bị tài khoản (chỉ làm một lần)

Region workload đã chốt là `ap-southeast-2`. Mọi thành viên chạy:

```bash
aws configure set region ap-southeast-2
```

#### 0.0. Tài khoản AWS của nhóm

Nhóm dùng một tài khoản AWS chung (gói free plan có credit), năm thành viên được thêm vào project
"Do the Thing" để vào AWS Console. Region workload là `ap-southeast-2`.

Các việc nhóm đã làm trên tài khoản này đều nằm trong credit: chi phí tháng hiện tại khoảng 0,05 USD
(kiểm tra ngày 2026-11-13). Ngân sách cảnh báo 5 USD/tháng đã được tạo bằng `terraform/`.

Về cấp quyền IAM từng người: script `scripts/setup_aws_foundation.sh` và `.ps1` có sẵn trong repo nhưng
nhóm **chưa chạy được** vì user đang dùng không có `iam:*` (xem mục 0.3 và bằng chứng ở
[`docs/security_test_week2.md`](docs/security_test_week2.md) mục 0.4). Trong thời gian đó nhóm dùng
một IAM user dùng chung để chạy AWS CLI.

#### 0.1. Kiểm tra đăng nhập CLI

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
`aws configure`. Không chia sẻ access key qua tin nhắn nhóm và không commit key lên repo.

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

#### 0.3. Cấp quyền IAM từng người (tùy chọn, cần IAM admin)

Chỉ làm khi có một user hoặc root có quyền `iam:*` và `budgets:*`. Script dừng ngay ở bước
preflight nếu thiếu quyền và liệt kê đúng các action cần cấp.

```bash
./scripts/setup_aws_foundation.sh \
  --member tv1=<email-tv1> \
  --member tv2=<email-tv2> \
  --member tv3=<email-tv3> \
  --member tv4=<email-tv4> \
  --member tv5=<email-tv5> \
  --region ap-southeast-2 --budget 5
```

Trên Windows:

```powershell
.\scripts\setup_aws_foundation.ps1 `
  -Member @("tv1=<email-tv1>", "tv2=<email-tv2>", "tv3=<email-tv3>", "tv4=<email-tv4>", "tv5=<email-tv5>") `
  -Region ap-southeast-2 -Budget 5
```

Xem trước thay đổi mà không thực thi: thêm `--dry-run` (bash) hoặc `-DryRun` (PowerShell).

Muốn user IAM đăng nhập được console thì thêm `--console-password "<mật-khẩu>"` (bash) hoặc
`-ConsolePassword "<mật-khẩu>"` (PowerShell). Mật khẩu phải khớp password policy của tài khoản:
**≥ 14 ký tự, có chữ hoa + chữ thường + số + ký hiệu**. Không ghi mật khẩu vào repo.

Quyền theo vai trò khi script chạy được: TV1 và TV5 là `deployer`, TV2 là `frontend`, TV3 và TV4 là
`reader`. Kiểm tra kết quả:

```bash
aws iam get-group --group-name linkpulse-devs
aws iam list-attached-user-policies --user-name linkpulse-tv1
```

Bằng chứng chạy thật: [`docs/security_test_week2.md`](docs/security_test_week2.md) mục 0.4.

### Bước 1 — Deploy backend (lần 1)

```bash
cd backend
sam build
sam deploy --guided
```

Nhập `IpHashSalt` (tối thiểu 16 ký tự, giữ kín). Các tham số khác để mặc định. Lấy output
`ApiDomain` để dùng cho bước 2.

### Bước 2 — Deploy lớp biên

Stack edge dùng CloudFront. Theo mặc định deploy ở `us-east-1`:

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

### Ảnh bằng chứng trên AWS Console

Một số bằng chứng cần ảnh chụp từ AWS Console. Thành viên đăng nhập console qua project
"Do the Thing" (IAM user dùng chung cho CLI không có `LoginProfile`, nên không đăng nhập console
bằng user đó).

| Bằng chứng | Đường dẫn console | File ảnh |
|---|---|---|
| Chi phí | Billing and Cost Management → Cost Explorer | `docs/screenshots/aws/lan3/09-cost-explorer-console.png` |

Các ảnh còn lại (`01`–`08`) dựng từ output thật của AWS CLI bằng `scripts/render_evidence.py`.

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

Tài khoản AWS chung: một tài khoản cho cả nhóm, năm thành viên cùng được thêm vào project
"Do the Thing". Phân quyền IAM theo vai trò (TV1 và TV5 `deployer`, TV2 `frontend`, TV3 và TV4
`reader`) đã được viết sẵn trong `scripts/setup_aws_foundation.*` nhưng chưa chạy được vì thiếu
quyền `iam:*`; xem mục 0.3.

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