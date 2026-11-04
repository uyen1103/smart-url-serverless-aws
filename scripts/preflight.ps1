<#
.SYNOPSIS
  preflight.ps1 - kiểm tra tài khoản AWS trước khi deploy (TV5)
.DESCRIPTION
  Mục đích: biết trước những gì sẽ bị chặn trước khi deploy thật.
    1. Xác nhận đang dùng đúng tài khoản AWS chung của nhóm (cảnh báo nếu dùng root).
    2. Kiểm tra Region workload có dùng được không (mặc định ap-southeast-2).
    3. Kiểm tra Region edge (us-east-1) cho CloudFront/WAF.
    4. Kiểm tra quyền CloudFront và WAF phạm vi CLOUDFRONT.
    5. Kiểm tra budget đã tồn tại chưa.
.EXAMPLE
  .\scripts\preflight.ps1
  .\scripts\preflight.ps1 -Region ap-southeast-2 -EdgeRegion us-east-1
#>
[CmdletBinding()]
param(
  [string]$Region = "ap-southeast-2",
  [string]$EdgeRegion = "us-east-1",
  [string]$BudgetName = ""
)

$ErrorActionPreference = "Continue"
$failCount = 0

function Write-Ok([string]$msg) {
  Write-Host "  [OK]   $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
  Write-Host "  [WARN] $msg" -ForegroundColor Yellow
}

function Write-Bad([string]$msg) {
  Write-Host "  [FAIL] $msg" -ForegroundColor Red
  $script:failCount++
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  Write-Error "ERROR: Chưa cài AWS CLI v2."
  exit 1
}

Write-Host "==> 1. Danh tính tài khoản"
$identityRaw = aws sts get-caller-identity --output json 2>&1
if ($LASTEXITCODE -eq 0 -and $identityRaw) {
  $identity = $identityRaw | ConvertFrom-Json
  $accountId = $identity.Account
  $arn = $identity.Arn
  Write-Ok "Account $accountId · $arn"
  if ($arn -like "*:root") {
    Write-Bad "Đang dùng tài khoản root — quy tắc nhóm LinkPulse là không dùng root"
  }
} else {
  Write-Bad "Không gọi được sts get-caller-identity: $identityRaw"
  Write-Host "Chạy 'aws configure' trước." -ForegroundColor Cyan
  exit 1
}

Write-Host "==> 2. Region workload: $Region"
$ec2Out = aws ec2 describe-regions --region $Region --query "Regions[?RegionName=='$Region'].RegionName" --output text 2>&1
if ($LASTEXITCODE -eq 0) {
  if ($ec2Out -match $Region) {
    Write-Ok "Region $Region dùng được"
  } else {
    Write-Warn "Region $Region không trả về trong danh sách — có thể bị hạn chế"
  }
} else {
  Write-Bad "AccessDenied ở $Region — tài khoản Free plan bị ghim Region theo project"
  Write-Host "         Xem Region cố định tại https://settings.aws.com (mục Project) rồi dùng đúng Region đó."
}

Write-Host "==> 3. Region edge: $EdgeRegion (CloudFront/WAF)"
$edgeOut = aws ec2 describe-regions --region $EdgeRegion --query "Regions[?RegionName=='$EdgeRegion'].RegionName" --output text 2>&1
if ($LASTEXITCODE -eq 0) {
  if ($edgeOut -match $EdgeRegion) {
    Write-Ok "Region $EdgeRegion dùng được"
  } else {
    Write-Warn "Region $EdgeRegion không trả về trong danh sách"
  }
} else {
  Write-Bad "AccessDenied ở $EdgeRegion — tài khoản Free plan chặn Region này"
  Write-Host "         Theo quyết định 19: deploy edge ở Region backend và bỏ kiểm thử WAF thật,"
  Write-Host "         trình bày WAF bằng thiết kế + tài liệu. Báo cả nhóm trước khi đổi hướng."
}

Write-Host "==> 4. CloudFront và WAF (scope CLOUDFRONT)"
$cfOut = aws cloudfront list-distributions --max-items 1 --output json 2>&1
if ($LASTEXITCODE -eq 0 -and $cfOut) {
  $cfJson = $cfOut | ConvertFrom-Json
  $cfCount = 0
  if ($cfJson.DistributionList -and $cfJson.DistributionList.Quantity) {
    $cfCount = $cfJson.DistributionList.Quantity
  }
  Write-Ok "Gọi được CloudFront (đang có $cfCount distribution)"
} else {
  Write-Bad "Không gọi được CloudFront: $cfOut"
}

$wafOut = aws wafv2 list-web-acls --scope CLOUDFRONT --region $EdgeRegion --output json 2>&1
if ($LASTEXITCODE -eq 0 -and $wafOut) {
  $wafJson = $wafOut | ConvertFrom-Json
  $wafCount = 0
  if ($wafJson.WebACLs) { $wafCount = $wafJson.WebACLs.Count }
  Write-Ok "Gọi được WAF scope CLOUDFRONT ở $EdgeRegion (đang có $wafCount Web ACL)"
} else {
  Write-Bad ("Không gọi được wafv2 ở " + $EdgeRegion + ": " + $wafOut)
}

Write-Host "==> 5. Budget"
if ([string]::IsNullOrWhiteSpace($BudgetName)) {
  $BudgetName = "linkpulse-monthly-${Region}-5usd"
}
$budgetOut = aws budgets describe-budget --account-id $accountId --budget-name $BudgetName --region us-east-1 --output json 2>&1
if ($LASTEXITCODE -eq 0 -and $budgetOut) {
  $bJson = $budgetOut | ConvertFrom-Json
  $limit = $bJson.Budget.BudgetLimit.Amount
  Write-Ok "Budget '$BudgetName' tồn tại (hạn mức `$$limit)"
} else {
  Write-Warn "Chưa thấy budget '$BudgetName' — chạy scripts/setup_aws_foundation.ps1 hoặc .sh để tạo"
}

Write-Host ""
if ($failCount -eq 0) {
  Write-Host "==> Không có vấn đề chặn deploy. Có thể tiến hành." -ForegroundColor Green
  exit 0
} else {
  Write-Host "==> Có $failCount mục [FAIL]. Xử lý các mục đó hoặc báo cả nhóm trước khi deploy." -ForegroundColor Red
  exit 1
}
