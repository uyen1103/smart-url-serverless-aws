#!/usr/bin/env bash
# Tra bảng urls của stack backend (TV5).
#   scripts/dyn_urls.sh get <code>
#   scripts/dyn_urls.sh list-suspicious
#   scripts/dyn_urls.sh scan
set -uo pipefail

REGION="${AWS_REGION:-ap-southeast-2}"
STACK="${STACK_NAME:-linkpulse-backend}"

if [[ -z "${URLS_TABLE:-}" ]]; then
  URLS_TABLE=$(aws cloudformation list-stack-resources --stack-name "$STACK" --region "$REGION" \
    --query "StackResourceSummaries[?LogicalResourceId=='UrlsTable'].PhysicalResourceId" --output text 2>/dev/null)
  URLS_TABLE=$(printf '%s' "$URLS_TABLE" | head -1)
  [[ "$URLS_TABLE" == "None" || -z "$URLS_TABLE" ]] && URLS_TABLE=""
fi
[[ -z "$URLS_TABLE" ]] && { echo "ERROR: chưa tìm được bảng urls của stack $STACK"; exit 1; }
echo "# bảng urls: $URLS_TABLE (region $REGION)"

case "${1:-}" in
  get)
    code="${2:-}"
    aws dynamodb get-item --table-name "$URLS_TABLE" --region "$REGION" \
      --key "{\"short_code\":{\"S\":\"$code\"}}" --output json
    ;;
  list-suspicious)
    aws dynamodb scan --table-name "$URLS_TABLE" --region "$REGION" \
      --filter-expression "status = :s" --expression-attribute-values '{":s":{"S":"suspicious"}}' --output json
    ;;
  scan)
    aws dynamodb scan --table-name "$URLS_TABLE" --region "$REGION" --output json
    ;;
  *)
    echo "Usage: $0 get <code> | list-suspicious | scan"; exit 1
    ;;
esac
