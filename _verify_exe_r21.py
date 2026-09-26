# -*- coding: utf-8 -*-
"""确认 exe 里真的是新代码。

为什么不能只 grep 二进制：
    PyInstaller 把主脚本压进 CArchive（zlib），任何字符串在 exe 里都搜不到
    —— grep 永远返回 0，看着像"新代码没进包"。第 20 轮差点据此误判。
    正确做法：用 CArchiveReader 把主脚本抠出来 → marshal.loads →
    递归翻 co_consts 收集字符串常量，再看关键新字符串在不在、旧的在不在。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else 'dist/FlyPet.exe')

from PyInstaller.archive.readers import CArchiveReader
import marshal

raw = CArchiveReader(EXE).extract('pet')
co = marshal.loads(raw if isinstance(raw, bytes) else raw[1])

strs = set()


def consts(code, out):
    for c in code.co_consts:
        if isinstance(c, str):
            out.add(c)
        elif hasattr(c, 'co_consts'):
            consts(c, out)


consts(co, strs)
names = set(co.co_names)


def has(c):
    cn = c.__code__
    found = set()
    consts(cn, found)
    return found | set(cn.co_names)


all_names = set(co.co_names)
for c in co.co_consts:
    if hasattr(c, 'co_consts'):
        all_names |= set(c.co_names)

# 本轮新增/改动的"指纹"
MUST_HAVE = [
    'fly_paint_radius',      # 新增的唯一真相源
    'bubble_rect',
    'frame_interval',
    'setMask_skip',
]
MUST_NOT_HAVE = [
    'want = 6',              # 只是给自己看的记号，下面单独测
]

print('exe =', EXE, '  %d 字节' % os.path.getsize(EXE))
print()
print('函数名在不在（本轮新增/改动的）：')
ok = True
for n in MUST_HAVE:
    hit = n in all_names
    print('   %-22s %s' % (n, '✅ 在' if hit else '❌ 不在'))
    ok = ok and hit

# 关键数字：200（暂停帧间隔）应当作为常量出现，6 应当**不再**出现在
# frame_interval 的字节码里 —— 直接反汇编那个函数最稳。
target = None
for c in co.co_consts:
    if getattr(c, 'co_name', '') == 'frame_interval':
        target = c
        break

if target is None:
    # 方法是嵌在类体里的，递归找
    def find(code, name):
        for c in code.co_consts:
            if getattr(c, 'co_name', '') == name:
                return c
            if hasattr(c, 'co_consts'):
                r = find(c, name)
                if r is not None:
                    return r
        return None
    target = find(co, 'frame_interval')

print()
if target is None:
    print('❌ 找不到 frame_interval（源码里应当有）')
    ok = False
else:
    nums = [c for c in target.co_consts if isinstance(c, int)]
    print('frame_interval 的字节码常量：', sorted(nums))
    print('   含 200（暂停帧间隔）:', '✅' if 200 in nums else '❌')
    print('   含 16 / 50（活动 / 打盹）:', '✅' if (16 in nums and 50 in nums) else '❌')
    print('   不再含 6（旧的 167fps 错误值）:', '✅ 是' if 6 not in nums else '❌ 否')
    ok = ok and 200 in nums and 16 in nums and 50 in nums and 6 not in nums

# 光晕算式里必须有 cfg['scale']：查 fly_paint_radius 的名字表
def find2(code, name):
    for c in code.co_consts:
        if getattr(c, 'co_name', '') == name:
            return c
        if hasattr(c, 'co_consts'):
            r = find2(c, name)
            if r is not None:
                return r
    return None


fpr = find2(co, 'fly_paint_radius')
if fpr is not None:
    print()
    print('fly_paint_radius 里引用的名字：', sorted(fpr.co_names))
    print('   is_legendary:', '✅' if 'is_legendary' in fpr.co_names else '❌')
    print('   size_factor:', '✅' if 'size_factor' in fpr.co_names else '❌')

print()
print('★ 结论：exe 里是新代码' if ok else '★ 有问题：exe 里不是新代码！')
sys.exit(0 if ok else 1)
