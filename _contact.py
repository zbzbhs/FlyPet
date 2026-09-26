# -*- coding: utf-8 -*-
"""把 _golden/ 里的基线图拼成一张总览图，方便一眼看全网长什么样。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

os.environ['QT_FONT_DPI'] = '96'
app = QApplication(sys.argv[:1])
HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, '_golden')
OUT = os.path.join(HERE, '绘制基线_总览_第21轮.png')


def autocrop(img, pad=6, alpha_min=8):
    """裁到非透明区域的包围盒（留一点边距）。找不到内容就原样返回。"""
    x0, y0, x1, y1 = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > alpha_min:
                x0 = min(x0, x); y0 = min(y0, y)
                x1 = max(x1, x); y1 = max(y1, y)
    if x1 < 0:
        return img
    # 注意 QImage.copy 的第 3/4 个参数是**宽高**，不是右下角坐标。
    # 第一版把 x1+pad+1 当宽传进去了，裁出来的尺寸正好等于"右下角坐标"，
    # 于是蛋的格子显示成 436x496（= 429+6+1 和 489+6+1）—— 尺寸看着离谱才发现。
    nx0, ny0 = max(0, x0 - pad), max(0, y0 - pad)
    nx1 = min(img.width() - 1, x1 + pad)
    ny1 = min(img.height() - 1, y1 + pad)
    return img.copy(nx0, ny0, nx1 - nx0 + 1, ny1 - ny0 + 1)

ORDER = ['overlay', 'overlay_hud', 'overlay_clock', 'cage_unlocked', 'cage_locked',
         'cage_hover', 'egg_young', 'egg_hatching', 'clock_board', 'bubble',
         'skin_sprite', 'skin_procedural']
CELL_W, CELL_H, PAD, LAB = 460, 320, 14, 22
COLS = 3
ROWS = (len(ORDER) + COLS - 1) // COLS
W = PAD + COLS * (CELL_W + PAD)
H = PAD + ROWS * (CELL_H + LAB + PAD)

sheet = QPixmap(W, H)
sheet.fill(QColor('#f4f6f9'))
p = QPainter(sheet)
p.setRenderHint(QPainter.Antialiasing)
p.setRenderHint(QPainter.SmoothPixmapTransform)
p.setFont(QFont('Microsoft YaHei', 9))

for i, name in enumerate(ORDER):
    r, c = divmod(i, COLS)
    x = PAD + c * (CELL_W + PAD)
    y = PAD + r * (CELL_H + LAB + PAD)
    # 白底格子（基线图大多是透明的，铺白才看得见）
    p.setPen(QColor('#d5dbe3'))
    p.setBrush(QColor('#ffffff'))
    p.drawRect(x, y, CELL_W, CELL_H)
    img = QImage(os.path.join(GOLD, name + '.png'))
    if not img.isNull():
        # 自动裁到"有内容"的范围再放大：蛋、气泡这类目标在 900x620 画布上
        # 只占几十像素，不裁的话总览图里基本看不见，也就失去了"一眼看全网"的意义。
        img = autocrop(img)
        s = min(CELL_W / img.width(), CELL_H / img.height())
        w, h = img.width() * s, img.height() * s
        p.drawImage(QRectF(x + (CELL_W - w) / 2, y + (CELL_H - h) / 2, w, h), img)
    p.setPen(QColor('#1d2733'))
    p.drawText(QRectF(x, y + CELL_H + 2, CELL_W, LAB), Qt.AlignCenter,
               '%s   %d×%d' % (name, img.width(), img.height()))
p.end()
sheet.save(OUT)
print('已生成', OUT, sheet.width(), 'x', sheet.height())
