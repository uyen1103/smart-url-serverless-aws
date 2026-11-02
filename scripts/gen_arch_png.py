"""Sinh docs/architecture.png từ kiến trúc trong docs/architecture.md (TV5).

Cách dùng:  python scripts/gen_arch_png.py
Yêu cầu:     pip install pillow
"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 2400, 1500
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
try:
    f_title = ImageFont.truetype("arialbd.ttf", 54)
    f_h = ImageFont.truetype("arialbd.ttf", 32)
    f_b = ImageFont.truetype("arial.ttf", 25)
    f_s = ImageFont.truetype("arial.ttf", 22)
except Exception:
    f_title = ImageFont.load_default()
    f_h = f_b = f_s = f_title


def box(x, y, w, h, fill, outline, title, lines):
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=fill, outline=outline, width=3)
    d.text((x + 20, y + 12), title, font=f_h, fill="black")
    yy = y + 58
    for ln in lines:
        d.text((x + 20, yy), ln, font=f_b, fill="#222222")
        yy += 33


d.text((60, 30), "LinkPulse Architecture - Serverless on AWS", font=f_title, fill="#111111")
d.text((60, 95), "ap-southeast-2 workload / WAF us-east-1 CLOUDFRONT - TV5 - Week 2 #11", font=f_s, fill="#333333")

box(60, 150, 520, 400, "#E8F0FE", "#1a73e8", "Client", [
    "Browser / Bot / Attacker",
    "Giao dien tinh: S3 + CloudFront",
    "index / dashboard / links",
    "protection / warning / error",
])
box(640, 150, 560, 400, "#FEF3C7", "#b45309", "Edge (CloudFront + WAF)", [
    "WAF us-east-1 scope CLOUDFRONT",
    "ShortenRateLimit 50/5'/IP",
    "GlobalRateLimit 1000/5'/IP",
    "AmazonIpReputation + CommonRuleSet",
    "Header X-Origin-Verify -> origin",
    "EnableWaf mac dinh false",
])
box(1260, 150, 520, 400, "#E9F7EF", "#137333", "HTTP API", [
    "POST /api/shorten (10 rps, burst 20)",
    "GET /{code}",
    "GET/DELETE /api/links",
    "GET /api/stats",
    "Toan API 100 rps, burst 200",
])
box(1840, 150, 500, 400, "#F3E8FD", "#7e22ce", "Ops & Secrets", [
    "Budget $5/mo + alarms",
    "WAF logs -> S3",
    "SSM Parameter Store SecureString",
    "origin-verify / turnstile-secret",
    "IAM least privilege + MFA",
])

for x in (580, 1200, 1780):
    d.polygon([(x, 340), (x + 60, 340), (x + 60, 320), (x + 90, 350),
               (x + 60, 380), (x + 60, 360), (x, 360)], fill="#111111")

box(60, 610, 560, 470, "#FFF7ED", "#c2410c", "Lambda shorten", [
    "validate_url 2 lop: cu phap + DNS",
    "Turnstile verify (bat buoc khi bat)",
    "rate_limits token-bucket 10/phut",
    "blocklist / Safe Browsing",
    "PutItem urls (attribute_not_exists)",
])
box(680, 610, 560, 470, "#ECFDF5", "#047857", "Lambda redirect", [
    "GetItem urls (1 read)",
    "blocked / expired / max_clicks",
    "suspicious -> can ?confirm=1",
    "ADD click_count co dieu kien",
    "PutItem clicks (TTL 30 ngay)",
])
box(1300, 610, 520, 470, "#EFF6FF", "#1d4ed8", "Workers", [
    "process_clicks: Stream NEW_IMAGE",
    "INSERT-only, batch 100 / 2 giay",
    "cong don stats theo phut",
    "abuse.evaluate -> suspicious",
    "stats_fn doc stats",
])
box(1880, 610, 460, 470, "#FEF2F2", "#b91c1c", "DynamoDB", [
    "urls PK short_code + GSI owner",
    "clicks TTL 30d + Stream",
    "stats PK scope / SK M#phut",
    "rate_limits TTL",
    "blocklist PK domain",
])

for x in (620, 1240, 1820):
    d.polygon([(x, 830), (x + 60, 830), (x + 60, 810), (x + 90, 840),
               (x + 60, 870), (x + 60, 850), (x, 850)], fill="#111111")

d.text((60, 1110), "TAO LINK: Client -> CF/WAF -> POST /api/shorten -> validate/Turnstile -> DynamoDB urls -> 201", font=f_s, fill="black")
d.text((60, 1150), "TRUY CAP: Client -> CF (TTL 0) -> GET /{code} -> GetItem -> 302 no-store -> PutItem clicks -> Stream -> stats", font=f_s, fill="black")
d.text((60, 1190), "TRUST: TB-0 client untrusted | TB-1 chi tin header CloudFront | TB-2 Lambda kiem tra | TB-3 conditional write", font=f_s, fill="black")
d.text((60, 1230), "Mermaid source = docs/architecture.md muc 2 | PNG cho Draw.io / bao cao | workload ap-southeast-2, WAF us-east-1", font=f_s, fill="black")
d.text((60, 1270), "TV5 - Week 2 - Issue #11", font=f_s, fill="#555555")

d.rectangle([40, 20, W - 40, H - 60], outline="#111111", width=4)
os.makedirs("docs", exist_ok=True)
img.save("docs/architecture.png")
print("saved", os.path.getsize("docs/architecture.png"))
