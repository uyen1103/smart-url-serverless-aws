#!/usr/bin/env bash
# Quản lý bảng blocklist (TV5) — chặn / gỡ chặn domain và trả link bị gắn cỏ về active.
#
# Bảng `blocklist` lưu theo domain (khóa HASH = `domain`). Backend tra theo host và các
# domain cha, nên chặn `bad.com` cũng chặn `a.b.bad.com`.
#
# Dùng script này để chặn/gỡ link theo yêu cầu của nhóm. Hệ thống không có giao diện quản trị.
#
# Ví dụ:
#   scripts/blocklist.sh add bad.com --reason phishing
#   scripts/blocklist.sh add bad.com --reason phishing --execute
#   scripts/blocklist.sh remove bad.com
#   scripts/blocklist.sh list
#   scripts/blocklist.sh activate abc1234        # đưa link bị gắn cờ về active
#
# Biến môi trường:
#   BLOCKLIST_TABLE  tên bảng blocklist (mặc định lấy từ stack backend output BlocklistTableName)
#   URLS_TABLE       tên bảng urls
#   AWS_REGION       region của stack backend
set -euo pipefail

TABLE_BLOCKLIST="${BLOCKLIST_TABLE:-}"
TABLE_URLS="${URLS_TABLE:-}"
REGION="${AWS_REGION:-ap-southeast-2}"
REASON=""
CODE=""
EXECUTE="false"

usage() {
  sed -n '2,20p' "$0"
  echo "Usage: $0 add <domain> [--reason R] | remove <domain> | list | activate <code> [--execute]"
}

ACTION=""
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    add)      ACTION="add"; TARGET="$2"; shift 2 ;;
    remove)   ACTION="remove"; TARGET="$2"; shift 2 ;;
    list)     ACTION="list"; shift ;;
    activate) ACTION="activate"; TARGET="$2"; shift 2 ;;
    --reason) REASON="$2"; shift 2 ;;
    --execute) EXECUTE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

[[ -z "$ACTION" ]] && { usage; exit 1; }
[[ "$ACTION" != "list" && -z "$TARGET" ]] && { echo "ERROR: thiếu đối số"; usage; exit 1; }

command -v aws >/dev/null || { echo "ERROR: chưa cài AWS CLI"; exit 1; }

# Tên bảng: ưu tiên biến môi trường, sau đó tra output của stack backend.
if [[ -z "$TABLE_BLOCKLIST" || -z "$TABLE_URLS" ]]; then
  stack="${STACK_NAME:-smart-url}"
  outputs=$(aws cloudformation describe-stacks --stack-name "$stack" --region "$REGION" --query "Stacks[0].Outputs" --output json 2>/dev/null || echo "[]")
  [[ -z "$TABLE_BLOCKLIST" ]] && TABLE_BLOCKLIST=$(echo "$outputs" | python -c "import json,sys;print(next((o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='BlocklistTableName'),''))" 2>/dev/null || echo "")
  # Bảng urls chưa có output riêng: lấy PhysicalName từ resource của stack.
  if [[ -z "$TABLE_URLS" ]]; then
    TABLE_URLS=$(aws cloudformation list-stack-resources --stack-name "$stack" --region "$REGION" \
      --query "StackResourceSummaries[?LogicalResourceId=='UrlsTable'].PhysicalResourceId[0]" --output text 2>/dev/null || echo "")
    [[ "$TABLE_URLS" == "None" ]] && TABLE_URLS=""
  fi
fi

if [[ "$ACTION" != "list" && -z "$TABLE_BLOCKLIST" ]]; then
  echo "ERROR: chưa biết tên bảng blocklist. Đặt BLOCKLIST_TABLE=... hoặc deploy stack backend trước." >&2
  exit 1
fi

# Chuẩn hóa domain: bỏ scheme, path, ký tự '/' cuối và chuyển chữ thường.
normalize_domain() {
  local d="$1"
  d="${d#*://}"
  d="${d%%/*}"
  d="${d%%:*}"
  d="${d,,}"
  d="${d#.}"
  d="${d%.}"
  echo "$d"
}

domain=""
if [[ "$ACTION" == "add" || "$ACTION" == "remove" ]]; then
  domain="$(normalize_domain "$TARGET")"
  if [[ ! "$domain" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]]; then
    echo "ERROR: '$TARGET' không phải tên miền hợp lệ." >&2
    exit 1
  fi
fi

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
epoch() { date -u +%s; }

case "$ACTION" in
  add)
    item=$(printf '{"domain": {"S": "%s"}, "reason": {"S": "%s"}, "added_at": {"S": "%s"}}' "$domain" "$REASON" "$(now_iso)")
    echo "Đang chặn domain: $domain${REASON:+ (lý do: $REASON)}"
    if [[ "$EXECUTE" != "true" ]]; then
      echo "[chưa thực thi] aws dynamodb put-item --table-name $TABLE_BLOCKLIST --item '$item' --region $REGION"
      echo "Thêm --execute để chạy thật."
      exit 0
    fi
    aws dynamodb put-item --table-name "$TABLE_BLOCKLIST" --item "$item" --region "$REGION" >/dev/null
    echo "Đã chặn $domain."
    ;;
  remove)
    echo "Đang gỡ chặn domain: $domain"
    if [[ "$EXECUTE" != "true" ]]; then
      echo "[chưa thực thi] aws dynamodb delete-item --table-name $TABLE_BLOCKLIST --key {\"domain\":{\"S\":\"$domain\"}} --region $REGION"
      echo "Thêm --execute để chạy thật."
      exit 0
    fi
    aws dynamodb delete-item --table-name "$TABLE_BLOCKLIST" --key "{\"domain\":{\"S\":\"$domain\"}}" --region "$REGION" >/dev/null
    echo "Đã gỡ chặn $domain."
    ;;
  list)
    aws dynamodb scan --table-name "$TABLE_BLOCKLIST" --region "$REGION" --projection-expression "domain,reason,added_at" --output json
    ;;
  activate)
    if [[ -z "$TABLE_URLS" ]]; then
      echo "ERROR: chưa biết tên bảng urls. Đặt URLS_TABLE=... hoặc deploy stack backend trước." >&2
      exit 1
    fi
    echo "Đang đưa link $TARGET về trạng thái active"
    if [[ "$EXECUTE" != "true" ]]; then
      echo "[chưa thực thi] aws dynamodb update-item --table-name $TABLE_URLS --key {\"short_code\":{\"S\":\"$TARGET\"}} --update-expression 'SET #s = :a REMOVE flag_reason, flagged_at' --condition-expression 'attribute_exists(short_code)' --region $REGION"
      echo "Thêm --execute để chạy thật."
      exit 0
    fi
    aws dynamodb update-item --table-name "$TABLE_URLS" \
      --key "{\"short_code\":{\"S\":\"$TARGET\"}}" \
      --update-expression "SET #s = :a REMOVE flag_reason, flagged_at" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{":a":{"S":"active"}}' \
      --condition-expression "attribute_exists(short_code)" \
      --region "$REGION" >/dev/null
    echo "Đã đưa $TARGET về active."
    ;;
esac
