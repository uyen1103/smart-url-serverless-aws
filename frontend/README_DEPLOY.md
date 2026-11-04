# Deploy frontend LinkPulse

1. Cần AWS CLI đã cấu hình quyền cho bucket S3 private và CloudFront.
2. Đặt biến `S3_BUCKET` và `CLOUDFRONT_DISTRIBUTION_ID`.
3. Đọc preview trước khi upload:

```powershell
$env:S3_BUCKET = "ten-bucket"
$env:CLOUDFRONT_DISTRIBUTION_ID = "E123EXAMPLE"
.\frontend\deploy.ps1
```

4. Upload và chỉ invalidate các path đã đổi:

```powershell
.\frontend\deploy.ps1 -Execute -Invalidate
```

`deploy.ps1` không upload `prototype/` và không dùng invalidation `/*`.
Chạy xem trước local: `python -m http.server 8000 --directory frontend`.
Giữ `USE_MOCK=true` khi chạy mock; khi API thật sẵn sàng đổi thành `false`.
Chỉ điền `TURNSTILE_SITE_KEY` sau khi TV5 bật secret backend đồng thời.
Không commit access key, secret, bucket credential hoặc Turnstile secret.