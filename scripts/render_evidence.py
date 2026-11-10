"""Render output kiem thu thanh anh chung de dung trong docs (TV5, issue #27).

Dung:
    python scripts/render_evidence.py <file.txt> <file.png> ["Tieu de"]

Chay duoi Windows can dat bien moi truong PYTHONUTF8=1 va PYTHONIOENCODING=utf-8
de in ra terminal khong loi UnicodeEncodeError.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

BG = (24, 26, 32)
FG = (222, 226, 233)
CHROME = (44, 47, 56)
ACCENT = (122, 162, 247)
GREEN = (126, 211, 135)
RED = (247, 140, 140)
YELLOW = (229, 192, 123)


def load_font(size, bold=False):
    names = ["consolab.ttf"] if bold else ["consola.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    for n in (["consolab.ttf", "arialbd.ttf"] if bold else ["consola.ttf", "arial.ttf"]):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def color_for(line):
    s = line.strip()
    if s.startswith("HTTP 201") or " -> 204" in s or '"created": true' in s:
        return GREEN
    if "HTTP 429" in s or "HTTP 4" in s or "HTTP 5" in s or "Too Many Requests" in s \
            or "rate_limited" in s or "blocked_domain" in s:
        return RED
    if s.startswith("---") or s.startswith("===") or s.startswith("Bắt đầu") \
            or s.startswith("Kết thúc") or s.startswith("###"):
        return ACCENT
    if '"cnt"' in s or '"N"' in s or '"S"' in s or '"Count"' in s:
        return YELLOW
    return FG


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(src)

    with open(src, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    f_body = load_font(17)
    f_title = load_font(20, bold=True)
    f_small = load_font(15)

    pad = 22
    chrome_h = 44
    line_h = 25
    width = 1700
    body_h = max(line_h * len(lines), 40)
    height = chrome_h + pad * 2 + body_h + 40

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # Thanh tiêu đề giống cửa sổ terminal
    d.rectangle([0, 0, width, chrome_h], fill=CHROME)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([18 + i * 22, 15, 30 + i * 22, 27], fill=c)
    d.text((width // 2 - d.textlength(title, font=f_title) / 2, 11), title,
           font=f_title, fill=FG)

    y = chrome_h + pad
    for line in lines:
        d.text((pad, y), line, font=f_body, fill=color_for(line))
        y += line_h

    d.text((pad, height - 28),
           f"{len(lines)} dong · {src}",
           font=f_small, fill=(130, 136, 150))
    img.save(dst)
    print(f"Đã tạo {dst} ({width}x{height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
