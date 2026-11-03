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
| `scripts/` | Script vận hành: kiểm tra tài khoản, IAM nền tảng, quản lý blocklist |
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

Region workload đã chốt là `ap-southeast-2` (tài khoản Free plan kiểu mới bị AWS ghim Region theo
project; TV1 đã bị chặn ở `ap-southeast-1`). Mọi thành viên chạy:

```bash
aws configure set region ap-southeast-2
```

Kiểm tra tài khoản trước khi làm bất cứ việc gì (chỉ đọc, không tạo tài nguyên):

```bash
./scripts/preflight.sh
```

Lệnh này cho biết trước Region nào bị chặn bởi service control policy, CloudFront/WAF có dùng
được không, và budget đã tồn tại chưa — tránh mất thời gian deploy rồi mới biết bị chặn.

Cấp quyền và tạo IAM user cho từng người:

```bash
./scripts/setup_aws_foundation.sh \
  --members "tv1,tv2,tv3,tv4,tv5" \
  --emails "kinkit784@gmail.com,nguyenuyen2017tn@gmail.com,lamvanhau202101@gmail.com,yendoan20062020@gmail.com,liemnt0773@ut.edu.vn" \
  --region ap-southeast-2 --budget 5
```

Thứ tự email phải khớp thứ tự `--members`. Bảng ánh xạ:

| Thành viên | Module | Email | IAM user | Vai trò |
|---|---|---|---|---|
| Trần Hữu Nam | TV1 Backend | kinkit784@gmail.com | `linkpulse-tv1` | deployer |
| Nguyễn Thảo Uyên | TV2 Frontend | nguyenuyen2017tn@gmail.com | `linkpulse-tv2` | frontend |
| Lâm Văn Hậu | TV3 Database | lamvanhau202101@gmail.com | `linkpulse-tv3` | reader |
| Đoàn Lê Hồng Yến | TV4 Analytics | yendoan20062020@gmail.com | `linkpulse-tv4` | reader |
| Liam Nguyễn | TV5 Security & DevOps | liemnt0773@ut.edu.vn | `linkpulse-tv5` | deployer |

Xem trước thay đổi mà không thực thi: thêm `--dry-run`.

Sau đó mừng thành viên tự bật MFA và tự tạo access key của mình.

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
