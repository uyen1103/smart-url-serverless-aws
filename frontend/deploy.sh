#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bucket="${S3_BUCKET:-}"
distribution_id="${CLOUDFRONT_DISTRIBUTION_ID:-}"
execute="${EXECUTE:-false}"
invalidate="${INVALIDATE:-false}"

# Kiểm tra cấu hình trước; mặc định chỉ in lệnh để xem trước, không upload.
if [[ -z "$bucket" ]]; then
  echo "Thiếu S3_BUCKET." >&2
  exit 1
fi
if [[ ! "$bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "S3_BUCKET phải là tên bucket S3, không kèm s3:// hoặc dấu /." >&2
  exit 1
fi
if [[ "$invalidate" == "true" && -z "$distribution_id" ]]; then
  echo "Thiếu CLOUDFRONT_DISTRIBUTION_ID để tạo invalidation." >&2
  exit 1
fi
if [[ "$invalidate" == "true" && ! "$distribution_id" =~ ^[A-Z0-9]+$ ]]; then
  echo "CLOUDFRONT_DISTRIBUTION_ID không đúng định dạng." >&2
  exit 1
fi

target="s3://${bucket}/"
# Không đẩy prototype và script deploy lên bucket phục vụ người dùng.
sync_args=(s3 sync "$root" "$target" --cache-control "max-age=300,s-maxage=300"
  --exclude "prototype/*" --exclude "deploy.ps1" --exclude "deploy.sh")
html_files=(index.html dashboard.html links.html protection.html warning.html error.html)
invalidation_paths=(/index.html /dashboard.html /links.html /protection.html /warning.html /error.html /css/\* /js/\* /mock/\*)

if [[ "$execute" != "true" ]]; then
  printf 'Chế độ xem trước; chưa tải file lên. Đích bucket root: %s (dùng bucket riêng cho frontend)\n' "$target"
  printf 'aws'; printf ' %q' "${sync_args[@]}"; printf '\n'
  for file in "${html_files[@]}"; do
    if [[ -f "$root/$file" ]]; then
      printf 'aws s3 cp %q %q --cache-control %q --content-type %q\n' \
        "$root/$file" "$target$file" "max-age=0,no-cache,must-revalidate" "text/html; charset=utf-8"
    fi
  done
  if [[ "$invalidate" == "true" ]]; then
    printf 'aws cloudfront create-invalidation --distribution-id %q --paths' "$distribution_id"
    printf ' %q' "${invalidation_paths[@]}"
    printf '\n'
  fi
  exit 0
fi

# HTML luôn phải revalidate để người dùng nhận bản giao diện mới sau deploy.
if ! command -v aws >/dev/null 2>&1; then
  echo "Không tìm thấy AWS CLI. Cài AWS CLI và cấu hình thông tin xác thực trước khi triển khai." >&2
  exit 1
fi

aws "${sync_args[@]}"
for file in "${html_files[@]}"; do
  if [[ -f "$root/$file" ]]; then
    aws s3 cp "$root/$file" "$target$file" \
      --cache-control "max-age=0,no-cache,must-revalidate" \
      --content-type "text/html; charset=utf-8"
  fi
done

if [[ "$invalidate" == "true" ]]; then
  aws cloudfront create-invalidation \
    --distribution-id "$distribution_id" \
    --paths "${invalidation_paths[@]}"
fi
