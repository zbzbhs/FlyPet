# -*- coding: utf-8 -*-
"""量三种状态下的**真实帧率**（数 tick 调用次数，不用采样 CPU —— 采样有噪声）。

踩过的坑：第一版用 `processEvents() + time.sleep(0.001)` 手动泵事件，
但 Windows 上 sleep(1ms) 实际睡 15.6ms，等于拿一个 16ms 粗粒度的泵去驱动
定时器 —— 测出来"打盹 30fps"这种四不像的数。定时器必须交给 Qt 自己的
事件循环（app.exec()），再用 singleShot 定时退出。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _golden as G
from PySide6.QtCore import QTimer

G.setup(verbose=False)
APP = G.ensure_app()
WIN = G.WIN

COUNT = [0]
REAL_TICK = WIN._tick


def counting_tick():
    COUNT[0] += 1
    REAL_TICK()


WIN._tick = counting_tick


def measure(label, seconds=3.0):
    COUNT[0] = 0
    WIN.loop.start(WIN.loop.interval())     # 先按当前 interval 起跑
    t0 = time.perf_counter()
    QTimer.singleShot(int(seconds * 1000), APP.quit)
    APP.exec()                              # ★ 交给 Qt 自己泵
    el = time.perf_counter() - t0
    fps = COUNT[0] / el
    print('   %-24s interval=%4d ms   实测 %6.1f fps' %
          (label, WIN.loop.interval(), fps))
    return fps


WIN.cfg['paused'] = False
WIN.flies, WIN.eggs, WIN.foods, WIN.pher, WIN.fx = [], [], [], [], []
G.mkfly(WIN, 300.0, 300.0)
G.mkfly(WIN, 600.0, 300.0)
WIN.cfg['bubbles']['enabled'] = False

print('三种状态的实测帧率（tick 调用次数 / 秒）：')

WIN.idleT = 0.0
WIN.loop.setInterval(16)
measure('活动（鼠标在动）')

WIN.idleT = 1e9
WIN.loop.setInterval(16)                    # 重置，看它自己会不会降到 50
measure('打盹（idleT > sleep_after）')

WIN.cfg['paused'] = True
WIN.loop.setInterval(16)
measure('暂停（用户手动暂停）')

print()
print('sleep_after = %.0f 秒（cfg sleep_minutes=%s）' %
      (WIN.sleep_after, WIN.cfg.get('sleep_minutes')))
print('want 是**毫秒**：16ms=62fps  50ms=20fps  6ms=167fps')
