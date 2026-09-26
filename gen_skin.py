# -*- coding: utf-8 -*-
"""
生成 4 套默认像素皮肤（skins/）：小果蝇 / 蜜蜂 / 萤火虫 / 蝴蝶
全部 24x24 朝右、6 帧扇翅循环，由同一个连接组脑驱动。
运行：python gen_skin.py（需 PySide6）
"""
import os
import sys
import math

from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QPen
from PySide6.QtCore import Qt, QPointF

S = 24
N = 6


def px(p, x, y, c):
    p.fillRect(int(round(x)), int(round(y)), 1, 1, c)


def ellipse_px(p, cx, cy, rx, ry, c1, c2=None):
    """简易像素椭圆：外圈 c2、内部 c1"""
    c2 = c2 or c1
    for x in range(int(cx - rx), int(cx + rx) + 1):
        for y in range(int(cy - ry), int(cy + ry) + 1):
            d = ((x - cx) / max(rx, 0.4)) ** 2 + ((y - cy) / max(ry, 0.4)) ** 2
            if d <= 1.0:
                px(p, x, y, c2 if d > 0.55 else c1)


WING = QColor(205, 224, 255, 145)
WING2 = QColor(230, 240, 255, 100)


def draw_wings(p, cx, cy, flap, span=1.0, color=WING, color2=WING2, drop=0.0):
    for s in (-1, 1):
        ang = s * (0.45 + flap * 0.55)
        for t in range(1, int(6 * span) + 1):
            wx = cx - 1 - t * 0.6
            wy = cy + s * (2 + t * math.sin(ang) * 1.4) + drop
            px(p, wx, wy, color if t < 4 else color2)


def legs(p, cx, cy, phase):
    p.setPen(QPen(QColor(45, 45, 54), 1))
    for s in (-1, 1):
        for k, base in enumerate((-3, 0, 3)):
            lx = cx - 3 + k * 3
            p.drawLine(QPointF(lx, cy + s * 3),
                       QPointF(lx + base * 0.4, cy + s * 6))


# ----------------------------- 小果蝇 -----------------------------
def fly_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    cx, cy = 10, 12
    flap = math.sin(phase)
    draw_wings(p, cx, cy, flap)
    ellipse_px(p, cx - 3, cy, 3.2, 3.4, QColor('#3d3d4a'), QColor('#26262e'))
    ellipse_px(p, cx + 1.5, cy, 2.2, 3.0, QColor('#35353f'))
    ellipse_px(p, cx + 4.5, cy, 1.8, 2.2, QColor('#2a2a33'))
    px(p, cx + 5, cy - 2, QColor('#a02838'))
    px(p, cx + 5, cy + 2, QColor('#a02838'))
    px(p, cx + 6, cy - 1, QColor('#a02838'))
    px(p, cx + 6, cy + 1, QColor('#a02838'))
    px(p, cx + 6, cy, QColor(255, 255, 255, 160))
    legs(p, cx, cy, phase)
    p.end()
    return img


# ----------------------------- 蜜蜂 -----------------------------
BEE_Y = QColor('#f4c531')
BEE_K = QColor('#26221a')
BEE_W = QColor(225, 240, 255, 150)
BEE_W2 = QColor(245, 250, 255, 95)


def bee_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    flap = math.sin(phase)
    bob = 1 if int(phase / (2 * math.pi) * N) % 2 else -1
    cx, cy = 10, 12 + bob
    # 圆翅（蜜蜂翅短圆）
    for s in (-1, 1):
        lift = flap * 2.2 * s
        ellipse_px(p, cx - 1, cy + s * (3 - abs(flap) * 1.2) + lift * 0.3,
                   4.2, 2.2, BEE_W, BEE_W2)
    # 身体：黄底黑纹（椭圆横向 3 格纹）
    ellipse_px(p, cx, cy, 6.2, 4.4, BEE_Y, BEE_K)
    for sx in (cx - 2, cx + 1):
        for dy in range(-4, 5):
            if abs(dy) <= 4 * math.sqrt(max(0.0, 1 - ((sx - cx) / 6.2) ** 2)) + 0.4:
                px(p, sx, cy + dy, BEE_K)
    # 头
    ellipse_px(p, cx + 6, cy, 2.4, 2.6, BEE_K)
    px(p, cx + 7, cy - 1, QColor(255, 255, 255, 190))
    # 螫针
    px(p, cx - 7, cy, BEE_K)
    p.end()
    return img


# ----------------------------- 萤火虫 -----------------------------
GLOW = [QColor(200, 255, 130, a) for a in (110, 150, 200, 230, 200, 150)]


def firefly_frame(phase):
    idx = int(phase / (2 * math.pi) * N) % N
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    cx, cy = 10, 12
    flap = math.sin(phase)
    draw_wings(p, cx, cy, flap, span=0.8,
               color=QColor(190, 210, 235, 120), color2=QColor(220, 235, 255, 80))
    # 发光腹部（脉动）
    g = GLOW[idx]
    ellipse_px(p, cx - 4.5, cy, 3.6, 3.0, g)
    ellipse_px(p, cx - 4.5, cy, 2.2, 1.8, QColor(245, 255, 190))
    # 深色身体
    ellipse_px(p, cx + 1, cy, 3.4, 2.8, QColor('#4a4038'), QColor('#2e2822'))
    ellipse_px(p, cx + 5, cy, 2.0, 2.2, QColor('#3a332c'))
    px(p, cx + 6, cy - 1, QColor('#ffd76a'))
    px(p, cx + 6, cy + 1, QColor('#ffd76a'))
    p.end()
    return img


# ----------------------------- 蝴蝶 -----------------------------
BF_W1 = QColor('#e77fb3')
BF_W2 = QColor('#8e5fd4')
BF_W3 = QColor(255, 255, 255, 170)


def butterfly_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    cx, cy = 11, 12
    # 展翅系数：0.25(合拢)~1(展开)
    spread = 0.3 + 0.7 * abs(math.sin(phase * 0.9))
    for s in (-1, 1):
        wy = s * 5.0 * spread
        # 上翅
        ellipse_px(p, cx - 1, cy + wy * 0.75, 5.5 * spread + 1.5, 3.2 * spread + 1.0,
                   BF_W1 if s < 0 else BF_W2, BF_W2)
        # 下翅
        ellipse_px(p, cx - 3, cy + wy * 1.25, 3.8 * spread + 1.0, 2.4 * spread + 0.8,
                   BF_W2 if s < 0 else BF_W1, BF_W1)
        # 翅斑
        if spread > 0.55:
            px(p, cx - 2, cy + wy * 0.7, BF_W3)
            px(p, cx - 4, cy + wy * 1.2, BF_W3)
    # 身体
    ellipse_px(p, cx + 2, cy, 3.4, 1.6, QColor('#3a3040'))
    # 触角
    px(p, cx + 5, cy - 2, QColor('#3a3040'))
    px(p, cx + 6, cy - 3, QColor('#3a3040'))
    px(p, cx + 5, cy + 2, QColor('#3a3040'))
    px(p, cx + 6, cy + 3, QColor('#3a3040'))
    p.end()
    return img


# ----------------------------- 蜻蜓 -----------------------------
DF_B = QColor('#2e9aa8')
DF_D = QColor('#1d6b76')
DF_W = QColor(200, 235, 250, 125)


def dragonfly_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    cx, cy = 10, 12
    flap = math.sin(phase)
    # 两对长薄翅（上/下各一对，扑动明显）
    for s in (-1, 1):
        wy = cy + s * (3.2 - flap * 1.8 * s)
        ellipse_px(p, cx - 2, wy, 6.0, 1.3, QColor(205, 240, 252, 165))
        px(p, cx + 1, wy, QColor(230, 248, 255, 200))
    # 分节长尾（越往尾越细，蓝绿相间）
    for k in range(6):
        ellipse_px(p, cx - 3 - k * 1.7, cy, 1.4 - k * 0.1, 1.05,
                   DF_B if k % 2 else DF_D)
    # 胸（粗壮）
    ellipse_px(p, cx + 2, cy, 2.6, 2.4, DF_B, DF_D)
    # 大复眼（几乎占满头部）
    ellipse_px(p, cx + 5, cy, 2.0, 2.2, QColor('#16323c'))
    px(p, cx + 5, cy - 1, QColor(255, 255, 255, 190))
    px(p, cx + 6, cy + 1, QColor(255, 255, 255, 120))
    p.end()
    return img


# ----------------------------- 蜂鸟 -----------------------------
HB_G = QColor('#3fae6a')
HB_D = QColor('#207a4a')
HB_R = QColor('#e0485f')


def hummingbird_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    flap = math.sin(phase)
    cx, cy = 10, 12
    # 高频翅：上下大幅挥动（两帧位置差很大=模糊感）
    for s in (-1, 1):
        wy = cy - 3 + s * (2.5 - flap * 3.0)
        ellipse_px(p, cx - 1, wy, 4.8, 1.5, QColor(190, 240, 210, 150))
    # 圆身
    ellipse_px(p, cx, cy, 3.6, 3.0, HB_G, HB_D)
    # 红喉
    px(p, cx + 2, cy + 1, HB_R)
    px(p, cx + 3, cy + 1, HB_R)
    px(p, cx + 2, cy + 2, HB_R)
    # 头
    ellipse_px(p, cx + 4, cy - 1, 2.0, 1.9, HB_G, HB_D)
    px(p, cx + 5, cy - 2, QColor(255, 255, 255, 170))
    # 细长喙：深色喙 + 浅色上缘（深色桌面也可见）
    for k in range(7):
        px(p, cx + 6 + k, cy - 1, QColor('#15151a'))
        px(p, cx + 6 + k, cy - 2, QColor(205, 215, 230, 120))
    # 尾羽
    px(p, cx - 4, cy + 1, HB_D)
    px(p, cx - 5, cy + 2, HB_D)
    px(p, cx - 5, cy, HB_D)
    p.end()
    return img


# ----------------------------- 纸飞机 -----------------------------
PP_W = QColor(236, 241, 248)
PP_S = QColor(186, 196, 210)
PP_L = QColor(122, 132, 148)


def paperplane_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    tilt = math.sin(phase * 0.8)
    cx, cy = 11, 12 + (1 if tilt > 0.5 else (-1 if tilt < -0.5 else 0))
    # 机头朝右：上翼亮、下翼暗
    for t in range(-9, 1):
        x = cx + t
        half = max(0, int(-t * 0.45))
        for dy in range(-half, half + 1):
            px(p, x, cy + dy, PP_W if dy <= 0 else PP_S)
        if half == 0:
            px(p, x, cy, PP_W)
    # 中折线
    for t in range(-9, 1):
        px(p, cx + t, cy, PP_L)
    # 尾迹虚线（闪两帧）
    idx = int(phase / (2 * math.pi) * N) % N
    if idx % 2 == 0:
        for k in range(3):
            px(p, cx - 11 - k * 2, cy, QColor(165, 180, 200, 130))
    p.end()
    return img


# ----------------------------- 小火箭 -----------------------------
RK_W = QColor(240, 244, 250)
RK_E = QColor(200, 208, 220)
RK_R = QColor('#e0483f')
FLAME = [QColor('#ffd76a'), QColor('#ff9d3c'), QColor('#ff6a2a')]


def rocket_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    idx = int(phase / (2 * math.pi) * N) % N
    cx, cy = 10, 12 + (1 if idx % 2 else -1)
    # 箭体（右为鼻锥）
    ellipse_px(p, cx, cy, 5.5, 2.4, RK_W, RK_E)
    ellipse_px(p, cx + 5, cy, 2.0, 1.8, RK_R)
    px(p, cx + 7, cy, RK_R)
    # 舷窗
    ellipse_px(p, cx + 2, cy, 1.3, 1.3, QColor('#7fd4f0'), QColor('#2e8fa3'))
    # 尾翼
    px(p, cx - 5, cy - 3, RK_R)
    px(p, cx - 6, cy - 4, RK_R)
    px(p, cx - 5, cy + 3, RK_R)
    px(p, cx - 6, cy + 4, RK_R)
    # 抖动火焰（每帧变长变短）
    fl = 2 + idx % 3
    for k in range(fl):
        c = FLAME[(idx + k) % 3]
        px(p, cx - 7 - k, cy, c)
        if k < 2:
            px(p, cx - 7 - k, cy - 1, FLAME[idx % 3])
            px(p, cx - 7 - k, cy + 1, FLAME[(idx + 1) % 3])
    p.end()
    return img


# ----------------------------- 飞碟 -----------------------------
UF_B = QColor('#9aa7b5')
UF_D = QColor('#5d6a78')
LIGHTS = [QColor('#ffe066'), QColor('#7fd4f0'), QColor('#ff8fa3'),
          QColor('#a3f97f'), QColor('#c5a3ff'), QColor('#ffb36a')]


def ufo_frame(phase):
    img = QImage(S, S, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    idx = int(phase / (2 * math.pi) * N) % N
    cx, cy = 11, 12 + (1 if idx % 2 else 0)
    # 玻璃罩 + 小外星人剪影
    ellipse_px(p, cx + 1, cy - 3.2, 2.6, 2.1, QColor(160, 240, 200, 130),
               QColor(90, 200, 160, 100))
    px(p, cx + 1, cy - 3, QColor('#3a6b52'))
    ellipse_px(p, cx + 1, cy - 2.2, 0.8, 0.8, QColor('#3a6b52'))
    # 盘身
    ellipse_px(p, cx, cy, 8, 2.6, UF_B, UF_D)
    ellipse_px(p, cx, cy + 2, 5, 1.4, UF_D)
    # 边缘灯轮转
    for k in range(4):
        px(p, cx - 6 + k * 4, cy + 1, LIGHTS[(idx + k) % 6])
    # 底部牵引光
    ellipse_px(p, cx, cy + 5.5, 3.0, 1.0, QColor(160, 240, 200, 45))
    p.end()
    return img


SKINS = [
    # (名, 中文名, 帧函数, fps, size, speed_scale, size_scale)
    ('pixel', '小果蝇', fly_frame, 22, 44, 1.0, 1.0),
    ('bee', '蜜蜂', bee_frame, 20, 46, 0.9, 0.95),
    ('firefly', '萤火虫', firefly_frame, 16, 44, 0.8, 0.9),
    ('butterfly', '蝴蝶', butterfly_frame, 9, 50, 0.65, 1.25),
    ('dragonfly', '蜻蜓', dragonfly_frame, 20, 46, 1.15, 1.0),
    ('hummingbird', '蜂鸟', hummingbird_frame, 24, 42, 1.1, 0.85),
    ('paperplane', '纸飞机', paperplane_frame, 8, 50, 1.3, 1.0),
    ('rocket', '小火箭', rocket_frame, 14, 52, 1.6, 1.05),
    ('ufo', '飞碟', ufo_frame, 10, 56, 0.85, 1.25),
]


def main():
    app = QGuiApplication(sys.argv[:1])
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skins')
    for name, _cn, fn, fps, size, spd, szs in SKINS:
        out = os.path.join(base, name)
        os.makedirs(out, exist_ok=True)
        for i in range(N):
            fn(i / N * 2 * math.pi).save(os.path.join(out, '%s_%02d.png' % (name, i)))
        with open(os.path.join(out, 'skin.json'), 'w', encoding='utf-8') as f:
            f.write('{\n  "fps": %d,\n  "size": %d,\n  "facing": "right",\n'
                    '  "speed_scale": %.2f,\n  "size_scale": %.2f\n}\n' % (fps, size, spd, szs))
        print('generated ->', out)
    # 皮肤中文名映射（托盘显示用）
    with open(os.path.join(base, 'names.json'), 'w', encoding='utf-8') as f:
        import json
        json.dump({n: cn for n, cn, *_ in SKINS}, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
