<#
.SYNOPSIS
  Quản lý bảng blocklist (TV5) — chặn / gỡ chặn domain và trả link bị gắn cờ về active.
.DESCRIPTION
  Bảng `blocklist` lưu theo domain (khóa HASH = `domain`). Backend tra theo host và các
  domain cha, nên chặn `bad.com` cũng chặn `a.b.bad.com`.

  Hệ thống không có giao diện quản trị; dùng script này để chặn/gỡ link.

.EXAMPLE
  .\scripts\blocklist.ps1 add bad.com -Reason phishing
  .\scripts\blocklist.ps1 add bad.com -Reason phishing -Execute
  .\scripts\blocklist.ps1 remove bad.com
  .\scripts\blocklist.ps1 list
  .\scripts\blocklist.ps1 activate abc1234

.ENVIRONMENT
  BLOCKLIST_TABLE  tên bảng blocklist (mặc định lấy từ output của stack backend)
  URLS_TABLE       tên bảng urls
  AWS_REGION       region của stack backend
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('add', 'remove', 'list', 'activate')]
  [string]$Action,

  [Parameter(Position = 1)]
  [string]$Target,

  [string]$Reason = '',

  [switch]$Execute
)

$ErrorActionPreference = "Stop"

if (-not $Action) {
  Write-Output "Usage: blocklist.ps1 add <domain> [-Reason R] | remove <domain> | list | activate <code> [-Execute]"
  exit 1
}
if ($Action -ne 'list' -and [string]::IsNullOrWhiteSpace($Target)) {
  throw "Thiếu đối số cho $Action."
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  throw "Chưa cài AWS CLI."
}

$region = if ($env:AWS_REGION) { $env:AWS_REGION } else { 'ap-southeast-2' }
$blocklistTable = $env:BLOCKLIST_TABLE
$urlsTable = $env:URLS_TABLE

# Tên bảng: ưu tiên biến môi trường, sau đó tra output của stack backend.
# Stack thật của nhóm là `linkpulse-backend`; `smart-url` là tên stack của tuần 1 nên
# vẫn thử để script chạy được trên cả hai môi trường.
if ([string]::IsNullOrWhiteSpace($blocklistTable) -or [string]::IsNullOrWhiteSpace($urlsTable)) {
  $candidates = @()
  if ($env:STACK_NAME) { $candidates += $env:STACK_NAME }
  $candidates += @('linkpulse-backend', 'smart-url')

  foreach ($stack in $candidates) {
    $outputs = aws cloudformation describe-stacks --stack-name $stack --region $region --query "Stacks[0].Outputs" --output json 2>$null
    if ($LASTEXITCODE -eq 0 -and $outputs) {
      $parsed = $outputs | ConvertFrom-Json
      if ([string]::IsNullOrWhiteSpace($blocklistTable)) {
        $hit = $parsed | Where-Object { $_.OutputKey -eq 'BlocklistTableName' }
        if ($hit) { $blocklistTable = $hit.OutputValue }
      }
    }
    if ([string]::IsNullOrWhiteSpace($urlsTable)) {
      $resource = aws cloudformation list-stack-resources --stack-name $stack --region $region `
        --query "StackResourceSummaries[?LogicalResourceId=='UrlsTable'].PhysicalResourceId" --output text 2>$null
      if ($LASTEXITCODE -eq 0 -and $resource) {
        $first = ($resource -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        if ($first -and $first.Trim() -ne 'None') { $urlsTable = $first.Trim() }
      }
    }
    if (-not [string]::IsNullOrWhiteSpace($blocklistTable)) { break }
  }
}

if ([string]::IsNullOrWhiteSpace($blocklistTable)) {
  throw "Chưa biết tên bảng blocklist. Đặt BLOCKLIST_TABLE=... hoặc STACK_NAME=<tên stack backend>."
}

function Get-NormalizedDomain([string]$value) {
  $d = $value.Trim().ToLowerInvariant()
  if ($d -match '^[a-z][a-z0-9+.-]*://') { $d = $d -replace '^[a-z][a-z0-9+.-]*://', '' }
  $d = $d -replace '/.*$', ''
  $d = $d -replace ':.*$', ''
  $d = $d.Trim('.')
  return $d
}

switch ($Action) {
  'add' {
    $domain = Get-NormalizedDomain $Target
    if ($domain -notmatch '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$') {
      throw "'$Target' không phải tên miền hợp lệ."
    }
    if ([string]::IsNullOrWhiteSpace($blocklistTable)) {
      throw "Chưa biết tên bảng blocklist. Đặt BLOCKLIST_TABLE=... hoặc deploy stack backend trước."
    }
    $addedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    # DynamoDB expression attribute values phải ở dạng JSON typed.
    # Trong PowerShell 5.1 dấu nháy của native command bị bỏ, nên phải escape bằng `\"`.
    # Dựng biến riêng (không nối chuỗi ngay trong argument) để không bị tách thành nhiều tham số.
    $item = '{\"domain\":{\"S\":\"' + $domain + '\"},\"reason\":{\"S\":\"' + $Reason + '\"},\"added_at\":{\"S\":\"' + $addedAt + '\"}}'
    # Bản dễ đọc (dùng cho thông báo), bản escape là bản truyền cho aws CLI.
    $itemReadable = '{ "domain": { "S": "' + $domain + '" }, "reason": { "S": "' + $Reason + '" }, "added_at": { "S": "' + $addedAt + '" } }'

    Write-Output "Đang chặn domain: $domain$(if ($Reason) { " (lý do: $Reason)" })"
    if (-not $Execute) {
      # Hiển thị JSON sạch (không escape) cho dễ copy sang bash.
      Write-Output "[chưa thực thi] aws dynamodb put-item --table-name $blocklistTable --item '$itemReadable' --region $region"
      Write-Output "Thêm -Execute để chạy thật."
      exit 0
    }
    aws dynamodb put-item --table-name $blocklistTable --item $item --region $region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Không chặn được $domain (aws dynamodb put-item thất bại)." }
    Write-Output "Đã chặn $domain."
  }
  'remove' {
    $domain = Get-NormalizedDomain $Target
    if ([string]::IsNullOrWhiteSpace($blocklistTable)) {
      throw "Chưa biết tên bảng blocklist. Đặt BLOCKLIST_TABLE=... hoặc deploy stack backend trước."
    }
    Write-Output "Đang gỡ chặn domain: $domain"
    if (-not $Execute) {
      Write-Output "[chưa thực thi] aws dynamodb delete-item --table-name $blocklistTable --key '{ ""domain"": { ""S"": ""$domain"" } }' --region $region"
      Write-Output "Thêm -Execute để chạy thật."
      exit 0
    }
    $keyJson = '{\"domain\":{\"S\":\"' + $domain + '\"}}'
    aws dynamodb delete-item --table-name $blocklistTable --key $keyJson --region $region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Không gỡ được $domain (aws dynamodb delete-item thất bại)." }
    Write-Output "Đã gỡ chặn $domain."
  }
  'list' {
    if ([string]::IsNullOrWhiteSpace($blocklistTable)) {
      throw "Chưa biết tên bảng blocklist. Đặt BLOCKLIST_TABLE=... hoặc deploy stack backend trước."
    }
    aws dynamodb scan --table-name $blocklistTable --region $region `
      --projection-expression "#d,reason,added_at" --expression-attribute-names '{\"#d\":\"domain\"}' --output json
  }
  'activate' {
    if ([string]::IsNullOrWhiteSpace($urlsTable)) {
      throw "Chưa biết tên bảng urls. Đặt URLS_TABLE=... hoặc deploy stack backend trước."
    }
    Write-Output "Đang đưa link $Target về trạng thái active"
    if (-not $Execute) {
      Write-Output "[chưa thực thi] aws dynamodb update-item --table-name $urlsTable --key {`"short_code`":{`"S`":`"$Target`"}} --update-expression 'SET #s = :a REMOVE flag_reason, flagged_at' --condition-expression 'attribute_exists(short_code)' --region $region"
      Write-Output "Thêm -Execute để chạy thật."
      exit 0
    }
    $keyJson = '{\"short_code\":{\"S\":\"' + $Target + '\"}}'
    $namesJson = '{\"#s\":\"status\"}'
    $valuesJson = '{":a\":{\"S\":\"active\"}}'
    aws dynamodb update-item --table-name $urlsTable `
      --key $keyJson `
      --update-expression "SET #s = :a REMOVE flag_reason, flagged_at" `
      --expression-attribute-names $namesJson `
      --expression-attribute-values $valuesJson `
      --condition-expression "attribute_exists(short_code)" `
      --region $region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Không đưa được $Target về active (aws dynamodb update-item thất bại)." }
    Write-Output "Đã đưa $Target về active."
  }
}
