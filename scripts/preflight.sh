#!/usr/bin/env bash
# preflight.sh — kiểm tra tài khoản AWS trước khi deploy (TV5)
#
# Mục đích: biết trước những gì sẽ bị chặn trước khi deploy thật.
#   1. Xác nhận đang dùng đúng tài khoản AWS chung của nhóm.
#   2. Kiểm tra Region workload có dùng được không (tài khoản Free plan kiểu mới bị AWS ghim
#      Region theo project và chặn bằng service control policy -> AccessDenied).
#   3. Kiểm tra Region edge (us-east-1) cho CloudFront/WAF.
#   4. Kiểm tra quyền CloudFront và WAF phạm vi CLOUDFRONT.
#   5. Kiểm tra budget đã tồn tại chưa.
#
# Cách dùng:
#   ./scripts/preflight.sh                      # dùng region mặc định ap-southeast-2
#   ./scripts/preflight.sh --region ap-southeast-2 --edge-region us-east-1
#
# Yêu cầu: AWS CLI v2 đã cấu hình (aws configure) hoặc đặt AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
# Script chỉ đọc, không tạo hay sửa tài nguyên nào.
set -uo pipefail

REGION="ap-southeast-2"
EDGE_REGION="us-east-1"
BUDGET_NAME=""
FAIL=0

usage() {
  sed -n '2,15p' "$0"
  echo "Options: [--region R] [--edge-region R] [--budget-name NAME]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)      REGION="$2"; shift 2 ;;
    --edge-region) EDGE_REGION="$2"; shift 2 ;;
    --budget-name) BUDGET_NAME="$2"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

command -v aws >/dev/null || { echo "ERROR: chưa cài AWS CLI"; exit 1; }

ok()   { echo "  [OK]   $*"; }
warn() { echo "  [WARN] $*"; }
bad()  { echo "  [FAIL] $*"; FAIL=1; }

echo "==> 1. Danh tính tài khoản"
if IDENTITY=$(aws sts get-caller-identity --output json 2>&1); then
  ACCOUNT_ID=$(echo "$IDENTITY" | python -c "import json,sys;print(json.load(sys.stdin)['Account'])" 2>/dev/null)
  ARN=$(echo "$IDENTITY" | python -c "import json,sys;print(json.load(sys.stdin)['Arn'])" 2>/dev/null)
  ok "Account $ACCOUNT_ID · $ARN"
  [[ "$ARN" == *":root" ]] && bad "đang dùng tài khoản root — quy tắc nhóm là không dùng root"
else
  bad "không gọi được sts get-caller-identity: $IDENTITY"
  echo "Chạy 'aws configure' trước."
  exit 1
fi

echo "==> 2. Region workload: $REGION"
if OUT=$(aws ec2 describe-regions --region "$REGION" --query "Regions[?RegionName=='$REGION'].RegionName" --output text 2>&1); then
  if echo "$OUT" | grep -q "$REGION"; then
    ok "Region $REGION dùng được"
  else
    warn "Region $REGION không trả về trong danh sách — có thể bị chặn"
  fi
else
  bad "AccessDenied ở $REGION — tài khoản Free plan bị ghim Region theo project"
  echo "         Xem Region cố định tại https://settings.aws.com (mục Project) rồi dùng đúng Region đó."
fi

echo "==> 3. Region edge: $EDGE_REGION (CloudFront/WAF)"
if OUT=$(aws ec2 describe-regions --region "$EDGE_REGION" --query "Regions[?RegionName=='$EDGE_REGION'].RegionName" --output text 2>&1); then
  if echo "$OUT" | grep -q "$EDGE_REGION"; then
    ok "Region $EDGE_REGION dùng được"
  else
    warn "Region $EDGE_REGION không trả về trong danh sách"
  fi
else
  bad "AccessDenied ở $EDGE_REGION — tài khoản Free plan chặn Region này"
  echo "         Theo quyết định 19: deploy edge ở Region backend và bỏ kiểm thử WAF thật,"
  echo "         trình bày WAF bằng thiết kế + tài liệu. Báo cả nhóm trước khi đổi hướng."
fi

echo "==> 4. CloudFront và WAF (scope CLOUDFRONT)"
if OUT=$(aws cloudfront list-distributions --max-items 1 --output json 2>&1); then
  COUNT=$(echo "$OUT" | python -c "import json,sys;d=json.load(sys.stdin);print(d.get('DistributionList',{}).get('Quantity',0))" 2>/dev/null)
  ok "gọi được CloudFront (đang có $COUNT distribution)"
else
  bad "không gọi được CloudFront: $OUT"
fi

if OUT=$(aws wafv2 list-web-acls --scope CLOUDFRONT --region "$EDGE_REGION" --output json 2>&1); then
  COUNT=$(echo "$OUT" | python -c "import json,sys;print(len(json.load(sys.stdin).get('WebACLs',[])))" 2>/dev/null)
  ok "gọi được WAF scope CLOUDFRONT ở $EDGE_REGION (đang có $COUNT Web ACL)"
else
  bad "không gọi được wafv2 ở $EDGE_REGION: $OUT"
fi

echo "==> 5. Budget"
if [[ -z "$BUDGET_NAME" ]]; then
  BUDGET_NAME="linkpulse-monthly-${REGION}-5usd"
fi
if OUT=$(aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$BUDGET_NAME" --region us-east-1 --output json 2>&1); then
  LIMIT=$(echo "$OUT" | python -c "import json,sys;print(json.load(sys.stdin)['Budget']['BudgetLimit']['Amount'])" 2>/dev/null)
  ok "budget '$BUDGET_NAME' tồn tại (hạn mức \$$LIMIT)"
else
  warn "chưa thấy budget '$BUDGET_NAME' — chạy scripts/setup_aws_foundation.sh để tạo"
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "==> Không có vấn đề chặn deploy. Có thể tiến hành."
else
  echo "==> Có mục [FAIL]. Xử lý các mục đó hoặc báo cả nhóm trước khi deploy."
fi
exit "$FAIL"
