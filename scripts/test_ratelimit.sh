#!/usr/bin/env bash
# Kiểm thử rate limit theo IP (TV5, issue #27 mục 1)
#
# Gửi 15 POST /api/shorten liên tiếp từ cùng một IP. Đúng 10 request đầu phải thành công,
# từ request thứ 11 phải trả 429 kèm header Retry-After.
#
# Cửa sổ đếm của rate limit là 60 giây và bắt đầu từ mốc phút (now // 60), nên lệnh chờ
# cho tới khi sang phút mới rồi mới bắt đầu, tránh dính lượt đếm của phút trước.
#
# Biến môi trường:
#   CF_DOMAIN    domain CloudFront (mặc định lấy từ output của stack edge)
#   OWNER        UUID chủ sở hữu dùng cho lần chạy này
#   KEEP_LINKS   1 = không xoá link tạo ra sau khi test (mặc định xoá)
set -uo pipefail

CF_DOMAIN="${CF_DOMAIN:-d3rsimgoxz85kx.cloudfront.net}"
OWNER="${OWNER:-33333333-3333-4333-8333-333333333333}"
KEEP_LINKS="${KEEP_LINKS:-0}"

# Chờ tới đầu phút (mốc 0-5 giây) để bộ đếm của phút mới luôn bắt đầu từ 0.
while :; do
  sec=$(date -u +%S)
  sec=$((10#$sec))
  if [[ "$sec" -le 5 ]]; then break; fi
  sleep 1
done

echo "Bắt đầu lúc $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC"
echo "CF_DOMAIN=$CF_DOMAIN  OWNER=$OWNER"
echo

codes=()
for i in $(seq 1 15); do
  out=$(curl -s -D - -o /tmp/rl_body.txt \
    -X POST "https://$CF_DOMAIN/api/shorten" \
    -H 'Content-Type: application/json' \
    -H "X-Owner-Id: $OWNER" \
    -d "{\"url\":\"https://example.com/rl-test-$i\"}")
  code=$(printf '%s' "$out" | head -1 | awk '{print $2}')
  retry=$(printf '%s' "$out" | grep -i '^retry-after:' | tr -d '\r' | awk '{print $2}')
  body=$(head -c 220 /tmp/rl_body.txt)
  printf '%2d  HTTP %s  Retry-After=%s  %s\n' "$i" "$code" "${retry:-<khong co>}" "$body"
  short=$(printf '%s' "$body" | sed -n 's/.*"code"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  [[ -n "$short" ]] && codes+=("$short")
done

echo
echo "Kết thúc lúc $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC"

if [[ "$KEEP_LINKS" != "1" && ${#codes[@]} -gt 0 ]]; then
  echo
  echo "Xoá ${#codes[@]} link test vừa tạo (chủ sở hữu $OWNER):"
  for c in "${codes[@]}"; do
    st=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "https://$CF_DOMAIN/api/links/$c" -H "X-Owner-Id: $OWNER")
    echo "  DELETE $c -> $st"
  done
fi
