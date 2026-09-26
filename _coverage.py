# -*- coding: utf-8 -*-
"""运行时覆盖统计：真跑一遍测试，看 pet.py 里到底哪些函数真的执行过。

为什么不用"在测试文件里搜函数名"那种文本对账：
    swat() 是 mouseReleaseEvent 内部调的，release_grab() 也是，
    feed() 是 mouseDoubleClickEvent 内部调的 —— 这些名字在测试文件里
    永远不会出现，文本对账会把它们全报成"没测过"，凭空造出一堆假空白。

为什么必须**两个进程**跑两套测试：
    _test_paths.py 先建了 QApplication 单例，同进程里再跑
    _render_check.py 会 RuntimeError: Please destroy the QApplication singleton。
    所以每个 harness 一个子进程，各自把命中的行号 dump 成 JSON 交回来。

而且两套一起算才准：只跑 _test_paths 的话，draw_egg/draw_skin/_paint
这些全会被判成空白 —— 但其实 _render_check 每次 grab() 都会把它们跑一遍。

输出：_coverage_report.txt

用法：python _coverage.py
"""
import ast
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(HERE, 'pet.py')
HARNESS = [
    ('_test_paths.py', '逻辑测试'),      # 286 项断言
    ('_render_check.py', '渲染验收'),    # 截图 + 采样不透明像素（**不带断言**）
    ('_golden.py', '绘制基线'),          # 逐字节比对基线图（带断言）
]
# 短名：报告里给每个函数标注它被哪几条 harness 跑过
SHORT = {'_test_paths.py': '逻辑', '_render_check.py': '渲染', '_golden.py': '基线'}
# 哪些 harness 会**断言**（渲染验收只是截图采样，不算）
ASSERTING = {'_test_paths.py', '_golden.py'}
assert set(SHORT) == {f for f, _ in HARNESS}
REPORT = os.path.join(HERE, '_coverage_report.txt')

os.chdir(HERE)
PET_ABS = os.path.abspath(PET).lower()

# ============================================================ 子进程分支
# 子进程只干一件事：跑指定 harness，把命中行号 + 它自己的输出写进 JSON。
_CHILD = os.environ.get('FLYPET_COV_CHILD')
if _CHILD:
    import runpy

    _hits = set()

    def _is_pet(frame):
        fn = frame.f_code.co_filename
        return fn.endswith('pet.py') and os.path.abspath(fn).lower() == PET_ABS

    def _trace(frame, event, arg):
        """只记 'line'。'call' 事件记的是 def 那一行 —— 那是坑，见下。"""
        if _is_pet(frame):
            if event == 'line':
                _hits.add(frame.f_lineno)
            return _trace
        return None

    _buf = io.StringIO()
    _ro, _re = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _buf
    sys.settrace(_trace)
    try:
        runpy.run_path(os.path.join(HERE, _CHILD), run_name='__main__')
    except SystemExit:
        pass
    except BaseException:
        sys.settrace(None)
        sys.stdout, sys.stderr = _ro, _re
        import traceback
        _buf.write(traceback.format_exc())
    finally:
        sys.settrace(None)
        sys.stdout, sys.stderr = _ro, _re

    with open(os.environ['FLYPET_COV_OUT'], 'w', encoding='utf-8') as f:
        json.dump({'hits': sorted(_hits), 'text': _buf.getvalue()}, f)
    sys.exit(0)


# ============================================================ 主进程分支
tree = ast.parse(open(PET, encoding='utf-8').read())
FUNCS = []          # (qualname, 函数体首行, 末行)


def _collect(node, prefix):
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 坑：行区间必须从 body[0] 起算，**不能**从 def 那行起算。
            # 因为在模块体/类体里执行 `def foo():` 这行本身会产生一个 line 事件，
            # 归属的还是 pet.py 帧 —— 于是每个函数都"至少命中 1 行"，
            # 报告直接显示 100% 覆盖。第一版就是这么骗了我一次
            # （main 760 行、"命中 1 行"，才露的马脚）。
            body = ch.body[0]
            FUNCS.append((prefix + ch.name, body.lineno,
                          ch.end_lineno or body.lineno))
        elif isinstance(ch, ast.ClassDef):
            _collect(ch, ch.name + '.')


_collect(tree, '')

# Qt 覆写的虚函数/平凡访问器：执行了但没有独立行为，单列，不算进分母
VIRTUAL = {'paintEvent', 'resizeEvent', 'closeEvent', 'showEvent', 'hideEvent',
           'event', 'sizeHint', 'nativeEventFilter', 'poll', 'encode'}


def run_harness(fname):
    """在子进程里跑一个 harness，回收 (输出, 命中行集合)。"""
    fd, path = tempfile.mkstemp(suffix='.json', prefix='flypet_cov_')
    os.close(fd)
    env = dict(os.environ, FLYPET_COV_CHILD=fname, FLYPET_COV_OUT=path)
    # 关键：清掉可能被继承、会改变 pet.py 行为的自检/测试环境变量
    for k in ('FLYPET_SELFTEST', 'FLYPET_AUDIT_OUT', 'FLYPET_TEST', 'FLYPET_SCENE'):
        env.pop(k, None)
    try:
        subprocess.run([sys.executable, os.path.abspath(__file__)],
                       env=env, cwd=HERE, capture_output=True, timeout=600)
        data = json.load(open(path, encoding='utf-8'))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return data['text'], set(data['hits'])


harness_out = {}
for _f, _label in HARNESS:
    _t, _h = run_harness(_f)
    harness_out[_f] = (_label, _t, _h)

HITS = {f: h for f, (_l, _t, h) in harness_out.items()}
ALL_HIT = set()
for _h in HITS.values():
    ALL_HIT |= _h

out = io.StringIO()


def emit(s=''):
    out.write(s + '\n')


def hits_in(lo, hi, hit):
    return sum(1 for ln in hit if lo <= ln <= hi)


covered, gaps, virtual = [], [], []
for name, lo, hi in FUNCS:
    base = name.rsplit('.', 1)[-1]
    n = hits_in(lo, hi, ALL_HIT)
    who = [SHORT[f] for f in HITS if hits_in(lo, hi, HITS[f]) > 0]
    src = '+'.join(who) if who else '无'
    asserted = any(f in ASSERTING and hits_in(lo, hi, HITS[f]) > 0 for f in HITS)
    if base in VIRTUAL and n:
        virtual.append((name, lo, n))
    elif n:
        covered.append((name, lo, n, hi - lo, src, asserted))
    else:
        gaps.append((name, lo, hi))

emit('=' * 74)
emit('FlyPet 运行时覆盖报告（真跑一遍，不是搜名字）')
emit('=' * 74)
emit('')
emit('三套测试各自的结果：')
for f, (label, text, hit) in harness_out.items():
    # 各脚本的"结论行"格式不一样，分开抓：
    #   _test_paths.py  → FAILED: ...  ／  _golden.py → 失败 N 项
    #   _render_check.py 没有断言，输出的是采样数字
    tail = [l.strip() for l in text.splitlines()
            if l.startswith('FAILED') or l.startswith('失败 ')]
    if f == '_render_check.py':
        tail = [l.strip() for l in text.splitlines()
                if '不透明像素采样' in l][:1]
    nums = [l.strip() for l in text.splitlines()
            if f == '_render_check.py' and '设置面板' in l][:1]
    npass = len([l for l in text.splitlines() if l.startswith('PASS')])
    emit('  %-17s %-5s pet.py 命中 %4d 行   %s'
         % (f, label, len(hit), '／'.join(tail) if tail else ''))
    if npass:
        emit('  %-17s       通过断言 %d 条' % ('', npass))
    for l in nums:
        emit('  %-17s       %s' % ('', l))
emit('')

n_all = len(FUNCS)
n_v = len(virtual)
emit('pet.py 顶层函数/方法 %d 个' % n_all)
emit('  · 运行时被执行   %3d（%.0f%%）' % (len(covered) + n_v,
                                         100.0 * (len(covered) + n_v) / n_all))
emit('  · 其中 Qt 虚函数/平凡访问器 %d 个（执行了但没有独立行为，注释计）' % n_v)
emit('  · 真·独立函数    %3d，被执行 %3d（%.0f%%）'
     % (len(covered) + len(gaps), len(covered),
        100.0 * len(covered) / max(len(covered) + len(gaps), 1)))
emit('  · 一次都没执行   %3d' % len(gaps))
emit('')
by_src = {}
for c in covered:
    by_src[c[4]] = by_src.get(c[4], 0) + 1
emit('  覆盖来源分布：%s' % ' ／ '.join(
    '%s %d' % (k, v) for k, v in sorted(by_src.items(), key=lambda x: -x[1])))
_nas = len([c for c in covered if not c[5]])
emit('  其中"有断言在检查它"的：%d 个；只被截图采样兜着、无断言的：%d 个'
     % (len(covered) - _nas, _nas))
emit('  （渲染验收只采样不透明像素数，不比对内容 —— 它跑到 ≠ 有人检查它）')
emit('')

emit('二、三套测试都没执行到的函数')
emit('-' * 74)
if not gaps:
    emit('  无')
for name, lo, hi in gaps:
    classify = ('绘制/渲染' if name.split('.')[-1].startswith(('draw', 'paint'))
                else '系统对接' if 'cpu' in name.lower() or 'clip' in name.lower()
                else '对话框/菜单' if 'menu' in name.lower() or 'dialog' in name.lower()
                else '事件处理器'
                if name.split('.')[-1].startswith(('mouse', 'drag', 'drop'))
                else '内部逻辑')
    emit('  %-46s pet.py:%-5d  [%s]' % (name, lo, classify))

emit('')
emit('三、只被截图采样兜着、没有任何断言在检查的函数（真正的灰区）')
emit('-' * 74)
onlyr = [c for c in covered if not c[5]]
for name, lo, n, span, src, _a in sorted(onlyr, key=lambda x: -x[3]):
    emit('  %-42s pet.py:%-5d 命中 %3d 行 / 共 %3d 行  [%s]'
         % (name, lo, n, span, src))
if not onlyr:
    emit('  无 —— 所有被执行到的函数都有断言在检查')

emit('')
emit('四、被执行但只在"顺带跑过"层面的（命中行数 ≤ 3）')
emit('-' * 74)
thin = [c for c in covered if c[2] <= 3]
for name, lo, n, span, src, _a in sorted(thin, key=lambda x: x[2]):
    emit('  %-44s pet.py:%-5d 命中 %d 行 / 共 %d 行  [%s]'
         % (name, lo, n, span, src))
if not thin:
    emit('  无')

emit('')
emit('五、覆盖最厚的几个（反向确认 trace 真的在工作）')
emit('-' * 74)
for name, lo, n, span, src, _a in sorted(covered, key=lambda x: -x[2])[:10]:
    emit('  %-44s pet.py:%-5d 命中 %4d 行 / 共 %4d 行  [%s]'
         % (name, lo, n, span, src))

open(REPORT, 'w', encoding='utf-8').write(out.getvalue())
print(out.getvalue())
print('报告已写入 %s' % os.path.basename(REPORT))
