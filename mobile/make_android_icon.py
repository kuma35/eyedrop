#!/usr/bin/env python3
"""make Android adaptive icon foreground from a transparent icon image

JP:
背景が透明のアイコン画像から、Android 用の icon_android.png を作る。

Flet は src/assets/icon_android.png があれば余白を付けずにそのまま使う。
図(透明でない部分)を囲む最小の円の中心をアイコンの中心に置き、
丸く切り抜いても欠けない安全な円(前景 108dp のうち直径 66dp)に収まる
最大の大きさにする(少し余裕を残す)。Pillow が必要(flet と一緒に入っている)。

使い方(mobile/ で):
    ../venv/bin/python make_android_icon.py src/assets/eyedrop-stock-icon.png
"""
import math
import sys
from pathlib import Path

from PIL import Image

SIZE = 1024
SAFE_RADIUS = SIZE * 66 / 108 / 2   # 安全な円の半径(313px)
MARGIN = 8                           # 安全な円からさらに内側に残す余裕(px)
OUT = Path(__file__).resolve().parent / 'src' / 'assets' / 'icon_android.png'


def enclosing_center(points, width, height):
    """center of (approximately) smallest circle enclosing points

    JP:
    図を囲む最小の円の中心(の近似)。格子で探す。
    """
    best = None
    for cy in range(int(height * 0.3), int(height * 0.7) + 1, 2):
        for cx in range(int(width * 0.3), int(width * 0.7) + 1, 2):
            radius = max(math.hypot(x - cx, y - cy) for x, y in points)
            if best is None or radius < best[0]:
                best = (radius, cx, cy)
    return best


def main(source: str) -> int:
    src = Image.open(source).convert('RGBA')
    src = src.crop(src.getbbox())
    width, height = src.size
    alpha = src.getchannel('A').load()
    # 図の点を4画素おきに間引いて使う(速くするため)
    points = [(x, y) for y in range(0, height, 4) for x in range(0, width, 4)
              if alpha[x, y] > 16]
    radius, cx, cy = enclosing_center(points, width, height)
    scale = (SAFE_RADIUS - MARGIN) / radius
    img = src.resize((round(width * scale), round(height * scale)),
                     Image.LANCZOS)
    out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    left = round(SIZE / 2 - cx * scale)
    top = round(SIZE / 2 - cy * scale)
    out.paste(img, (left, top), img)
    out.save(OUT)
    out_alpha = out.getchannel('A').load()
    far = max(math.hypot(x - SIZE / 2 + 0.5, y - SIZE / 2 + 0.5)
              for y in range(SIZE) for x in range(SIZE)
              if out_alpha[x, y] > 16)
    box = out.getbbox()
    print(f'{OUT}: 倍率 {scale:.3f}、図 {box[2] - box[0]}x{box[3] - box[1]}、'
          f'最も遠い画素 {far:.0f}px / 安全な円 {SAFE_RADIUS:.0f}px')
    return 0 if far <= SAFE_RADIUS else 1


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
