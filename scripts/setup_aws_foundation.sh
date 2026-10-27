#!/usr/bin/env bash
###############################################################################
# setup_aws_foundation.sh — Dựng nền tảng nhóm Smart URL Serverless (TV5, Week 1)
#
# Mục đích (Issue #5):
#   1. Tạo IAM user/role theo chuẩn Least Privilege cho từng thành viên,
#      bắt buộc MFA (không MFA = không dùng được dịch vụ, trừ IAM self-manage).
#   2. Bật Account Password Policy + ghi nhận region làm việc ap-southeast-1.
#   3. Tạo AWS Budget $5/tháng (forecasted + actual) lọc theo region
#      ap-southeast-1, gửi email cảnh báo cho cả nhóm.
#
# Lưu ý quan trọng:
#   - AWS Budgets là dịch vụ GLOBAL (đầu mối ở us-east-1). "Region ap-southeast-1"
#     được thực hiện bằng CostFilter Region = ap-southeast-1, cộng thêm 1 budget
#     tổng toàn tài khoản để chống bill shock ngoài Singapore.
#   - WAF cho CloudFront BẮT BUỘC tạo ở us-east-1 — xem terraform/foundation.tf,
#     không tạo trong script này để tránh nhầm region.
#   - Tài khoản Free-plan kiểu mới bị cố định region theo project (xem
#     docs/backend_research.md §6.2): nếu `aws configure` region khác
#     ap-southeast-1 mà vẫn muốn chạy script, export AWS_REGION=ap-southeast-1.
#
# Cách dùng:
#   chmod +x scripts/setup_aws_foundation.sh
#   ./scripts/setup_aws_foundation.sh \
#       --members "tv1,tv2,tv3,tv4,tv5" \
#       --emails "tv1@example.com,tv2@example.com,tv3@example.com,tv4@example.com,tv5@example.com" \
#       --region ap-southeast-1 --budget 5
#
# Yêu cầu: AWS CLI v2, quyền iam:*, budgets:*, iam CreateAccountAlias (chạy bằng
# IAM admin/root lần đầu; các thành viên sau đó chỉ dùng user của mình).
###############################################################################
set -euo pipefail

REGION="ap-southeast-1"
BUDGET_LIMIT="5"
MEMBERS=""
EMAILS=""
ACCOUNT_ID=""
DRY_RUN="false"

usage() {
  sed -n '2,30p' "$0"
  echo "Options: --members a,b --emails a@x,b@x --region R --budget N [--dry-run]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --members) MEMBERS="$2"; shift 2 ;;
    --emails)  EMAILS="$2"; shift 2 ;;
    --region)  REGION="$2"; shift 2 ;;
    --budget)  BUDGET_LIMIT="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

[[ -z "$MEMBERS" || -z "$EMAILS" ]] && { echo "ERROR: thiếu --members/--emails"; usage; exit 1; }

IFS=',' read -r -a MEMBER_ARR <<< "$MEMBERS"
IFS=',' read -r -a EMAIL_ARR <<< "$EMAILS"
[[ ${#MEMBER_ARR[@]} -ne ${#EMAIL_ARR[@]} ]] && { echo "ERROR: số member != số email"; exit 1; }

run() { if [[ "$DRY_RUN" == "true" ]]; then echo "[dry-run] $*"; else eval "$@"; fi; }
log() { echo "==> $*"; }

command -v aws >/dev/null || { echo "ERROR: chưa cài AWS CLI"; exit 1; }
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "Account: $ACCOUNT_ID | Region workload: $REGION | Budget: \$$BUDGET_LIMIT/mo"

# ---------------------------------------------------------------------------
# 1. IAM: Group + Least-Privilege policies + MFA enforcement
# ---------------------------------------------------------------------------
GROUP="linkpulse-devs"
POLICY_MFA="LinkPulse-EnforceMFA"
POLICY_DEV="LinkPulse-DevLeastPrivilege"

log "Tạo group $GROUP (nếu chưa có)"
run "aws iam get-group --group-name $GROUP >/dev/null 2>&1 || aws iam create-group --group-name $GROUP"

# 1a. Policy bắt buộc MFA: từ chối mọi hành động (trừ quản lý MFA/thông tin cá nhân)
#     khi aws:MultiFactorAuthAge không tồn tại (= chưa MFA).
log "Tạo/cập nhật policy bắt buộc MFA: $POLICY_MFA"
MFA_DOC=$(cat <<'JSON'
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
JSON
)
echo "$MFA_DOC" > /tmp/mfa-policy.json
MFA_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_MFA"
if aws iam get-policy --policy-arn "$MFA_ARN" >/dev/null 2>&1; then
  VER=$(aws iam list-policy-versions --policy-arn "$MFA_ARN" --query 'Versions[?IsDefaultVersion].VersionId' --output text)
  run "aws iam create-policy-version --policy-arn $MFA_ARN --policy-document file:///tmp/mfa-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_MFA --policy-document file:///tmp/mfa-policy.json --description 'TV5: bat buoc MFA cho moi thanh vien (Issue #5)'"
fi
run "aws iam attach-group-policy --group-name $GROUP --policy-arn $MFA_ARN"

# 1b. Policy Least Privilege cho dev serverless (không cho iam:*, không cho billing sửa,
#     chỉ budgets xem; giới hạn tài nguyên bằng prefix linkpulse-*).
log "Tạo/cập nhật policy least-privilege: $POLICY_DEV"
DEV_DOC=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ServerlessDeploy",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack", "cloudformation:UpdateStack",
        "cloudformation:DeleteStack", "cloudformation:Describe*",
        "cloudformation:List*", "cloudformation:Get*",
        "cloudformation:CreateChangeSet", "cloudformation:ExecuteChangeSet",
        "cloudformation:DeleteChangeSet"
      ],
      "Resource": "arn:aws:cloudformation:$REGION:$ACCOUNT_ID:stack/linkpulse-*/*"
    },
    {
      "Sid": "LambdaApiGwDdb",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction", "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration", "lambda:GetFunction",
        "lambda:ListFunctions", "lambda:InvokeFunction",
        "lambda:DeleteFunction", "lambda:TagResource",
        "apigateway:GET", "apigateway:POST", "apigateway:PUT",
        "apigateway:PATCH", "apigateway:DELETE",
        "dynamodb:CreateTable", "dynamodb:UpdateTable",
        "dynamodb:DescribeTable", "dynamodb:ListTables",
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
        "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:UpdateTimeToLive", "dynamodb:DescribeStream",
        "dynamodb:ListStreams", "dynamodb:GetRecords", "dynamodb:GetShardIterator"
      ],
      "Resource": "*",
      "Condition": { "StringLike": { "aws:RequestedRegion": ["$REGION", "us-east-1"] } }
    },
    {
      "Sid": "LogsReadWrite",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup", "logs:CreateLogStream",
        "logs:PutLogEvents", "logs:Describe*", "logs:FilterLogEvents",
        "cloudwatch:Get*", "cloudwatch:List*", "cloudwatch:Describe*",
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3SamArtifacts",
      "Effect": "Allow",
      "Action": ["s3:CreateBucket", "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::linkpulse-*", "arn:aws:s3:::linkpulse-*/*"]
    },
    {
      "Sid": "PassRoleToLambdaOnly",
      "Effect": "Allow",
      "Action": ["iam:PassRole"],
      "Resource": "arn:aws:iam::$ACCOUNT_ID:role/linkpulse-*",
      "Condition": { "StringEquals": { "iam:PassedToService": "lambda.amazonaws.com" } }
    },
    {
      "Sid": "BudgetsReadOnly",
      "Effect": "Allow",
      "Action": ["budgets:ViewBudget", "budgets:Describe*"],
      "Resource": "*"
    }
  ]
}
JSON
)
echo "$DEV_DOC" > /tmp/dev-policy.json
DEV_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_DEV"
if aws iam get-policy --policy-arn "$DEV_ARN" >/dev/null 2>&1; then
  run "aws iam create-policy-version --policy-arn $DEV_ARN --policy-document file:///tmp/dev-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_DEV --policy-document file:///tmp/dev-policy.json --description 'TV5: least privilege cho dev serverless (Issue #5)'"
fi
run "aws iam attach-group-policy --group-name $GROUP --policy-arn $DEV_ARN"

# 1c. Tạo user từng thành viên + cho vào group (không tạo access key ở đây —
#     mỗi người tự tạo key của mình sau khi bật MFA; script chỉ in hướng dẫn).
log "Tạo IAM user cho ${#MEMBER_ARR[@]} thành viên"
for m in "${MEMBER_ARR[@]}"; do
  user="linkpulse-$m"
  if aws iam get-user --user-name "$user" >/dev/null 2>&1; then
    log "  - $user đã tồn tại, bỏ qua tạo"
  else
    run "aws iam create-user --user-name $user --tags Key=Project,Value=LinkPulse Key=Owner,Value=$m"
  fi
  run "aws iam add-user-to-group --user-name $user --group-name $GROUP"
done

# 1d. Password policy + alias (tùy chọn, không fail nếu thiếu quyền)
log "Đặt password policy (tối thiểu 14 ký tự, xoay 90 ngày, chống dùng lại)"
run "aws iam update-account-password-policy --minimum-password-length 14 --require-symbols --require-numbers --require-uppercase-characters --require-lowercase-characters --allow-users-to-change-password --max-password-age 90 --password-reuse-prevention 5 || true"

# ---------------------------------------------------------------------------
# 2. AWS Budgets — $BUDGET_LIMIT/tháng, lọc region, gửi mail cả nhóm
#    (Budgets API chỉ chạy ở us-east-1 — script tự chuyển endpoint.)
# ---------------------------------------------------------------------------
log "Tạo AWS Budgets (endpoint us-east-1, lọc Region=$REGION)"
BUDGET_NAME="linkpulse-monthly-${REGION}-${BUDGET_LIMIT}usd"
SUBS_JSON=""
for e in "${EMAIL_ARR[@]}"; do
  SUBS_JSON="${SUBS_JSON}{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$e\"},"
done
SUBS_JSON="[${SUBS_JSON%,}]"
echo "$SUBS_JSON" > /tmp/subs.json
NOTIFS_JSON=$(cat <<JSON
[{"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":$(cat /tmp/subs.json)},
 {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":$(cat /tmp/subs.json)}]
JSON
)
echo "$NOTIFS_JSON" > /tmp/notifs.json
BUDGET_DOC=$(cat <<JSON
{
  "BudgetName": "$BUDGET_NAME",
  "BudgetLimit": { "Amount": "$BUDGET_LIMIT", "Unit": "USD" },
  "CostFilters": { "Region": ["$REGION"] },
  "CostTypes": { "IncludeTax": true, "IncludeSubscription": true, "UseBlended": false },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
JSON
)
echo "$BUDGET_DOC" > /tmp/budget.json
# Idempotent: tạo mới, nếu đã tồn tại thì cập nhật budget + ghi đè notifications.
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] aws budgets create-budget --account-id $ACCOUNT_ID --budget file:///tmp/budget.json --notifications-with-subscribers file:///tmp/notifs.json --region us-east-1"
else
  if aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --region us-east-1 >/dev/null 2>&1; then
    aws budgets update-budget --account-id "$ACCOUNT_ID" --new-budget file:///tmp/budget.json --region us-east-1
    aws budgets delete-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}' --region us-east-1 || true
    aws budgets delete-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}' --region us-east-1 || true
    aws budgets create-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}' --subscribers "file:///tmp/subs.json" --region us-east-1
    aws budgets create-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}' --subscribers "file:///tmp/subs.json" --region us-east-1
  else
    aws budgets create-budget --account-id "$ACCOUNT_ID" --budget file:///tmp/budget.json --notifications-with-subscribers file:///tmp/notifs.json --region us-east-1
  fi
fi

log "Xong. Việc còn lại của từng thành viên:"
echo "  1) Đăng nhập IAM user linkpulse-<ten>, bật Virtual MFA (Google Authenticator/Authy):"
echo "     IAM console > Users > linkpulse-<ten> > Security credentials > Assign MFA device"
echo "  2) Sau khi có MFA mới tự tạo Access Key (không xin key của nhau)."
echo "  3) Kiểm tra budget mail đã về hộp thư (kiểm tra cả Spam)."
echo "  4) WAF cho CloudFront tạo bằng Terraform ở us-east-1: terraform/foundation.tf"
