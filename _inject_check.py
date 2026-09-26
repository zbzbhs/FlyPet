# -*- coding: utf-8 -*-
"""反向注入：把已经修好的 bug 再塞回源码，确认对应的测试**真的会红**。

为什么必须做这一步：
    "测试全绿"本身不能证明测试有用。测试可能在测一个不存在的情况、
    断言写反了、或者干脆没被执行到 —— 它照样是绿的。
    唯一可靠的验证方式是把旧 bug 放回去，看它是不是立刻变红。

⚠ 判据只看 **FAIL 开头的行**，不能在整份输出里搜关键字：
    期望文案往往同时出现在 PASS 行里（"解锁时把关着的虫一起放出来"），
    全局搜字符串会把"测试通过"误判成"成功抓获" —— 一个自带假阳性的检测器。
    这里改成一个字都不能错：必须在某条 FAIL 行里出现。

用法：python _inject_check.py
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# 解释器可用环境变量 FLYPET_PY 覆盖；默认就用当前正在跑的这个。
PY = os.environ.get('FLYPET_PY', sys.executable)
# ⚠ 必须用**与打 exe 相同**的那套解释器。
#   两套环境装的是不同 Qt：.workbuddy venv 是 PySide6 6.11.2（打 exe 用的），
#   hermes venv 是 6.8.2.1。文本抗锯齿会差 208 px，拿 6.8 去跑 _golden.py
#   会被环境守卫拦下（或者更糟：悄悄比出 0.037% 的假差异）。
#   踩过的坑：之前一直用 hermes venv 生成基线，等于在测一个
#   用户根本看不到的渲染器。

# runner: 用哪套测试去抓这个 bug（默认逻辑测试；绘制类走 golden 基线）
# expect: 必须出现在某条 FAIL 行里的文案
INJECTIONS = [
    # ---------------- 逻辑类（第 19 轮修的） ----------------
    dict(name='笼子"解锁"时不放虫（条件写反）',
         old="            if locked:\n"
             "                for fly in self.flies:\n"
             "                    fly.inCage = False",
         new="            if not locked:\n"
             "                for fly in self.flies:\n"
             "                    fly.inCage = False",
         expect='解锁时把关着的虫一起放出来'),
    dict(name='热键过滤器不判空指针（进程段错误）',
         old="            if not message:\n"
             "                return False, 0\n",
         new="",
         expect='★ message 是空指针时返回 False'),
    dict(name='报时牌周几差一天（下标基准搞错）',
         # tm_wday 是"周一=0"，而 '日一二三四五六' 是"周日=0"，
         # 拿 tm_wday 直接当这套字符串的下标就会整体差一天。
         # 老的断言只写了 `'周' in 文本`，等于没验，所以这个错一直没被发现
         # —— 是绘制基线总览图把日期渲染出来才让人看出来的。
         old="            wd = '一二三四五六日'[now.tm_wday % 7]",
         new="            wd = '日一二三四五六'[now.tm_wday % 7]",
         expect='报时牌的周几与真实日历一致'),
    dict(name='settings.json 打开失败不记日志',
         old="        dbg_log('打开 settings.json 失败\\n' + traceback.format_exc())\n"
             "        return False",
         new="        return False",
         expect='打开失败会把原因写进日志'),

    # ---------------- 绘制类（第 20 轮新加的 golden 基线） ----------------
    dict(name='蛋的"快孵化"裂纹分支丢失',
         old="        if prog > 0.75:",
         new="        if prog > 9.99:      # INJECTED: 裂纹永远不画",
         expect='绘制未回归：egg_hatching',
         runner='_golden.py'),
    dict(name='蛋的裂纹 与 未孵化 长得一样（裂纹画了但没区别）',
         old="                p.drawLine(QPointF(cx - r * 0.5, yy),\n"
             "                           QPointF(cx - r * 0.05, yy + r * 0.22))",
         new="                pass      # INJECTED: 少画一笔",
         expect='绘制未回归：egg_hatching',
         runner='_golden.py'),
    dict(name='笼子锁定 / 解锁指示点同色',
         old="            p.setBrush(QColor('#e26a2a'))",
         new="            p.setBrush(QColor('#4fae5c'))    # INJECTED: 锁定也是绿的",
         expect='绘制未回归：cage_locked',
         runner='_golden.py'),
    dict(name='传说光晕不画了（_paint 里的分支）',
         old="            if fly.is_legendary():",
         new="            if False:      # INJECTED: 光晕不画",
         expect='绘制未回归：overlay',
         runner='_golden.py'),
    dict(name='气泡整体不画了（静默丢绘制）',
         old="        text = fly.bubble[0]\n"
             "        alpha = clamp(fly.bubble[2] / 0.4, 0.0, 1.0)",
         new="        return        # INJECTED: 气泡整块不画\n"
             "        text = fly.bubble[0]\n"
             "        alpha = clamp(fly.bubble[2] / 0.4, 0.0, 1.0)",
         expect='绘制未回归：bubble',
         runner='_golden.py'),

    # ------------- mask 一致性（第 21 轮：_mask_check.py 新增的一类断言）--------
    # 这两个 Bug 的共性是"绘制写一套数、mask 写另一套数"。它们既不会让
    # golden 基线变红（基线看不出 mask 与内容是否一致），也不会让逻辑测试
    # 变红（只验点击能否命中），但会让内容被 setMask **静默裁掉** ——
    # 元素明明在那儿却看不见，而且脏区不含它 → 拖动残影。
    dict(name='气泡 mask 写死 180px（回到旧代码）',
         old="            # 气泡：矩形与 draw_bubble 共用 bubble_rect，不再写死 180px\n"
             "            br = self.bubble_rect(fly)\n"
             "            if br is not None:\n"
             "                # 上下各多留 8px：尾巴画在矩形下沿之外\n"
             "                region |= QRegion(br.adjusted(-2, -2, 2, 8).toAlignedRect())",
         new="            if fly.bubble:\n"
             "                _thb = QFontMetrics(QFont('Microsoft YaHei', 9)).height() + 10\n"
             "                if fly.y - 40 * self.cfg['scale'] - _thb < 4:\n"
             "                    region |= QRegion(QRect(int(fly.x) - 90,\n"
             "                        int(fly.y + 40 * self.cfg['scale']), 180, _thb + 22))\n"
             "                else:\n"
             "                    region |= QRegion(QRect(int(fly.x) - 90,\n"
             "                        int(fly.y) - rf - 60, 180, 60 + _thb + 6))",
         expect='气泡不被裁',
         runner='_mask_check.py'),
    dict(name='传说光晕不乘 cfg scale（mask 与绘制各写一套数）',
         old="                aura = (20.0 + 22.0 * sm) * self.cfg['scale'] * ss",
         new="                aura = 20.0 + 22.0 * sm      # INJECTED: 不乘 scale",
         expect='传说光晕不被裁',
         runner='_mask_check.py'),

    # ------------- 帧率判据（第 21 轮）------------
    # 把"暂停 200ms"改回"6ms"，即 167fps。
    # ⚠ 这里特别值得注意：既有的那条断言原本写的是 `interval() <= 8`，
    #   正好是这个 Bug 的保险栓 —— 注入后它照样通过，只有改正过的断言
    #   （>= 200）才会红。也就是说"测试全绿"曾经是假的。
    dict(name='暂停态帧间隔写 6ms（167fps，比活动还费）',
         old="            return 16 if self.need_mouse else 200",
         new="            return 6        # INJECTED: 把毫秒当成 fps 写",
         expect='暂停时帧率降到很低'),
]

SRC = os.path.join(HERE, 'pet.py')
ok_all = True

for inj in INJECTIONS:
    runner = inj.get('runner', '_test_paths.py')
    src = io.open(SRC, encoding='utf-8').read()
    n = src.count(inj['old'])
    print('=' * 74)
    print('注入：%s   [%s]' % (inj['name'], runner))
    if n != 1:
        print('  跳过 —— 目标片段在 pet.py 里出现 %d 次（应为 1 次），'
              '源码可能已经改过' % n)
        ok_all = False
        continue
    io.open(SRC, 'w', encoding='utf-8').write(
        src.replace(inj['old'], inj['new'], 1))
    try:
        p = subprocess.run([PY, '-u', runner], capture_output=True, timeout=600)
        text = p.stdout.decode('utf-8', 'replace') + \
            p.stderr.decode('utf-8', 'replace')
        # 只有 FAIL 行才算数（见文件头注释）
        bad = [l for l in text.splitlines() if l.startswith('FAIL')]
        hit = [l for l in bad if inj['expect'] in l]
        crashed = p.returncode not in (0, 1)
        if hit:
            print('  ✅ 被抓到：测试变红')
            print('     %s' % hit[0][:100])
        elif crashed:
            print('  ✅ 被抓到：进程直接崩了（returncode=%d）' % p.returncode)
            for l in text.strip().splitlines()[-3:]:
                print('     %s' % l)
        else:
            print('  ❌ 没抓到！把 bug 放回去，%s 照样全绿 —— 这条测试是假的'
                  % runner)
            if bad:
                print('     （红了 %d 条，但都不是期望的那条：%s）'
                      % (len(bad), bad[0][:70]))
            ok_all = False
    finally:
        io.open(SRC, 'w', encoding='utf-8').write(src)      # 一定要还原

print('=' * 74)
print('反向注入结论：%s' % ('全部抓获 —— 这些测试是真的在测东西'
                          if ok_all else '有漏网的，测试不可信'))
sys.exit(0 if ok_all else 1)
