<#
.SYNOPSIS
  setup_aws_foundation.ps1 — Dựng nền tảng nhóm LinkPulse trên Windows (TV5)
.DESCRIPTION
  Mục đích:
    1. Tạo IAM user cho từng thành viên, bắt buộc MFA.
    2. Cấp quyền theo vai trò (quyết định #17 trong docs/QUYET_DINH_CHOT_TUAN_2.md):
         - deployer (TV1, TV5): PowerUserAccess + quyền SAM (IAM roles/policies) + CloudFront/SSM/WAF/CloudWatch alarm.
         - frontend (TV2): ghi bucket giao diện + invalidation CloudFront.
         - reader (TV3, TV4): đọc tài nguyên, DynamoDB và CloudWatch.
    3. Đặt password policy cho tài khoản.
    4. Tạo AWS Budget $5/tháng (forecasted 80% + actual 100%) lọc theo region workload.
.EXAMPLE
  .\scripts\setup_aws_foundation.ps1 `
      -Member @("tv1=kinkit784@gmail.com", "tv2=nguyenuyen2017tn@gmail.com", "tv3=lamvanhau202101@gmail.com", "tv4=yendoan20062020@gmail.com", "tv5=liemnt0773@ut.edu.vn") `
      -Region ap-southeast-2 -Budget 5
#>
[CmdletBinding()]
param(
  [string[]]$Member,
  [string]$Members = "",
  [string]$Emails = "",
  [string]$Roles = "",
  [string]$Region = "ap-southeast-2",
  [string]$EdgeRegion = "us-east-1",
  [int]$Budget = 5,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Log-Info([string]$msg) {
  Write-Host "==> $msg" -ForegroundColor Cyan
}

function Invoke-Run([string]$cmd) {
  if ($DryRun) {
    Write-Host "[dry-run] $cmd" -ForegroundColor Gray
  } else {
    Invoke-Expression $cmd
  }
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  Write-Error "ERROR: Chưa cài AWS CLI v2."
  exit 1
}

$memberArr = @()
$emailArr = @()

if ($Member -and $Member.Count -gt 0) {
  foreach ($item in $Member) {
    if ($item -match '^([^=]+)=(.+)$') {
      $memberArr += $Matches[1].Trim()
      $emailArr += $Matches[2].Trim()
    } else {
      Write-Error "ERROR: -Member cần dạng ten=email, nhận '$item'"
      exit 1
    }
  }
} elseif ($Members -and $Emails) {
  $memberArr = $Members.Split(',') | ForEach-Object { $_.Trim() }
  $emailArr = $Emails.Split(',') | ForEach-Object { $_.Trim() }
} else {
  Write-Error "ERROR: Cần cung cấp -Member tv1=email... hoặc -Members và -Emails."
  exit 1
}

if ($memberArr.Count -ne $emailArr.Count) {
  Write-Error "ERROR: Số lượng thành viên ($($memberArr.Count)) khác số lượng email ($($emailArr.Count))."
  exit 1
}

function Get-DefaultRole([string]$m) {
  switch ($m.ToLowerInvariant()) {
    { $_ -in 'tv1', 'tv5' } { return "deployer" }
    'tv2'                  { return "frontend" }
    { $_ -in 'tv3', 'tv4' } { return "reader" }
    default                { return "reader" }
  }
}

$roleMap = @{}
$roleOverrides = @{}
if ($Roles) {
  foreach ($r in $Roles.Split(',')) {
    if ($r -match '^([^=]+)=(.+)$') {
      $roleOverrides[$Matches[1].Trim().ToLowerInvariant()] = $Matches[2].Trim()
    }
  }
}

for ($i = 0; $i -lt $memberArr.Count; $i++) {
  $m = $memberArr[$i].ToLowerInvariant()
  if ($roleOverrides.ContainsKey($m)) {
    $roleMap[$m] = $roleOverrides[$m]
  } else {
    $roleMap[$m] = Get-DefaultRole $m
  }
}

$accountId = aws sts get-caller-identity --query Account --output text
Log-Info "Account: $accountId | Region workload: $Region | Region edge: $EdgeRegion | Budget: `$$Budget/mo"

$tempDir = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "linkpulse-setup-" + [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
  $group = "linkpulse-devs"
  $policyMfa = "LinkPulse-EnforceMFA"
  $policyDeployer = "LinkPulse-Deployer"
  $policyFrontend = "LinkPulse-FrontendDeploy"
  $policyReader = "LinkPulse-ReadOnly"

  Log-Info "Tạo group $group (nếu chưa có)"
  $null = aws iam get-group --group-name $group 2>$null
  if ($LASTEXITCODE -ne 0) {
    Invoke-Run "aws iam create-group --group-name $group"
  }

  $oldPolicyArn = "arn:aws:iam::${accountId}:policy/LinkPulse-DevLeastPrivilege"
  $null = aws iam get-policy --policy-arn $oldPolicyArn 2>$null
  if ($LASTEXITCODE -eq 0) {
    Log-Info "Gỡ policy cũ LinkPulse-DevLeastPrivilege khỏi group $group"
    Invoke-Run "aws iam detach-group-policy --group-name $group --policy-arn $oldPolicyArn"
  }

  # 1a. MFA Policy
  Log-Info "Tạo/cập nhật policy bắt buộc MFA: $policyMfa"
  $mfaJsonPath = Join-Path $tempDir "mfa-policy.json"
  @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowViewAccountInfo",
      "Effect": "Allow",
      "Action": ["iam:ListUsers", "iam:ListVirtualMFADevices"],
      "Resource": "*"
    },
    {
      "Sid": "AllowManageOwnMFA",
      "Effect": "Allow",
      "Action": [
        "iam:CreateVirtualMFADevice", "iam:EnableMFADevice",
        "iam:ResyncMFADevice", "iam:DeleteVirtualMFADevice",
        "iam:ListMFADevices", "iam:ChangePassword",
        "iam:GetUser", "iam:ListGroupsForUser"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyAllExceptListedIfNoMFA",
      "Effect": "Deny",
      "NotAction": [
        "iam:CreateVirtualMFADevice", "iam:EnableMFADevice",
        "iam:ResyncMFADevice", "iam:DeleteVirtualMFADevice",
        "iam:ListMFADevices", "iam:ChangePassword",
        "iam:GetUser", "iam:ListGroupsForUser",
        "iam:ListUsers", "iam:ListVirtualMFADevices",
        "sts:GetSessionToken"
      ],
      "Resource": "*",
      "Condition": { "BoolIfExists": { "aws:MultiFactorAuthPresent": "false" } }
    }
  ]
}
'@ | Out-File -FilePath $mfaJsonPath -Encoding utf8

  $mfaArn = "arn:aws:iam::${accountId}:policy/$policyMfa"
  $null = aws iam get-policy --policy-arn $mfaArn 2>$null
  if ($LASTEXITCODE -eq 0) {
    Invoke-Run "aws iam create-policy-version --policy-arn $mfaArn --policy-document file://$mfaJsonPath --set-as-default"
  } else {
    Invoke-Run "aws iam create-policy --policy-name $policyMfa --policy-document file://$mfaJsonPath --description 'TV5: bat buoc MFA cho moi thanh vien'"
  }

  # 1b. Deployer Policy
  Log-Info "Tạo/cập nhật policy deployer: $policyDeployer"
  $deployerJsonPath = Join-Path $tempDir "deployer-policy.json"
  @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SamIamRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
        "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy",
        "iam:GetRolePolicy", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:ListRoleTags",
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::${accountId}:role/linkpulse-*",
        "arn:aws:iam::${accountId}:role/smart-url*",
        "arn:aws:iam::${accountId}:role/stack-*"
      ]
    },
    {
      "Sid": "SamIamPolicies",
      "Effect": "Allow",
      "Action": [
        "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy",
        "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
        "iam:DeletePolicyVersion", "iam:GetPolicyVersion", "iam:ListPolicyVersions",
        "iam:TagPolicy", "iam:UntagPolicy",
        "iam:AttachPolicy", "iam:DetachPolicy", "iam:ListAttachedPolicies"
      ],
      "Resource": [
        "arn:aws:iam::${accountId}:policy/linkpulse-*",
        "arn:aws:iam::${accountId}:policy/smart-url*"
      ]
    },
    {
      "Sid": "EdgeServices",
      "Effect": "Allow",
      "Action": [
        "cloudfront:CreateDistribution", "cloudfront:UpdateDistribution",
        "cloudfront:DeleteDistribution", "cloudfront:GetDistribution",
        "cloudfront:ListDistributions", "cloudfront:CreateInvalidation",
        "cloudfront:GetInvalidation", "cloudfront:ListInvalidations",
        "cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl",
        "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl",
        "cloudfront:ListOriginAccessControls",
        "cloudfront:CreateCachePolicy", "cloudfront:GetCachePolicy",
        "cloudfront:UpdateCachePolicy", "cloudfront:DeleteCachePolicy",
        "cloudfront:ListCachePolicies",
        "cloudfront:CreateOriginRequestPolicy", "cloudfront:GetOriginRequestPolicy",
        "cloudfront:UpdateOriginRequestPolicy", "cloudfront:DeleteOriginRequestPolicy",
        "cloudfront:ListOriginRequestPolicies",
        "cloudfront:CreateResponseHeadersPolicy", "cloudfront:GetResponseHeadersPolicy",
        "cloudfront:UpdateResponseHeadersPolicy", "cloudfront:DeleteResponseHeadersPolicy",
        "cloudfront:ListResponseHeadersPolicies",
        "cloudfront:CreateFunction", "cloudfront:GetFunction",
        "cloudfront:UpdateFunction", "cloudfront:DeleteFunction",
        "cloudfront:ListFunctions", "cloudfront:PublishFunction",
        "wafv2:CreateWebACL", "wafv2:GetWebACL", "wafv2:UpdateWebACL",
        "wafv2:DeleteWebACL", "wafv2:ListWebACLs",
        "wafv2:CreateWebACLAssociation", "wafv2:GetWebACLAssociation",
        "wafv2:DeleteWebACLAssociation",
        "wafv2:ListWebACLAssociationForResource",
        "wafv2:CreateLoggingConfiguration", "wafv2:GetLoggingConfiguration",
        "wafv2:DeleteLoggingConfiguration", "wafv2:ListLoggingConfigurations",
        "acm:DescribeCertificate", "acm:ListCertificates",
        "ssm:GetParameter", "ssm:GetParameters", "ssm:PutParameter",
        "ssm:DeleteParameter", "ssm:GetParametersByPath",
        "kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey",
        "secretsmanager:GetSecretValue", "secretsmanager:CreateSecret",
        "secretsmanager:DeleteSecret", "secretsmanager:DescribeSecret",
        "sqs:CreateQueue", "sqs:DeleteQueue", "sqs:GetQueueAttributes",
        "sqs:SetQueueAttributes", "sqs:SendMessage", "sqs:ReceiveMessage",
        "sqs:DeleteMessage", "sqs:PurgeQueue", "sqs:ListQueues",
        "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms",
        "cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory",
        "logs:CreateLogGroup", "logs:PutRetentionPolicy",
        "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy", "s3:GetBucketPolicy", "s3:GetBucketLocation",
        "s3:PutBucketWebsite", "s3:GetBucketWebsite",
        "s3:PutLifecycleConfiguration", "s3:GetLifecycleConfiguration"
      ],
      "Resource": "*",
      "Condition": {
        "StringLike": { "aws:RequestedRegion": ["$Region", "$EdgeRegion"] }
      }
    },
    {
      "Sid": "BudgetsReadOnly",
      "Effect": "Allow",
      "Action": ["budgets:ViewBudget", "budgets:Describe*"],
      "Resource": "*"
    }
  ]
}
"@ | Out-File -FilePath $deployerJsonPath -Encoding utf8

  $deployerArn = "arn:aws:iam::${accountId}:policy/$policyDeployer"
  $null = aws iam get-policy --policy-arn $deployerArn 2>$null
  if ($LASTEXITCODE -eq 0) {
    Invoke-Run "aws iam create-policy-version --policy-arn $deployerArn --policy-document file://$deployerJsonPath --set-as-default"
  } else {
    Invoke-Run "aws iam create-policy --policy-name $policyDeployer --policy-document file://$deployerJsonPath --description 'TV5: quyen deploy backend va edge (TV1, TV5)'"
  }
  $powerUserArn = "arn:aws:iam::aws:policy/PowerUserAccess"

  # 1c. Frontend Policy
  Log-Info "Tạo/cập nhật policy frontend: $policyFrontend"
  $frontendJsonPath = Join-Path $tempDir "frontend-policy.json"
  @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteFrontendBucket",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject", "s3:DeleteObject", "s3:GetObject",
        "s3:ListBucket", "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::linkpulse-*",
        "arn:aws:s3:::linkpulse-*/*"
      ]
    },
    {
      "Sid": "InvalidateCloudFront",
      "Effect": "Allow",
      "Action": [
        "cloudfront:CreateInvalidation", "cloudfront:GetInvalidation",
        "cloudfront:ListInvalidations", "cloudfront:GetDistribution",
        "cloudfront:ListDistributions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ReadOwnLogs",
      "Effect": "Allow",
      "Action": [
        "logs:Describe*", "logs:FilterLogEvents", "logs:GetLogEvents",
        "cloudwatch:Get*", "cloudwatch:List*", "cloudwatch:Describe*"
      ],
      "Resource": "*"
    }
  ]
}
'@ | Out-File -FilePath $frontendJsonPath -Encoding utf8

  $frontendArn = "arn:aws:iam::${accountId}:policy/$policyFrontend"
  $null = aws iam get-policy --policy-arn $frontendArn 2>$null
  if ($LASTEXITCODE -eq 0) {
    Invoke-Run "aws iam create-policy-version --policy-arn $frontendArn --policy-document file://$frontendJsonPath --set-as-default"
  } else {
    Invoke-Run "aws iam create-policy --policy-name $policyFrontend --policy-document file://$frontendJsonPath --description 'TV5: quyen deploy giao dien (TV2)'"
  }

  # 1d. Reader Policy
  Log-Info "Tạo/cập nhật policy reader: $policyReader"
  $readerJsonPath = Join-Path $tempDir "reader-policy.json"
  @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadEverything",
      "Effect": "Allow",
      "Action": [
        "iam:Get*", "iam:List*", "sts:GetCallerIdentity",
        "cloudformation:Describe*", "cloudformation:List*", "cloudformation:Get*",
        "lambda:Get*", "lambda:List*",
        "apigateway:GET",
        "dynamodb:Describe*", "dynamodb:List*",
        "dynamodb:GetItem", "dynamodb:BatchGetItem",
        "dynamodb:Query", "dynamodb:Scan",
        "s3:ListAllMyBuckets", "s3:ListBucket", "s3:GetObject",
        "logs:Describe*", "logs:FilterLogEvents", "logs:GetLogEvents",
        "cloudwatch:Get*", "cloudwatch:List*", "cloudwatch:Describe*",
        "cloudfront:List*", "cloudfront:Get*",
        "wafv2:List*", "wafv2:Get*",
        "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath",
        "sqs:GetQueueAttributes", "sqs:ListQueues",
        "budgets:ViewBudget", "budgets:Describe*"
      ],
      "Resource": "*"
    }
  ]
}
'@ | Out-File -FilePath $readerJsonPath -Encoding utf8

  $readerArn = "arn:aws:iam::${accountId}:policy/$policyReader"
  $null = aws iam get-policy --policy-arn $readerArn 2>$null
  if ($LASTEXITCODE -eq 0) {
    Invoke-Run "aws iam create-policy-version --policy-arn $readerArn --policy-document file://$readerJsonPath --set-as-default"
  } else {
    Invoke-Run "aws iam create-policy --policy-name $policyReader --policy-document file://$readerJsonPath --description 'TV5: quyen doc de kiem chung (TV3, TV4)'"
  }

  # 1e. Users & Role assignments
  Log-Info "Tạo IAM user cho $($memberArr.Count) thành viên và gán quyền theo vai trò"
  for ($i = 0; $i -lt $memberArr.Count; $i++) {
    $m = $memberArr[$i].ToLowerInvariant()
    $email = $emailArr[$i]
    $role = $roleMap[$m]
    $user = "linkpulse-$m"

    $null = aws iam get-user --user-name $user 2>$null
    if ($LASTEXITCODE -eq 0) {
      Log-Info "  - $user đã tồn tại, giữ nguyên"
    } else {
      Invoke-Run "aws iam create-user --user-name $user --tags Key=Project,Value=LinkPulse Key=Owner,Value=$m"
    }

    Invoke-Run "aws iam add-user-to-group --user-name $user --group-name $group"
    Invoke-Run "aws iam attach-user-policy --user-name $user --policy-arn $mfaArn"

    switch ($role) {
      'deployer' {
        Invoke-Run "aws iam attach-user-policy --user-name $user --policy-arn $powerUserArn"
        Invoke-Run "aws iam attach-user-policy --user-name $user --policy-arn $deployerArn"
      }
      'frontend' {
        Invoke-Run "aws iam attach-user-policy --user-name $user --policy-arn $frontendArn"
      }
      'reader' {
        Invoke-Run "aws iam attach-user-policy --user-name $user --policy-arn $readerArn"
      }
      default {
        Write-Error "ERROR: Vai trò lạ '$role' cho $m"
        exit 1
      }
    }
    Log-Info "  - $user ($email): vai trò $role"
  }

  # 1f. Password policy
  Log-Info "Đặt password policy (tối thiểu 14 ký tự, xoay 90 ngày, chống dùng lại)"
  Invoke-Run "aws iam update-account-password-policy --minimum-password-length 14 --require-symbols --require-numbers --require-uppercase-characters --require-lowercase-characters --allow-users-to-change-password --max-password-age 90 --password-reuse-prevention 5"

  # 2. AWS Budgets ($5/mo)
  Log-Info "Tạo AWS Budgets (endpoint us-east-1, lọc Region=$Region)"
  $budgetName = "linkpulse-monthly-${Region}-${Budget}usd"
  $subscribers = @()
  foreach ($email in $emailArr) {
    $subscribers += @{
      SubscriptionType = "EMAIL"
      Address = $email
    }
  }

  $notifications = @(
    @{
      Notification = @{
        NotificationType = "FORECASTED"
        ComparisonOperator = "GREATER_THAN"
        Threshold = 80
        ThresholdType = "PERCENTAGE"
      }
      Subscribers = $subscribers
    },
    @{
      Notification = @{
        NotificationType = "ACTUAL"
        ComparisonOperator = "GREATER_THAN"
        Threshold = 100
        ThresholdType = "PERCENTAGE"
      }
      Subscribers = $subscribers
    }
  )

  $budgetObj = @{
    BudgetName = $budgetName
    BudgetLimit = @{ Amount = "$Budget"; Unit = "USD" }
    CostFilters = @{ Region = @($Region) }
    CostTypes = @{ IncludeTax = $true; IncludeSubscription = $true; UseBlended = $false }
    TimeUnit = "MONTHLY"
    BudgetType = "COST"
  }

  $budgetJsonPath = Join-Path $tempDir "budget.json"
  $notifsJsonPath = Join-Path $tempDir "notifs.json"
  $budgetObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $budgetJsonPath -Encoding utf8
  $notifications | ConvertTo-Json -Depth 5 | Out-File -FilePath $notifsJsonPath -Encoding utf8

  $null = aws budgets describe-budget --account-id $accountId --budget-name $budgetName --region us-east-1 2>$null
  if ($LASTEXITCODE -eq 0) {
    Invoke-Run "aws budgets update-budget --account-id $accountId --new-budget file://$budgetJsonPath --region us-east-1"
  } else {
    Invoke-Run "aws budgets create-budget --account-id $accountId --budget file://$budgetJsonPath --notifications-with-subscribers file://$notifsJsonPath --region us-east-1"
  }

  Log-Info "Hoàn thành khởi tạo nền tảng IAM và Budget."
  Write-Host "Việc còn lại của từng thành viên:" -ForegroundColor Yellow
  Write-Host "  1) Đăng nhập IAM user linkpulse-<ten>, bật Virtual MFA:"
  Write-Host "     IAM console > Users > linkpulse-<ten> > Security credentials > Assign MFA device"
  Write-Host "  2) Sau khi có MFA mới tự tạo Access Key."
  Write-Host "  3) aws configure set region $Region"
  Write-Host "  4) Kiểm tra budget mail đã về hộp thư (kiểm tra cả Spam)."
} finally {
  Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
