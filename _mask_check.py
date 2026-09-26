# -*- coding: utf-8 -*-
"""mask 不得裁掉内容 —— 现有测试的盲区。

为什么必须单独测：
  · 基线图用 win.grab() 整窗渲染，**看不见 mask 与"该画什么"之间的一致性**；
  · 逻辑测试只验"点击能不能命中"，验不到"像素会不会被裁"。
而产品的 mask 是双用途的：既做点击穿透区，又是 setMask 的可见范围。
一旦某个元素画在 mask 之外，它会被**静默裁掉**（不是画错，是根本看不见），
同时那一块的脏区也不含它 → 残影。

判据：把 mask 摘掉渲染出"本来要画出来的全部内容"（content），
      逐像素检查 content 的非透明像素是否都落在 build_mask() 返回的 region 内。
      落在 region 外的像素 = 会被裁掉的像素。

性能说明：第一版逐像素调 QImage.pixelColor()，900x620 x 十几个用例要上千万次
Python->C++ 调用，慢到没法用。改成 img.constBits() 取原始字节（ARGB32 小端，
alpha 在 offset 3）+ 纯 Python 判矩形，快两个数量级。

用法：python _mask_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _golden as G                          # noqa: E402  复用它的 QApplication 与夹具
from PySide6.QtGui import QImage             # noqa: E402

# ★ 必须显式 setup()。_golden 的场景是**延迟构建**的（模块级不建 Overlay），
# 不调这一步拿到的 G.WIN 是 None —— 之前踩过：直接 G.WIN 后面全线 AttributeError。
G.setup(verbose=False)
WIN = G.WIN
FAILS = []
CHECKS = []


def check(name, cond, extra=''):
    CHECKS.append((name, bool(cond)))
    print(('PASS' if cond else 'FAIL') + ' - ' + name + (('  ' + extra) if extra else ''))
    if not cond:
        FAILS.append(name)


def content_pixels(win):
    """摘掉 mask 渲染，得到"本来要画出来的全部内容"。"""
    win.clearMask()
    win._prev_mask = None      # setMask_skip 的幂等缓存必须一起失效，否则 mask 设不回去
    pm = win.grab()
    return pm.toImage().convertToFormat(QImage.Format_ARGB32)


def outside_stats(win):
    """返回 (内容非透明像素数, region 外像素数, 外溢包围盒或 None)"""
    img = content_pixels(win)
    region = win.build_mask()                 # 顺带把真实 mask 设回去
    # ★ PySide6 的 QRegion **没有 rects()**（Qt5 的 QRegion::rects 已废），
    # 但它支持序列协议，直接迭代就能逐个拿到 QRect。踩过一次 AttributeError。
    rects = [(r.x(), r.y(), r.width(), r.height()) for r in region]
    if not rects:
        # region 为空 = 整个窗口都该被裁掉，那一定是探针自己坏了，别让它装成"全外溢"
        raise AssertionError('build_mask() 返回了空 region，探针不可信')

    w, h = img.width(), img.height()
    sx = win.w / float(w)
    sy = win.h / float(h)
    stride = img.bytesPerLine()
    raw = img.constBits()
    data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)

    total = out = 0
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(h):
        ly = int(y * sy)
        base = y * stride
        for x in range(w):
            if data[base + x * 4 + 3] <= 8:       # ARGB32 小端：alpha 在第 4 字节
                continue
            total += 1
            lx = int(x * sx)
            inside = False
            for (rx, ry, rw, rh) in rects:
                if rx <= lx < rx + rw and ry <= ly < ry + rh:
                    inside = True
                    break
            if not inside:
                out += 1
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                if y > y1:
                    y1 = y
    box = None if out == 0 else (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))
    return total, out, box


def reset_state():
    """复位到"两只虫、无糖无蛋无笼"的干净态。"""
    w = WIN
    w.flies, w.eggs, w.foods = [], [], []
    w.pher, w.fx, w.cage = [], [], None
    w.reminders, w.announce = [], None
    w.drag_hover, w.drop_fly_hover = False, None
    w.pending_place, w.capture_mode = False, False
    w.focus, w.clock_fid = None, 0
    w.cfg['paused'] = True
    w.cfg['show_labels'] = True
    w.cfg['scale'] = 1.0
    G.fit(w)
    w.update()


LONG = '收纳 3 个文件 → C:\\Users\\you\\Desktop\\收集\\2026 年度归档 项目文件 906'

print('=' * 72)
print('用例 A：基准态（内容应当全部落在 mask 内）')
print('=' * 72)
reset_state()
G.mkfly(WIN, 300.0, 300.0)
G.mkfly(WIN, 600.0, 380.0)
tot, out, box = outside_stats(WIN)
check('基准态：内容全部在 mask 内', out == 0, '%d/%d 外溢 %s' % (out, tot, box))

print()
print('=' * 72)
print('用例 B：传说个体金色光晕 × 整体缩放')
print('  不变式：光晕半径与 mask 半径都由 fly_paint_radius() 给出（同一处）')
print('  曾经的 Bug：绘制写 20+22*sm（不乘 scale），mask 写 46*scale*ss*sm（乘了）')
print('  → scale=0.70 时光晕外溢 1256 px，被 setMask 静默裁成方角')
print('=' * 72)
for sc in (0.5, 0.7, 0.87, 1.0, 1.5):
    reset_state()
    WIN.cfg['scale'] = sc
    f = G.mkfly(WIN, 450.0, 300.0, spd=1.8, siz=1.6, bold=1.4, hue=1.9)
    aura = (20.0 + 22.0 * f.size_factor()) * sc      # 光晕最外圈的应有半径（独立算式，不调产品代码）
    tot, out, box = outside_stats(WIN)
    print('   scale=%.2f  应有光晕半径≈%.0f  mask 半径=%.0f  外溢 %d/%d  box=%s'
          % (sc, aura, WIN.fly_paint_radius(f), out, tot, box))
    # 失败信息只报**实测外溢**：不要拿上面那个"应有半径"去和 mask 比，
    # 因为一旦 Bug 被注入，实际画出来的半径就不再等于这个数，
    # 会出现"需 23 而 mask 给 27"却照样失败的读起来自相矛盾的输出。
    check('scale=%.2f：传说光晕不被裁' % sc, out == 0,
          '' if out == 0 else 'mask 之外仍有 %d px 内容（包围盒 %s）' % (out, box))

print()
print('=' * 72)
print('用例 C：气泡宽度 × 虫的横向位置')
print('  不变式：mask 用 bubble_rect()，与 draw_bubble 共用同一个矩形')
print('  曾经的 Bug：mask 写死 180px 宽、以 fly.x 为中心，而绘制宽度是')
print('  advance(text)+18 且会夹到窗口内 → 长气泡两端被切（外溢 3912 px）')
print('=' * 72)
for label, txt, fx in (('短气泡/居中', '基线气泡', 450.0),
                       ('长气泡/居中', LONG, 450.0),
                       ('长气泡/贴左缘', LONG, 20.0),
                       ('长气泡/贴右缘', LONG, 880.0),
                       ('长气泡/顶端翻下', LONG, 450.0)):
    reset_state()
    f = G.mkfly(WIN, fx, 20.0 if '顶端' in label else 300.0)
    f.bubble = [txt, 0.0, 3.2]
    tot, out, box = outside_stats(WIN)
    print('   %-16s 外溢 %d/%d  box=%s' % (label, out, tot, box))
    check('气泡不被裁：%s' % label, out == 0,
          '' if out == 0 else '外溢 %d px box=%s' % (out, box))

print()
print('=' * 72)
print('用例 D：其它元素（蛋 / 糖 / 粒子 / 信息素 / 笼子三态 / 报时牌）')
print('=' * 72)
reset_state()
WIN.eggs = [{'x': 420, 'y': 300, 'age': 12.0, 'gene': G.pet.new_gene(), 'skin': None},
            {'x': 470, 'y': 300, 'age': G.pet.EGG_TIME * 0.9,
             'gene': G.pet.new_gene(), 'skin': None}]
WIN.foods = [{'x': 700.0, 'y': 260.0, 'e': G.pet.FOOD_E0},
             {'x': 745.0, 'y': 260.0, 'e': G.pet.FOOD_E0 * 0.05}]
WIN.fx = [{'x': 300, 'y': 300, 'age': 0.2, 'color': (255, 240, 200), 'life': 0.7},
          {'x': 340, 'y': 300, 'age': 0.4, 'color': (255, 255, 255), 'life': 1.2, 'char': 'z'}]
WIN.pher = [{'x': 520, 'y': 400, 'age': 0.0},
            {'x': 570, 'y': 400, 'age': G.pet.PHER_TAU * 3}]
tot, out, box = outside_stats(WIN)
check('蛋/糖/粒子/信息素 都不外溢', out == 0, '%d/%d %s' % (out, tot, box))

for locked in (False, True):
    for hover in (False, True):
        reset_state()
        WIN.cage = {'x': 480, 'y': 120, 'w': G.pet.CAGE_W,
                    'h': G.pet.CAGE_H, 'locked': locked}
        WIN.drag_hover = hover
        tot, out, box = outside_stats(WIN)
        check('笼子 locked=%s hover=%s 不外溢' % (locked, hover), out == 0,
              '%d/%d %s' % (out, tot, box))

reset_state()
f = G.mkfly(WIN, 700.0, 300.0)
f.fid = 1
WIN.clock_fid = 1
tot, out, box = outside_stats(WIN)
check('报时牌不外溢', out == 0, '%d/%d %s' % (out, tot, box))

print()
print('=' * 72)
print('用例 E：窗口尺寸（多分辨率 / 小窗口下的稳健性）')
print('=' * 72)
for W, H in ((320, 240), (640, 480), (900, 620), (1600, 900)):
    reset_state()
    WIN.w, WIN.h = W, H
    WIN.setGeometry(0, 0, W, H)
    G.mkfly(WIN, W * 0.5, H * 0.5)
    G.mkfly(WIN, W * 0.8, H * 0.3)
    fb = G.mkfly(WIN, W * 0.5, H * 0.8)
    fb.bubble = [LONG, 0.0, 3.2]
    tot, out, box = outside_stats(WIN)
    check('%dx%d 下内容不外溢' % (W, H), out == 0, '%d/%d %s' % (out, tot, box))

print()
print('=' * 72)
npass = sum(1 for _, ok in CHECKS if ok)
print('共 %d 项，通过 %d，失败 %d' % (len(CHECKS), npass, len(FAILS)))
if FAILS:
    print('失败清单：')
    for n in FAILS:
        print('  · ' + n)
print('=' * 72)
sys.exit(1 if FAILS else 0)
