param(
  [string]$Bucket = $env:S3_BUCKET,
  [string]$DistributionId = $env:CLOUDFRONT_DISTRIBUTION_ID,
  [switch]$Execute,
  [switch]$Invalidate
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path

# Kiểm tra tên bucket và distribution trước khi tạo lệnh AWS.
if ([string]::IsNullOrWhiteSpace($Bucket)) {
  throw "Thiếu S3_BUCKET. Hãy truyền -Bucket hoặc đặt biến môi trường S3_BUCKET."
}
if ($Bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
  throw "S3_BUCKET phải là tên bucket S3, không kèm s3:// hoặc dấu /."
}
if ($Invalidate -and [string]::IsNullOrWhiteSpace($DistributionId)) {
  throw "Thiếu CLOUDFRONT_DISTRIBUTION_ID để tạo invalidation."
}
if ($Invalidate -and $DistributionId -notmatch '^[A-Z0-9]+$') {
  throw "CLOUDFRONT_DISTRIBUTION_ID không đúng định dạng."
}

$target = "s3://$Bucket/"
# Giữ prototype và script triển khai ngoài bucket phục vụ giao diện.
$syncArguments = @(
  "s3", "sync", $root, $target,
  "--cache-control", "max-age=300,s-maxage=300",
  "--exclude", "prototype/*",
  "--exclude", "deploy.ps1",
  "--exclude", "deploy.sh"
)
$htmlFiles = @("index.html", "dashboard.html", "links.html", "protection.html", "warning.html", "error.html")
$invalidationPaths = @("/index.html", "/dashboard.html", "/links.html", "/protection.html", "/warning.html", "/error.html", "/css/*", "/js/*", "/mock/*")

if (-not $Execute) {
  Write-Output "Chế độ xem trước; chưa tải file lên. Đích bucket root: $target (dùng bucket riêng cho frontend)"
  Write-Output ("aws " + ($syncArguments -join " "))
  foreach ($file in $htmlFiles) {
    if (Test-Path (Join-Path $root $file)) {
      Write-Output "aws s3 cp `"$root\$file`" `"$target$file`" --cache-control `"max-age=0,no-cache,must-revalidate`" --content-type `"text/html; charset=utf-8`""
    }
  }
  if ($Invalidate) {
    Write-Output "aws cloudfront create-invalidation --distribution-id $DistributionId --paths $($invalidationPaths -join ' ')"
  }
  exit 0
}

# Dừng sớm nếu máy chưa có AWS CLI để tránh deploy nửa chừng.
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  throw "Không tìm thấy AWS CLI. Cài AWS CLI và cấu hình thông tin xác thực trước khi triển khai."
}

& aws @syncArguments
if ($LASTEXITCODE -ne 0) {
  throw "aws s3 sync thất bại với mã lỗi $LASTEXITCODE."
}

foreach ($file in $htmlFiles) {
  $source = Join-Path $root $file
  if (Test-Path $source) {
    & aws s3 cp $source "$target$file" --cache-control "max-age=0,no-cache,must-revalidate" --content-type "text/html; charset=utf-8"
    if ($LASTEXITCODE -ne 0) {
      throw "Không thể cập nhật cache metadata cho $file (mã lỗi $LASTEXITCODE)."
    }
  }
}

if ($Invalidate) {
  & aws cloudfront create-invalidation --distribution-id $DistributionId --paths $invalidationPaths
  if ($LASTEXITCODE -ne 0) {
    throw "CloudFront invalidation thất bại với mã lỗi $LASTEXITCODE."
  }
}
