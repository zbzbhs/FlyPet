# -*- coding: utf-8 -*-
"""体检：把产品对外的"表面"清点出来，再跟测试套件逐项对账。

做这件事的起因：前 18 轮的功能和测试都是"写功能时顺手补一条"攒出来的，
覆盖到哪儿、哪儿还是空白，从来没实测过。这个脚本就是那个实测。

用法（先跑一遍自检拿到清单）：
    FLYPET_SELFTEST=inventory FLYPET_AUDIT_OUT=D:/tmp/inv.json python pet.py
    python _audit.py D:/tmp/inv.json

输出：控制台报告 + _audit_report.txt
"""
import ast
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(HERE, 'pet.py')
TEST = os.path.join(HERE, '_test_paths.py')
REPORT = os.path.join(HERE, '_audit_report.txt')

out = io.StringIO()


def emit(s=''):
    print(s)
    out.write(s + '\n')


# ---------------------------------------------------------------- 1. 产品表面

def collect_defs(path):
    """把 pet.py 里所有函数/方法按 所属类 分组抓出来。"""
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    mod_level, classes = [], {}

    def walk(node, cls, prefix=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                if cls is None:
                    mod_level.append((name, child.lineno))
                else:
                    classes.setdefault(cls, []).append((name, child.lineno))
            elif isinstance(child, ast.ClassDef):
                # 嵌套类不单独成组，合并进外层
                walk(child, child.name, prefix)
    walk(tree, None)

    # 按出现顺序重排类
    order = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            order.append(node.name)
    return mod_level, [(c, classes.get(c, [])) for c in order], src


mod_defs, cls_defs, pet_src = collect_defs(PET)
test_src = open(TEST, encoding='utf-8').read()

# ---------------------------------------------------------- 2. 谁被测试碰过

def _name_re(name):
    """匹配一个完整标识符。

    坑：一开始写的是 (?<![\\w.]) —— 把前面带点的引用全漏了。
    于是 pet.apply_settings_values(...)/win.setMask_skip(...) 这种
    最常见的调用方式一个都认不出来，报告里凭空多出一堆"从没过问"的假空白。
    对账脚本漏报比误报危险得多，所以这里只用 \\b 词边界。
    """
    return re.compile(r'\b' + re.escape(name) + r'\b')


def is_referenced(name, _cache={}):
    """测试文件里有没有出现过这个名字。"""
    if name not in _cache:
        _cache[name] = _name_re(name).search(test_src) is not None
    return _cache[name]


def has_assertion_near(name):
    """同一行/紧邻几行里出现了 check( → 认为这条被"断言"过，而不只是被调用。"""
    pat = _name_re(name)
    lines = test_src.splitlines()
    for i, ln in enumerate(lines):
        if pat.search(ln):
            win = '\n'.join(lines[i:min(i + 6, len(lines))])
            if 'check(' in win:
                return True
    return False


# 这些是 Qt 覆写的虚函数 / 平凡访问器，没有独立行为，不参与"覆盖空白"统计
TRIVIAL = re.compile(
    r'^(__\w+__|paintEvent|resizeEvent|closeEvent|showEvent|hideEvent|'
    r'event|sizeHint|paint|cursor|setCursor|unsetCursor|'
    r'__init__|__repr__|_?ui)$')


def measure(title, items, depth=1):
    """对一组函数做对账，返回 (总数, 断言过, 只调用过, 从没碰过)"""
    n = assert_n = onlycall = never = 0
    blanks = []
    for name, lineno in items:
        if TRIVIAL.match(name):
            continue
        n += 1
        if not is_referenced(name):
            never += 1
            blanks.append((name, lineno))
        elif has_assertion_near(name):
            assert_n += 1
        else:
            onlycall += 1
    pad = '  ' * depth
    emit('%s%-28s 共 %3d  断言 %3d  仅调用 %3d  %s' % (
        pad, title, n, assert_n, onlycall,
        ('从没过问 %d' % never) if never else '全覆盖'))
    for name, lineno in blanks:
        emit('%s   · %-34s pet.py:%d' % (pad, name, lineno))
    return n, assert_n, onlycall, never


emit('=' * 74)
emit('FlyPet 体检报告   生成脚本：_audit.py')
emit('=' * 74)
emit('')
emit('⚠ 第一节是**静态文本对账**，口径仅"这个名字在测试文件里出现过"。')
emit('  它的"从没过问"不等于真的没测到 —— swat() / feed() / release_grab()')
emit('  都是事件处理器内部调的，名字在测试文件里永远不会出现，会被误判成空白。')
emit('  **权威结论以 _coverage.py 的运行时覆盖报告为准**；本节只用来找')
emit('  "测试文件里连名字都没提过"的线索。')

tot = [0, 0, 0, 0]
emit('')
emit('一、函数级覆盖对账（pet.py vs _test_paths.py）')
emit('-' * 74)
r = measure('模块级函数', mod_defs)
tot = [a + b for a, b in zip(tot, r)]
for cname, items in cls_defs:
    if not items:
        continue
    emit('')
    r = measure('class %s' % cname, items)
    tot = [a + b for a, b in zip(tot, r)]

emit('')
emit('小计：函数 %d 个 → 有断言 %d（%.0f%%）／仅调用 %d／从没过问 %d'
     % (tot[0], tot[1], 100.0 * tot[1] / max(tot[0], 1), tot[2], tot[3]))

# ------------------------------------------------------------ 3. 菜单表面
inv_path = sys.argv[1] if len(sys.argv) > 1 else None
if inv_path and os.path.exists(inv_path):
    inv = json.load(open(inv_path, encoding='utf-8'))
    menu = inv['menu']
    menus = [e for e in menu if e['kind'] == 'menu']
    acts = [e for e in menu if e['kind'] == 'action']
    real = [a for a in acts if a['text'].strip()]
    seps = [a for a in acts if not a['text'].strip()]
    emit('')
    emit('二、托盘菜单表面')
    emit('-' * 74)
    emit('  子菜单 %d 个 ／ 条目 %d 项（真条目 %d + 分隔线 %d）／ 禁用 %d'
         % (len(menus), len(acts), len(real), len(seps),
            len([a for a in real if not a['enabled']])))
    emit('')
    emit('  各子菜单：')
    for m in menus:
        kids = [a for a in menu
                if a['kind'] == 'action' and a['path'].startswith(m['path'] + ' ▸')]
        emit('    %-46s %2d 项' % (m['path'], len(kids)))

    emit('')
    emit('三、设置面板表面')
    emit('-' * 74)
    emit('  规格表 %d 行，分 %d 组：%s'
         % (len(inv['settings_keys']), len(inv['settings_groups']),
            ' / '.join(inv['settings_groups'])))
    emit('  键：%s' % ', '.join(inv['settings_keys']))

    emit('')
    emit('四、存档表面（save_version=%s）' % inv['save_version'])
    emit('-' * 74)
    emit('  顶层键 %d：%s' % (len(inv['save_top_keys']), ', '.join(inv['save_top_keys'])))
    emit('  单虫键 %d：%s' % (len(inv['fly_keys']), ', '.join(inv['fly_keys'])))

    # 存档键有没有在测试里被断言
    emit('')
    emit('  存档键覆盖：')
    for k in inv['save_top_keys']:
        emit('    %-12s %s' % (k, '有断言' if has_assertion_near(k)
                               else ('仅出现' if is_referenced(k) else '从没过问')))
else:
    emit('')
    emit('（未提供清单 JSON，跳过菜单/设置/存档部分）')

open(REPORT, 'w', encoding='utf-8').write(out.getvalue())
emit('')
emit('报告已写入 %s' % os.path.basename(REPORT))
