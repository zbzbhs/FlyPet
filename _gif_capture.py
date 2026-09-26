# -*- coding: utf-8 -*-
"""离屏渲染一段演示动图（README 用）。

为什么要"离屏"而不是录屏：
  1. 桌宠是透明覆盖窗，录屏必然把用户桌面上的私人窗口一起拍进去；
  2. grab() 渲染的是窗口自身内容，与屏幕无关 —— 干净、可控、可复现。

做法：真启动世界模拟（paused=False，虫会飞、会社交、会追糖），
     但不 show() 窗口，只按 140ms 一帧 grab() 窗口内容，
     摘掉 mask 拿到完整画面，合成到深色底上，最后拼成 GIF。
     中途 feed() 一次，让画面里有"投喂 → 虫群聚过来吃"的情节。

用法：python _gif_capture.py [输出路径]   （须用打包同源解释器跑）
"""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer                    # noqa: E402
from PySide6.QtGui import QImage                     # noqa: E402
from PIL import Image                                # noqa: E402

import pet                                           # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else 'assets/demo.gif'

# 存档/配置指到临时目录，绝不动真实数据
_td = tempfile.mkdtemp(prefix='flypet_gif_')
pet.SETTINGS_PATH = os.path.join(_td, 'settings.json')
pet.SAVE_PATH = os.path.join(_td, 'pet.json')

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

random.seed(7)
cfg = pet.load_settings()
cfg['count'] = 14
cfg['paused'] = False
cfg['show_labels'] = True
cfg['scale'] = 1.0
win = pet.Overlay(cfg)          # 构造期会按 count 自动建虫

BG = (24, 26, 34)               # GIF 的底色（比纯黑柔和）
MAXF = 52                       # 52 帧 × 140ms ≈ 7.3 秒
# 全屏窗里虫只有几十像素，直接缩到 640 宽会小得看不清。
# 裁出虫群出生区（屏幕中带）再缩放，等效 2 倍变焦。
CROP_W, CROP_H = 960, 640


def one_frame():
    win.clearMask()
    win._prev_mask = None       # setMask_skip 的幂等缓存必须一起失效
    pm = win.grab()
    img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    raw = img.constBits()
    raw = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else bytes(raw)
    rows = [raw[y * bpl: y * bpl + w * 4] for y in range(h)]
    pil = Image.frombytes('RGBA', (w, h), b''.join(rows))
    bg = Image.new('RGB', (w, h), BG)
    bg.paste(pil, (0, 0), pil)                     # alpha 做蒙版合成
    # 裁中心带（虫出生 + 投喂点都在这），再缩到 640 宽
    cx, cy = w * 0.5, h * 0.45
    x0 = int(max(0, min(w - CROP_W, cx - CROP_W / 2)))
    y0 = int(max(0, min(h - CROP_H, cy - CROP_H / 2)))
    bg = bg.crop((x0, y0, x0 + CROP_W, y0 + CROP_H))
    tw = 640
    bg = bg.resize((tw, round(CROP_H * tw / CROP_W)), Image.LANCZOS)
    FRAMES.append(bg)

    state['i'] += 1
    if state['i'] == 12:        # 第 12 帧投喂一次，制造"虫群聚糖"的情节
        win.feed(win.w * 0.5, win.h * 0.5)
    if state['i'] >= MAXF:
        timer.stop()
        os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
        FRAMES[0].save(OUT, save_all=True, append_images=FRAMES[1:],
                       duration=140, loop=0, optimize=True)
        print('GIF=%s  frames=%d  %.0f KB' % (
            OUT, len(FRAMES), os.path.getsize(OUT) / 1024))
        app.quit()


FRAMES = []
state = {'i': 0}
timer = QTimer()
timer.timeout.connect(one_frame)
timer.start(140)
QTimer.singleShot(30000, app.quit)   # 兜底：30s 没采完也退出
app.exec()
