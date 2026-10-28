
#!/usr/bin/env bash
set -euo pipefail

ENDPOINT_URL="${DYNAMODB_ENDPOINT_URL:-http://localhost:8000}"
REGION="${AWS_DEFAULT_REGION:-ap-southeast-1}"

create_table_if_missing() {
  local table_name="$1"
  shift

  if aws dynamodb describe-table \
    --table-name "$table_name" \
    --endpoint-url "$ENDPOINT_URL" \
    --region "$REGION" >/dev/null 2>&1; then
    echo "Table '$table_name' already exists; skipping."
  else
    echo "Creating table '$table_name'..."
    aws dynamodb create-table \
      --table-name "$table_name" \
      --endpoint-url "$ENDPOINT_URL" \
      --region "$REGION" \
      "$@"
  fi
}

create_table_if_missing urls \
  --attribute-definitions AttributeName=short_code,AttributeType=S \
  --key-schema AttributeName=short_code,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

create_table_if_missing clicks \
  --attribute-definitions \
    AttributeName=short_code,AttributeType=S \
    AttributeName=click_key,AttributeType=S \
  --key-schema \
    AttributeName=short_code,KeyType=HASH \
    AttributeName=click_key,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

create_table_if_missing stats_agg \
  --attribute-definitions \
    AttributeName=short_code,AttributeType=S \
    AttributeName=time_bucket,AttributeType=S \
  --key-schema \
    AttributeName=short_code,KeyType=HASH \
    AttributeName=time_bucket,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

create_table_if_missing rate_limits \
  --attribute-definitions AttributeName=ip,AttributeType=S \
  --key-schema AttributeName=ip,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

create_table_if_missing blocklist \
  --attribute-definitions AttributeName=domain,AttributeType=S \
  --key-schema AttributeName=domain,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

enable_ttl_if_needed() {
  local table_name="$1"
  local attribute_name="$2"
  local status

  status="$(aws dynamodb describe-time-to-live \
    --table-name "$table_name" \
    --endpoint-url "$ENDPOINT_URL" \
    --region "$REGION" \
    --query 'TimeToLiveDescription.TimeToLiveStatus' \
    --output text 2>/dev/null || true)"

  if [[ "$status" == "ENABLED" ]]; then
    local current_attribute
    current_attribute="$(aws dynamodb describe-time-to-live \
      --table-name "$table_name" \
      --endpoint-url "$ENDPOINT_URL" \
      --region "$REGION" \
      --query 'TimeToLiveDescription.AttributeName' \
      --output text)"
    if [[ "$current_attribute" == "$attribute_name" ]]; then
      echo "TTL already enabled on '$table_name' using '$attribute_name'; skipping."
      return
    fi
    echo "WARNING: TTL on '$table_name' is enabled with '$current_attribute', not '$attribute_name'."
    return 1
  fi

  echo "Enabling TTL on '$table_name' using '$attribute_name'..."
  aws dynamodb update-time-to-live \
    --table-name "$table_name" \
    --time-to-live-specification "Enabled=true,AttributeName=$attribute_name" \
    --endpoint-url "$ENDPOINT_URL" \
    --region "$REGION"
}

enable_ttl_if_needed clicks expires_at
enable_ttl_if_needed rate_limits expires_at

echo "Done. Tables and TTL configuration checked."
