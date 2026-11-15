# -*- coding: utf-8 -*-
"""生成应用图标（docs/icon.ico + docs/icon.png）。用带 Pillow 的运行时执行：

    "C:\\Users\\39954\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe" dev/make_icon.py

设计上只做减法：深色圆角方块 + 一个「课」字，桌面 48px 下能认出是什么。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
SIZE = 256
BG = (16, 18, 22, 255)      # #101216
BORDER = (38, 43, 51, 255)  # #262b33
FG = (233, 236, 242, 255)   # #e9ecf2
ACCENT = (91, 156, 248, 255)  # #5b9cf8

FONTS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def load_font(px: int):
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return ImageFont.load_default()


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=54, fill=BG, outline=BORDER, width=3)

    # 「课」
    font = load_font(132)
    text = "课"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - tw) / 2 - box[0], (SIZE - th) / 2 - box[1] - 6), text, font=font, fill=FG)

    # 底部一条强调线：小尺寸下也能看出是「有标识的应用」
    d.rounded_rectangle((SIZE / 2 - 46, SIZE - 52, SIZE / 2 + 46, SIZE - 44), radius=4, fill=ACCENT)
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    img = build()
    png = OUT / "icon.png"
    img.save(png)
    ico = OUT / "icon.ico"
    img.save(ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"saved: {png} ({png.stat().st_size} B)")
    print(f"saved: {ico} ({ico.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
