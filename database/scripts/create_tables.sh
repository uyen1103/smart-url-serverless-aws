#!/usr/bin/env bash
set -euo pipefail

# DynamoDB Local only; mirrors backend/template.yaml. No AWS deployment.
ENDPOINT_URL="${DYNAMODB_ENDPOINT_URL:-http://localhost:8000}"
REGION="${AWS_DEFAULT_REGION:-ap-southeast-1}"

aws_local() {
  aws dynamodb "$@" --endpoint-url "$ENDPOINT_URL" --region "$REGION"
}

table_exists() {
  aws_local describe-table --table-name "$1" >/dev/null 2>&1
}

create_table_if_missing() {
  local table_name="$1"
  shift
  if table_exists "$table_name"; then
    echo "Table '$table_name' already exists; skipping creation."
    echo "WARNING: Existing key schema/GSI cannot be changed in place. Delete this LOCAL table if it has the old schema, then rerun."
    return
  fi
  echo "Creating table '$table_name'..."
  aws_local create-table --table-name "$table_name" "$@"
  aws_local wait table-exists --table-name "$table_name"
}

enable_ttl() {
  local table_name="$1"
  local status current_attribute
  status="$(aws_local describe-time-to-live --table-name "$table_name" --query 'TimeToLiveDescription.TimeToLiveStatus' --output text 2>/dev/null || true)"
  current_attribute="$(aws_local describe-time-to-live --table-name "$table_name" --query 'TimeToLiveDescription.AttributeName' --output text 2>/dev/null || true)"

  if [[ "$status" == "ENABLED" && "$current_attribute" == "expires_at" ]]; then
    echo "TTL already enabled: $table_name.expires_at"
    return
  fi
  if [[ "$status" == "ENABLED" && "$current_attribute" != "expires_at" ]]; then
    echo "ERROR: TTL on '$table_name' uses '$current_attribute', expected 'expires_at'." >&2
    return 1
  fi

  echo "Enabling TTL: $table_name.expires_at"
  aws_local update-time-to-live --table-name "$table_name" --time-to-live-specification "Enabled=true,AttributeName=expires_at"
}

# urls: PK short_code; GSI owner-index (PK owner_id, SK created_at)
create_table_if_missing urls \
  --attribute-definitions \
    AttributeName=short_code,AttributeType=S \
    AttributeName=owner_id,AttributeType=S \
    AttributeName=created_at,AttributeType=S \
  --key-schema AttributeName=short_code,KeyType=HASH \
  --global-secondary-indexes \
    'IndexName=owner-index,KeySchema=[{AttributeName=owner_id,KeyType=HASH},{AttributeName=created_at,KeyType=RANGE}],Projection={ProjectionType=ALL},ProvisionedThroughput={ReadCapacityUnits=2,WriteCapacityUnits=4}' \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=6,WriteCapacityUnits=5

# clicks: PK short_code, SK sk; TTL expires_at; Streams NEW_IMAGE
create_table_if_missing clicks \
  --attribute-definitions \
    AttributeName=short_code,AttributeType=S \
    AttributeName=sk,AttributeType=S \
  --key-schema \
    AttributeName=short_code,KeyType=HASH \
    AttributeName=sk,KeyType=RANGE \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=4 \
  --stream-specification StreamEnabled=true,StreamViewType=NEW_IMAGE

# stats: PK scope, SK sk; TTL expires_at
create_table_if_missing stats \
  --attribute-definitions \
    AttributeName=scope,AttributeType=S \
    AttributeName=sk,AttributeType=S \
  --key-schema \
    AttributeName=scope,KeyType=HASH \
    AttributeName=sk,KeyType=RANGE \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=10,WriteCapacityUnits=4

# rate_limits: PK pk; TTL expires_at
create_table_if_missing rate_limits \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=5

# blocklist: PK domain
create_table_if_missing blocklist \
  --attribute-definitions AttributeName=domain,AttributeType=S \
  --key-schema AttributeName=domain,KeyType=HASH \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=3,WriteCapacityUnits=1

enable_ttl clicks
enable_ttl stats
enable_ttl rate_limits

echo
echo "Done. DynamoDB Local table creation/configuration finished."
