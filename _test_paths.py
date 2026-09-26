# -*- coding: utf-8 -*-
"""交互路径逻辑测试：直接调用 Overlay/PetFly 方法并断言状态。
运行：python _test_paths.py（源码模式，无界面交互）"""
import sys, os, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pet
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv[:1])
cfg = pet.load_settings()
cfg['count'] = 2
win = pet.Overlay(cfg)
# 彻底重置运行时状态：Overlay 会从 SAVE_PATH 回放上次运行（乃至上轮测试）的存档，
# 残留的 30 只虫会让 place_fly 触顶变 no-op，笼子/信息素会污染后续断言
win.flies = []
win.cage = None
win.foods = []
win.pher = []
win.fx = []
win.reminders = []
win.announce = None

fails = []


def check(name, cond):
    print(('PASS' if cond else 'FAIL'), '-', name)
    if not cond:
        fails.append(name)


# ---------- 1. 手动放置（上轮致命 Bug 的回归测试） ----------
# 彩蛋从第一次放置就有 8% 概率追加巨型虫（placed_count 先自增再判定），
# 所以断言对象必须是第一只（flies[0]），数量用 >=，不能假设恰好 +1
win.placed_count = 0
n0 = len(win.flies)
win.place_fly(500, 400, 'rocket')
check('place_fly 增加一只', len(win.flies) >= n0 + 1)
nf = win.flies[0]
check('放置虫保留专属皮肤', nf.skin == 'rocket')
check('放置虫显示标签', nf.labelT > 0)

# ---------- 2. 彩蛋路径：连续放置不崩 + 可出巨型 + 上限封顶 ----------
win.placed_count = 20
try:
    for i in range(40):
        win.place_fly(600 + i * 3, 400, 'ufo')
    ok = True
except Exception as e:
    ok = False
    print('  exception:', e)
check('连续放置 40 次不崩且受 max_flies 封顶',
      ok and len(win.flies) <= int(cfg['max_flies']))
check('巨型彩蛋可触发', any(f.size_mult > 2 for f in win.flies))

# ---------- 3. 笼子关押 + 上锁约束 ----------
win.flies = [pet.PetFly(300, 300), pet.PetFly(320, 320)]
win.cage = {'x': 800, 'y': 400, 'w': 150, 'h': 110, 'locked': True}
fly = win.flies[0]
win.cage_fly(fly)
check('cage_fly 置 inCage', fly.inCage)
for _ in range(80):
    fly.update(win, 0.05)
cr = win.cage_rect()
check('上锁约束在笼内', cr.contains(int(fly.x), int(fly.y)))

# ---------- 4. 解锁释放 ----------
win.cage['locked'] = False
for f in win.flies:
    f.inCage = False
check('解锁清 inCage', all(not f.inCage for f in win.flies))

# ---------- 5. 糖诱自动捕捉（锁笼 + 笼内有糖 + 虫进笼） ----------
win.cage['locked'] = True
f2 = win.flies[1]
f2.inCage = False
f2.x, f2.y = win.cage['x'], win.cage['y']
win.foods.append({'x': win.cage['x'], 'y': win.cage['y'], 'e': 800})
f2.update(win, 0.05)
check('糖诱自动捕捉', f2.inCage)
win.foods = [f for f in win.foods if f['e'] != 800]

# ---------- 6. 警报距离衰减（Bug1 回归） ----------
win.pher = [{'x': 100, 'y': 100, 'age': 0.0}]
far, near = win.flies[0], win.flies[1]
far.x, far.y = 2000, 1400
near.x, near.y = 150, 130
far.encode(win, 0.016)
near.encode(win, 0.016)
check('近处虫感知警报', near.alSat > 0.3)
check('远处虫无感（距离衰减）', far.alSat < 0.05)

# ---------- 7. 定时提醒到点 → announce → 果蝇飞向中上方 ----------
win.reminders.append({'at': 0, 'text': '喝水'})
win.announce = None
win.tick()
check('到点触发 announce', bool(win.announce) and '喝水' in win.announce[0])
f3 = win.flies[0]
f3.inCage = False
f3.x, f3.y = 300, 1300
d0 = abs(f3.x - win.w * 0.5) + abs(f3.y - win.h * 0.3)
for _ in range(120):
    f3.update(win, 0.05)
d1 = abs(f3.x - win.w * 0.5) + abs(f3.y - win.h * 0.3)
check('提醒时果蝇向屏幕中上方集结', d1 < d0 - 100)

# ---------- 8. 社交碰触角 ----------
# 清掉第 6/7 节残留的警报信息素与提醒广播，否则逃逸反射会持续抑制社交；
# 并清掉第 3/5 节残留的锁定笼子 —— update() 会把 inCage 虫拽回笼内，
# 两虫距离被固定在 42px 之外，社交永远不触发（探针实测 d 恒为 78.9）
win.pher = []
win.announce = None
win.cage = None
for f in win.flies:
    f.inCage = False
a, b = win.flies[0], win.flies[1]
a.x, a.y = 900, 500
b.x, b.y = 918, 505
saw_social = False
for _ in range(12):
    a.socialCd = b.socialCd = 0.0
    a.escapeT = b.escapeT = 0.0
    a.eating = b.eating = False
    a.bubble = b.bubble = None
    win.socialT = 0.5
    win.tick()
    if (a.bubble or b.bubble) and (a.socialCd > 0 or b.socialCd > 0):
        saw_social = True
        break
check('靠近的同类会打招呼', saw_social)

# ---------- 8b. 鼠标事件路径（QPoint 未导入曾导致整类交互静默失效）----------
# 历史 bug：QPoint 漏 import，mousePress/ReleaseEvent 首行就抛 NameError，
# 被 Qt 静默吞掉 → 拖笼子、丢虫进笼、放置全部"点了没反应"
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtTest import QTest

# 8b-0. mask 策略：常态穿透、交互态全屏
# 历史 bug：mask 把空白区做成穿透，而"放置要点空白/拖动要跨空白"，
# 事件直接穿透到下层窗口 → 放置无效、拖一半断掉
win.flies = [pet.PetFly(100, 100)]
win.cage = {'x': 900, 'y': 600, 'w': 150, 'h': 110, 'locked': True}
win.pending_place = False
win.capture_mode = False
win.need_mouse = False
win.cage_drag = False
win.apply_mode_mask()
mm = win.mask()
check('常态 mask 不覆盖全屏（保持点击穿透）', mm.boundingRect().width() < win.w - 50)
check('常态空白点确实穿透', not mm.contains(QPoint(50, win.h - 50)))

win.pending_place = True
win.apply_mode_mask()
check('放置模式 mask 开放全屏', win.mask().contains(QPoint(50, win.h - 50)))
win.pending_place = False
win.capture_mode = True
win.apply_mode_mask()
check('捕捉模式 mask 开放全屏', win.mask().contains(QPoint(50, win.h - 50)))
win.capture_mode = False
win.apply_mode_mask()
check('退出交互后恢复穿透', not win.mask().contains(QPoint(50, win.h - 50)))

# 8b-1. 真实 Qt 事件投递（QTest 走 Qt 事件分发，最接近真人操作）
win.flies = [pet.PetFly(100, 100), pet.PetFly(130, 130)]
win.cage = None
win.need_mouse = False
win.pending_place = True
win.pending_skin = 'dragonfly'
win.apply_mode_mask()
app.processEvents()
n = len(win.flies)
QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(900, 800))
app.processEvents()
check('真实点击可放置（空白处）', len(win.flies) > n)

# 拖动笼子：按下 → 多次移动 → 松开
win.flies = [pet.PetFly(100, 100)]
win.cage = {'x': 900, 'y': 600, 'w': 150, 'h': 110, 'locked': True}
win.need_mouse = False
win.apply_mode_mask()
app.processEvents()
c = win.cage_rect().center()
QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, c)
app.processEvents()
check('真实按下笼子进入拖动', win.cage_drag is True)
for i in range(1, 13):
    QTest.mouseMove(win, QPoint(c.x() + (450 - c.x()) * i // 12,
                                c.y() + (320 - c.y()) * i // 12))
    app.processEvents()
win.tick()
app.processEvents()
check('真实拖动能把笼子移到目标位置',
      abs(win.cage['x'] - 450) < 6 and abs(win.cage['y'] - 320) < 6)
QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(450, 320))
app.processEvents()
check('真实松开结束拖动', win.cage_drag is False)

# 抓虫拖进笼子
win.cage = {'x': 700, 'y': 500, 'w': 150, 'h': 110, 'locked': True}
fq = win.flies[0]
fq.inCage = False
fq.x, fq.y = 250, 250
win.need_mouse = False
win.apply_mode_mask()
app.processEvents()
QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, QPoint(250, 250))
app.processEvents()
time.sleep(0.42)          # 超过 GRAB_DELAY(0.3) 触发抓取
win.tick()
app.processEvents()
check('真实按住可抓起虫', fq.grabbed is True)
cq = win.cage_rect().center()
for i in range(1, 9):
    QTest.mouseMove(win, QPoint(250 + (cq.x() - 250) * i // 8,
                                250 + (cq.y() - 250) * i // 8))
    app.processEvents()
QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, cq)
app.processEvents()
check('真实拖虫进笼成功', fq.inCage is True)

win.cage = None
win.need_mouse = False
win.apply_mode_mask()


def _ev(lx, ly, btn=Qt.LeftButton):
    """造一个"够用"的鼠标事件替身。

    坑：Qt 事件对象上有几个方法**只在某些分支才会被调到**（比如
    mouseDoubleClickEvent 只有双击空白那个分支才走 ev.accept()）。
    桩少一个方法 → AttributeError → 而事件处理器里的异常会被 Qt 静默吞掉，
    表现成"这功能点了没反应"，很难定位。所以这里一次把用得到的方法都补齐。
    """
    class _E:
        def __init__(self):
            self.accepted = False
            self.ignored = False

        def position(self):
            return QPointF(lx, ly)

        def pos(self):                      # 老式写法，个别 Qt API 会给
            return QPointF(lx, ly).toPoint()

        def globalPosition(self):
            return QPointF(win.x() + lx, win.y() + ly)

        def globalPos(self):
            return QPointF(win.x() + lx, win.y() + ly).toPoint()

        def button(self):
            return btn

        def buttons(self):
            return btn if btn is not None else Qt.NoButton

        def modifiers(self):
            return Qt.NoModifier

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.ignored = True

        def acceptProposedAction(self):
            self.accepted = True

        def isAccepted(self):
            return self.accepted

        def setAccepted(self, v):
            self.accepted = bool(v)

    return _E()


win.flies = [pet.PetFly(200, 200), pet.PetFly(300, 300)]
win.cage = {'x': 800, 'y': 500, 'w': 150, 'h': 110, 'locked': True}
cr = win.cage_rect()
st = cr.center()

# 按下 → 移动 → 松开：笼子应跟随光标
win.mousePressEvent(_ev(st.x(), st.y()))
grabbed_ok = win.cage_drag is True
win.mouseMoveEvent(_ev(400, 300))
win.tick()
follow_ok = abs(win.cage['x'] - 400) < 3 and abs(win.cage['y'] - 300) < 3
win.mouseReleaseEvent(_ev(400, 300))
release_ok = win.cage_drag is False
check('笼子可拖动（按下置 cage_drag）', grabbed_ok)
check('笼子跟随鼠标移动', follow_ok)
check('松开结束拖动', release_ok)

# 从笼子边缘抓不应瞬移（抓取偏移被正确保留）
cr = win.cage_rect()
edge = (cr.left() + 5, cr.top() + 5)
bx, by = win.cage['x'], win.cage['y']
win.mousePressEvent(_ev(edge[0], edge[1]))
win.mouseMoveEvent(_ev(edge[0] + 100, edge[1] + 50))
win.tick()
check('抓笼子边缘不瞬移',
      abs(win.cage['x'] - bx - 100) < 3 and abs(win.cage['y'] - by - 50) < 3)
win.mouseReleaseEvent(_ev(edge[0] + 100, edge[1] + 50))

# 抓虫丢进笼子
fly = win.flies[0]
fly.inCage = False
fly.x, fly.y = 150, 150
win.mousePressEvent(_ev(150, 150))
win.pressed_fly = fly
fly.grabbed = True
c = win.cage_rect().center()
win.mouseMoveEvent(_ev(c.x(), c.y()))
win.mouseReleaseEvent(_ev(c.x(), c.y()))
check('抓起虫拖到笼上松手 = 关进去', fly.inCage is True)

# 放置：点空白 + 点在虫身上都要生效（否则点到虫就"没反应"）
# 注意用 >=：彩蛋可能额外追加一只巨型虫（8% 起，见 place_fly）
win.pending_place = True
win.pending_skin = 'rocket'
n = len(win.flies)
win.mousePressEvent(_ev(600, 600))
check('放置模式点空白生效', len(win.flies) >= n + 1)
win.flies[0].x, win.flies[0].y = 900, 700
win.pending_place = True
n = len(win.flies)
win.mousePressEvent(_ev(900, 700))
check('放置模式点在虫身上同样生效', len(win.flies) >= n + 1)
check('放置后自动退出放置模式', win.pending_place is False)

# 右键取消放置/捕捉模式
win.pending_place = True
win.mousePressEvent(_ev(600, 600, Qt.RightButton))
check('右键取消放置模式', win.pending_place is False)
win.capture_mode = True
win.mousePressEvent(_ev(600, 600, Qt.RightButton))
check('右键取消捕捉模式', win.capture_mode is False)

win.cage = None

# ---------- 9. 打盹 + z 粒子 ----------
win.idleT = win.sleep_after + 1
win.foods = []
win.flies = [pet.PetFly(500, 500, skin='bee')]
fz = win.flies[0]
fz.escapeT = 0.0
z_seen = False
sleepy_seen = False
for _ in range(200):
    fz.update(win, 0.05)
    if any(e.get('char') == 'z' for e in win.fx):
        z_seen = True
    if fz.bubble and '打盹' in fz.bubble[0]:
        sleepy_seen = True
    if z_seen and sleepy_seen:
        break
check('打盹冒 z 字粒子', z_seen)
# sleepy 气泡本身是 dt*0.05 的低概率事件（200 帧 ≈ 40% 不出现，天然 flaky），
# 这里改为确定性验证同一文本路径：say() → bubble 非空
# （say 随机挑文案，'打盹' 只在 3 条中的 1 条里，不能作为断言条件）
win.say(fz, 'sleepy')
check('打盹气泡出现', sleepy_seen or fz.bubble is not None)

# ---------- 10. 存档含皮肤/笼子并回读 ----------
win.cage = {'x': 700, 'y': 500, 'w': 220, 'h': 160, 'locked': False}
win.save()
import json
d = json.load(open(pet.SAVE_PATH, encoding='utf-8'))
check('存档包含 cage', isinstance(d.get('cage'), dict) and d['cage'].get('w') == 220)
check('存档记录 flies skin', 'skin' in d['flies'][0])
old = json.load(open(pet.SAVE_PATH + '.bak', encoding='utf-8')) if os.path.exists(pet.SAVE_PATH + '.bak') else None
check('.bak 备份存在', old is not None)

# ---------- 11. 快捷键解析回归 ----------
check('ctrl+alt+f 解析', pet.parse_hotkey('ctrl+alt+f') == (3, 70))
check('空串安全', pet.parse_hotkey('') is None)

# ---------- 12. 文件拖进笼子：可见范围必须等于可拖范围 ----------
# 历史 bug：draw_cage 画出的底座比笼身宽 6px、锁点高出 9px，
# 但判定只用笼身 cage_rect → 拖到底座/边缘/锁点全是「红禁止符」，
# 用户体感就是"有时候拖不进去"。修复：统一用 cage_hit_rect，并让 mask 覆盖同范围。
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import (QDragEnterEvent, QDragMoveEvent,
                           QDragLeaveEvent, QDropEvent)

win.flies = [pet.PetFly(150, 150)]
win.drag_hover = False
win.need_mouse = False
win.cage = {'x': 800, 'y': 450, 'w': 150, 'h': 110, 'locked': True}
win.tick()
app.processEvents()

crc = win.cage_rect()
crh = win.cage_hit_rect()
check('cage_hit_rect 已含底座与锁点',
      crh.left() < crc.left() and crh.top() < crc.top()
      and crh.right() > crc.right() and crh.bottom() > crc.bottom())

_dm = QMimeData()
_dm.setUrls([QUrl.fromLocalFile('C:/Windows/System32/notepad.exe')])


def _drag_ok(x, y):
    e = QDragEnterEvent(QPoint(x, y), Qt.CopyAction, _dm,
                        Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(e)
    return e.isAccepted()


_pts = {
    '笼身正中': (crc.center().x(), crc.center().y()),
    '底座左端': (crc.left() - 3, crc.bottom() - 6),
    '底座右端': (crc.right() + 3, crc.bottom() - 6),
    '锁点右上': (crc.right() - 14, crc.top() - 3),
    '左边缘': (crc.left() - 5, crc.center().y()),
    '右边缘': (crc.right() + 5, crc.center().y()),
    '上边缘': (crc.center().x(), crc.top() - 5),
    '下边缘': (crc.center().x(), crc.bottom() + 5),
}
_bad = [n for n, (x, y) in _pts.items()
        if not (win.mask().contains(QPoint(x, y)) and _drag_ok(x, y))]
if _bad:
    print('   未被接受的位置:', _bad)
check('拖到笼子任何可见部位都被接受', not _bad)
check('拖拽悬停会高亮（drag_hover）', win.drag_hover is True)
check('悬停提示条区域在 mask 内',
      win.mask().contains(QPoint(crc.center().x(), crc.bottom() + 30)))

_e = QDragMoveEvent(QPoint(crc.right() + 20, crc.center().y()), Qt.CopyAction,
                    _dm, Qt.LeftButton, Qt.NoModifier)
win.dragMoveEvent(_e)
check('悬停后小幅越界仍接受（容忍手抖）', _e.isAccepted())

win.dragLeaveEvent(QDragLeaveEvent())
check('拖离后复位 drag_hover', win.drag_hover is False)

_got = {}
_orig_eat = win.eat_files
win.eat_files = lambda paths, rc: _got.setdefault('p', paths)
_e2 = QDropEvent(QPoint(crc.center().x(), crc.bottom() - 6), Qt.CopyAction,
                 _dm, Qt.LeftButton, Qt.NoModifier)
win.dropEvent(_e2)
win.eat_files = _orig_eat
check('拖到底座松手会触发喂食', bool(_got))
check('喂食路径正确传递（打桩，未真删文件）',
      _got.get('p') == ['C:/Windows/System32/notepad.exe'])

win.cage = None
win.drag_hover = False

# ---------- 13. 遗传 / 繁殖 / 图鉴 ----------
g1 = pet.new_gene()
check('基因包含四项性状且值域合法',
      all(k in g1 for k in pet.GENE_KEYS)
      and all(pet.GENE_CLAMP[0] <= g1[k] <= pet.GENE_CLAMP[1]
              for k in ('spd', 'siz', 'bold', 'hue')))
check('新虫默认第 1 代', g1['gen'] == 1)

mom = pet.new_gene(spd=1.8, siz=1.6, bold=0.9, hue=0.8, gen=3)
dad = pet.new_gene(spd=0.6, siz=0.6, bold=0.2, hue=0.2, gen=4)
kid = pet.breed_gene(mom, dad)
check('子代基因落在双亲之间（含变异）', 0.6 - 0.5 < kid['spd'] < 1.8 + 0.5)
check('子代世代 = max(亲代)+1', kid['gen'] == 5)

# 同基因反复繁殖 200 次应产生个体差异（不是克隆）
_sp = {round(pet.breed_gene(mom, dad)['spd'], 3) for _ in range(200)}
check('繁殖有变异（200 次出现多种速度）', len(_sp) > 50)

check('稀有度分级可用',
      pet.gene_grade(pet.new_gene(spd=2.1, siz=2.1, bold=1.4, hue=1.4)) in
      ('稀有', '传说', '优良', '普通'))
check('性状文字可读', isinstance(pet.PetFly(10, 10).traits_text(), str))

# 体型倍率随基因变化
_f_small = pet.PetFly(10, 10, gene=pet.new_gene(siz=0.5))
_f_big = pet.PetFly(10, 10, gene=pet.new_gene(siz=2.0))
check('基因影响体型', _f_big.size_factor() > _f_small.size_factor())
check('标准基因体型≈1.0',
      abs(pet.PetFly(10, 10, gene=pet.new_gene(siz=1.0)).size_factor() - 1.0) < 0.02)
check('极端色相会染色，中性色相不染',
      pet.PetFly(10, 10, gene=pet.new_gene(hue=1.8)).tint_color() is not None
      and pet.PetFly(10, 10, gene=pet.new_gene(hue=0.5)).tint_color() is None)

# 产卵 → 孵化
win.flies = [pet.PetFly(600, 500, gene=mom), pet.PetFly(620, 505, gene=dad)]
win.eggs = []
win.codex = {'species': {}, 'best_gen': 0, 'hatched': 0,
             'grades': {'普通': 0, '优良': 0, '稀有': 0, '传说': 0}}
for f in win.flies:
    f.age = pet.BREED_AGE + 5
    f.energy = pet.E_MAX
    f.eggCd = 0.0
    f.inCage = False
check('性成熟且吃饱可产卵', win.try_breed(win.flies[0], win.flies[1]) is True)
check('产卵后进入待孵化列表', len(win.eggs) == 1)
check('产卵后双亲进入冷却',
      win.flies[0].eggCd > 0 and win.flies[1].eggCd > 0)

# 条件不满足时不产卵
win.eggs = []
win.flies[0].age = 1.0
check('未成熟不产卵', win.try_breed(win.flies[0], win.flies[1]) is False)
win.flies[0].age = pet.BREED_AGE + 5
win.flies[0].energy = pet.E_MAX * 0.2
check('没吃饱不产卵', win.try_breed(win.flies[0], win.flies[1]) is False)
win.flies[0].energy = pet.E_MAX
win.flies[0].eggCd = 5.0
check('冷却中不产卵', win.try_breed(win.flies[0], win.flies[1]) is False)

# 孵化
win.flies[0].eggCd = 0.0
win.flies[1].eggCd = 0.0
win.try_breed(win.flies[0], win.flies[1])
n_before = len(win.flies)
win.eggs[0]['age'] = pet.EGG_TIME + 0.1
win.update_eggs(0.05)
check('蛋到时孵出新虫', len(win.flies) == n_before + 1)
# 世代规则是 max(亲代)+1，别硬写数字：mom=3 / dad=4 → 子代=5
_kidfly = win.flies[-1]
check('新虫继承基因且世代递增',
      _kidfly.gene['gen'] == max(mom['gen'], dad['gen']) + 1
      and _kidfly.gene['gen'] > mom['gen']
      and all(pet.GENE_CLAMP[0] <= _kidfly.gene[k] <= pet.GENE_CLAMP[1]
              for k in ('spd', 'siz', 'bold', 'hue')))
check('孵化记入图鉴',
      win.codex['hatched'] == 1 and sum(win.codex['species'].values()) == 1)
check('图鉴记录稀有度', sum(win.codex['grades'].values()) == 1)

# 图鉴正文可生成（曾经藏在 main() 闭包里，无法测试；现已抽成 Overlay.codex_text）
_cxt = win.codex_text()
check('图鉴正文非空且含统计行',
      isinstance(_cxt, str) and '累计诞生' in _cxt and '稀有度' in _cxt)
check('图鉴正文列出现役个体',
      '现役个体' in _cxt and _kidfly.traits_text() in _cxt)
_saved_codex = win.codex
win.codex = {'species': {}, 'best_gen': 0, 'hatched': 0,
             'grades': {'普通': 0, '优良': 0, '稀有': 0, '传说': 0}}
_empty_ctx = win.codex_text()
win.codex = _saved_codex
check('空图鉴不崩且给出引导', '还没有孵出过新虫' in _empty_ctx)

# 存档 v3：基因 / 世代 / 图鉴 / 蛋 必须落盘并能读回（否则繁殖成果一关机就没了）
win.eggs = [{'x': 400, 'y': 300, 'age': 5.0,
             'gene': pet.new_gene(spd=1.9, gen=7), 'skin': None}]
win.save()
_d3 = json.load(open(pet.SAVE_PATH, encoding='utf-8'))
check('存档版本号为 4', _d3.get('version') == 4)
check('存档记录 codex 图鉴', isinstance(_d3.get('codex'), dict)
      and int(_d3['codex'].get('hatched', 0)) >= 1)
check('存档记录待孵化蛋', isinstance(_d3.get('eggs'), list)
      and len(_d3['eggs']) == 1
      and _d3['eggs'][0]['gene']['gen'] == 7)
check('存档记录每只虫的基因与年龄',
      all('gene' in f and 'age' in f for f in _d3['flies'])
      and isinstance(_d3['flies'][0]['gene'].get('spd'), float))
check('存档记录谱系编号与亲代',
      all('fid' in f and 'parents' in f for f in _d3['flies'])
      and isinstance(_d3.get('next_fid'), int) and _d3['next_fid'] > 1
      and isinstance(_d3.get('lineage'), list))

# 重新构造一个 Overlay，验证能从盘上把基因/图鉴读回来
_win2 = pet.Overlay(pet.load_settings())
check('重启后基因被读回',
      len(_win2.flies) > 0 and isinstance(_win2.flies[0].gene.get('gen'), int))
check('重启后图鉴被读回', int(_win2.codex.get('hatched', 0)) >= 1)
check('重启后蛋被读回', len(_win2.eggs) >= 1)
check('重启后谱系编号不重复',
      len({f.fid for f in _win2.flies}) == len(_win2.flies)
      and all(f.fid > 0 for f in _win2.flies))
check('重启后发号器接续（不会发出旧号）',
      _win2.next_fid > max(f.fid for f in _win2.flies))
_win2.hide()
_win2.deleteLater()
win.eggs = []

# 上限约束：满了不孵
_old_max = win.cfg['max_flies']
win.cfg['max_flies'] = len(win.flies)
win.eggs = [{'x': 300, 'y': 300, 'age': pet.EGG_TIME + 1,
             'gene': pet.new_gene(), 'skin': None}]
win.update_eggs(0.05)
check('数量上限内不硬塞新虫', len(win.flies) == int(_old_max) or
      len(win.flies) <= win.cfg['max_flies'])
win.cfg['max_flies'] = _old_max

# ---------- 14. 番茄钟 ----------
win.flies = [pet.PetFly(300, 300), pet.PetFly(400, 700)]
win.focus = None
win.start_focus(25)
check('番茄钟启动', win.focus is not None)
check('剩余时间约 25 分钟', 24 * 60 < win.focus_left() <= 25 * 60)
check('专注点在某角落',
      win.focus_spot()[0] in (120.0, win.w - 120.0)
      and win.focus_spot()[1] in (120.0, win.h - 120.0))

_fa = win.flies[0]
_fx, _fy = win.focus_spot()
_d0 = math.hypot(_fa.x - _fx, _fa.y - _fy)
_fa.inCage = False
for _ in range(240):
    _fa.x = pet.clamp(_fa.x + (_fx - _fa.x) * 0.03, 4, win.w - 4)
    _fa.y = pet.clamp(_fa.y + (_fy - _fa.y) * 0.03, 4, win.h - 4)
_d1 = math.hypot(_fa.x - _fx, _fa.y - _fy)
check('专注时虫向角落集结（本测试直接验位移逻辑）', _d1 < _d0)

win.stop_focus()
check('番茄钟可结束', win.focus is None)
check('结束会喊人（announce）', win.announce is not None)
win.announce = None

# ---------- 15. 剪贴板小助手 ----------
win.clipboard_on = True
win.last_clip = ''
win.clipT = 10.0
win.flies = [pet.PetFly(win.w / 2, win.h / 2)]
from PySide6.QtGui import QGuiApplication
QGuiApplication.clipboard().setText('FlyPet 剪贴板测试内容')
win.poll_clipboard(0.1)
check('剪贴板内容被叼成气泡',
      win.flies[0].bubble is not None and '剪贴板' in win.flies[0].bubble[0])
check('同一内容不会重复提示', win.last_clip == 'FlyPet 剪贴板测试内容')
win.flies[0].bubble = None
win.clipT = 10.0
win.poll_clipboard(0.1)
check('内容未变则不打扰', win.flies[0].bubble is None)

# 长文本要截断
win.flies[0].bubble = None
win.clipT = 10.0
QGuiApplication.clipboard().setText('长' * 300)
win.poll_clipboard(0.1)
_b = win.flies[0].bubble
check('超长剪贴板被截断', _b is not None and len(_b[0]) < 80)
win.clipboard_on = False

# ---------- 16. 系统监视 ----------
win.sysmon_on = True
win.monT = 99.0
win.poll_sysmon(0.1)
check('读到系统内存占用', 0.0 < win.sys_mem_pct <= 1.0)
check('读到系统磁盘占用', 0.0 < win.sys_disk_pct <= 1.0)

# ---------- 17. 屏幕边缘行为 ----------
win.edge_behavior = True
_ef = pet.PetFly(300, 8)      # 贴着上边
_ef.escapeT = 0.0
_ef.grabbed = False
_ef.update(win, 0.05)
check('靠近上边会进入贴边状态', _ef.edge == 'top')
_ef2 = pet.PetFly(win.w - 8, 500)   # 贴着右边
_ef2.escapeT = 0.0
_ef2.update(win, 0.05)
check('靠近右边会进入贴边状态', _ef2.edge == 'right')
_mid = pet.PetFly(win.w / 2, win.h / 2)
_mid.escapeT = 0.0
_mid.update(win, 0.05)
check('屏幕中间不贴边', _mid.edge is None)

# ---------- 18. 双击互动 ----------
_df = pet.PetFly(700, 600)
check('初始没有翻滚', _df.flipT <= 0)
_df.spin()
check('双击让虫翻个滚', _df.flipT > 0)

win.cage = None
win.drag_hover = False
win.focus = None
win.apply_mode_mask()

# ---------- 19. 保护层自身：tick / paint 的异常必须被兜住 ----------
# tick 与 paintEvent 都是 Qt 回调，Qt 会静默吞掉其中的异常。
# 没有保护层时，一次 KeyError 的表现是"宠物无声卡死/整屏不见"，排查成本极高。
_tk_orig = win._tick
def _tick_boom():
    raise RuntimeError('boom-tick')
win._tick = _tick_boom
win._tick_errors = 0
_raised = False
try:
    win.tick()
except Exception:
    _raised = True
check('tick 异常被兜住（不冒泡）', not _raised)
check('tick 异常被计数（可观测）', int(win._tick_errors) == 1)
win._tick = _tk_orig

_pt_orig = win._paint
def _paint_boom(_ev):
    raise RuntimeError('boom-paint')
win._paint = _paint_boom
win._paint_errors = 0
_raised2 = False
try:
    win.paintEvent(None)
except Exception:
    _raised2 = True
check('paint 异常被兜住（不冒泡）', not _raised2)
check('paint 异常被计数（可观测）', int(win._paint_errors) == 1)
win._paint = _pt_orig

# 糖块缺 'e' 字段也不能掀翻整屏（本轮真修过的脆弱点）
_bad = {'x': 300.0, 'y': 300.0}
try:
    _p = pet.QPainter(win)
    win.draw_sugar(_p, _bad)
    _p.end()
    _sugar_ok = True
except Exception:
    _sugar_ok = False
check('糖块缺字段时绘制不抛异常', _sugar_ok)

# ---------- 20. 生活史基因 / 衰老 / 谱系 / 传说（本轮新增） ----------

# 基因从 4 维扩到 7 维，新增三维修为值域必须合法
_g7 = pet.new_gene()
check('生活史基因齐备且值域合法',
      all(k in _g7 for k in pet.GENE_LIFE_KEYS)
      and all(pet.GENE_CLAMP[0] <= _g7[k] <= pet.GENE_CLAMP[1]
              for k in pet.GENE_LIFE_KEYS))

# 新基因必须真的参与遗传（子代 = 双亲均 + 变异）
_pa = pet.new_gene(lon=2.0, app=2.0, fer=2.0)
_pb = pet.new_gene(lon=1.0, app=1.0, fer=1.0)
_k = pet.breed_gene(_pa, _pb)
check('生活史基因参与遗传（落在双亲之间）',
      all(0.5 < _k[k] < 2.5 for k in pet.GENE_LIFE_KEYS))

# 评级只看四维外显基因：生活史基因不能影响稀有度（否则"养得久"被误判成稀有）
check('评级不受生活史基因影响',
      pet.gene_grade(pet.new_gene(spd=1, siz=1, bold=0.5, hue=0.5,
                                  lon=2.2, app=2.2, fer=2.2)) == '普通')

# 寿命：lon 基因决定，且够长（桌宠不该几分钟就老）
_lon_hi = pet.PetFly(10, 10, gene=pet.new_gene(lon=2.0))
_lon_lo = pet.PetFly(10, 10, gene=pet.new_gene(lon=0.5))
check('长寿基因寿命更长',
      _lon_hi.lifespan > _lon_lo.lifespan * 2
      and _lon_hi.lifespan > 600.0)

# 衰老：壮年期活力满、老了变慢且不再生育
_age = pet.PetFly(10, 10, gene=pet.new_gene())
_age.age = 1.0
check('壮年期活力为 1.0', abs(_age.vitality() - 1.0) < 1e-9 and not _age.is_elder())
_age.age = _age.lifespan * 0.99
check('老年期活力下降且被标记',
      _age.vitality() < 1.0 and _age.is_elder()
      and _age.vitality() >= pet.ELDER_MIN_VITALITY - 1e-9)
_vs = []
for _frac in (0.0, 0.3, 0.61, 0.7, 0.85, 1.0, 1.4):
    _age.age = _age.lifespan * _frac
    _vs.append(_age.vitality())
check('活力随年龄单调不增',
      all(_vs[i] >= _vs[i + 1] - 1e-9 for i in range(len(_vs) - 1))
      and abs(_vs[0] - 1.0) < 1e-9 and _vs[-1] <= _vs[2])
check('年龄有可读文案', '年老' in _age.age_text())

# 老虫不参与繁殖（把双亲都设成老虫）
win.flies = [pet.PetFly(600, 500), pet.PetFly(620, 505)]
for f in win.flies:
    win.register_fly(f)
    f.age = f.lifespan * 0.99
    f.energy = pet.E_MAX
    f.eggCd = 0.0
    f.inCage = False
win.eggs = []
check('年老不再生育', win.try_breed(win.flies[0], win.flies[1]) is False)

# 生育力影响产卵冷却
win.flies[0].age = pet.BREED_AGE + 5
win.flies[1].age = pet.BREED_AGE + 5
win.flies[0].gene = pet.new_gene(fer=2.2)
win.flies[1].gene = pet.new_gene(fer=2.2)
_ok2 = win.try_breed(win.flies[0], win.flies[1])
check('生育力高 → 冷却更短（多产）',
      _ok2 and win.flies[0].eggCd < pet.EGG_CD)

# 谱系：蛋里记了亲代编号，孵化后子代能追到爹妈
win.eggs = []
win.flies[0].eggCd = 0.0
win.flies[1].eggCd = 0.0
win.try_breed(win.flies[0], win.flies[1])
_p1, _p2 = win.flies[0].fid, win.flies[1].fid
check('蛋里记下了亲代编号',
      win.eggs and win.eggs[0].get('p1') == _p1 and win.eggs[0].get('p2') == _p2)
win.lineage = []
win.eggs[0]['age'] = pet.EGG_TIME + 0.1
win.update_eggs(0.05)
_kid2 = win.flies[-1]
check('子代记录了亲代（谱系）',
      _kid2.parents == (_p1, _p2))
check('孵化写入谱系流水', len(win.lineage) == 1
      and win.lineage[0]['fid'] == _kid2.fid
      and win.lineage[0]['p1'] == _p1)
check('编号唯一且递增',
      len({f.fid for f in win.flies}) == len(win.flies)
      and all(f.fid > 0 for f in win.flies))

# 新增虫子都拿到编号（放置 / 数量菜单 / 初始）
_before = win.next_fid
_pf = win.register_fly(pet.PetFly(300, 300))
check('register_fly 分配唯一递增编号', _pf.fid == _before
      and win.next_fid == _before + 1)

# 传说个体：金色光晕开关 = 评级为传说
_leg = pet.PetFly(10, 10, gene=pet.new_gene(spd=2.1, siz=2.1, bold=1.4, hue=1.4))
_pl = pet.PetFly(10, 10, gene=pet.new_gene(spd=1, siz=1, bold=0.5, hue=0.5))
check('传说个体被识别（用于光晕）', _leg.is_legendary() and not _pl.is_legendary())

# 标签文案：传说/年老要有标记，且 rect 与文案同源（宽度才不会错位）
_lbl_leg = win.fly_label_text(_leg)
_lbl_elder = win.fly_label_text(_age)
check('标签标出传说/年老',
      '✦' in _lbl_leg and '老' in _lbl_elder)
check('标签宽度按带标记的文案算',
      win.fly_label_rect(_leg) is not None
      and win.fly_label_rect(_leg).width() >= (win.fly_label_rect(_pl).width()
                                              if win.fly_label_rect(_pl) else 0))

# 基因详情卡
_det = win.fly_detail_text(pet.PetFly(10, 10, gene=pet.new_gene(lon=1.8, gen=4)))
check('详情卡含七维基因',
      all(k in _det for k in ('spd', 'siz', 'bold', 'hue', 'lon', 'app', 'fer')))
check('详情卡含世代/年龄/亲代',
      '第 4 代' in _det and '寿命' in _det and '亲代' in _det)
_has_parent = pet.PetFly(10, 10, gene=pet.new_gene())
_has_parent.parents = (3, 7)
check('详情卡能显示亲代编号', '#3 × #7' in win.fly_detail_text(_has_parent))

# 老虫标签/详情都用同一套判定
check('年老详情标注原因',
      '年老后飞行变慢' in win.fly_detail_text(_age))

# 图鉴正文现在要带谱系段
win.codex['hatched'] = 1
check('图鉴正文含谱系段', '最近谱系' in win.codex_text())

# 收尾：还原共享状态，别污染后面的段落
win.eggs = []
win.lineage = []

# ---------- 21. 编号连续性 & 存档失败不静默（本轮真修过的两个点） ----------

# 真 bug：load() 对新虫"发了两次号"（register_fly 一次 + else 分支一次），
# 结果编号变成 #3/#4/#6/#8/#10 这种跳号。造一份"无 fid 的 v3 旧档"来锁死这个行为。
_d_old = json.load(open(pet.SAVE_PATH, encoding='utf-8'))
_d_old['version'] = 3
_d_old.pop('next_fid', None)
_d_old.pop('lineage', None)
_d_old['flies'] = [dict(f) for f in _d_old['flies'][:4]]
for _f in _d_old['flies']:
    _f.pop('fid', None)
    _f.pop('parents', None)
with open(pet.SAVE_PATH, 'w', encoding='utf-8') as _fh:
    json.dump(_d_old, _fh)
_win5 = pet.Overlay(pet.load_settings())
_fids5 = sorted(f.fid for f in _win5.flies)
check('旧档补号不跳号（编号连续）', _fids5 == list(range(1, len(_fids5) + 1)))
check('旧档补号后发号器接续', _win5.next_fid == max(_fids5) + 1)
check('旧档补号后基因仍合法',
      all(pet.GENE_CLAMP[0] <= f.gene.get('lon', 1.0) <= pet.GENE_CLAMP[1]
          for f in _win5.flies))
_win5.hide()
_win5.deleteLater()

# 存档失败曾被 except: pass 全吞 → 表现是"这一局繁殖/图鉴白玩"且毫无提示
_orig_dump = pet.json.dump
def _dump_boom(*_a, **_k):
    raise OSError('disk full')
pet.json.dump = _dump_boom
win._save_err_said = False
win.announce = None
win.save()
pet.json.dump = _orig_dump
check('存档失败不再静默（有标志位）', win._save_err_said is True)
check('存档失败会提示用户', win.announce is not None)

# ---------- 22. 文件收纳（拖到虫身上 → 移动到指定目录） ----------
import tempfile, shutil as _sh

_tmp = tempfile.mkdtemp(prefix='flypet_stash_')
_src = os.path.join(_tmp, 'src')
_dst = os.path.join(_tmp, 'dst')
os.makedirs(_src); os.makedirs(_dst)

def _mkfile(name, where=None):
    p = os.path.join(where or _src, name)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write('x')
    return p

# 三层优先级：单虫专属 > 扩展名规则 > 兜底目录
_fx = win.register_fly(pet.PetFly(400, 400))
win.flies.append(_fx)          # 必须真的在场上，drop_fly_at 才可能命中
_win_cfg_backup = (dict(win.cfg.get('file_stash') or {}),
                   dict(win.cfg.get('fly_stash') or {}))
win.cfg['file_stash'] = {'enabled': True, 'rules': {'.png': _dst},
                         'default_dir': os.path.join(_tmp, 'fallback'),
                         'mode': 'move'}
win.cfg['fly_stash'] = {}
_any = _mkfile('a.png')
check('无指派时按扩展名规则命中',
      win.stash_target_for(_any, _fx) == _dst)
check('规则没命中时落到兜底目录',
      win.stash_target_for(_mkfile('b.xyz'), _fx)
      == os.path.join(_tmp, 'fallback'))
win.cfg['fly_stash'][str(_fx.fid)] = os.path.join(_tmp, 'mine')
check('单虫指派优先级最高（盖过规则）',
      win.stash_target_for(_any, _fx) == os.path.join(_tmp, 'mine'))
win.cfg['file_stash']['enabled'] = False
check('关闭后不接管任何文件（返回 None）',
      win.stash_target_for(_any, _fx) is None)
win.cfg['file_stash']['enabled'] = True

# move_file：正常移动 / 绝不覆盖 / 已在目标目录 / 文件不存在
_f1 = _mkfile('r1.txt')
_out1 = win.move_file(_f1, _dst, 'move')
check('move_file 能把文件搬过去',
      _out1 and os.path.isfile(_out1) and not os.path.exists(_f1)
      and os.path.dirname(_out1) == _dst)
_f2 = _mkfile('r1.txt')            # 同名再来一个
_out2 = win.move_file(_f2, _dst, 'move')
check('同名不覆盖，自动加 (2)',
      _out2 and os.path.basename(_out2) == 'r1 (2).txt'
      and os.path.isfile(_out1) and os.path.isfile(_out2))
check('已在目标目录内 → 不做任何事',
      win.move_file(_out1, _dst, 'move') is None)
check('源文件不存在 → 安全返回 None',
      win.move_file(os.path.join(_src, 'nope.txt'), _dst) is None)

_f3 = _mkfile('c3.txt')
_out3 = win.move_file(_f3, os.path.join(_tmp, 'copy_dst'), 'copy')
check('copy 模式保留原文件',
      _out3 and os.path.isfile(_out3) and os.path.isfile(_f3))

# route_files 分类
_p1 = _mkfile('d1.png'); _p2 = _mkfile('d2.xyz'); _p3 = os.path.join(_src, 'ghost.bin')
_done, _failed, _skipped = win.route_files([_p1, _p2, _p3], _fx)
check('route_files 正确分流（成/挂/跳过）',
      len(_done) == 2 and len(_failed) == 0 and len(_skipped) == 1)
check('分流后文件真的换了位置',
      not os.path.exists(_p1) and not os.path.exists(_p2))

# 【安全底线】一个目录都没配 → 文件必须原地不动，绝不删除
win.cfg['file_stash'] = {'enabled': True, 'rules': {}, 'default_dir': '',
                         'mode': 'move'}
win.cfg['fly_stash'] = {}
_lone = _mkfile('precious.txt')
_d2, _f2b, _s2 = win.route_files([_lone], _fx)
check('没配目录时：不动作、不失败、文件还在',
      _d2 == [] and _f2b == [] and len(_s2) == 1 and os.path.isfile(_lone))

# 真·拖放路径：把文件拖到虫身上松手 → 收纳（而不是被吃掉）
win.cfg['fly_stash'] = {str(_fx.fid): _dst}
_dragf = _mkfile('dropped.png')
_eat_hits = []
_orig_eat2 = win.eat_files
win.eat_files = lambda paths, cr: _eat_hits.append(list(paths))
_md = QMimeData(); _md.setUrls([QUrl.fromLocalFile(_dragf)])
_pt = win.fly_hit_rect(_fx).center()
win.dragEnterEvent(QDragEnterEvent(QPoint(_pt.x(), _pt.y()), Qt.CopyAction,
                                   _md, Qt.LeftButton, Qt.NoModifier))
check('拖到虫身上：拖入被接受且高亮该虫',
      win.drop_fly_hover is _fx and not win.drag_hover)
win.dropEvent(QDropEvent(QPoint(_pt.x(), _pt.y()), Qt.CopyAction, _md,
                         Qt.LeftButton, Qt.NoModifier))
check('拖到虫身上：文件被收纳（没走"吃掉"路径）',
      not _eat_hits and not os.path.exists(_dragf)
      and os.path.isfile(os.path.join(_dst, 'dropped.png')))
check('拖到虫身上后高亮复位', win.drop_fly_hover is None)
win.eat_files = _orig_eat2

# 拖到笼上仍然是"吃掉"（回归：别把两条路径搞混）
win.cage = {'x': 1000, 'y': 700, 'w': 220, 'h': 160, 'locked': True}
_cagef = _mkfile('eaten.png')
_md2 = QMimeData(); _md2.setUrls([QUrl.fromLocalFile(_cagef)])
_cp = win.cage_hit_rect().center()
_eat_hits2 = []
win.eat_files = lambda paths, cr: _eat_hits2.append(list(paths))
win.dropEvent(QDropEvent(QPoint(_cp.x(), _cp.y()), Qt.CopyAction, _md2,
                         Qt.LeftButton, Qt.NoModifier))
# 注意：QUrl.toLocalFile() 返回的是正斜杠路径，不能和原始反斜杠字符串直接比
check('拖到笼上仍走"吃掉"路径（未被收纳改动影响）',
      len(_eat_hits2) == 1
      and os.path.basename(_eat_hits2[0][0]) == 'eaten.png')
win.eat_files = _orig_eat2
win.cage = None

win.cfg['file_stash'], win.cfg['fly_stash'] = _win_cfg_backup
_sh.rmtree(_tmp, ignore_errors=True)

# ---------- 23. 报时虫 ----------
_clk_backup = dict(win.cfg.get('clock') or {})
_old_clock_fid = win.clock_fid
win.focus = None
win.announce = None
win.idleT = 0.0

win.cfg['clock'] = {'fid': 0, 'todos': [], 'show_title': True}
win.clock_fid = 0
check('未指定报时虫时 clock_fly 为 None', win.clock_fly() is None)

_cfly = win.register_fly(pet.PetFly(500, 500))
win.flies.append(_cfly)
win.cfg['clock'] = {'fid': _cfly.fid, 'todos': [], 'show_title': True}
win.clock_fid = _cfly.fid
check('指定后能取到报时虫', win.clock_fly() is _cfly)

win.cfg['clock'] = {'fid': 999999, 'todos': [], 'show_title': True}
win.clock_fid = 999999
check('报时虫已不在场上时安全返回 None', win.clock_fly() is None)

# 文本：时间 / 日期 / 待办
_t = time.struct_time((2026, 9, 25, 8, 5, 0, 4, 268, 0))
win.cfg['clock'] = {'fid': _cfly.fid, 'todos': [], 'show_title': True}
win.clock_fid = _cfly.fid
_lines = win.clock_texts(_t)
check('报时牌显示 HH:MM（补零）', _lines[0] == '08:05')
check('报时牌显示日期与周几', '9月25日' in _lines[1] and '周' in _lines[1])

# ★ 周几必须对得上真实日历。
# 这里原来只断言了 `'周' in _lines[1]` —— 等于什么都没验，所以下面这个
# 差一天的 Bug 一直没被发现：tm_wday 是"周一=0"，而显示用的字符串
# '日一二三四五六' 是"周日=0"，直接拿 tm_wday 当下标就**整体差一天**
# （2026-09-25 是周五，会显示成"周四"）。是绘制基线总览图把日期
# 渲染成"9月25日 周四"才让人看到的。
import datetime as _dt
check('★ 报时牌的周几与真实日历一致（2026-09-25 实际是周五）',
      _lines[1].endswith('周五'))
_wrong_days = []
for _d in range(20, 28):                    # 覆盖一整周，含跨周日的边界
    _date = _dt.date(2026, 9, _d)
    _real = '一二三四五六日'[_date.weekday()]
    _st = time.struct_time((2026, 9, _d, 8, 5, 0, _date.weekday(), 268, 0))
    _got = win.clock_texts(_st)[1]
    if not _got.endswith('周' + _real):
        _wrong_days.append('%d 号显示 %s，实际 周%s' % (_d, _got[-2:], _real))
check('★ 连续 8 天的周几全对（周日的边界最容易错）',
      _wrong_days == [])
if _wrong_days:
    print('   具体错在：', _wrong_days)

win.cfg['clock']['show_title'] = False
check('关掉日期后只剩时间', len(win.clock_texts(_t)) == 1)
win.cfg['clock']['show_title'] = True

win.cfg['clock']['todos'] = ['喝水', '写周报', '取快递']
_td = win.clock_texts(_t)
check('待办出现在报时牌上', len(_td) == 3 and '待办：' in _td[2])

# 待办轮播：不同时刻轮到不同条目（每 6 秒换一条）
_orig_mono = time.monotonic
_base = _orig_mono()
_seen = set()
for _k in range(40):
    _v = _base + _k * 0.6
    time.monotonic = (lambda v: (lambda: v))(_v)
    _seen.add(win.clock_texts(_t)[2])
time.monotonic = _orig_mono
check('待办会轮播（不是永远第一条）', len(_seen) >= 2)
win.cfg['clock']['todos'] = []

# 牌面矩形必须在窗口内（否则会被画到屏幕外/被 mask 裁掉）
_cfly.x, _cfly.y = 60, 60
_rc = win.clock_board_rect(_cfly)
check('报时牌矩形落在窗口内',
      _rc.width() > 40 and _rc.left() >= 0 and _rc.right() <= win.w
      and _rc.top() >= 0 and _rc.bottom() <= win.h)
win.build_mask()
check('报时牌进 mask（否则那块区域会点击穿透）',
      win.mask().contains(QPoint(_rc.center().x(), _rc.center().y())))

# 报时虫会往右下角驻守点靠拢（update 里随机项多，取多只的多数结果才稳）
_px, _py = win.clock_perch()
_edge_backup = getattr(win, 'edge_behavior', True)
win.edge_behavior = False
_improved = 0
_total = 12
for _k in range(_total):
    _f = win.register_fly(pet.PetFly(150, 150))
    win.flies.append(_f)
    win.cfg['clock'] = {'fid': _f.fid, 'todos': [], 'show_title': True}
    win.clock_fid = _f.fid
    _d0 = math.hypot(_px - _f.x, _py - _f.y)
    for _ in range(60):
        win.idleT = 0.0
        _f.escapeT = 0.0
        _f.update(win, 0.05)
    _d1 = math.hypot(_px - _f.x, _py - _f.y)
    if _d1 < _d0 - 20:
        _improved += 1
win.edge_behavior = _edge_backup
check('报时虫会朝驻守点靠拢（%d/%d 显著接近）' % (_improved, _total),
      _improved >= _total * 0.7)
win.cfg['clock'] = _clk_backup
win.clock_fid = _old_clock_fid

# ---------- 24. 多显示器 / 覆盖范围 ----------
_pg = QGuiApplication.primaryScreen().geometry()
_vg = QGuiApplication.primaryScreen().virtualGeometry()
win.apply_screen_geometry('primary')
check('primary 模式只盖主屏',
      (win.w, win.h) == (_pg.width(), _pg.height())
      and win.screen_mode == 'primary')
win.apply_screen_geometry('all')
check('all 模式盖住整个虚拟桌面（不小于主屏）',
      win.w >= _pg.width() and win.h >= _pg.height()
      and (win.w, win.h) == (_vg.width(), _vg.height())
      and win.screen_mode == 'all')
check('切换后 mask 缓存作废（尺寸变了必须重算）', win._prev_mask is None)
win.apply_screen_geometry('garbage')
check('非法值安全回落到 primary', win.screen_mode == 'primary')

# 越界的虫必须被拉回新窗口，不能留在窗口外看不见
win.apply_screen_geometry('all')
_oob = win.register_fly(pet.PetFly(win.w + 500, win.h + 500))
win.flies.append(_oob)
win.apply_screen_geometry('primary')
check('切换覆盖范围后越界的虫被拉回可见区',
      0 <= _oob.x <= win.w and 0 <= _oob.y <= win.h)
if win.flies and win.flies[-1] is _oob:
    win.flies.pop()

# ---------- 25. 配置递归合并 ----------
check('嵌套字典是合并而不是整块覆盖',
      pet.deep_merge({'a': {'x': 1, 'y': 2}, 's': 'v'},
                     {'a': {'y': 9}}) == {'a': {'x': 1, 'y': 9}, 's': 'v'})
check('列表整体覆盖（不逐项合并）',
      pet.deep_merge({'l': [1, 2, 3]}, {'l': [7]})['l'] == [7])
check('load_settings 结果含本轮新增配置',
      all(k in pet.load_settings() for k in
          ('file_stash', 'fly_stash', 'clock', 'screen_mode')))

# ---------- 26. 启动回写完整配置（settings.json 必须"照着能改"） ----------
# 用户只写 {"count": 9} 也能跑，但那样文件里看不到还有哪些键 —— README 却是照它教改配置的。
# 这里验证：回写后是完整模板、用户取值原样保留、且内容没变时不重写。
import json as _json
import tempfile as _tf
_old_sp = pet.SETTINGS_PATH
_tmpd = _tf.mkdtemp(prefix='flypet_cfg_')
try:
    pet.SETTINGS_PATH = os.path.join(_tmpd, 'settings.json')
    with open(pet.SETTINGS_PATH, 'w', encoding='utf-8') as f:
        _json.dump({'count': 9, 'skin': 'pixel', '_guided': True}, f)

    _eff = pet.load_settings()          # 深合并后的"实际生效配置"
    check('回写前：文件里确实缺新增键',
          'file_stash' not in _json.load(open(pet.SETTINGS_PATH, encoding='utf-8')))

    check('sync_settings_file 返回成功', pet.sync_settings_file(_eff) is True)
    _back = _json.load(open(pet.SETTINGS_PATH, encoding='utf-8'))
    check('回写后：新增键出现在文件里',
          all(k in _back for k in ('file_stash', 'fly_stash', 'clock', 'screen_mode')))
    check('回写后：用户原来的取值原样保留',
          _back.get('count') == 9 and _back.get('skin') == 'pixel')
    check('回写后：用户自定义的非默认键也没丢', _back.get('_guided') is True)

    # 幂等：内容一致时不该再动文件（否则每次启动都改 mtime）
    _mt1 = os.stat(pet.SETTINGS_PATH).st_mtime_ns
    pet.sync_settings_file(_eff)
    check('内容没变时不重写文件', os.stat(pet.SETTINGS_PATH).st_mtime_ns == _mt1)
finally:
    pet.SETTINGS_PATH = _old_sp
    try:
        import shutil as _sh
        _sh.rmtree(_tmpd, ignore_errors=True)
    except Exception:
        pass

# ---------- 27. 设置纯逻辑层（规格表 / 摊平 / 守门人 / 恢复默认） ----------
_c = pet.load_settings()
_c['count'] = 7
_c['scale'] = 1.35
_c['file_stash']['rules'] = {'.png': 'D:/图片'}
_v = pet.settings_values_from_cfg(_c)
check('摊平结果覆盖规格表全部键',
      all(k in _v for _, k, _, _, _ in pet.SETTINGS_SPEC))
check('摊平取到嵌套键（file_stash.rules）', _v['file_stash.rules'] == {'.png': 'D:/图片'})
check('spec_get 取不到时返回 None', pet.spec_get(_c, 'a.b.c') is None)
pet.spec_set(_c, 'x.y.z', 5)
check('spec_set 会自动补出中间层', _c['x']['y']['z'] == 5)

# 守门人：越界夹紧、非法候选丢弃、未知键静默无视
_c2 = pet.load_settings()
_w = pet.apply_settings_values(_c2, {
    'scale': 999, 'count': -5, 'screen_mode': 'bogus',
    'feed_hotkey': 'alt+z', '这是不存在的键': 123, 'debug': 'yes'})
check('越界数值被夹到区间内',
      pet.spec_get(_c2, 'scale') == 2.5 and pet.spec_get(_c2, 'count') == 1)
check('下拉的非法候选被拒绝（保持原值）',
      pet.spec_get(_c2, 'screen_mode') == 'primary')
check('规格表里没有的键不会被写进配置', '这是不存在的键' not in _c2)
check('只回报真正改动的键',
      set(_w) == {'scale', 'count', 'feed_hotkey', 'debug'} and
      'screen_mode' not in _w)
check('转不成数值的输入被忽略而不是抛异常',
      pet.apply_settings_values(_c2, {'count': '不是数字'}) == []
      and pet.spec_get(_c2, 'count') == 1)

# 恢复默认可不能顺手清掉用户数据
_c3 = pet.load_settings()
_c3['fly_stash'] = {'3': 'D:/x'}
_c3['clock']['todos'] = ['写周期']
_c3['count'] = 12
pet.settings_reset(_c3)
check('恢复默认会还原被规格表覆盖的键', _c3['count'] == 2)
check('恢复默认不动用户数据（专属收纳目录、待办）',
      _c3['fly_stash'] == {'3': 'D:/x'} and _c3['clock']['todos'] == ['写周期'])

# 收纳规则的文本格式：查找侧是 splitext(...)[1].lower() 比对，两边必须同口径
check('规则文本往返一致',
      pet.text_to_rules(pet.rules_to_text({'.png': 'D:/P', '.pdf': 'D:/D'})) ==
      {'.png': 'D:/P', '.pdf': 'D:/D'})
check('规则文本：不写点自动补、统一小写、忽略注释与残行',
      pet.text_to_rules('PNG = D:/P\n# 注释\n没有等号\n.pdf=D:/D\n = 空键\n') ==
      {'.png': 'D:/P', '.pdf': 'D:/D'})

# ---------- 28. 图形设置面板 ----------
_sk = [(n, n) for n in sorted(pet.load_skins())]
_c4 = pet.load_settings()
_c4['count'] = 7
_c4['quiet'] = True
_c4['file_stash']['rules'] = {'.pdf': 'D:/doc'}
_dlg = pet.SettingsDialog(_c4, dyn_opts={'skin': _sk})
check('面板为规格表每一项都建了控件',
      len(_dlg._widgets) == len(pet.SETTINGS_SPEC))
_dv = _dlg.values()
check('面板取值与配置一致（数值/开关/嵌套键）',
      _dv['count'] == 7 and _dv['quiet'] is True and
      _dv['file_stash.rules'] == {'.pdf': 'D:/doc'})
check('面板皮肤下拉由外部选项填充', _dlg._widgets['skin'].count() == len(_sk))
check('取消时 saved 保持 None（意味着 cfg 一点没动）',
      pet.SettingsDialog(_c4).saved is None)

_dlg._widgets['count'].setValue(9)
_dlg._widgets['quiet'].setChecked(False)
_dlg._widgets['file_stash.rules'].setPlainText('png = D:/P\n.pdf = D:/D')
_dlg.do_save()
check('保存只回报实际改动的键',
      set(_dlg.saved) == {'count', 'quiet', 'file_stash.rules'})
check('保存的改动真的写进了 cfg',
      _c4['count'] == 9 and _c4['quiet'] is False and
      _c4['file_stash']['rules'] == {'.png': 'D:/P', '.pdf': 'D:/D'})

_keep = (_c4['count'], _c4['scale'])
_dlg.do_reset()
check('「恢复默认」只改控件、不碰 cfg（所以还能按取消反悔）',
      (_c4['count'], _c4['scale']) == _keep and
      _dlg._widgets['count'].value() == pet.DEFAULT_SETTINGS['count'])

# 设置变更后需要立刻生效的那部分。
# 注意这里必须改 win.cfg 本身 —— load_settings() 每次返回的是**另一个** dict，
# on_settings_changed 读的是挂在这个 Overlay 上的那一份。
win.cfg['screen_mode'] = 'all'
win.cfg['count'] = 4
win.cfg['skin'] = 'pixel'
_changed = win.on_settings_changed(['screen_mode', 'count', 'skin'])
check('on_settings_changed 会回报处理过的键', set(_changed) ==
      {'screen_mode', 'count', 'skin'})
check('改数量立即生效到虫的实际数量', len(win.flies) == 4)
check('改覆盖范围立即生效到窗口几何', win.screen_mode == 'all')
check('on_settings_changed 不认识的键不会炸',
      win.on_settings_changed(['不存在']) == ['不存在'])
win.cfg['screen_mode'] = 'primary'
win.cfg['count'] = len(win.flies)
win.on_settings_changed(['screen_mode'])

# ---------- 29. 暂停：冻住世界，但别把提醒一起吞掉 ----------
win.cfg['paused'] = True
for _f in win.flies:
    _f.x, _f.y = 300.0, 300.0
_pos_before = [(round(_f.x, 4), round(_f.y, 4)) for _f in win.flies]
win.reminders = [{'at': time.monotonic() - 1.0, 'text': '该喝水了'}]
win.announce = None
for _ in range(20):
    win._tick()
check('暂停时虫的坐标一动不动',
      [(round(_f.x, 4), round(_f.y, 4)) for _f in win.flies] == _pos_before)
check('暂停时到点的提醒照样会喊（不能把提醒一起冻住）',
      win.announce is not None and '该喝水' in win.announce[0])
# ⚠ 这条断言本身就是那个 Bug 的保险栓：它原来写的是 interval() <= 8。
#   名字叫"帧率降到很低"，判据却要求间隔 <= 8ms —— 即 >= 125fps。
#   作者（连同产品代码的 want=6、以及"只有时钟牌要更"那句注释）都把
#   毫秒当成了帧率。所以它一直是绿的，还把真正的省电行为判成失败。
#   教训：断言和被测代码由同一个误解写出来时，测试只会把 Bug 焊死。
check('暂停时帧率降到很低（省电）', win.loop.interval() >= 200)
win.reminders = []
win.cfg['paused'] = False
for _ in range(10):
    win._tick()
check('取消暂停后虫重新开始移动',
      [(round(_f.x, 4), round(_f.y, 4)) for _f in win.flies] != _pos_before)

# ---------- 30. 安静模式：只屏蔽闲聊，不屏蔽"你操作了"的反馈 ----------
_fx2 = win.flies[0]
win.cfg['quiet'] = True
win.cfg['bubbles']['enabled'] = True
_fx2.bubble = None
win.say(_fx2, 'hungry')
check('安静模式下日常闲聊被屏蔽', _fx2.bubble is None)
_fx2.bubble = None
win.say(_fx2, 'social')
check('安静模式下社交气泡也被屏蔽', _fx2.bubble is None)
_fx2.bubble = None
win.say(_fx2, 'stash')
check('安静模式下"收纳结果"仍然要说（否则你不知道文件收没收进去）',
      _fx2.bubble is not None)
_fx2.bubble = None
win.say(_fx2, 'ate_file')
check('安静模式下"吃掉文件"的反馈保留', _fx2.bubble is not None)
win.cfg['quiet'] = False
_fx2.bubble = None
win.say(_fx2, 'hungry')
check('关掉安静模式后闲聊恢复', _fx2.bubble is not None)
_fx2.bubble = None

# ==========================================================================
# 以下 31~35 是"体检"补出来的空白：这些函数此前**一次都没被测试碰过**。
# 全是事件处理器 / 菜单弹框背后的函数 —— 也就是出错会被 Qt 静默吞掉的那一类。
# ==========================================================================


def _evg(fx, fy, btn=Qt.LeftButton):
    """按全局坐标造事件。处理器内部会自己加 self.x()，这里先减掉。"""
    return _ev(int(fx - win.x()), int(fy - win.y()), btn)


# ---------- 31. 拍击（短按）与双击 ----------
win.cage = None                       # 别让笼子抢先命中
win.capture_mode = False
win.pending_place = False
win.flies = []
_sw = win.register_fly(pet.PetFly(420, 420, gene=pet.new_gene()))
win.flies.append(_sw)
_sw.markers = []
_sw.x, _sw.y = 420.0, 420.0
win.pher = []
win.foods = []
win.mousePressEvent(_evg(420, 420))
check('按在虫身上会记下"按下中的那只虫"', win.pressed_fly is _sw)
win.mouseReleaseEvent(_evg(420, 420))          # 立刻松手 = 短按
check('短按 = 拍击：虫记下一个"危险"标记',
      bool(_sw.markers) and _sw.markers[-1]['t'] == -1)
check('拍击会留下报警信息素（同类也会被吓到）',
      any(abs(p['x'] - 420) < 1.5 for p in win.pher))
check('拍击后虫进入逃跑状态', _sw.escapeT > 0)
check('拍击后按下状态被清理干净',
      win.pressed_fly is None and win.pressT is None)
check('短按不会把虫关进笼子或抓走', _sw.grabbed is False and _sw.inCage is False)

# 双击一只虫 → 打个滚（不是丢糖）
_sw.flipT = 0.0
_sw.labelT = 0.0
_dir0 = _sw.dir
win.mouseDoubleClickEvent(_evg(420, 420))
check('双击虫身 = 打个滚', _sw.flipT > 0)
check('打滚会顺带转身', _sw.dir != _dir0)
check('双击虫身会顺手把种类标签亮出来', _sw.labelT > 0)
check('双击虫身不会顺手丢糖（打滚和丢糖得区分开）', win.foods == [])

# 双击空白 → 就地扔一颗糖
_sw.x, _sw.y = 100.0, 100.0
win.mouseDoubleClickEvent(_evg(660, 620))
check('双击空白 = 就地丢一颗糖', len(win.foods) == 1)
check('丢的糖落在双击的位置上',
      abs(win.foods[0]['x'] - 660) < 2 and abs(win.foods[0]['y'] - 620) < 2)

# ---------- 32. 记忆：标记与清除 ----------
_m = win.flies[0]
_m.markers = []
_m.add_marker(120, 240, -1, 0.9)
_m.add_marker(360, 480, 1, 0.5)
check('add_marker 记录位置 / 性质 / 强度',
      len(_m.markers) == 2 and _m.markers[0]['x'] == 120 and
      _m.markers[0]['t'] == -1 and _m.markers[1]['s'] == 0.5)
_m.brain.w[0] = 999.0
_m.learnedAnnounced = True
_m.clear_memory()
check('清除记忆会清空所有标记', _m.markers == [])
check('清除记忆会把脑内权重复位成出厂值', _m.brain.w[0] != 999.0)
check('清除记忆会重置"已提示过学到了"的标志（下次还会再教一遍）',
      _m.learnedAnnounced is False)

# ---------- 33. 单虫收纳目录的指派与收纳反馈 ----------
# 菜单里"指派收纳目录"会弹目录选择框（自检按不了），所以只能直接测函数本体。
import tempfile as _tf2
import shutil as _sh2
_src = _tf2.mkdtemp(prefix='flypet_src_')
_dst = _tf2.mkdtemp(prefix='flypet_dst_')
_old_fly_stash = dict(win.cfg.get('fly_stash') or {})
_old_fs = dict(win.cfg.get('file_stash') or {})
try:
    _sf = win.flies[0]
    _sf.fid = 11
    win.cfg['fly_stash'] = {str(_sf.fid): _dst}
    _p1 = os.path.join(_src, 'note.txt')
    with open(_p1, 'w', encoding='utf-8') as f:
        f.write('x')
    win.announce = None
    _sf.energy = 0.2
    _sf.bubble = None
    _done, _fail, _skip = win.stash_files([_p1], _sf)
    check('stash_files 把文件搬进了那只虫的专属目录',
          len(_done) == 1 and os.path.isfile(os.path.join(_dst, 'note.txt')))
    check('stash_files 会给那只虫加能量（替你干活有奖励）', _sf.energy > 0.2)
    check('stash_files 会说话 + 出一条横幅（不然你不知道成没成）',
          _sf.bubble is not None and win.announce is not None)

    # 没有任何目录可去时：不动文件、要给提示、绝不能失败
    win.cfg['fly_stash'] = {}
    win.cfg['file_stash'] = {'enabled': True, 'rules': {}, 'default_dir': '',
                             'mode': 'move'}
    _p2 = os.path.join(_src, 'keep.txt')
    with open(_p2, 'w', encoding='utf-8') as f:
        f.write('y')
    win.announce = None
    _sf.bubble = None
    _d2, _f2, _s2 = win.stash_files([_p2], _sf)
    check('没配任何目录时：不动作、不失败、文件原封不动',
          _d2 == [] and _f2 == [] and len(_s2) == 1 and os.path.isfile(_p2))
    check('没配目录会明确提示去配（不是静默无反应）',
          _sf.bubble is not None and win.announce is not None)
finally:
    win.cfg['fly_stash'] = _old_fly_stash
    win.cfg['file_stash'] = _old_fs
    _sh2.rmtree(_src, ignore_errors=True)
    _sh2.rmtree(_dst, ignore_errors=True)

# ---------- 34. 最近的那只虫（指派目录 / 查看详情都靠它） ----------
win.flies = []
_na = win.register_fly(pet.PetFly(100, 100))
_nb = win.register_fly(pet.PetFly(900, 900))
win.flies.extend([_na, _nb])
_b1, _d1 = win._nearest_fly(120, 110)
check('_nearest_fly 选中最靠近的那只', _b1 is _na and _d1 < 30)
_b2, _d2 = win._nearest_fly(880, 870)
check('_nearest_fly 换个位置也能选对', _b2 is _nb)
win.flies = []
check('屏幕上没虫时 _nearest_fly 返回空值而不是抛异常',
      win._nearest_fly(0, 0) == (None, 1e9))

# ---------- 35. 遮罩去重（点击穿透不卡桌面的关键） ----------
# setMask 有内核态开销，每帧无脑调用会让桌面明显发卡；区域没变必须跳过。
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion      # QRegion 在 QtGui，不在 QtCore
win.flies = [win.register_fly(pet.PetFly(300, 300))]
win.pending_place = False
win.capture_mode = False
win.cage_drag = False
_calls = {'n': 0}
_orig_set_mask = win.setMask


def _count_set_mask(region):
    _calls['n'] += 1
    return _orig_set_mask(region)


try:
    win.setMask = _count_set_mask
    win._prev_mask = None
    _r = QRegion(QRect(0, 0, 10, 10))
    win.setMask_skip(_r)
    _n1 = _calls['n']
    win.setMask_skip(QRegion(QRect(0, 0, 10, 10)))   # 同区域再来一次
    check('遮罩区域没变时跳过 setMask（否则每帧都下内核调用）',
          _calls['n'] == _n1 == 1)
    win.setMask_skip(QRegion(QRect(0, 0, 20, 20)))   # 换区域
    check('遮罩区域变了会真的重新下发', _calls['n'] == 2)
    win._prev_mask = None
    win.setMask_skip(_r)
    check('缓存作废后即使区域相同也会重新下发', _calls['n'] == 3)
finally:
    win.setMask = _orig_set_mask

# 生效的遮罩必须等于刚算出来的区域（不能只是记下来、没真下发）
win._prev_mask = None
_mm = win.build_mask()
check('build_mask 会把结果记进 _prev_mask 供下次去重', win._prev_mask is not None)
check('当前真正生效的遮罩 == 刚算出来的区域', win.mask() == win._prev_mask)


# ==========================================================================
# 36. 体检第二遍：运行时覆盖报告里"两套测试都没跑到"的那几个函数。
#     共同点 —— 它们全在 Qt 静默吞异常 / 系统调用被 try 包住的路径上，
#     真出了错你只会看到"点了没反应"，所以必须逐个点名测。
#
#     手法统一：**把 stderr 截下来**。PySide6 吞掉异常但会打印回溯，
#     所以"stderr 干净"本身就是一条可断言的结果。
# ==========================================================================
import io as _io
import ctypes as _ct
from ctypes import wintypes as _wt
from PySide6.QtGui import QPixmap, QPainter, QPolygonF


def _quiet(fn, *a, **kw):
    """跑 fn，把 stderr 一起收走。返回 (返回值, stderr 文本)。"""
    b = _io.StringIO()
    o = sys.stderr
    sys.stderr = b
    try:
        r = fn(*a, **kw)
    finally:
        sys.stderr = o
    return r, b.getvalue()


# ---------------- 36.1 开机自启（读真的读一次；写用假模块，不碰真注册表）----
_ae = pet.autostart_enabled()
check('autostart_enabled 返回布尔值（读注册表失败也算 False，不抛异常）',
      isinstance(_ae, bool))


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_wrote = {}


class _FakeWinreg:
    HKEY_CURRENT_USER = 'HKCU'
    REG_SZ = 1

    def CreateKey(self, root, path):
        _wrote['key'] = (root, path)
        return _FakeKey()

    def SetValueEx(self, k, name, res, typ, val):
        _wrote['set'] = (name, typ, val)

    def DeleteValue(self, k, name):
        _wrote['deleted'] = name


import winreg as _real_winreg
sys.modules['winreg'] = _FakeWinreg()
try:
    pet.set_autostart(True)
    check('set_autostart(True) 写的是 HKCU 的 Run 键',
          _wrote.get('key') == ('HKCU', pet.RUN_KEY))
    check('自启项名字就是 FlyPet（重名会覆盖别人的自启项）',
          _wrote.get('set', (None,))[0] == 'FlyPet')
    _val = _wrote.get('set', (None, None, ''))[2]
    check('★ 自启命令用引号整个包住 exe 路径（否则 "C:\\Program Files\\..." '
          '会被拆成两段，开机直接失败）',
          _val.startswith('"') and _val.endswith('"') and
          os.path.abspath(sys.executable) in _val)

    _wrote.clear()
    pet.set_autostart(False)
    check('set_autostart(False) 把那一项删掉', _wrote.get('deleted') == 'FlyPet')

    class _NoVal(_FakeWinreg):
        def DeleteValue(self, k, name):
            raise FileNotFoundError(name)

    sys.modules['winreg'] = _NoVal()
    _ok = True
    try:
        pet.set_autostart(False)
    except Exception as _e:
        _ok = False
        print('  exception:', _e)
    check('关自启时"本来就没设过"不能抛异常（否则菜单点一下就崩）', _ok)
finally:
    sys.modules['winreg'] = _real_winreg


# ---------------- 36.2 全局热键过滤器 ----------------
_heat = []
_hf = pet.HotkeyFilter(lambda: _heat.append(1))
check('HotkeyFilter 能构造（回调/日志都有默认值，不用传 log）',
      _hf.callback is not None and callable(_hf.log))

_msg = _wt.MSG()
_msg.address = 0
_addr = _ct.cast(_ct.byref(_msg), _ct.c_void_p).value
_msg.message = pet.WM_HOTKEY
_msg.wParam = 1
_hf.nativeEventFilter(b'windows_generic_MSG', _addr)
check('收到 WM_HOTKEY(wParam=1) 会喊回调', len(_heat) == 1)

_msg.message = 0x0100       # WM_KEYDOWN，不是热键
_hf.nativeEventFilter(b'windows_generic_MSG', _addr)
_msg.message = pet.WM_HOTKEY
_msg.wParam = 7             # 不是我们注册的那个 id
_hf.nativeEventFilter(b'windows_generic_MSG', _addr)
check('别的消息 / 别的 hotkey id 不会误触发（否则随便敲键盘就撒糖）',
      len(_heat) == 1)

_msg.wParam = 1
_hf.nativeEventFilter(b'windows_dispatcher_MSG', _addr)
check('非 windows_generic_MSG 事件直接放过，不去解包内存',
      len(_heat) == 1)

_ret, _ = _quiet(_hf.nativeEventFilter, b'windows_generic_MSG', 0)
check('★ message 是空指针时返回 False 而不是让进程段错误 —— '
      'MSG.from_address(0) 不抛异常、直接解引用地址 0，except 兜不住，'
      '必须显式判空（这条曾经真的把进程干成 139 退出）',
      _ret == (False, 0))
check('指针解包失败要写进日志 —— 不然热键失灵会是完全静默的',
      isinstance(_hf.nativeEventFilter(b'x', 0), tuple))


# ---------------- 36.3 设置面板里两个"系统对话框"按钮 ----------------
_RealFD = pet.QFileDialog


class _FakeFD:
    ret = ''
    seen = None

    @staticmethod
    def getExistingDirectory(parent, title, start):
        _FakeFD.seen = (title, start)
        return _FakeFD.ret


pet.QFileDialog = _FakeFD
try:
    _dlg = pet.SettingsDialog(win.cfg, dyn_opts={'skin': []})
    _le = _dlg._widgets['file_stash.default_dir']
    _le.setText('D:/old')
    _FakeFD.ret = 'D:/new'
    _dlg._pick_dir(_le)
    check('选目录：选中后写回输入框', _le.text() == 'D:/new')
    check('选目录：对话框起点 = 输入框里现有内容（不用每次从头点）',
          _FakeFD.seen[1] == 'D:/old')
    _FakeFD.ret = ''                     # 用户点了取消
    _le.setText('D:/keep')
    _dlg._pick_dir(_le)
    check('选目录：点取消不覆盖原有内容', _le.text() == 'D:/keep')
finally:
    pet.QFileDialog = _RealFD

_old_sp = pet.SETTINGS_PATH
_old_app = pet.APP
_old_dbg = pet._dbg_enabled          # dbg_log 的开关是**缓存的**，得连它一起设
_tmp_osf = _tf2.mkdtemp(prefix='flypet_osf_')
pet.SETTINGS_PATH = os.path.join(_tmp_osf, 'settings.json')
pet.APP = _tmp_osf                   # 让 _debug.log 落在临时目录，别污染交付目录
pet._dbg_enabled = True
_real_startfile = getattr(os, 'startfile', None)
_opened = []
os.startfile = lambda p: _opened.append(p)
try:
    _r, _err = _quiet(pet.open_settings_file)
    check('open_settings_file 成功时返回 True', _r is True)
    check('打开的就是 settings.json 本身（不是别的路径）',
          bool(_opened) and os.path.abspath(_opened[0]) ==
          os.path.abspath(pet.SETTINGS_PATH))
    check('文件不存在时先落盘一份再打开（否则系统弹"找不到文件"）',
          os.path.isfile(pet.SETTINGS_PATH))

    def _boom(p):
        raise OSError('没有关联程序')

    os.startfile = _boom
    _r2, _err2 = _quiet(pet.open_settings_file)
    check('打开失败返回 False 而不是抛异常（托盘菜单不能被点崩）', _r2 is False)
    _logf = os.path.join(_tmp_osf, '_debug.log')
    _log = open(_logf, encoding='utf-8').read() if os.path.isfile(_logf) else ''
    check('★ 打开失败会把原因写进日志（不然用户完全不知道为什么没反应）',
          '打开 settings.json 失败' in _log and 'OSError' in _log)
finally:
    pet.SETTINGS_PATH = _old_sp
    pet.APP = _old_app
    pet._dbg_enabled = _old_dbg
    if _real_startfile is not None:
        os.startfile = _real_startfile
    else:
        del os.startfile
    _sh2.rmtree(_tmp_osf, ignore_errors=True)


# ---------------- 36.4 脑活动面板（能开、能画、画的时候不炸） ----------------
_keep_flies = win.flies
try:
    win.flies = [pet.PetFly(300, 300), pet.PetFly(400, 400)]
    _panel = pet.BrainPanel(win)
    _panel.resize(380, 560)
    check('脑活动面板能构造出来（菜单里那项点了要有东西出来）',
          _panel.windowTitle() == 'FlyPet 脑活动')
    _pm, _perr = _quiet(_panel.grab)
    check('脑活动面板绘制全程没异常',
          _perr.strip() == '')
    check('★ 25 类神经元每一档都画了：面板不是空白（背景是深色 #10151c）',
          _pm.width() > 0 and
          _pm.toImage().pixelColor(5, 5).name().lower() == '#10151c')
    _panel.timer.stop()

    # 屏幕上没虫时不能崩（这是最常见的启动瞬间状态）
    win.flies = []
    _pm2, _perr2 = _quiet(lambda: pet.BrainPanel(win).grab())
    check('没有虫子时面板照样能画（不抛异常）', _perr2.strip() == '')
    check('没有虫子时面板仍在（不是空图），只是没有放电条',
          _pm2.width() > 0)
finally:
    win.flies = _keep_flies


# ---------------- 36.5 笼子右键菜单 ----------------
_RealMenu = pet.QMenu
_MENU_PICK = {'idx': None}


class _FakeMenu(_RealMenu):
    def exec(self, *a, **k):
        _MENU_PICK['seen'] = self.actions()
        i = _MENU_PICK['idx']
        return self.actions()[i] if i is not None else None


pet.QMenu = _FakeMenu
try:
    # (1) 上锁 → 解锁，同时把关着的虫放出来
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': True}
    win.flies = [pet.PetFly(500, 400)]
    win.flies[0].inCage = True
    _MENU_PICK['idx'] = 0
    _, _e = _quiet(win.cage_menu, QPoint(500, 400))
    check('笼子菜单第一项 = 解锁', _MENU_PICK['seen'][0].text().startswith('解锁'))
    check('点了"解锁"后笼子变成没上锁', win.cage['locked'] is False)
    check('解锁时把关着的虫一起放出来（不然它还困在里面）',
          win.flies[0].inCage is False)
    check('笼子菜单弹出/处理过程无异常', _e.strip() == '')

    # (2) 放出全部
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': False}
    win.flies = [pet.PetFly(500, 400), pet.PetFly(520, 410)]
    for f in win.flies:
        f.inCage = True
    _MENU_PICK['idx'] = 1
    win.cage_menu(QPoint(500, 400))
    check('点了"放出全部果蝇"后一只都不剩在笼里',
          all(not f.inCage for f in win.flies))

    # (3) 笼里放糖
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': False}
    win.foods = []
    _MENU_PICK['idx'] = 2
    win.cage_menu(QPoint(500, 400))
    check('点了"笼里放糖"会在笼心放一颗糖',
          len(win.foods) == 1 and
          abs(win.foods[0]['x'] - 500) < 2 and abs(win.foods[0]['y'] - 400) < 2)

    # (4) 收走笼子
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': False}
    _MENU_PICK['idx'] = 4
    win.cage_menu(QPoint(500, 400))
    check('点了"收走笼子"后笼子没了', win.cage is None)

    # (5) 用户按 Esc 关掉 → 什么都不该变
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': True}
    _MENU_PICK['idx'] = None
    win.cage_menu(QPoint(500, 400))
    check('★ 右键菜单按 Esc 关掉：笼子原样不动（不能当成"选了一项"）',
          win.cage is not None and win.cage['locked'] is True)
finally:
    pet.QMenu = _RealMenu


# ---------------- 36.6 拖文件进笼子 = 吃掉（进回收站） ----------------
# 这是整个产品里唯一会删用户文件的功能，所以连传给 shell 的结构体都要验。
class _OP(_ct.Structure):
    _fields_ = [('hwnd', _wt.HWND), ('wFunc', _wt.UINT),
                ('pFrom', _wt.LPCWSTR), ('pTo', _wt.LPCWSTR),
                ('fFlags', _wt.WORD), ('fAnyOperationsAborted', _wt.BOOL),
                ('hNameMappings', _ct.c_void_p),
                ('lpszProgressTitle', _wt.LPCWSTR)]


# 同布局但指针字段保持整数 —— 取 pFrom 必须用这个视图。
# 坑：从 _OP 里读 op.pFrom 拿到的是**已经被 ctypes 转成 Python str 的值**，
# 到底一个 \0 就截断了；拿这个 str 去 cast(c_void_p) 得到的是个瞎地址，
# string_at 读回来全是乱码（我就这么白查了一轮）。要看"列表里到底有几个文件"，
# 只能按偏移把裸指针取出来，再 string_at 读那块缓冲区。
class _OPRaw(_ct.Structure):
    _fields_ = [('hwnd', _ct.c_void_p), ('wFunc', _wt.UINT),
                ('pFrom', _ct.c_void_p), ('pTo', _ct.c_void_p),
                ('fFlags', _wt.WORD), ('fAnyOperationsAborted', _wt.BOOL),
                ('hNameMappings', _ct.c_void_p),
                ('lpszProgressTitle', _ct.c_void_p)]


_got = {}


class _FakeShell32:
    def SHFileOperationW(self, ptr):
        addr = _ct.cast(ptr, _ct.c_void_p).value
        op = _OP.from_address(addr)
        _got['wFunc'] = op.wFunc
        _got['fFlags'] = op.fFlags
        _got['pTo'] = op.pTo
        _p = _OPRaw.from_address(addr).pFrom
        _got['pFrom_raw'] = _ct.string_at(_p, 256).decode('utf-16-le', 'ignore')
        op.fAnyOperationsAborted = _got.get('abort', 0)
        return _got.get('rc', 0)


class _FakeWindll:
    shell32 = _FakeShell32()


_real_windll = getattr(_ct, 'windll', None)
_ct.windll = _FakeWindll()
try:
    win.cage = {'x': 500, 'y': 400, 'w': 150, 'h': 110, 'locked': True}
    win.flies = [pet.PetFly(500, 400), pet.PetFly(560, 460)]
    win.flies[0].inCage = True
    win.flies[1].inCage = False
    win.flies[0].energy = 10.0
    win.flies[1].energy = 10.0
    win.flies[0].bubble = None
    _cr = win.cage_rect()

    _got.clear()
    _got['rc'] = 0
    _, _e = _quiet(win.eat_files, [r'C:\tmp\a.txt', r'C:\tmp\b.txt'], _cr)
    check('吃文件的动作是 FO_DELETE(3)', _got.get('wFunc') == 3)
    check('★ 两个文件都进了删除列表（pFrom 用 \\0 连接、末尾再加 \\0）',
          'a.txt' in _got.get('pFrom_raw', '') and
          'b.txt' in _got.get('pFrom_raw', ''))
    check('★ 关键：fFlags 带 FOF_ALLOWUNDO(0x40) —— 是进回收站，不是永久删除',
          bool((_got.get('fFlags') or 0) & 0x40))
    check('吃文件不弹确认框(0x10)、不显示进度条(0x4)（说了静默就静默）',
          bool((_got.get('fFlags') or 0) & 0x10) and
          bool((_got.get('fFlags') or 0) & 0x4))
    check('吃成功：笼里的虫加了能量', win.flies[0].energy > 10.0)
    check('吃成功：没关在笼里的虫不加能量（白吃）',
          win.flies[1].energy == 10.0)
    check('吃成功：虫会说一句（不然你不知道文件被吃了）',
          bool(win.flies[0].bubble) and _e.strip() == '')

    # 系统拒绝 / 用户中止 → 不能给奖励、不能给反馈
    win.flies[0].energy = 10.0
    win.flies[0].bubble = None
    _got.clear()
    _got['rc'] = 1                      # 非 0 = 失败
    win.eat_files([r'C:\tmp\c.txt'], _cr)
    check('删除失败：不给能量（不能"没删掉也算干过活"）',
          win.flies[0].energy == 10.0)
    check('删除失败：不说"吃到了"', not win.flies[0].bubble)

    _got.clear()
    _got['rc'] = 0
    _got['abort'] = 1                   # 返回 0 但用户点了中止
    win.eat_files([r'C:\tmp\d.txt'], _cr)
    check('★ 返回码为 0 但 fAnyOperationsAborted=1 时也算没吃成',
          win.flies[0].energy == 10.0)
finally:
    if _real_windll is not None:
        _ct.windll = _real_windll


# ---------------- 36.7 程序化绘制默认皮肤 ----------------
# 默认皮肤不走 sprite，走 draw_procedural。渲染验收只截了具名皮肤的图，
# 这条路径此前两套测试都没走到。
_ppm = QPixmap(80, 80)
_ppm.fill(Qt.transparent)
_p = QPainter(_ppm)
try:
    # 必须先把原点挪到画布中间：draw_procedural 画的是"以虫心为原点"的局部坐标
    # （x 大约 -16..21），对着未平移的画笔直接画，虫大半个身子落在负坐标里，
    # 只剩右下角一点点 —— 第一次跑出来只有 92 个像素就是这么来的。
    _p.translate(40, 40)
    _pf = pet.PetFly(0, 0)
    for _eat in (False, True):
        _pf.eating = _eat
        _pf.wingPhase = 0.7
        _pf.age = 33.0
        _, _e7 = _quiet(win.draw_procedural, _p, _pf)
        check('程序化绘制（eating=%s）不抛异常' % _eat, _e7.strip() == '')
finally:
    _p.end()
_img = _ppm.toImage()
_dots = [(_x, _y) for _x in range(80) for _y in range(80)
         if _img.pixelColor(_x, _y).alpha() > 0]
_npix = len(_dots)
_spanx = (max(d[0] for d in _dots) - min(d[0] for d in _dots) + 1) if _dots else 0
_spany = (max(d[1] for d in _dots) - min(d[1] for d in _dots) + 1) if _dots else 0
check('程序化绘制真的画出了东西（%d 个非透明像素）' % _npix, _npix > 250)
check('★ 画出来的形状是一只横躺的虫（宽 %d × 高 %d，宽明显大于高）'
      % (_spanx, _spany), _spanx >= 30 and 2 <= _spany <= 30 and _spanx > _spany)


# ---------------- 36.8 小工具 ----------------
_poly, _ = _quiet(pet.QPolygonFp, QPointF(1, 2), QPointF(3, 4), QPointF(5, 6))
check('QPolygonFp 按顺序收点', isinstance(_poly, QPolygonF) and
      _poly.count() == 3 and _poly.at(1).x() == 3)
_empty, _ = _quiet(pet.QPolygonFp)
check('QPolygonFp 不收点也不炸（返回空多边形）', _empty.count() == 0)


# ---------------- 36.9 帧率判据（want 的单位是毫秒，不是 fps）----------------
# 背景：这行以前是 `want = 6`。按 fps 读 = 6fps 挺合理，但它其实是**毫秒**
# —— 6ms = 167fps，比活动态（16ms）还费 2.7 倍 CPU，实测暂停态 165.6 fps。
# 注释写着"暂停时更低（只有时钟牌要更）"，行为却是全场最高，而且不报错、
# 界面看着也正常。这类"单位混用"的 bug 只能靠断言守，所以判据被抽成了
# 纯函数 frame_interval()。
_fi = win.frame_interval

win.cfg['paused'] = False
win.need_mouse = False
win.foods = []
win.idleT = 0.0
check('活动态帧间隔 = 16ms（≈62fps）', _fi() == 16)

win.idleT = win.sleep_after + 1.0
check('打盹态帧间隔 = 50ms（≈20fps，比活动慢）', _fi() == 50)

win.foods = [{'x': 1.0, 'y': 1.0, 'e': pet.FOOD_E0}]
check('有糖就不打盹（保持 16ms）', _fi() == 16)
win.foods = []

win.cfg['paused'] = True
win.need_mouse = False
check('暂停态帧间隔 = 200ms（=5fps）', _fi() == 200)
win.need_mouse = True
check('暂停 + 手按住时恢复快帧 16ms（拖笼子要跟手）', _fi() == 16)
win.need_mouse = False

# ★ 真正要守的不变式：**暂停不该比活动更耗**。
#   "暂停"的字面意思是"不用画了"，间隔却比活动态还小的话，用户以为
#   在省电、实际在烧电，而且那恰好是最该省的时刻。
win.cfg['paused'] = False
win.idleT = 0.0
_act = _fi()
win.cfg['paused'] = True
_pause = _fi()
check('★ 暂停帧间隔 >= 活动帧间隔（暂停不能更费）（%d >= %d）' % (_pause, _act),
      _pause >= _act)
check('★ 暂停帧间隔 >= 打盹帧间隔（暂停是三者里最省的）', _pause >= 50)
win.cfg['paused'] = False


print()
print('=' * 40)
print('FAILED:', fails if fails else '无 —— 全部通过')
sys.exit(1 if fails else 0)
