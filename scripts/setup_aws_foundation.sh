#!/usr/bin/env bash
###############################################################################
# setup_aws_foundation.sh — Dựng nền tảng nhóm LinkPulse (TV5)
#
# Mục đích:
#   1. Tạo IAM user cho từng thành viên, bắt buộc MFA.
#   2. Cấp quyền theo vai trò (quyết định #17 trong docs/QUYET_DINH_CHOT_TUAN_2.md):
#        - deployer (TV1, TV5): PowerUserAccess + quyền tạo IAM role/policy mà SAM cần,
#          + CloudFront/SSM/WAF/CloudWatch alarm để deploy edge.
#        - frontend (TV2): ghi vào bucket giao diện + tạo invalidation CloudFront.
#        - reader (TV3, TV4): đọc tài nguyên, DynamoDB và CloudWatch.
#   3. Đặt password policy cho tài khoản.
#   4. Tạo AWS Budget $5/tháng (forecasted 80% + actual 100%) lọc theo region workload.
#
# Region:
#   - Workload (backend, edge, DynamoDB): mặc định ap-southeast-2. Tài khoản Free plan kiểu mới bị
#     AWS ghim Region theo project; TV1 đã deploy thử ở ap-southeast-2 và bị chặn ở ap-southeast-1
#     (docs/backend_research.md §6.2). Mọi thành viên `aws configure set region <region này>`.
#   - Edge: CloudFront/WAF nằm ở us-east-1 (EDGE_REGION).
#   - Budgets: endpoint toàn cục, dùng us-east-1.
#
# Cách dùng:
#   ./scripts/setup_aws_foundation.sh \
#       --members "tv1,tv2,tv3,tv4,tv5" \
#       --emails "tv1@example.com,tv2@example.com,tv3@example.com,tv4@example.com,tv5@example.com" \
#       --region ap-southeast-2 --budget 5
#
#   Hoặc gắn email trực tiếp theo từng người (đỡ phải nhớ thứ tự):
#       ./scripts/setup_aws_foundation.sh \
#           --member tv1=kinkit784@gmail.com \
#           --member tv2=nguyenuyen2017tn@gmail.com \
#           --member tv3=lamvanhau202101@gmail.com \
#           --member tv4=yendoan20062020@gmail.com \
#           --member tv5=liemnt0773@ut.edu.vn \
#           --region ap-southeast-2 --budget 5
#
#   Vai trò suy ra từ tên: tv1/tv5 -> deployer, tv2 -> frontend, tv3/tv4 -> reader.
#   Ghi đè tường minh bằng --roles "tv1=deployer,tv5=deployer,tv2=frontend,tv3=reader,tv4=reader".
#
#   Cấp cả console access (tuỳ chọn) để thành viên đăng nhập được AWS Console:
#       ./scripts/setup_aws_foundation.sh --member tv5=liamnguyen.piupear206@gmail.com \
#           --console-password "LinkPulse-TV5-2026!x"
#   Mật khẩu phải khớp password policy của tài khoản: >= 14 ký tự, hoa + thường + số + ký hiệu.
#
# Yêu cầu: AWS CLI v2, quyền iam:* và budgets:* (chạy lần đầu bằng IAM admin/root).
# Sau đó mỗi người dùng user của mình, không dùng chung key.
###############################################################################
set -euo pipefail

REGION="ap-southeast-2"
EDGE_REGION="us-east-1"
BUDGET_LIMIT="5"
CONSOLE_PASSWORD=""
MEMBERS=""
EMAILS=""
ROLES=""
MEMBER_PAIRS=()
ACCOUNT_ID=""
DRY_RUN="false"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

usage() {
  sed -n '2,42p' "$0"
  echo "Options: --members a,b --emails a@x,b@x [--member a=mail ...] [--roles a=role,...]"
  echo "         [--region R] [--edge-region R] [--budget N] [--console-password P] [--dry-run]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --members)     MEMBERS="$2"; shift 2 ;;
    --emails)      EMAILS="$2"; shift 2 ;;
    --member)      MEMBER_PAIRS+=("$2"); shift 2 ;;
    --roles)       ROLES="$2"; shift 2 ;;
    --region)      REGION="$2"; shift 2 ;;
    --edge-region) EDGE_REGION="$2"; shift 2 ;;
    --budget)      BUDGET_LIMIT="$2"; shift 2 ;;
    --console-password) CONSOLE_PASSWORD="$2"; shift 2 ;;
    --dry-run)     DRY_RUN="true"; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

if [[ ${#MEMBER_PAIRS[@]} -gt 0 ]]; then
  # Dạng --member ten=email: ghép thành --members/--emails để không phải nhớ thứ tự.
  local_names=""
  local_mails=""
  for pair in "${MEMBER_PAIRS[@]}"; do
    [[ "$pair" == *"="* ]] || { echo "ERROR: --member cần dạng ten=email, nhận '$pair'"; exit 1; }
    local_names="${local_names}${pair%%=*},"
    local_mails="${local_mails}${pair#*=},"
  done
  MEMBERS="${local_names%,}"
  EMAILS="${local_mails%,}"
fi

[[ -z "$MEMBERS" || -z "$EMAILS" ]] && { echo "ERROR: thiếu --members/--emails hoặc --member"; usage; exit 1; }

IFS=',' read -r -a MEMBER_ARR <<< "$MEMBERS"
IFS=',' read -r -a EMAIL_ARR <<< "$EMAILS"
[[ ${#MEMBER_ARR[@]} -ne ${#EMAIL_ARR[@]} ]] && { echo "ERROR: số member != số email"; exit 1; }

# Vai trò mặc định theo module trong nhóm; --roles ghi đè từng người.
default_role() {
  case "$1" in
    tv1|tv5) echo "deployer" ;;
    tv2)     echo "frontend" ;;
    tv3|tv4) echo "reader" ;;
    *)       echo "reader" ;;
  esac
}

declare -A ROLE_OF
OVERRIDE=()
if [[ -n "$ROLES" ]]; then
  IFS=',' read -r -a OVERRIDE <<< "$ROLES"
fi
for i in "${!MEMBER_ARR[@]}"; do
  m="${MEMBER_ARR[$i]}"
  role="$(default_role "$m")"
  for ov in "${OVERRIDE[@]}"; do
    [[ "$ov" == "$m="* ]] && role="${ov#*=}"
  done
  ROLE_OF["$m"]="$role"
done

run() { if [[ "$DRY_RUN" == "true" ]]; then echo "[dry-run] $*"; else eval "$@"; fi; }
log() { echo "==> $*"; }

command -v aws >/dev/null || { echo "ERROR: chưa cài AWS CLI"; exit 1; }
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "Account: $ACCOUNT_ID | Region workload: $REGION | Region edge: $EDGE_REGION | Budget: \$$BUDGET_LIMIT/mo"

# Preflight: script cần iam:* (tạo group/user/policy) và budgets:* (tạo budget).
# Nếu tài khoản không có quyền thì dừng ngay với thông báo rõ ràng, thay vì để lỗi
# AccessDenied xen giữa quá trình.
IAM_PROBE_ERR="$(aws iam get-group --group-name linkpulse-devs 2>&1 >/dev/null || true)"
if grep -qE "AccessDenied|not authorized" <<<"$IAM_PROBE_ERR" && ! grep -qE "NoSuchEntity|does not exist" <<<"$IAM_PROBE_ERR"; then
  echo ""
  echo "!! KHÔNG ĐỦ QUYỀN — script cần quyền IAM admin (iam:*) và budgets:*." >&2
  echo "   Caller hiện tại: $(aws sts get-caller-identity --query Arn --output text)" >&2
  echo "   Lỗi: $IAM_PROBE_ERR" >&2
  echo ""
  echo "   Cách xử lý:" >&2
  echo "   1) Chạy script này bằng root user hoặc IAM admin của tài khoản 567627324019." >&2
  echo "   2) Hoặc admin gán cho user hiện tại: iam:CreateUser, iam:CreateGroup, iam:CreatePolicy," >&2
  echo "      iam:AttachUserPolicy, iam:AttachGroupPolicy, iam:PutUserPolicy, iam:CreateLoginProfile," >&2
  echo "      iam:UpdateAccountPasswordPolicy, budgets:CreateBudget, budgets:UpdateBudget." >&2
  echo ""
  exit 1
fi

# Tên stack của nhóm: TV1 dùng smart-url cho stack backend, các stack khác dùng linkpulse-*.

# ---------------------------------------------------------------------------
# 1. IAM: group, policy MFA, policy theo vai trò, user
# ---------------------------------------------------------------------------
GROUP="linkpulse-devs"
POLICY_MFA="LinkPulse-EnforceMFA"
POLICY_DEPLOYER="LinkPulse-Deployer"
POLICY_FRONTEND="LinkPulse-FrontendDeploy"
POLICY_READER="LinkPulse-ReadOnly"

log "Tạo group $GROUP (nếu chưa có)"
run "aws iam get-group --group-name $GROUP >/dev/null 2>&1 || aws iam create-group --group-name $GROUP"

# Policy least-privilege cũ của tuần 1 (LinkPulse-DevLeastPrivilege) đã gắn vào group và thiếu
# CloudFront/SSM/WAF/iam:PassRole cho SAM. Gỡ đi để user chỉ dùng quyền theo vai trò.
OLD_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/LinkPulse-DevLeastPrivilege"
if aws iam get-policy --policy-arn "$OLD_POLICY_ARN" >/dev/null 2>&1; then
  log "Gỡ policy cũ LinkPulse-DevLeastPrivilege khỏi group $GROUP"
  run "aws iam detach-group-policy --group-name $GROUP --policy-arn $OLD_POLICY_ARN || true"
fi

# 1a. Bắt buộc MFA cho mọi thành viên: chặn mọi hành động khi chưa bật MFA,
#     trừ thao tác tự quản lý MFA và đổi mật khẩu của chính mình.
log "Tạo/cập nhật policy bắt buộc MFA: $POLICY_MFA"
cat > "$WORKDIR/mfa-policy.json" <<'JSON'
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
MFA_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_MFA"
if aws iam get-policy --policy-arn "$MFA_ARN" >/dev/null 2>&1; then
  run "aws iam create-policy-version --policy-arn $MFA_ARN --policy-document file://$WORKDIR/mfa-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_MFA --policy-document file://$WORKDIR/mfa-policy.json --description 'TV5: bat buoc MFA cho moi thanh vien'"
fi

# 1b. Policy theo vai trò.
#
# deployer — chạy `sam deploy` (backend) và deploy edge (CloudFront/S3/WAF/SSM).
# PowerUserAccess đã cho mọi quyền trừ quản lý IAM; SAM cần tạo role + policy nên bổ sung
# các lệnh IAM giới hạn theo prefix stack của nhóm.
log "Tạo/cập nhật policy deployer: $POLICY_DEPLOYER"
cat > "$WORKDIR/deployer-policy.json" <<JSON
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
        "arn:aws:iam::${ACCOUNT_ID}:role/linkpulse-*",
        "arn:aws:iam::${ACCOUNT_ID}:role/smart-url*",
        "arn:aws:iam::${ACCOUNT_ID}:role/stack-*"
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
        "arn:aws:iam::${ACCOUNT_ID}:policy/linkpulse-*",
        "arn:aws:iam::${ACCOUNT_ID}:policy/smart-url*"
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
        "StringLike": { "aws:RequestedRegion": ["$REGION", "$EDGE_REGION"] }
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
JSON
DEPLOYER_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_DEPLOYER"
if aws iam get-policy --policy-arn "$DEPLOYER_ARN" >/dev/null 2>&1; then
  run "aws iam create-policy-version --policy-arn $DEPLOYER_ARN --policy-document file://$WORKDIR/deployer-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_DEPLOYER --policy-document file://$WORKDIR/deployer-policy.json --description 'TV5: quyen deploy backend va edge (TV1, TV5)'"
fi
# PowerUser do AWS quản lý: cho mọi quyền trừ quản lý IAM. Phần IAM bị thiếu thì policy trên bổ sung.
POWERUSER_ARN="arn:aws:iam::aws:policy/PowerUserAccess"

# frontend — TV2: nạp giao diện lên bucket, tạo invalidation CloudFront, xem log để debug.
log "Tạo/cập nhật policy frontend: $POLICY_FRONTEND"
cat > "$WORKDIR/frontend-policy.json" <<JSON
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
JSON
FRONTEND_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_FRONTEND"
if aws iam get-policy --policy-arn "$FRONTEND_ARN" >/dev/null 2>&1; then
  run "aws iam create-policy-version --policy-arn $FRONTEND_ARN --policy-document file://$WORKDIR/frontend-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_FRONTEND --policy-document file://$WORKDIR/frontend-policy.json --description 'TV5: quyen deploy giao dien (TV2)'"
fi

# reader — TV3, TV4: xem cấu hình, đọc DynamoDB và CloudWatch để kiểm chứng.
log "Tạo/cập nhật policy reader: $POLICY_READER"
cat > "$WORKDIR/reader-policy.json" <<JSON
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
JSON
READER_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_READER"
if aws iam get-policy --policy-arn "$READER_ARN" >/dev/null 2>&1; then
  run "aws iam create-policy-version --policy-arn $READER_ARN --policy-document file://$WORKDIR/reader-policy.json --set-as-default"
else
  run "aws iam create-policy --policy-name $POLICY_READER --policy-document file://$WORKDIR/reader-policy.json --description 'TV5: quyen doc de kiem chung (TV3, TV4)'"
fi

# 1c. Gán policy cho từng user theo vai trò.
log "Tạo IAM user cho ${#MEMBER_ARR[@]} thành viên và gán quyền theo vai trò"
for i in "${!MEMBER_ARR[@]}"; do
  m="${MEMBER_ARR[$i]}"
  email="${EMAIL_ARR[$i]}"
  role="${ROLE_OF[$m]}"
  user="linkpulse-$m"
  if aws iam get-user --user-name "$user" >/dev/null 2>&1; then
    log "  - $user đã tồn tại, giữ nguyên"
  else
    run "aws iam create-user --user-name $user --tags Key=Project,Value=LinkPulse Key=Owner,Value=$m"
  fi
  run "aws iam add-user-to-group --user-name $user --group-name $GROUP"
  run "aws iam attach-user-policy --user-name $user --policy-arn $MFA_ARN"

  # Console access (tuỳ chọn): tạo LoginProfile để thành viên đăng nhập AWS Console.
  # Mật khẩu phải khớp password policy của tài khoản: >= 14 ký tự, hoa + thường + số + ký hiệu.
  if [[ -n "$CONSOLE_PASSWORD" ]]; then
    if aws iam get-login-profile --user-name "$user" >/dev/null 2>&1; then
      log "  - $user đã có console access, giữ nguyên"
    else
      # Không nội suy mật khẩu vào chuỗi `run` vì `run` dùng `eval`: mật khẩu chứa
      # ký tự shell (nhất là `'` hoặc `$`) sẽ bị diễn giải sai. Gọi aws trực tiếp.
      if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] aws iam create-login-profile --user-name $user --password <ẩn>"
      else
        aws iam create-login-profile --user-name "$user" --password "$CONSOLE_PASSWORD"
      fi
      log "  - $user: đã tạo console access (chuyển mật khẩu '$CONSOLE_PASSWORD' cho thành viên, chỉ hiện 1 lần)"
    fi
  fi
  case "$role" in
    deployer)
      run "aws iam attach-user-policy --user-name $user --policy-arn $POWERUSER_ARN"
      run "aws iam attach-user-policy --user-name $user --policy-arn $DEPLOYER_ARN"
      ;;
    frontend) run "aws iam attach-user-policy --user-name $user --policy-arn $FRONTEND_ARN" ;;
    reader)   run "aws iam attach-user-policy --user-name $user --policy-arn $READER_ARN" ;;
    *) echo "ERROR: vai trò lạ '$role' cho $m"; exit 1 ;;
  esac
  log "  - $user ($email): vai trò $role"
done

# 1d. Password policy cho tài khoản.
log "Đặt password policy (tối thiểu 14 ký tự, xoay 90 ngày, chống dùng lại)"
run "aws iam update-account-password-policy --minimum-password-length 14 --require-symbols --require-numbers --require-uppercase-characters --require-lowercase-characters --allow-users-to-change-password --max-password-age 90 --password-reuse-prevention 5 || true"

# ---------------------------------------------------------------------------
# 2. AWS Budgets — $BUDGET_LIMIT/tháng lọc theo region workload, gửi mail cả nhóm.
#    Budgets API chỉ có endpoint ở us-east-1.
# ---------------------------------------------------------------------------
log "Tạo AWS Budgets (endpoint us-east-1, lọc Region=$REGION)"
BUDGET_NAME="linkpulse-monthly-${REGION}-${BUDGET_LIMIT}usd"
SUBS_JSON=""
for e in "${EMAIL_ARR[@]}"; do
  SUBS_JSON="${SUBS_JSON}{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$e\"},"
done
SUBS_JSON="[${SUBS_JSON%,}]"
echo "$SUBS_JSON" > "$WORKDIR/subs.json"
cat > "$WORKDIR/notifs.json" <<JSON
[{"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":$(cat "$WORKDIR/subs.json")},
 {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":$(cat "$WORKDIR/subs.json")}]
JSON
cat > "$WORKDIR/budget.json" <<JSON
{
  "BudgetName": "$BUDGET_NAME",
  "BudgetLimit": { "Amount": "$BUDGET_LIMIT", "Unit": "USD" },
  "CostFilters": { "Region": ["$REGION"] },
  "CostTypes": { "IncludeTax": true, "IncludeSubscription": true, "UseBlended": false },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
JSON
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] aws budgets create-budget --account-id $ACCOUNT_ID --budget file://$WORKDIR/budget.json --notifications-with-subscribers file://$WORKDIR/notifs.json --region us-east-1"
else
  if aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --region us-east-1 >/dev/null 2>&1; then
    aws budgets update-budget --account-id "$ACCOUNT_ID" --new-budget file://"$WORKDIR/budget.json" --region us-east-1
    aws budgets delete-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}' --region us-east-1 || true
    aws budgets delete-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}' --region us-east-1 || true
    aws budgets create-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}' --subscribers "file://$WORKDIR/subs.json" --region us-east-1
    aws budgets create-notification --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --notification '{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}' --subscribers "file://$WORKDIR/subs.json" --region us-east-1
  else
    aws budgets create-budget --account-id "$ACCOUNT_ID" --budget "file://$WORKDIR/budget.json" --notifications-with-subscribers "file://$WORKDIR/notifs.json" --region us-east-1
  fi
fi

log "Xong. Việc còn lại của từng thành viên:"
echo "  1) Đăng nhập IAM user linkpulse-<ten>, bật Virtual MFA:"
echo "     IAM console > Users > linkpulse-<ten> > Security credentials > Assign MFA device"
echo "  2) Sau khi có MFA mới tự tạo Access Key (không xin key của nhau)."
echo "  3) aws configure set region $REGION   (cùng Region cho cả nhóm)"
echo "  4) Kiểm tra budget mail đã về hộp thư (kiểm tra cả Spam)."
echo "  5) WAF không tạo ở script này: nằm trong infra/edge.yaml, bật bằng tham số EnableWaf."
