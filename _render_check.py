# -*- coding: utf-8 -*-
"""渲染回归：把这一轮新增的绘制路径（蛋 / 专注进度条 / 基因染色 / 拖放高亮）
全部塞进同一帧，然后 grab() 出来存盘。
目的：paintEvent 里的异常会被 PySide6 静默吞掉，进程照样活着但整屏空白 —— 必须肉眼/像素确认。
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pet
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv[:1])
# 探针绝不能碰真实存档：万一将来有人在这里触发一次 save()，
# 就会把交付目录 / 源码目录的 pet.json 覆盖成"一屏测试数据"。
import tempfile as _tf
pet.SAVE_PATH = os.path.join(_tf.mkdtemp(prefix='flypet_render_'), 'pet.json')
cfg = pet.load_settings()
cfg['count'] = 6
cfg['show_labels'] = True
win = pet.Overlay(cfg)

# 造一屏"什么绘制分支都走一遍"的状态
win.flies = []
for i, (spd, siz, bold, hue) in enumerate(
        [(1.9, 1.8, 1.5, 1.9), (0.5, 0.5, 0.4, 0.5), (1.0, 1.0, 1.0, 1.0),
         (1.4, 1.6, 1.2, 1.3), (0.8, 0.7, 1.6, 1.05), (1.1, 1.3, 0.9, 1.7)]):
    f = win.register_fly(pet.PetFly(
        140 + i * 210, 300 + (i % 3) * 120,
        gene=pet.new_gene(spd=spd, siz=siz, bold=bold, hue=hue, gen=i + 1)))
    f.labelT = 20.0            # 逼出种类标签 + 性状文字
    f.bubble = ('气泡：这一帧要能看见我', time.monotonic() + 30)
    win.flies.append(f)

# 传说个体（金色光晕）+ 老年个体（灰败 + 标签带 ·老）
_leg = win.register_fly(pet.PetFly(300, 1050,
                                   gene=pet.new_gene(spd=2.1, siz=2.1,
                                                     bold=1.4, hue=1.4)))
_leg.labelT = 20.0
_eld = win.register_fly(pet.PetFly(560, 1050, gene=pet.new_gene()))
_eld.age = _eld.lifespan * 0.98          # 逼出"年老"绘制分支
_eld.labelT = 20.0
win.flies += [_leg, _eld]

win.eggs = [{'x': 400, 'y': 700, 'age': 12.0, 'gene': pet.new_gene(), 'skin': None},
            {'x': 460, 'y': 720, 'age': 28.0, 'gene': pet.new_gene(), 'skin': None}]
win.cage = {'x': 1200, 'y': 760, 'w': pet.CAGE_W, 'h': pet.CAGE_H, 'locked': False}
win.drag_hover = True          # 拖放高亮 + 提示条
# 「文件拖到虫身上」的收纳高亮 + 提示条（和笼子那条互斥，这里单独取一帧）
win.cfg['file_stash'] = {'enabled': True, 'rules': {}, 'default_dir': '',
                         'mode': 'move'}
win.cfg['fly_stash'] = {str(win.flies[2].fid): 'D:/收纳/实验图片'}
win.drop_fly_hover = win.flies[2]
# 报时虫：右下角驻守 + 待办
win.cfg['clock'] = {'fid': win.flies[0].fid, 'show_title': True,
                    'todos': ['把渲染验证跑一遍', '写周报']}
win.clock_fid = win.flies[0].fid
win.flies[0].x, win.flies[0].y = win.clock_perch()
win.foods = [{'x': 700.0, 'y': 900.0, 'e': pet.FOOD_E0}]
win.fx = []
win.announce = ('渲染回归测试横幅', time.monotonic() + 60)
win.start_focus(25)            # 专注进度条

win.show()
app.processEvents()
# 跑几帧，让 paintEvent 真的执行到
for _ in range(6):
    win.tick()
    app.processEvents()
    time.sleep(0.05)

pm = win.grab()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_render_check.png')
pm.save(out)

# 像素级自检：不能是纯空白
img = pm.toImage()
nonblank = 0
for y in range(0, img.height(), 4):
    for x in range(0, img.width(), 4):
        c = img.pixelColor(x, y)
        if c.alpha() > 20:
            nonblank += 1
print('保存', out, img.width(), 'x', img.height())
print('不透明像素采样数 =', nonblank)
print('蛋数 =', len(win.eggs), ' 虫数 =', len(win.flies), ' 专注中 =', bool(win.focus))
win.stop_focus(silent=True)

# ---- 设置面板也要能真的画出来（它是个独立窗口，paintEvent 没跑过就不知道会不会白屏）----
skins = [(n, win.skin_disp.get(n, n)) for n in sorted(win.skins)]
dlg = pet.SettingsDialog(win.cfg, dyn_opts={'skin': skins})
dlg.resize(600, 470)
dlg.show()
app.processEvents()
dpm = dlg.grab()
dout = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_dlg_check.png')
dpm.save(dout)
dimg = dpm.toImage()
dop = 0
dtot = 0
for y in range(0, dimg.height(), 4):
    for x in range(0, dimg.width(), 4):
        dtot += 1
        if dimg.pixelColor(x, y).alpha() > 20:
            dop += 1
print('保存', dout, dimg.width(), 'x', dimg.height())
print('设置面板不透明像素采样数 =', dop, '/', dtot)
print('设置面板分组数 =', pet.SETTINGS_SPEC and
      len({r[0] for r in pet.SETTINGS_SPEC}))
print('设置面板控件数 =', len(dlg._widgets))
dlg.close()
