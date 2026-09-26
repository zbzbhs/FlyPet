# -*- coding: utf-8 -*-
"""绘制基线（golden image）回归：把绘制结果定死成图片，之后每次跑都逐像素比对。

为什么需要这一套：
    _test_paths.py 能测"状态对不对"，但测不了"画出来长什么样"。
    绘制函数（_paint / draw_cage / draw_egg / draw_clock_board /
    draw_bubble / draw_skin / draw_procedural）此前**只被 _render_check.py
    的截图采样兜着** —— 只要不是整屏空白就算过。少画一块、颜色错、
    文字换成乱码、蛋的裂纹分支丢了……截图采样统统发现不了。

为什么这次能定死（关键前提）：
    这三处不确定性必须先冻住，否则基线图每次都不一样：
      ① 传说个体金色光晕：sin(time.monotonic()*2.2 + castSeed) —— 会呼吸
      ② 报时牌：显示当前时间，待办每 6 秒轮换一条
      ③ 构造期 random：基因、castSeed、皮肤帧起点
    冻法：pet.time 换成假模块（pet.py 里只用到 monotonic/localtime/strftime
    三个名字）、random.seed 固定、castSeed 显式钉死。
    另外 draw_skin 每调一次会自己推进 skinT，所以每帧渲染前要把它重置。

用法：
    python _golden.py            # 比对，有差异则退出码 1
    python _golden.py --update   # 重建基线（确认改动是预期内的才用）
"""
import json
import os
import random
import sys
import time

# ⚠ 必须在创建 QApplication 之前设，否则不生效。
# 为什么必须钉死字体 DPI：draw_bubble / draw_clock_board / 标签都是先量字体
# 再决定画多大（th = fm.height() + 10、w = horizontalAdvance(t) + 26）。
# 本机是 150% 缩放，同一份代码在不同进程里量出来的 fm.height() 会飘
# （实测 16 / 18），于是气泡与文字类基线图**跨进程永远对不上**，
# 而进程内连渲两次却是稳的 —— 这种"只在跨进程才现形"的不确定性最坑。
# 钉死 96 DPI + 关掉高 DPI 缩放后，渲染回到 1x，度量稳定且基线不随显示器变。
os.environ['QT_FONT_DPI'] = '96'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
os.environ['QT_SCALE_FACTOR'] = '1'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempfile

import pet
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD_DIR = os.path.join(HERE, '_golden')
UPDATE = '--update' in sys.argv
# ★ 判据是"逐字节相同"，不留百分比容差。
#
# 一开始留了 0.15% 的容差（想着吸收字体微调），结果反向注入当场打脸：
#   笼子锁定指示点从橙改绿（15x15 的点）→ 约 176 像素 = 0.03% → 判"通过"
#   蛋的裂纹整块不画 → 只有几十像素 → 也判"通过"
# 小范围但语义重大的改动全都能溜过去，这个网等于白织。
# 既然第 0 步已证明"同一状态渲染两次逐字节相同"，就没有理由留容差。
MAX_DIFF = 0

# 基线图的环境指纹。
#
# ★ 为什么必须记这个：基线图是**在某个 Qt 版本下**渲染出来的像素。
#   文字抗锯齿、圆角描边这些会随 Qt 版本变 —— 实测同一份代码、
#   同一台机器，PySide6 6.8.2.1（hermes venv / Python 3.11）与
#   6.11.2（打包用的 .workbuddy venv / Python 3.13）在 clock_board
#   上差 208 px（最大通道差 34）。量很小、不刺眼，但逐字节判据会红。
#
#   要命的不是差异本身，而是**基线一直是在非打包环境里生成的**：
#   exe 是拿打包环境（PySide6 6.11.2）打出来的，用户看到的是那一版渲染，
#   而基线守着的是另一版。等于这个网测的是用户根本看不到的画面。
#   更糟的是，一旦哪天在打包环境里跑一遍，会冒出 0.037% 的差异，
#   看上去像"绘制被改坏了"，实际只是换了 Qt —— 极难定位。
#
#   所以把环境指纹存进基线目录：不一致就直接报错并给出该用哪个解释器。
ENV_FILE = os.path.join(GOLD_DIR, '_env.json')

# 冻结用常量。todos 有 2 条时 int(1.7e9/6)%2 == 1，即固定显示第 2 条。
FIXED_MONO = 1_700_000_000.0
FIXED_LOCAL = time.struct_time((2026, 9, 25, 14, 30, 0, 4, 268, 0))
FIXED_SEED = 20260925

fails = []


def check(name, cond, extra=''):
    print(('PASS' if cond else 'FAIL'), '-', name, extra)
    if not cond:
        fails.append(name)


class _FakeTime:
    """把 pet.py 眼里的 time 冻住。别动真正的 time 模块，只换 pet 的名字。"""

    def __init__(self, mono, lt):
        self._mono, self._lt = mono, lt

    def monotonic(self):
        return self._mono

    def localtime(self, *a):
        return self._lt

    def strftime(self, *a):
        return time.strftime(*a)      # 只有 dbg_log 用得到


# ⚠ 下面这几件事**故意不放在模块级**。
#
# 它们原本是裸的模块级语句（pet.time = ... / app = QApplication(...) / 字体打印），
# 后果是 _coverage.py、_mask_check.py 这类"想复用它冻结好的渲染环境"的脚本，
# 一 import 就被塞进一个已经冻结、已经建好 QApplication 的世界：
#   · QApplication 是单例，先被本文件拿走的，import 方再建只会拿到同一个实例，
#     而它的 argv 已被截成 sys.argv[:1]，出问题时搞不清是谁建的；
#   · 字体度量那几行会在 import 时打印一段与调用方无关的噪音；
#   · pet.time 被换掉之后，调用方想测"真实时间驱动"的行为就没法测了。
# 改成显式 setup()，谁需要谁自己打开。
_app = None


def ensure_app():
    """建（或复用）QApplication。所有渲染函数都要求它已存在。"""
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


def report_font_metrics():
    """把字体度量打印出来：万一将来基线又飘，第一眼就能看出是不是它变了。"""
    pm = QPixmap(8, 8)
    p = QPainter(pm)
    p.setFont(QFont('Microsoft YaHei', 9))
    print('字体度量（基线稳定性关键量）: Microsoft YaHei 9pt → height=%d  '
          '"基线气泡" advance=%d  dpr=%s'
          % (p.fontMetrics().height(),
             p.fontMetrics().horizontalAdvance('基线气泡'),
             pm.devicePixelRatio()))
    p.end()


def freeze():
    """冻住一切不确定性来源。渲染前**必须**调用，否则基线毫无意义。"""
    ensure_app()
    pet.time = _FakeTime(FIXED_MONO, FIXED_LOCAL)
    random.seed(FIXED_SEED)
    # 探针绝不碰真实存档
    pet.SAVE_PATH = os.path.join(tempfile.mkdtemp(prefix='flypet_gold_'), 'pet.json')


def env_fingerprint():
    """当前进程的渲染环境指纹（换了解释器/Qt 就该重生成基线）。"""
    from PySide6 import __version__ as pyside_ver
    from PySide6.QtCore import __version__ as qt_ver, qVersion
    ensure_app()
    pm = QPixmap(8, 8)
    p = QPainter(pm)
    p.setFont(QFont('Microsoft YaHei', 9))
    fm = p.fontMetrics()
    fp = {
        'pyside': pyside_ver,
        'qt': qt_ver,
        'qt_runtime': qVersion(),
        'python': '%d.%d.%d' % sys.version_info[:3],
        'font_height': fm.height(),
        'font_advance': fm.horizontalAdvance('基线气泡'),
    }
    p.end()
    return fp


def setup(verbose=True):
    """import 方要复现基线的渲染环境，调这一个就够。

    顺序不能换：先有 app（Overlay 需要）→ 再冻时间（构造期读 monotonic）
    → 最后才建场景（构造期就用掉了冻结后的时间与种子）。
    """
    freeze()
    build_scene()
    if verbose:
        report_font_metrics()
    return _app


def build_world(**cfg_over):
    """造一个完全确定的 Overlay：虫的位置/基因/年龄/皮肤全部写死。

    为什么要开 paused：渲染时要调 processEvents()，而世界有一个 QTimer
    在驱动 _tick。虫的移动是
        self.x += cos(dir)*speed*dt + randn()*0.06
    —— 注意 randn()*0.06 **没有乘 dt**，所以哪怕把时钟冻住（dt=0），
    每多跑一次 update() 位置照样会随机漂一点。两帧之间定时器触发次数
    只要差一次，基线图就不一样（实测 2.4% 像素不同）。
    用产品自带的"暂停"把世界停掉最干净，顺便也顺带验了暂停态的绘制。
    """
    random.seed(FIXED_SEED)           # 每次重建都从同一个种子开始
    cfg = pet.load_settings()
    cfg['count'] = 2
    cfg['show_labels'] = True
    cfg['scale'] = 1.0
    cfg['bubbles'] = {'enabled': True, 'show_seconds': 4.0, 'texts': {}}
    cfg['paused'] = True              # ★ 关键：让世界停摆
    cfg.update(cfg_over)
    win = pet.Overlay(cfg)
    win.flies, win.eggs, win.foods = [], [], []
    win.pher, win.fx, win.cage = [], [], None
    win.reminders, win.announce, win.bubble = [], None, None
    win.drag_hover = False
    win.drop_fly_hover = None
    win.pending_place = False
    win.capture_mode = False
    win.focus = None
    win.clock_fid = 0
    win.resize(900, 620)
    return win


def mkfly(win, x, y, **gene):
    """造一只可复现的虫，并把所有随机量钉死。"""
    g = pet.new_gene(**gene) if gene else pet.new_gene()
    f = win.register_fly(pet.PetFly(x, y, gene=g))
    f.castSeed = 1.234                 # 构造期 random.random()*TAU → 钉死
    f.wingPhase = 0.8                  # 翅膀相位 → 钉死
    f.age = 30.0
    f.dir = 0.0
    f.speed = 60.0
    f.labelT = 0.0
    f.bubble = None
    f.markers = []
    win.flies.append(f)
    return f


# 场景句柄。**build_scene() 之前都是 None** —— 这里刻意不直接建。
#
# 原因：build_world() 会 new 一个 pet.Overlay，而它要求 QApplication 已存在、
# pet.time 已冻结。放在模块级就等于"import 本文件的人必须先交出 app 且接受
# 时间被冻住"，本文件也就没法被 _coverage.py / _mask_check.py 复用了。
WIN = None
FLY_A = None
FLY_B = None

# 把覆盖层钉成固定尺寸。
# 真实运行时它是整屏大小的（apply_screen_geometry → 主屏分辨率），
# 但基线图不该随显示器分辨率变化，而且整屏图逐像素比对太慢。
FIT_W, FIT_H = 900, 620


def fit(win):
    win.w, win.h = FIT_W, FIT_H
    win.setGeometry(0, 0, FIT_W, FIT_H)


def build_scene():
    """把世界状态一次性固定：两只虫 + 一颗蛋 + 一块糖 + 一个笼子。

    FLY_A 普通个体；FLY_B 故意给高分基因（dev=6.0 → 传说级），
    这样 _paint 里那条"金色光晕呼吸"分支才会被画到 ——
    它是整个绘制路径上唯一读 time.monotonic() 的地方，正是最该冻住的。

    渲染函数（r_* / build_mask 类探针）都通过模块级全局 WIN / FLY_A / FLY_B
    取场景，所以这里 global 赋值而不是返回一个对象。
    """
    global WIN, FLY_A, FLY_B
    WIN = build_world()
    fit(WIN)
    FLY_A = mkfly(WIN, 200.0, 220.0, spd=1.2, siz=1.0, bold=1.0, hue=1.0)
    FLY_B = mkfly(WIN, 620.0, 300.0, spd=1.8, siz=1.6, bold=1.4, hue=1.9)
    FLY_A.skin = None
    FLY_B.skin = None
    WIN.eggs = [{'x': 420, 'y': 480, 'age': 12.0, 'gene': pet.new_gene(), 'skin': None}]
    WIN.foods = [{'x': 780.0, 'y': 200.0, 'e': pet.FOOD_E0}]
    WIN.cage = {'x': 480, 'y': 120, 'w': pet.CAGE_W, 'h': pet.CAGE_H, 'locked': False}
    return WIN


def canvas(w, h):
    """给"以世界坐标为参数"的绘制函数用的画布。"""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    return pm


def to_img(pm):
    return pm.toImage().convertToFormat(QImage.Format_ARGB32)


def nonblank(img):
    n = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            if img.pixelColor(x, y).alpha() > 8:
                n += 1
    return n


# ---------------------------------------------------------------- 各帧渲染
def r_overlay():
    """整窗 grab → 走 paintEvent → _paint 全部主干（信息素/笼子/糖/蛋/特效/虫/标签）"""
    fit(WIN)                         # 每帧前重新钉尺寸，防止 processEvents 里被改回整屏
    WIN.pher = [{'x': 330.0, 'y': 360.0, 'age': 0.0, 's': 1.0}]
    WIN.fx = [{'x': 500.0, 'y': 400.0, 'age': 0.1, 'life': 0.7,
               'color': (255, 220, 120)}]
    WIN.announce = None
    WIN.show()
    fit(WIN)
    ensure_app().processEvents()
    fit(WIN)
    FLY_A.skinT = 0.0
    FLY_B.skinT = 0.0
    return to_img(WIN.grab())


def r_overlay_hud():
    """叠上 HUD：专注进度条 + 横幅 + 放置模式提示条"""
    fit(WIN)
    WIN.announce = ('基线帧横幅', FIXED_MONO + 60)
    WIN.start_focus(25)
    WIN.pending_place = True
    WIN.pending_skin = 'rocket'
    try:
        return to_img(WIN.grab())
    finally:
        WIN.pending_place = False
        WIN.stop_focus(silent=True)
        WIN.announce = None


def r_overlay_clock():
    """报时牌 + 气泡 + 传说光晕（这三条都在 _paint 里，且都读过时钟）"""
    fit(WIN)
    WIN.cfg['clock'] = {'fid': FLY_A.fid, 'show_title': True,
                        'todos': ['第一件事', '轮换到第二件事']}
    WIN.clock_fid = FLY_A.fid
    FLY_A.x, FLY_A.y = WIN.clock_perch()
    FLY_A.bubble = ['基线气泡', FIXED_MONO, 4.0]
    try:
        return to_img(WIN.grab())
    finally:
        WIN.clock_fid = 0
        WIN.cfg['clock'] = {'fid': 0, 'todos': [], 'show_title': True}
        FLY_A.bubble = None


def r_cage_unlocked():
    WIN.cage['locked'] = False
    WIN.drag_hover = False
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.draw_cage(p, WIN.cage_rect())
    p.end()
    return to_img(pm)


def r_cage_locked():
    WIN.cage['locked'] = True
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.draw_cage(p, WIN.cage_rect())
    p.end()
    WIN.cage['locked'] = False
    return to_img(pm)


def r_cage_hover():
    """拖放高亮分支：外发光 + 绿色栏杆"""
    WIN.drag_hover = True
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.draw_cage(p, WIN.cage_rect())
    p.end()
    WIN.drag_hover = False
    return to_img(pm)


def r_egg_young():
    """prog < 0.75：没有裂纹"""
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.draw_egg(p, {'x': 420, 'y': 480, 'age': pet.EGG_TIME * 0.25})
    p.end()
    return to_img(pm)


def r_egg_hatching():
    """prog > 0.75：必须冒出裂纹（这条分支以前没人验过）"""
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.draw_egg(p, {'x': 420, 'y': 480, 'age': pet.EGG_TIME * 0.95})
    p.end()
    return to_img(pm)


def r_clock_board():
    pm = canvas(900, 620)
    p = QPainter(pm)
    WIN.clock_fid = FLY_A.fid
    WIN.cfg['clock'] = {'fid': FLY_A.fid, 'show_title': True,
                        'todos': ['第一件事', '轮换到第二件事']}
    try:
        WIN.draw_clock_board(p)
    finally:
        p.end()
    return to_img(pm)


def r_bubble():
    """⚠ 渲染函数**必须清理自己动过的共享状态**。

    整个夹具只用一个全局 WIN，而第 0 步会把所有 TARGETS 先跑一遍、
    比对遍再跑一遍。r_bubble 曾经把 FLY_B.bubble 留在那里没还 ——
    于是比对遍渲染 overlay / overlay_hud / overlay_clock 时，
    FLY_B 头上凭空多了一个气泡（第 0 步残留下来的），
    那三张基线实际测的就不是"无气泡的整窗"。
    这一类泄漏不会让测试变红，只会让基线**名不副实**，最难查。
    """
    FLY_B.bubble = ['基线气泡', FIXED_MONO, 4.0]
    try:
        pm = canvas(900, 620)
        p = QPainter(pm)
        WIN.draw_bubble(p, FLY_B)
        p.end()
        return to_img(pm)
    finally:
        FLY_B.bubble = None


def r_skin_sprite():
    """具名皮肤：走 sprite 贴图分支。必须先定 skinT，否则帧号会漂。"""
    name = sorted(n for n in WIN.skins if n != '_procedural')[0]
    skin = WIN.skins[name]
    pm = QPixmap(120, 120)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.translate(60, 60)              # draw_skin 画的是以虫心为原点的局部坐标
    FLY_A.skin = name
    FLY_A.skinT = 3.0                # 钉死帧号（这个函数会自己推进 skinT）
    WIN.draw_skin(p, skin, FLY_A)
    p.end()
    FLY_A.skin = None
    return to_img(pm)


def r_skin_procedural():
    WIN.cfg['clock'] = {'fid': 0, 'todos': [], 'show_title': True}
    pm = QPixmap(120, 120)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.translate(60, 60)
    FLY_A.eating = False
    WIN.draw_procedural(p, FLY_A)
    p.end()
    return to_img(pm)


TARGETS = [
    ('overlay', r_overlay),
    ('overlay_hud', r_overlay_hud),
    ('overlay_clock', r_overlay_clock),
    ('cage_unlocked', r_cage_unlocked),
    ('cage_locked', r_cage_locked),
    ('cage_hover', r_cage_hover),
    ('egg_young', r_egg_young),
    ('egg_hatching', r_egg_hatching),
    ('clock_board', r_clock_board),
    ('bubble', r_bubble),
    ('skin_sprite', r_skin_sprite),
    ('skin_procedural', r_skin_procedural),
]


def diff_ratio(a, b):
    """返回 (不同像素数, 总像素数, 最大通道差, 差异包围盒)。

    先走字节快路径：完全相同就直接 0，省掉 55 万次 pixel() 调用。
    """
    if a.size() != b.size():
        return (a.width() * a.height(), a.width() * a.height(), 255,
                (0, 0, a.width(), a.height()))
    if bytes(a.constBits()) == bytes(b.constBits()):
        return (0, a.width() * a.height(), 0, None)
    ndiff, worst = 0, 0
    x0, y0, x1, y1 = 10 ** 9, 10 ** 9, -1, -1
    w, h = a.width(), a.height()
    for y in range(h):
        for x in range(w):
            ca, cb = a.pixel(x, y), b.pixel(x, y)
            if ca != cb:
                ndiff += 1
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                if y > y1:
                    y1 = y
                for sh in (0, 8, 16, 24):
                    d = abs(((ca >> sh) & 255) - ((cb >> sh) & 255))
                    if d > worst:
                        worst = d
    return (ndiff, w * h, worst, (x0, y0, x1, y1))



def main():
    setup()                          # 建 app + 冻时间/随机种子 + 隔离存档
    if not UPDATE and not os.path.isdir(GOLD_DIR):
        print('!! 基线目录不存在：%s' % GOLD_DIR)
        print('   先用 --update 生成一次基线，再提交它。')
        sys.exit(2)

    os.makedirs(GOLD_DIR, exist_ok=True)

    fp = env_fingerprint()
    if UPDATE:
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.write(json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        old = None
        if os.path.isfile(ENV_FILE):
            with open(ENV_FILE, encoding='utf-8') as f:
                old = json.load(f)
        if old != fp:
            # 这里直接收工：逐字节比对一个"来自别的渲染器"的基线毫无意义，
            # 硬跑下去只会刷出一屏看着像"绘制被改坏"的红字，把人带偏。
            print('=' * 74)
            print('!! 渲染环境与基线不一致 —— 逐字节比对已无意义，直接停。')
            print('=' * 74)
            print('   基线的环境：%s' % json.dumps(old, ensure_ascii=False, sort_keys=True))
            print('   当前的进程：%s' % json.dumps(fp, ensure_ascii=False, sort_keys=True))
            print('   文本抗锯齿随 Qt 版本变化（实测 Qt 6.8.2.1 → 6.11.2 差 208 px）。')
            print('   若这次**故意**换环境（例如换了打包用的解释器），请：')
            print('       python _golden.py --update    # 重建基线并刷新指纹')
            print('   否则请用生成基线的那套环境跑（应与打 exe 的一致），')
            print('   具体版本见 _golden/_env.json 里记录的 python / pyside 指纹。')
            print()
            check('基线渲染环境与当前一致', False, '（见上：环境指纹不匹配）')
            print()
            print('失败 1 项')
            sys.exit(1)

    rendered = {}
    print('=' * 74)
    print('绘制基线回归（golden image）  %s' % ('【重建基线】' if UPDATE else '【比对】'))
    print('=' * 74)

    # ---- 第 0 步：确定性自检 ----
    # 必须先证明"同一个状态渲染两次完全相同"，否则基线毫无意义 ——
    # 图每次都不一样的话，比对失败到底是"改坏了"还是"本来就不稳定"根本分不清。
    # 这一步也顺带验证了 pet.time 冻结、random.seed、castSeed/skinT 钉死都生效。
    print('第 0 步：确定性自检（每帧连续渲染两次，必须逐字节相同）')
    for name, fn in TARGETS:
        a = fn()
        b = fn()
        nd, tot, worst, box = diff_ratio(a, b)
        check('渲染可复现：%s' % name, nd == 0,
              '' if nd == 0 else '（两次渲染有 %d/%d 像素不同，最大通道差 %d，'
              '差异集中在 %s）' % (nd, tot, worst, box))
    print()

    for name, fn in TARGETS:
        img = fn()
        rendered[name] = img
        path = os.path.join(GOLD_DIR, name + '.png')
        if UPDATE:
            img.save(path)
            print('  写入基线 %-18s %4d x %-4d 不透明采样 %d'
                  % (name, img.width(), img.height(), nonblank(img)))
            continue
        if not os.path.isfile(path):
            check('基线存在：%s' % name, False, '（缺 %s.png，用 --update 生成）' % name)
            continue
        gold = QImage(path).convertToFormat(QImage.Format_ARGB32)
        nd, tot, worst, box = diff_ratio(gold, img)
        ratio = nd / float(tot)
        if nd == 0:
            check('绘制未回归：%s' % name, True, '（逐字节相同）')
        else:
            check('绘制未回归：%s' % name, ratio <= MAX_DIFF,
                  '（%d/%d 像素不同 = %.3f%%，最大通道差 %d，差异集中在 x%d..%d y%d..%d）'
                  % (nd, tot, ratio * 100, worst, box[0], box[2], box[1], box[3]))

    if UPDATE:
        print()
        print('基线已写入 %s' % GOLD_DIR)
        sys.exit(0)

    # ------------------------------------------------- 基线网自身的灵敏度
    # 只比"跟上次一样"还不够：如果基线图是空白的，那它永远也不会变，
    # 比对永远通过 —— 一个永远绿的假测试。所以下面这些必须成立。
    print()
    print('-' * 74)
    print('基线网灵敏度自检（防止"比的是空白图"这种假绿）')
    print('-' * 74)

    for name, img in rendered.items():
        nb = nonblank(img)
        # 门槛很低（一颗蛋在 900x620 上采样也只有 20 来个点），
        # 真正的判别力来自"逐字节比对基线"+ 下面那几条成对差异断言。
        # 这条只负责挡住"整屏空白"这种最粗的故障。
        check('基线不是空白图：%s' % name, nb >= 5, '（不透明采样 %d 点）' % nb)

    check('笼子上锁 / 解锁画出来不一样（锁指示点颜色不同）',
          diff_ratio(rendered['cage_locked'], rendered['cage_unlocked'])[0] > 20)
    check('拖放高亮分支画出来不一样（外发光 + 绿色栏杆）',
          diff_ratio(rendered['cage_hover'], rendered['cage_unlocked'])[0] > 20)
    check('★ 蛋快孵化时会冒出裂纹（prog>0.75 分支）',
          diff_ratio(rendered['egg_hatching'], rendered['egg_young'])[0] > 10)
    check('报时牌 / 气泡 / 皮肤三种绘制互不相同（没画串）',
          len({bytes(i.constBits()) for i in
               (rendered['clock_board'], rendered['bubble'],
                rendered['skin_sprite'])}) == 3)
    check('sprite 皮肤与程序化绘制是两条不同的通路',
          diff_ratio(rendered['skin_sprite'], rendered['skin_procedural'])[0] > 100)

    print()
    print('=' * 40)
    print('失败 %d 项' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
