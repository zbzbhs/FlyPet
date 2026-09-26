# -*- coding: utf-8 -*-
"""
FlyPet —— 连接组脑桌宠
一只由真实果蝇连接组约简 LIF 脑驱动的小飞虫：
  · 拍它会记仇（PPL1 多巴胺 → KC→MBON_av 惩罚学习，会随时间消退）
  · 投喂会亲近（GRN → PAM 奖赏学习）
  · 鼠标逼近会触发巨纤维逃逸反射
  · 会饿，饿了更敢冒险；CPU 占用高时烦躁乱飞
  · 脑的可塑权重 + 空间记忆存 JSON，重启后还记得你
形象可换肤：skins/<名字>/skin.json + 同目录 PNG 帧序列
"""
import sys
import os
import json
import math
import time
import random
import shutil
import tempfile
import traceback
import ctypes
from ctypes import wintypes

from PySide6.QtCore import (Qt, QTimer, QRect, QRectF, QPoint, QPointF, QElapsedTimer,
                            QAbstractNativeEventFilter)
from PySide6.QtGui import (QGuiApplication, QPainter, QColor, QPen, QPixmap, QIcon,
                           QCursor, QAction, QFont, QFontMetrics, QRegion)
from PySide6.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu,
                               QInputDialog, QMessageBox, QFileDialog,
                               QDialog, QTabWidget, QFormLayout,
                               QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox,
                               QDoubleSpinBox, QComboBox, QLineEdit, QPushButton,
                               QLabel, QPlainTextEdit)

from brain import Brain, NET, CTYPE, clamp, randn, angdiff

# 打包(PyInstaller onefile)后：资源在 _MEIPASS，用户数据/配置/自装皮肤在 exe 旁
if getattr(sys, 'frozen', False):
    BUNDLE = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    APP = os.path.dirname(sys.executable)
else:
    BUNDLE = os.path.dirname(os.path.abspath(__file__))
    APP = BUNDLE
DATA_DIR = os.path.join(APP, 'data')
SKINS_DIRS = [os.path.join(BUNDLE, 'skins'), os.path.join(APP, 'skins')]
SAVE_PATH = os.path.join(DATA_DIR, 'pet.json')
SETTINGS_PATH = os.path.join(APP, 'settings.json')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SKINS_DIRS[-1], exist_ok=True)

TAU = math.pi * 2

# ----------------------------- 世界参数 -----------------------------
FOOD_E0 = 2000.0        # 一块糖总能量
FOOD_DECAY = 0.30       # 自然变质 (能量/s)
FOOD_EMIT = 3.0         # 气味强度
FOOD_L = 170.0          # 气味衰减距离 (px)
ALARM_R = 320.0         # 警报传播距离 (px)，超过就"事不关己"
CAGE_W, CAGE_H = 150, 110   # 笼子尺寸
FOOD_R = 13.0
FEED_RANGE = 24.0
FEED_RATE = 25.0        # 进食回能 (能量/s)
FOOD_CONSUME = 1.3
E_MAX, E_START = 145.0, 115.0
HUNGRY_AT, DESP_AT = 62.0, 26.0
CRUISE, SURGE = 85.0, 190.0
TURN, NOISE, CAST = 5.0, 2.4, 5.2
WALL_PAD = 40.0
SEEK_GAIN, ALARM_GAIN = 1.7, 1.15
AVOID_R, AVOID_GAIN = 90.0, 3.4
FEED_THR, ESCAPE_THR = 6.0, 20.0
GRAB_DELAY = 0.30       # 按住多久算抓取 (s)
FORGET_SECONDS = 2.0 * 86400   # 空间记忆遗忘时间 (2 天)
PHER_TAU = 6.0

# ---- 遗传 / 繁殖 ----
# 四维"外显"基因（决定长相与能力，参与稀有度评级）
GENE_KEYS = ('spd', 'siz', 'bold', 'hue')
# 三维"生活史"基因（决定寿命/食量/生育力，不参与评级——它们不该让虫"更稀有"）
GENE_LIFE_KEYS = ('lon', 'app', 'fer')
GENE_ALL_KEYS = GENE_KEYS + GENE_LIFE_KEYS
GENE_SIGMA = 0.16       # 子代相对亲代的变异幅度
GENE_CLAMP = (0.45, 2.2)
BREED_AGE = 25.0        # 至少活这么久才性成熟 (s)
BREED_ENERGY = 0.72     # 能量高于此比例才有生育意愿
EGG_TIME = 34.0         # 孵化时长 (s)
EGG_CD = 26.0           # 同一只虫产卵冷却 (s)

# ---- 寿命与衰老（不死亡，只是"老了"）----
# 桌宠不该会死，那会让人难受。老龄表现为：飞行变慢、不再生育、体色发灰。
BASE_LIFESPAN = 1500.0  # 标准寿命 25 分钟，× lon 基因（0.45~2.2 → 约 11~55 分钟）
ELDER_AT = 0.62         # 走过寿命的 62% 开始显老
ELDER_MIN_VITALITY = 0.62   # 年老后活力下限（速度/生育意愿乘子）

# ---- 谱系 ----
LINEAGE_KEEP = 24       # 图鉴里保留的最近诞生记录条数

# ---- 番茄钟 ----
FOCUS_SPOTS = ('bottom-right', 'bottom-left', 'top-right', 'top-left')

# ---- 屏幕边缘行为 ----
EDGE_BAND = 46.0        # 距边多近算"贴边"
EDGE_HUG_CHANCE = 0.35  # 空闲时选择贴边的概率


GROUP_COLOR = {'Sensory': '#e2b714', 'Drives': '#9b59b6',
               'Central': '#28a6e2', 'Motor': '#e26a2a'}

DEFAULT_SETTINGS = {
    "skin": "pixel",
    "scale": 1.0,
    "speed_scale": 1.0,
    "count": 2,
    "max_flies": 30,
    "show_labels": True,
    "feed_hotkey": "ctrl+alt+f",
    "hunger_minutes": 35,
    "sleep_minutes": 5,
    "cpu_agitation": True,
    # ---- 开关型状态（也是配置，跟着 settings.json 走）----
    "paused": False,       # 暂停：冻住虫的移动/衰老/繁殖，但提醒与番茄钟照常计时
    "quiet": False,        # 安静模式：屏蔽日常闲聊气泡，保留"你操作后"的反馈
    "pomodoro_min": 25,    # 番茄钟默认时长（分钟）
    "debug": False,        # 写 _debug.log 排障日志
    # ---- 文件收纳：把文件拖到某只虫身上 → 移动到指定文件夹 ----
    # 解析顺序：该虫专属目录（菜单可指派）→ 扩展名规则 → 兜底目录
    # 三者都没配 → 什么都不做并提示（绝不静默删用户的文件）
    "file_stash": {
        "enabled": True,
        "rules": {},          # {".png": "D:/图片", ".pdf": "D:/文档"}
        "default_dir": "",    # 兜底目录（配了才生效）
        "mode": "move",       # move | copy
    },
    # 每只虫的专属收纳目录，按编号存（编号跨重启稳定）
    "fly_stash": {},
    # ---- 报时虫：一只虫头顶顶一块时钟牌，可顺带轮播待办 ----
    "clock": {
        "fid": 0,             # 0 = 关闭；其它值 = 负责报时的那只虫的编号
        "todos": [],          # 待办清单，报时牌上轮流显示
        "show_title": True,   # 牌子上是否显示"周几"
    },
    # ---- 多显示器 ----
    "screen_mode": "primary",  # primary = 只覆盖主屏；all = 覆盖所有显示器
    "bubbles": {
        "enabled": True,
        "show_seconds": 2.8,
        "texts": {
            "hungry":   ["有点饿了…", "哪里有糖味？", "嗡嗡…想吃东西"],
            "starving": ["快饿扁了！！", "任何糖都行…"],
            "full":     ["吃饱啦~", "满足！", "这糖不错"],
            "swat":     ["记住了，这里危险！", "可恶，被拍到了…"],
            "scared":   ["！！！", "好险好险", "有袭击！"],
            "learned":  ["这片区域…我记住了"],
            "sleepy":   ["（打盹中）zzz", "呼…呼…", "（悬停小憩）"],
            "social":   ["碰碰触角~", "同类！嗡嗡", "一起飞呀", "你的糖分我了吗？"],
            "lay":      ["（产下一枚卵）", "要有小宝宝了…", "这里不错，就这儿"],
            "contest":  ["这块我先来的！", "让开让开！", "（把同伴挤走了）"],
            "fight":    ["嗡嗡！（撞了一下）", "别过来！", "（两只扭打在一起）"],
            "tired":    ["呼…内存有点挤", "（累了，喘口气）", "这机器有点喘"],
            "focus_on": ["（找个角落安静趴着）", "专注中，不打扰你", "（安静的小角落）"],
            "caged":    ["又进来啦？", "笼子待着也行", "嗡嗡（安顿下来）", "这里视野不错"],
            "elder":    ["（飞得慢了些…）", "年纪大了，飞不动咯", "（动作变缓）"],
            "legend":   ["（身上泛着金光）", "我可是传说哦", "（稀有血统）"],
            "stash":    ["这个我搬走啦", "收好了~", "（把文件拖走了）", "放到你的收纳夹了"],
            "stash_no": ["没给我指派收纳目录…", "这个我不知道该放哪", "先给只虫指定个文件夹吧"],
            "ate_file": ["嘎嘣脆！", "好吃！谢谢投喂", "吃掉了哦~", "唔…这是什么味的"],
            "grabbed":  ["放开我！", "挣扎挣扎…", "嗡嗡嗡！"],
            "idle":     ["嗡嗡…", "（巡逻中）"],
            "food_in":  ["糖！！", "有吃的！！", "冲冲冲！"]
        }
    }
}


def deep_merge(base, over):
    """递归合并配置：字典逐层合并，其它类型（含列表）整体覆盖。
    settings.json 里只写半个嵌套字典时，不会把默认值整块冲掉。"""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings():
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            s = json.load(f)
    except Exception:
        s = {}
    if not isinstance(s, dict):
        s = {}
    return deep_merge(DEFAULT_SETTINGS, s)


def pick(lst):
    return random.choice(lst) if lst else ''


# ----------------------------- 遗传 -----------------------------
def new_gene(spd=None, siz=None, bold=None, hue=None, gen=1,
             lon=None, app=None, fer=None):
    """一只虫的基因。全部以 1.0 为"标准个体"，上下浮动即个体差异。
    lon=寿命倍率 / app=食欲 / fer=生育力；不给则随机生成。"""
    g = {
        'spd': clamp(spd if spd is not None else random.gauss(1.0, GENE_SIGMA),
                     *GENE_CLAMP),
        'siz': clamp(siz if siz is not None else random.gauss(1.0, GENE_SIGMA * 0.7),
                     *GENE_CLAMP),
        'bold': clamp(bold if bold is not None else random.gauss(0.5, 0.18),
                      *GENE_CLAMP),
        'hue': clamp(hue if hue is not None else random.gauss(0.5, 0.22),
                     *GENE_CLAMP),
        'gen': int(gen),
    }
    # 生活史基因：老档没有这几项，读取时一律用 1.0 兜底（见 gene_life_keys 注释）
    for k, v in (('lon', lon), ('app', app), ('fer', fer)):
        g[k] = clamp(v if v is not None else random.gauss(1.0, GENE_SIGMA),
                     *GENE_CLAMP)
    return g


def breed_gene(a, b):
    """子代基因 = 双亲平均 + 高斯变异（变异让种群能慢慢漂移出极端个体）"""
    g = {}
    for k in GENE_ALL_KEYS:
        mid = (a.get(k, 1.0) + b.get(k, 1.0)) / 2.0
        g[k] = clamp(mid + random.gauss(0.0, GENE_SIGMA), *GENE_CLAMP)
    g['gen'] = max(int(a.get('gen', 1)), int(b.get('gen', 1))) + 1
    return g


def gene_traits(g):
    """基因 → 人类可读的性状描述（图鉴/标签用）"""
    t = []
    if g.get('spd', 1) > 1.25:
        t.append('迅捷')
    elif g.get('spd', 1) < 0.8:
        t.append('迟缓')
    if g.get('siz', 1) > 1.25:
        t.append('大只')
    elif g.get('siz', 1) < 0.8:
        t.append('小巧')
    if g.get('bold', 0.5) > 0.68:
        t.append('胆大')
    elif g.get('bold', 0.5) < 0.32:
        t.append('胆小')
    if g.get('hue', 0.5) > 0.72:
        t.append('冷色')
    elif g.get('hue', 0.5) < 0.28:
        t.append('暖色')
    if g.get('lon', 1) > 1.25:
        t.append('长寿')
    elif g.get('lon', 1) < 0.8:
        t.append('短寿')
    if g.get('app', 1) > 1.25:
        t.append('贪食')
    elif g.get('app', 1) < 0.8:
        t.append('小食量')
    if g.get('fer', 1) > 1.25:
        t.append('多产')
    elif g.get('fer', 1) < 0.8:
        t.append('少子')
    return t


def gene_grade(g):
    """稀有度：偏离标准个体越远越稀有（用于图鉴收集感）
    只算四维外显基因：生活史基因（lon/app/fer）不该让虫"显得更稀有"，
    否则养活一只长寿虫也会被标成传说，收集感就失真了。"""
    dev = sum(abs(g.get(k, 1.0) - 1.0) for k in ('spd', 'siz')) \
        + abs(g.get('bold', 0.5) - 0.5) * 2 + abs(g.get('hue', 0.5) - 0.5) * 2
    if dev > 1.35:
        return '传说'
    if dev > 0.95:
        return '稀有'
    if dev > 0.6:
        return '优良'
    return '普通'



def persist_settings(cfg):
    """托盘里改的数量/皮肤写回 settings.json，下次启动生效（原子写防损坏）"""
    try:
        tmp = SETTINGS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except Exception:
        pass


def sync_settings_file(cfg):
    """启动时把"生效后的完整配置"回写 settings.json。

    为什么必须回写：`load_settings()` 是深合并，用户只写了 `{"count":9}` 也能跑，
    但这样文件里就**看不到**还有哪些键可调 —— 而 README 恰恰是照着这份文件教人改配置的。
    回写后文件始终是一份"完整、可直接改"的模板，且用户的取值原样保留。
    内容没变就不动它（避免每次启动都改 mtime）。"""
    try:
        new_txt = json.dumps(cfg, ensure_ascii=False, indent=2)
        old_txt = ''
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                old_txt = f.read()
        if new_txt != old_txt:
            persist_settings(cfg)
        return True
    except Exception:
        dbg_log('settings 同步失败\n' + traceback.format_exc())
        return False


# ----------------------------- 设置项规格表 -----------------------------
# 图形设置面板（SettingsDialog）与测试**共用这一张表**：想加一个可调项 = 加一行。
# 字段：(分组, 键, 显示名, 类型, 附加参数)
#   类型 bool   → 勾选框
#   类型 int/float → 数值框，附加参数 = (最小, 最大, 步长)
#   类型 choice → 下拉框，附加参数 = 选项元组；None 表示选项在运行时动态填（如已装皮肤）
#   类型 str    → 单行文本
#   类型 dir    → 单行文本 + 「…」选目录按钮
SETTINGS_SPEC = (
    ('外观', 'skin',                '皮肤',                'choice', None),
    ('外观', 'scale',               '整体缩放',            'float', (0.5, 2.5, 0.05)),
    ('外观', 'show_labels',         '显示种类标签',        'bool', None),
    ('外观', 'bubbles.enabled',     '显示气泡',            'bool', None),
    ('外观', 'bubbles.show_seconds', '气泡停留（秒）',      'float', (0.5, 10.0, 0.1)),

    ('行为', 'count',               '桌宠数量',            'int', (1, 30, 1)),
    ('行为', 'max_flies',           '数量上限',            'int', (1, 60, 1)),
    ('行为', 'speed_scale',         '总速度倍率',          'float', (0.2, 3.0, 0.05)),
    ('行为', 'hunger_minutes',      '饿了会喊的间隔（分钟）', 'int', (5, 240, 1)),
    ('行为', 'sleep_minutes',       '多久不动开始打盹（分钟）', 'int', (1, 120, 1)),
    ('行为', 'feed_hotkey',         '投喂快捷键',          'str', None),
    ('行为', 'cpu_agitation',       'CPU 高时焦躁',        'bool', None),
    ('行为', 'paused',              '暂停（冻住不动）',     'bool', None),
    ('行为', 'quiet',               '安静模式（不闲聊）',   'bool', None),

    ('实用', 'screen_mode',         '覆盖范围',            'choice', ('primary', 'all')),
    ('实用', 'pomodoro_min',        '番茄钟默认时长（分钟）', 'int', (1, 240, 1)),
    ('实用', 'clock.fid',           '报时虫（0=关闭）',     'int', (0, 30, 1)),
    ('实用', 'clock.show_title',    '报时牌显示日期',       'bool', None),
    ('实用', 'file_stash.enabled',    '文件收纳',          'bool', None),
    ('实用', 'file_stash.default_dir', '收纳兜底目录',      'dir', None),
    ('实用', 'file_stash.mode',       '收纳方式',          'choice', ('move', 'copy')),
    ('实用', 'file_stash.rules',      '扩展名规则',         'rules', None),

    ('高级', 'debug',               '写调试日志（_debug.log）', 'bool', None),
)

# 「安静模式」下仍然放行的气泡：都是"你刚做了个操作"的反馈，
# 静音把这些也吞掉的话，你会不知道文件到底收没收进去。
QUIET_KEEP = ('stash', 'stash_no', 'ate_file', 'full', 'grabbed', 'caged')


def spec_get(cfg, key):
    """按 'a.b' 路径取配置值；路径不存在返回 None"""
    cur = cfg
    for part in key.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def spec_set(cfg, key, val):
    """按 'a.b' 路径写配置值，中间层缺失就补出来"""
    parts = key.split('.')
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = val


def settings_values_from_cfg(cfg):
    """把嵌套的 cfg 摊平成 {键: 值}，供面板填控件（纯函数，可测）"""
    return {k: spec_get(cfg, k) for _, k, _, _, _ in SETTINGS_SPEC}


def apply_settings_values(cfg, values):
    """把面板读回的 {键: 值} 写进 cfg（就地修改），返回实际写入的键列表。

    这里是**类型与范围的守门人**：手改 settings.json 写进乱值、或者面板传了
    一个规格表里没有的键，都不该影响程序运行。规则：
      - 只写规格表里认识的键（未知键静默丢弃）
      - 数值一律夹到 (最小, 最大) 区间；转不成数值的保持原值
      - 下拉只接受候选项之内的值
    返回的列表让调用方知道"哪些真的改了"，好决定要不要做重活（如重建几何）。"""
    written = []
    for _, key, _, kind, arg in SETTINGS_SPEC:
        if key not in values:
            continue
        old = spec_get(cfg, key)
        new = values[key]
        try:
            if kind == 'bool':
                new = bool(new)
            elif kind in ('int', 'float'):
                lo, hi, _step = arg
                new = int(clamp(float(new), lo, hi)) if kind == 'int' \
                    else float(clamp(float(new), lo, hi))
            elif kind == 'choice':
                opts = arg if arg else (old,)
                if new not in opts:
                    continue
            elif kind == 'rules':
                if not isinstance(new, dict):
                    continue
                new = {str(k): str(v) for k, v in new.items() if str(k).strip()}
            else:                      # str / dir
                new = str(new)
        except (TypeError, ValueError):
            continue
        if new != old:
            spec_set(cfg, key, new)
            written.append(key)
    return written


def settings_reset(cfg):
    """恢复默认：只把规格表覆盖到的键还原，**不动用户数据**
    （每只虫的专属收纳目录 `fly_stash`、待办清单 `clock.todos`、全局皮肤表都不在规格表里）。"""
    values = {k: spec_get(DEFAULT_SETTINGS, k) for _, k, _, _, _ in SETTINGS_SPEC}
    return apply_settings_values(cfg, values)


def rules_to_text(rules):
    """收纳规则 dict → 多行文本。面板里让人一行一条地改，比表格好懂。"""
    return '\n'.join('%s = %s' % (k, v)
                     for k, v in sorted((rules or {}).items()))


def text_to_rules(text):
    """多行文本 → 收纳规则 dict。每行 `扩展名 = 目录`：
    空行与 # 开头忽略；没有 = 的行忽略；扩展名没写点自动补上并统一小写
    （查找侧是 `splitext(path)[1].lower()` 比对，两边必须同一口径）。"""
    out = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k, v = k.strip(), v.strip()
        if not k or not v:
            continue
        if not k.startswith('.'):
            k = '.' + k
        out[k.lower()] = v
    return out


# ----------------------------- 图形设置面板 -----------------------------
CHOICE_LABEL = {
    'primary': '只盖主屏',
    'all': '盖住所有显示器',
    'move': '移动（推荐）',
    'copy': '复制一份（原文件留着）',
}


def open_settings_file():
    """用系统默认程序打开 settings.json。
    面板覆盖不到的东西（22 条气泡文案、每只虫的收纳目录）只能手改这个文件，
    所以得给一个"一键打开"的入口，不然用户根本找不到它在哪。"""
    try:
        if not os.path.isfile(SETTINGS_PATH):
            persist_settings(load_settings())
        if hasattr(os, 'startfile'):        # Windows
            os.startfile(SETTINGS_PATH)
        return True
    except Exception:
        dbg_log('打开 settings.json 失败\n' + traceback.format_exc())
        return False


class SettingsDialog(QDialog):
    """托盘菜单「设置…」打开的面板。settings.json 里的键都能在这儿改，不用手改 JSON。

    三处刻意的设计（背后都是踩过的坑）：
      - **不挂父窗口**。覆盖层带着 Tool / WindowDoesNotAcceptFocus / 全屏 mask，
        挂上去很容易让对话框抢不到焦点、输入框点不动。宁可自己设一段干净的窗口标志。
      - 控件的创建与取值全部由 `SETTINGS_SPEC` 驱动 —— 想加一个可调项只需加一行规格，
        不用改这个类；也让整块逻辑能脱离窗口被测试。
      - 「恢复默认」**只改控件、不碰 cfg**，所以点完还能按「取消」反悔。
    """

    def __init__(self, cfg, dyn_opts=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dyn_opts = dict(dyn_opts or {})   # 如 {'skin': [(内部名, 显示名), ...]}
        self.saved = None        # 保存时记下"实际改动的键"；取消时保持 None
        self._widgets = {}       # 键 → 真正读写的那个控件（目录项读的是行编辑框）
        self.setWindowTitle('FlyPet 设置')
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint |
                            Qt.WindowCloseButtonHint)
        self.setMinimumWidth(560)
        self._build()
        self.set_values(settings_values_from_cfg(cfg))

    # ---- 构建 ----
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        tabs = QTabWidget(self)
        groups = {}
        for row in SETTINGS_SPEC:
            groups.setdefault(row[0], []).append(row)
        for gname, rows in groups.items():
            page = QWidget()
            form = QFormLayout(page)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setSpacing(8)
            for _, key, label, kind, arg in rows:
                fw, vw = self._make_widget(key, kind, arg)
                self._widgets[key] = vw
                form.addRow(label, fw)
            tabs.addTab(page, gname)
        root.addWidget(tabs)

        tip = QLabel('设置写在 exe 旁的 settings.json 里，保存后立即生效（投喂快捷键除外，需重启）。\n'
                     '气泡文案和每只虫的收纳目录不在这块面板里：前者改 settings.json，后者用托盘菜单指派。')
        tip.setWordWrap(True)
        root.addWidget(tip)

        row = QHBoxLayout()
        self.btn_reset = QPushButton('恢复默认')
        self.btn_reset.setToolTip('只把上面的选项还原成默认值，不会动你的待办、收纳目录等数据')
        self.btn_reset.clicked.connect(self.do_reset)
        self.btn_open = QPushButton('打开 settings.json')
        self.btn_open.clicked.connect(lambda: open_settings_file())
        row.addWidget(self.btn_reset)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton('保存并应用')
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.do_save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        root.addLayout(row)

    def _make_widget(self, key, kind, arg):
        """返回 (放进表单的控件, 用来读写的控件)。多数情况下两者是同一个。"""
        if kind == 'bool':
            w = QCheckBox()
            return w, w
        if kind == 'int':
            lo, hi, step = arg
            w = QSpinBox()
            w.setRange(int(lo), int(hi))
            w.setSingleStep(int(step))
            return w, w
        if kind == 'float':
            lo, hi, step = arg
            w = QDoubleSpinBox()
            w.setRange(float(lo), float(hi))
            w.setSingleStep(float(step))
            w.setDecimals(2)
            return w, w
        if kind == 'choice':
            w = QComboBox()
            opts = self.dyn_opts.get(key)
            if opts is None:
                opts = [(o, CHOICE_LABEL.get(o, o)) for o in (arg or ())]
            for val, disp in opts:
                w.addItem(disp, val)
            return w, w
        if kind == 'rules':
            w = QPlainTextEdit()
            w.setPlaceholderText('.png = D:/图片\n.pdf = D:/文档\n'
                                 '# 一行一条；扩展名不写点也行，空行和 # 开头的会忽略')
            w.setFixedHeight(100)
            return w, w
        if kind == 'dir':
            le = QLineEdit()
            le.setPlaceholderText('留空 = 这条规则不生效')
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            btn = QPushButton('…')
            btn.setFixedWidth(34)
            btn.clicked.connect(lambda: self._pick_dir(le))
            h.addWidget(le)
            h.addWidget(btn)
            return box, le
        w = QLineEdit()               # str
        return w, w

    # ---- 读写 ----
    def _read(self, key, kind):
        w = self._widgets.get(key)
        if w is None:
            return None
        if kind == 'bool':
            return w.isChecked()
        if kind in ('int', 'float'):
            return w.value()
        if kind == 'choice':
            return w.currentData()
        if kind == 'rules':
            return text_to_rules(w.toPlainText())
        return w.text()

    def values(self):
        """当前面板上的全部取值（键与规格表一致）"""
        return {k: self._read(k, kind) for _, k, _, kind, _ in SETTINGS_SPEC}

    def set_values(self, vals):
        """把一组取值刷到控件上（供初始填表与「恢复默认」共用）"""
        for _, key, _, kind, _ in SETTINGS_SPEC:
            w = self._widgets.get(key)
            if w is None:
                continue
            v = vals.get(key)
            try:
                if kind == 'bool':
                    w.setChecked(bool(v))
                elif kind in ('int', 'float'):
                    if v is not None:
                        w.setValue(v)
                elif kind == 'choice':
                    i = w.findData(v)
                    w.setCurrentIndex(i if i >= 0 else 0)
                elif kind == 'rules':
                    w.setPlainText(rules_to_text(v))
                else:
                    w.setText('' if v is None else str(v))
            except (TypeError, ValueError):
                pass

    def _pick_dir(self, le):
        d = QFileDialog.getExistingDirectory(self, '选择目录', le.text() or '')
        if d:
            le.setText(d)

    # ---- 按钮 ----
    def do_reset(self):
        """恢复默认**只改控件、不碰 cfg** —— 这样点完还能按「取消」反悔。"""
        self.set_values({k: spec_get(DEFAULT_SETTINGS, k)
                         for _, k, _, _, _ in SETTINGS_SPEC})

    def do_save(self):
        self.saved = apply_settings_values(self.cfg, self.values())
        self.accept()


# ----------------------------- CPU 占用（Win32）-----------------------------
class CpuMeter:
    def __init__(self):
        self.ok = hasattr(ctypes, 'windll')
        self.prev = None
        self.usage = 0.0

    def poll(self):
        if not self.ok:
            return 0.0
        idle = wintypes.FILETIME()
        kern = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return 0.0
        q = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        cur = (q(idle), q(kern), q(user))
        if self.prev:
            pi, pk, pu = self.prev
            di, dk, du = cur[0] - pi, cur[1] - pk, cur[2] - pu
            busy = (dk + du) - di
            total = dk + du
            if total > 0:
                self.usage = self.usage * 0.4 + clamp(busy / total, 0, 1) * 0.6
        self.prev = cur
        return self.usage


# ----------------------------- 全局快捷键（Win32）-----------------------------
WM_HOTKEY = 0x0312
MOD_MAP = {'ctrl': 0x0002, 'alt': 0x0001, 'shift': 0x0004, 'win': 0x0008}
# 注意：parse_hotkey 会把按键统一 lower()，此表必须用小写键
VK_MAP = {c.lower(): ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'}
for i in range(1, 13):
    VK_MAP['f%d' % i] = 0x70 + i - 1
VK_MAP['space'] = 0x20


def parse_hotkey(text):
    parts = [p.strip().lower() for p in text.split('+') if p.strip()]
    mods = 0
    key = None
    for p in parts:
        if p in MOD_MAP:
            mods |= MOD_MAP[p]
        elif p in VK_MAP:
            key = VK_MAP[p]
    return (mods, key) if (mods and key) else None


# ----------------------------- 调试日志 -----------------------------
_dbg_enabled = None


def dbg_log(*a):
    """默认静默；settings.json 加 "debug": true 或环境变量 FLYPET_DEBUG=1 才写 exe 旁 _debug.log"""
    global _dbg_enabled
    if _dbg_enabled is None:
        try:
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                _dbg_enabled = bool(json.load(f).get('debug'))
        except Exception:
            _dbg_enabled = False
        if os.environ.get('FLYPET_DEBUG'):
            _dbg_enabled = True
    if not _dbg_enabled:
        return
    try:
        with open(os.path.join(APP, '_debug.log'), 'a', encoding='utf-8') as fp:
            fp.write(time.strftime('[%H:%M:%S] ') + ' '.join(str(x) for x in a) + '\n')
    except Exception:
        pass


# ----------------------------- 开机自启（注册表 Run 键） -----------------------------
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'FlyPet'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:
        return False


def set_autostart(on):
    import winreg
    exe = os.path.abspath(sys.executable)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, '"%s"' % exe)
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback, log=None):
        super().__init__()
        self.callback = callback
        self.log = log or (lambda *a: None)

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            # 空指针必须先挡掉。wintypes.MSG.from_address(0) **不会抛异常**，
            # 它直接解引用地址 0 → 整个进程段错误。所以下面那个 except 兜不住，
            # 只能在解包之前显式判空。（体检时喂了一个 0 指针，进程直接 139 退出）
            if not message:
                return False, 0
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == 1:
                    self.log('WM_HOTKEY 收到')
                    self.callback()
            except Exception as e:
                self.log('filter error:', e)
        return False, 0


# ----------------------------- 皮肤系统 -----------------------------
def load_skins():
    """skins/<名>/skin.json {"fps":18,"size":56,"facing":"right",
    可选参数覆盖: "speed_scale":0.8 飞行速度倍率, "size_scale":1.2 体型倍率}
    + 同目录 *.png 帧。扫描内置(BUNDLE)与 exe 旁(APP)两个皮肤目录，同名时 APP 优先"""
    skins = {'_procedural': {'fps': 0, 'size': 46, 'facing': 'right',
                             'speed_scale': 1.0, 'size_scale': 1.0, 'frames': []}}
    skin_dirs = []
    for base in SKINS_DIRS:
        try:
            for name in sorted(os.listdir(base)):
                d = os.path.join(base, name)
                if os.path.isdir(d):
                    skin_dirs.append((name, d))
        except OSError:
            continue
    seen = set()
    for name, d in skin_dirs:
        if name in seen:
            continue
        seen.add(name)
        cfg = {'fps': 18, 'size': 56, 'facing': 'right',
               'speed_scale': 1.0, 'size_scale': 1.0, 'frames': []}
        sj = os.path.join(d, 'skin.json')
        if os.path.isfile(sj):
            try:
                with open(sj, 'r', encoding='utf-8') as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        frames = []
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith('.png'):
                pm = QPixmap(os.path.join(d, fn))
                if not pm.isNull():
                    frames.append(pm)
        if frames:
            cfg['frames'] = frames
            skins[name] = cfg
    return skins


# ----------------------------- 桌宠个体 -----------------------------
class PetFly:
    def __init__(self, x, y, skin=None, gene=None):
        self.brain = Brain()
        self.x, self.y = x, y
        self.dir = random.random() * TAU
        self.age = 0.0
        self.energy = E_START
        self.speed = CRUISE
        self.gene = gene if isinstance(gene, dict) else new_gene()
        # 谱系：世界分配的唯一编号 + 亲代编号（野生/放置的虫为空）
        self.fid = 0
        self.parents = ()
        self.eggCd = random.uniform(4.0, EGG_CD)   # 产卵冷却错开，别同时生
        # 寿命由基因决定；桌宠不死，只会在后半生"显老"
        self.lifespan = BASE_LIFESPAN * self.gene.get('lon', 1.0)
        self.elderSaid = False   # 刚变老时只说一次（防止每帧刷气泡）
        self.born = 0.0        # 出生时刻（世界时间），用于"刚孵化"表现
        self.edge = None       # 贴边时记住贴的是哪条边
        self.curious = 0.0     # 追光标玩的意愿（随基因/年龄变化）
        self.flipT = 0.0       # 被双击后的翻滚动画计时
        self.wingPhase = random.random() * TAU
        self.castSeed = random.random() * TAU
        self.brainAcc = 0.0
        self.state = 'cruise'
        self.socialCd = 0.0     # 社交冷却（秒）
        self.skin = skin        # 专属皮肤（None=跟随全局换肤）
        self.labelT = 8.0       # 出现时名称标签显示时长（秒）
        self.size_mult = 1.0    # 个体体型倍率（放置时可选，彩蛋可巨型化）
        self.eating = False
        self.onFood = False
        self.foodPatch = None
        self.escapeT = 0.0
        self.usContact = 0.0
        self.grabbed = False
        self.inCage = False
        self.aversion = 0.0
        self.hunger = 0.0
        self.odSat = 0.0
        self.alSat = 0.0
        self.learnedAnnounced = False
        self.hungryAnnounced = False
        self.starvingAnnounced = False
        self.markers = []   # {'x','y','s','t'}  t=-1 回避 / +1 亲近
        self.bubble = None  # [text, elapsed, remain]

    # ---------- 感觉编码：环境量 → 感觉神经元外部驱动电流 ----------
    def encode(self, world, dt):
        b = self.brain
        ext = b.ext
        for i in range(b.n):
            ext[i] = 0.0
        hunger = clamp(1.0 - self.energy / HUNGRY_AT, 0.0, 1.0)
        self.hunger = hunger

        # 嗅觉：糖块点源气味（指数衰减）
        odor = 0.0
        patch = None
        for f in world.foods:
            d = math.hypot(f['x'] - self.x, f['y'] - self.y)
            odor += FOOD_EMIT * (f['e'] / FOOD_E0) * math.exp(-d / FOOD_L)
            if d < FOOD_R + FEED_RANGE and f['e'] > 0:
                patch = f
        self.foodPatch = patch
        self.onFood = patch is not None
        odSat = odor / (odor + 0.45)
        self.odSat = odSat

        # 报警信息素（世界级：同伴的求救信号也能闻到；带距离衰减，远处不怕）
        al = 0.0
        for p in world.pher:
            d = math.hypot(p['x'] - self.x, p['y'] - self.y)
            al += 2.0 * math.exp(-p['age'] / PHER_TAU) * math.exp(-d / ALARM_R)
        alSat = al / (al + 0.75)
        self.alSat = alSat
        alW = 0.25 if self.onFood else 1.0

        oGain = 0.7 + 1.3 * hunger

        def setn(name, val):
            ct = NET['ct'][name]
            for i in range(ct['start'], ct['start'] + ct['n']):
                ext[i] = val

        setn('ORN_food', 2.45 * odSat * oGain)
        setn('ORN_ferm', 0.0)
        setn('ORN_alarm', 2.25 * alSat * alW)
        setn('GRN_sugar', 2.40 if self.onFood else 0.0)

        # 机械感觉：光标贴身 / 屏幕边缘 / CPU 躁动
        mx, my = world.cursor
        dCur = math.hypot(mx - self.x, my - self.y)
        mech = 0.0
        if dCur < 48:
            mech += 1.2
        wp = WALL_PAD * 0.4
        if self.x < wp or self.x > world.w - wp or self.y < wp or self.y > world.h - wp:
            mech += 1.2
        if world.agi > 0.3 and random.random() < world.agi * 0.3:
            mech += 0.6
        setn('mechano', mech)

        # 视觉 loom：光标快速逼近 → 巨纤维逃逸通路
        near = max(0.0, 1.0 - dCur / 150.0)
        loom = 0.2 + 1.9 * near * (0.4 + 0.6 * world.cursorThreat)
        setn('visual', loom)

        # 内部驱动
        setn('Hugin', 2.05 * hunger)
        setn('NPF', 2.10 if self.eating else 0.45 + 0.8 * odSat * (1.0 if self.onFood else 0.3))
        setn('FB_energy', 2.05 * clamp((self.energy / E_MAX - 0.8) / 0.2, 0.0, 1.0))

        # 非条件刺激：被拍 → PPL1 惩罚多巴胺
        us = 2.40 if self.usContact > 0 else 0.0
        setn('PPL1', us + 1.5 * alSat * alW)
        setn('MN_oviposit', 0.0)

    # ---------- 主更新 ----------
    def update(self, world, dt):
        self.age += dt
        self.escapeT = max(0.0, self.escapeT - dt)
        self.socialCd = max(0.0, self.socialCd - dt)
        self.labelT = max(0.0, self.labelT - dt)
        self.usContact = max(0.0, self.usContact - dt)
        self.eggCd = max(0.0, self.eggCd - dt)
        self.flipT = max(0.0, self.flipT - dt)
        if self.flipT > 0:
            self.dir += dt * 16.0    # 翻滚：快速旋转
        if self.bubble:
            self.bubble[2] -= dt
            if self.bubble[2] <= 0:
                self.bubble = None

        self.encode(world, dt)
        self.brainAcc += dt
        steps = 0
        while self.brainAcc >= 0.01 and steps < 3:
            self.brain.step(0.01)
            self.brainAcc -= 0.01
            steps += 1
        if self.brainAcc > 0.06:
            self.brainAcc = 0.0

        b = self.brain
        hunger = self.hunger
        aversion = b.aversion()
        self.aversion = aversion

        # 学习里程碑（只报一次直到记忆消退回 1.05 以下）
        li = b.learnIndex()
        if li > 1.3 and not self.learnedAnnounced:
            self.learnedAnnounced = True
            world.say(self, 'learned')
        elif li < 1.05:
            self.learnedAnnounced = False

        # 巨纤维逃逸
        if b.escapeDrive() > ESCAPE_THR and self.escapeT <= 0 and not self.grabbed:
            self.escapeT = 0.45
            self.dir += random.choice((-1, 1)) * random.uniform(1.2, 2.4)
            world.spawn_fx(self.x, self.y, (255, 210, 140))
            if not self.usContact:
                world.say(self, 'scared')

        # ---------- 导航（VNC 局部反射 + 脑读出）----------
        want_x = want_y = 0.0
        # 番茄钟：专注期间全体躲到角落安静趴着，不打扰用户
        if getattr(world, 'focus', None):
            fx_, fy_ = world.focus_spot()
            dx, dy = fx_ - self.x, fy_ - self.y
            d = math.hypot(dx, dy) or 1.0
            if d > 26:
                want_x += dx / d * 3.4
                want_y += dy / d * 3.4
        # 报时虫：守在右下角（像一块会呼吸的时钟贴纸，位置可预期才好用）
        if getattr(world, 'clock_fid', 0) and self.fid == world.clock_fid:
            tx, ty = world.clock_perch()
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy) or 1.0
            if d > 26:
                want_x += dx / d * 3.4
                want_y += dy / d * 3.4
        # 定时提醒：飞到屏幕中上方"举牌"
        if getattr(world, 'announce', None):
            tx, ty = world.w * 0.5, world.h * 0.3
            dx, dy = tx - self.x, ty - self.y
            d = math.hypot(dx, dy) or 1.0
            want_x += dx / d * 3.0
            want_y += dy / d * 3.0
        # 好奇：胆大的虫会凑过来看光标（小鼠速慢时；猛冲的鼠标反而是威胁）
        if world.cursorThreat < 0.15 and self.escapeT <= 0 \
                and not self.grabbed and not getattr(world, 'focus', None):
            bold = self.gene.get('bold', 0.5)
            self.curious = clamp((bold - 0.5) * 2.0, 0.0, 1.0) \
                * clamp(self.age / 20.0, 0.0, 1.0) * (1.0 - self.hunger * 0.6)
            cx_, cy_ = world.cursor
            dx, dy = cx_ - self.x, cy_ - self.y
            d = math.hypot(dx, dy) or 1.0
            if 40 < d < 320:
                w = 1.5 * self.curious
                want_x += dx / d * w
                want_y += dy / d * w
            elif d <= 40:
                want_x -= dx / d * 1.2
                want_y -= dy / d * 1.2
        else:
            self.curious = 0.0
        # 屏幕边缘行为：空闲时会贴边爬行，撞到边会顺着边拐弯
        if getattr(world, 'edge_behavior', True) and not self.grabbed \
                and self.escapeT <= 0 and self.odSat < 0.12:
            m = EDGE_BAND
            e = None
            if self.y < m:
                e = 'top'
            elif self.y > world.h - m:
                e = 'bottom'
            elif self.x < m:
                e = 'left'
            elif self.x > world.w - m:
                e = 'right'
            self.edge = e
            if e in ('top', 'bottom'):
                want_y += (m * 0.75 - self.y) if e == 'top' \
                    else (world.h - m * 0.75 - self.y)
                want_x += math.sin(self.age * 3 + self.castSeed) * 0.9
            elif e in ('left', 'right'):
                want_x += (m * 0.75 - self.x) if e == 'left' \
                    else (world.w - m * 0.75 - self.x)
                want_y += math.sin(self.age * 3 + self.castSeed) * 0.9
        else:
            self.edge = None
        if self.odSat > 0.035:
            bx, by, bd = 0.0, 0.0, 1e9
            for f in world.foods:
                d = math.hypot(f['x'] - self.x, f['y'] - self.y)
                if d < bd:
                    bd, bx, by = d, f['x'] - self.x, f['y'] - self.y
            if bd > 1:
                w = self.odSat * SEEK_GAIN * (0.45 + 1.75 * hunger)
                want_x += bx / bd * w
                want_y += by / bd * w
        if self.alSat > 0.035:
            px = py = 0.0
            tw = 0.0
            for p in world.pher:
                st = math.exp(-p['age'] / PHER_TAU)
                px += p['x'] * st
                py += p['y'] * st
                tw += st
            if tw > 0:
                px /= tw
                py /= tw
                dx = self.x - px
                dy = self.y - py
                d = math.hypot(dx, dy) or 1.0
                w = self.alSat * ALARM_GAIN * (1.0 - 0.5 * hunger)
                want_x += dx / d * w
                want_y += dy / d * w
        # 空间记忆：回避（记仇）/ 亲近（糖点）
        for m in self.markers:
            dx = self.x - m['x']
            dy = self.y - m['y']
            d = math.hypot(dx, dy) or 1.0
            if m['t'] < 0:
                if d < AVOID_R:
                    w = (1.0 - d / AVOID_R) * m['s'] * AVOID_GAIN * 0.6
                    want_x += dx / d * w
                    want_y += dy / d * w
            else:
                if d < 320 and d > 1:
                    w = (1.0 - d / 320.0) * m['s'] * 1.2
                    want_x -= dx / d * w
                    want_y -= dy / d * w
        # 边界回避
        if self.x < WALL_PAD:
            want_x += (1.0 - self.x / WALL_PAD) * 1.2
        if self.x > world.w - WALL_PAD:
            want_x -= (1.0 - (world.w - self.x) / WALL_PAD) * 1.2
        if self.y < WALL_PAD:
            want_y += (1.0 - self.y / WALL_PAD) * 1.2
        if self.y > world.h - WALL_PAD:
            want_y -= (1.0 - (world.h - self.y) / WALL_PAD) * 1.2

        # 航向
        wm = math.hypot(want_x, want_y)
        if self.grabbed:
            mx, my = world.cursor
            self.x = clamp(mx, 2, world.w - 2)
            self.y = clamp(my, 2, world.h - 2)
            self.dir += math.sin(self.age * 30) * 14.0 * dt  # 挣扎抖动
            self.wingPhase += dt * 46
        else:
            if wm > 0.08:
                desired = math.atan2(want_y, want_x)
                dd = angdiff(desired, self.dir)
                self.dir += clamp(dd, -TURN * dt, TURN * dt)
            else:
                self.dir += math.sin(self.age * 13 + self.castSeed) * CAST * dt * 0.55
            self.dir += clamp(b.steerBias() * 18.0, -3, 3) * dt
            focus = clamp(self.odSat, 0.0, 1.0)
            self.dir += NOISE * (1.0 + 1.6 * world.agi) * (1.0 - 0.75 * focus) * randn() * dt

            # 速度：MN_walk 放电率驱动
            tracking = wm > 0.35
            base = SURGE if tracking else CRUISE
            walkD = clamp(b.walkDrive(), 0.0, 2.5)
            target = base * (0.75 + 0.5 * hunger) * clamp(0.45 + 0.85 * walkD, 0.3, 2.3)
            # 基因：速度天赋；年老后变慢；系统内存吃紧时全体发蔫（喘气感）
            target *= self.gene.get('spd', 1.0) * self.vitality()
            if getattr(world, 'sys_mem_pct', 0.0) > 0.86:
                target *= 0.72
            target *= world.cfg['speed_scale'] * \
                world.skins.get(world.skin_name, {}).get('speed_scale', 1.0)
            # 番茄钟：安静趴着，速度压到最低
            if getattr(world, 'focus', None):
                target *= 0.16
            # 打盹：环境长时间无变化（鼠标没动、没有糖、没有警报）就悬停小憩
            if world.idleT > world.sleep_after and not self.onFood \
                    and self.escapeT <= 0:
                target *= 0.05
                if random.random() < dt * 0.05:
                    world.say(self, 'sleepy')
                # 冒 z 字粒子
                if random.random() < dt * 2.5:
                    world.spawn_fx(self.x + random.uniform(-9, 9),
                                   self.y - 32 * world.cfg.get('scale', 1.0),
                                   (175, 205, 255), life=1.7, char='z')
            if self.escapeT > 0:
                target *= 1.9
            if self.eating:
                target *= 0.25
            if self.energy < DESP_AT:
                target *= 0.7
            self.speed += (target - self.speed) * clamp(dt * 6, 0.0, 1.0)

            # CPU 躁动：随机逃窜
            if world.cfg['cpu_agitation'] and world.agi > 0:
                if random.random() < world.agi * 0.12 * dt:
                    self.dir += random.choice((-1, 1)) * random.uniform(1.0, 2.0)
                    self.escapeT = max(self.escapeT, 0.25)

            # 移动
            self.x += math.cos(self.dir) * self.speed * dt + randn() * 0.06
            self.y += math.sin(self.dir) * self.speed * dt + randn() * 0.06
            self.x = clamp(self.x, 2, world.w - 2)
            self.y = clamp(self.y, 2, world.h - 2)
            # 笼子：上锁时关在笼内；糖在笼里时飞进去会被自动关住（糖诱）
            cr = world.cage_rect()
            if cr is not None and world.cage.get('locked'):
                inner = cr.adjusted(14, 14, -14, -22)
                if self.inCage:
                    if self.x < inner.left():
                        self.x = inner.left()
                        self.dir = math.pi - self.dir
                    if self.x > inner.right():
                        self.x = inner.right()
                        self.dir = math.pi - self.dir
                    if self.y < inner.top():
                        self.y = inner.top()
                        self.dir = -self.dir
                    if self.y > inner.bottom():
                        self.y = inner.bottom()
                        self.dir = -self.dir
                elif inner.contains(int(self.x), int(self.y)) \
                        and any(inner.contains(int(f['x']), int(f['y']))
                                for f in world.foods):
                    self.inCage = True    # 顺着糖香进了笼，门一锁
                    world.say(self, 'caged')
            self.wingPhase += dt * (16.0 + self.speed * 0.07)

        # 代谢：食量基因 app 越大，掉能量越快（贪食的代价）
        cost = (world.drain_base + world.drain_move * (self.speed / SURGE) * 2.0) \
            * self.gene.get('app', 1.0)
        if world.idleT > world.sleep_after:
            cost *= 0.6    # 打盹省电
        if self.energy < DESP_AT:
            cost *= 0.7
        self.energy = max(0.0, self.energy - cost * dt)

        # 取食：MN_feed (MN9) 放电率 > 阈值 → 喙伸展取食
        was_eating = self.eating
        self.eating = False
        if self.onFood and self.foodPatch and self.foodPatch['e'] > 0:
            feed = b.feedDrive()
            if feed > FEED_THR:
                gain = min(FEED_RATE * self.gene.get('app', 1.0) * dt,
                           self.foodPatch['e'] / FOOD_CONSUME)
                self.eating = True
                self.foodPatch['e'] -= gain * FOOD_CONSUME
                self.energy = min(E_MAX, self.energy + gain)
                self.dir += math.sin(self.age * 6) * 1.2 * dt
                if random.random() < dt * 1.5:
                    world.spawn_fx(self.x, self.y, (240, 200, 120))
                # 奖赏学习空间标记（PAM 已在脑内写入 KC→MBON_app）
                if random.random() < dt * 0.5:
                    self.add_marker(self.foodPatch['x'], self.foodPatch['y'], 1, 0.35)
        if was_eating and not self.eating and self.energy > E_MAX * 0.88:
            world.say(self, 'full')

        # 饥饿气泡
        if self.energy < HUNGRY_AT and not self.hungryAnnounced:
            self.hungryAnnounced = True
            world.say(self, 'hungry')
        elif self.energy >= HUNGRY_AT + 8:
            self.hungryAnnounced = False
        if self.energy < DESP_AT and not self.starvingAnnounced:
            self.starvingAnnounced = True
            world.say(self, 'starving')
        elif self.energy >= DESP_AT + 8:
            self.starvingAnnounced = False

        # 记忆衰减
        for m in self.markers:
            m['s'] -= dt / FORGET_SECONDS
        self.markers = [m for m in self.markers if m['s'] > 0.03]
        if len(self.markers) > 24:
            self.markers = sorted(self.markers, key=lambda m: -m['s'])[:24]
        # 偶发闲聊
        if not self.grabbed and random.random() < dt * 0.006:
            world.say(self, 'idle')

        # 状态
        if self.grabbed:
            self.state = 'grab'
        elif self.escapeT > 0:
            self.state = 'alarm'
        elif self.eating:
            self.state = 'feed'
        elif wm > 0.35:
            self.state = 'seek'
        else:
            self.state = 'cast'

    def add_marker(self, x, y, t, s):
        self.markers.append({'x': x, 'y': y, 's': s, 't': t})

    # ---------- 基因表现 ----------
    def size_factor(self):
        """最终体型倍率 = 个体尺寸（放置所选/彩蛋巨型）× 基因体型"""
        return getattr(self, 'size_mult', 1.0) * (0.7 + 0.3 * self.gene.get('siz', 1.0))

    def tint_color(self):
        """基因色相 → 叠加色（接近中位则不染色，返回 None）"""
        h = self.gene.get('hue', 0.5)
        if abs(h - 0.5) < 0.13:
            return None
        if h < 0.5:
            return QColor(255, 150, 60, int(72 * ((0.5 - h) / 0.5)))
        return QColor(70, 150, 255, int(72 * ((h - 0.5) / 0.5)))

    def spin(self):
        """被双击：打个滚"""
        self.flipT = 0.55
        self.dir += random.choice((-1, 1)) * 3.2

    def traits_text(self):
        t = gene_traits(self.gene)
        return '·'.join(t) if t else '标准'

    # ---------- 衰老（只变慢，不死） ----------
    def is_elder(self):
        """是否进入老年：走过寿命的 ELDER_AT 比例"""
        return self.age > self.lifespan * ELDER_AT

    def vitality(self):
        """活力 1.0 → ELDER_MIN_VITALITY。影响速度与生育意愿，壮年期恒为 1.0。"""
        start = self.lifespan * ELDER_AT
        if self.age <= start:
            return 1.0
        k = (self.age - start) / max(1.0, self.lifespan * (1.0 - ELDER_AT))
        return clamp(1.0 - k * (1.0 - ELDER_MIN_VITALITY),
                     ELDER_MIN_VITALITY, 1.0)

    def age_text(self):
        """图鉴/详情用的人话年龄"""
        pct = int(100 * self.age / max(1.0, self.lifespan))
        if self.is_elder():
            return '年老（%d%% 寿命）' % pct
        return '壮年（%d%% 寿命）' % pct

    def is_legendary(self):
        """传说级：绘制时加一层金色光晕（收集感的外在体现）"""
        return gene_grade(self.gene) == '传说'

    def clear_memory(self):
        self.markers = []
        self.brain.w = NET['W0'][:]
        self.learnedAnnounced = False

    def swat(self, world):
        """被拍：惩罚学习（PPL1 → KC→MBON_av）+ 报警信息素（世界级，同类也会怕）"""
        self.usContact = 1.6
        self.escapeT = 0.45
        self.dir += random.choice((-1, 1)) * random.uniform(1.2, 2.6)
        self.add_marker(self.x, self.y, -1, 0.85)
        world.pher.append({'x': self.x, 'y': self.y, 'age': 0.0})
        world.spawn_fx(self.x, self.y, (255, 120, 90))
        world.say(self, 'swat')

    def release_grab(self):
        self.grabbed = False
        self.escapeT = 0.6
        self.usContact = max(self.usContact, 0.8)
        self.dir += random.uniform(-math.pi, math.pi)


# ----------------------------- 脑活动面板 -----------------------------
class BrainPanel(QWidget):
    def __init__(self, world):
        super().__init__()
        self.world = world
        self.setWindowTitle('FlyPet 脑活动')
        self.resize(380, 560)
        self.setStyleSheet('background:#10151c;')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(100)

    def paintEvent(self, _ev):
        flies = self.world.flies
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#10151c'))
        if not flies:
            return
        fly = flies[0]
        b = fly.brain
        p.setPen(QColor('#dfe8f2'))
        f = QFont('Microsoft YaHei', 10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(14, 26, '连接组脑 #1 · 25 类神经元实时放电率（共 %d 只）' % len(flies))
        f2 = QFont('Consolas', 8)
        p.setFont(f2)
        y = 52
        bar_x = 130
        bar_w = 200
        for name, group, _sign, _n, desc in CTYPE:
            rate = b.rate(name)
            p.setPen(QColor('#9fb2c8'))
            p.drawText(14, y, name)
            p.setPen(QColor('#3d4a5a'))
            p.drawRect(bar_x - 1, y - 8, bar_w + 2, 9)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GROUP_COLOR[group]))
            w = clamp(rate / 40.0, 0.0, 1.0) * bar_w
            p.drawRect(bar_x, y - 7, max(1, int(w)), 7)
            p.setPen(QColor('#6d7f94'))
            p.drawText(bar_x + bar_w + 8, y, '%5.1f' % rate)
            y += 17
        p.setPen(QColor('#28a6e2'))
        f3 = QFont('Microsoft YaHei', 9)
        p.setFont(f3)
        p.drawText(14, y + 14, '惩罚记忆(记仇) ×%.2f   能量 %d/%d   CPU %d%%'
                   % (b.learnIndex(), int(fly.energy), int(E_MAX), int(self.world.agi * 100)))
        p.setPen(QColor('#566876'))
        p.drawText(14, y + 32, '放电 %d spikes/步   状态 %s   空间记忆 %d 条'
                   % (b.lastSpikes, fly.state, len(fly.markers)))
        p.end()


# ----------------------------- 透明覆盖主窗口 -----------------------------
class Overlay(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        # 屏幕范围：primary = 只盖主屏；all = 盖住整个虚拟桌面（多显示器可用）
        self.apply_screen_geometry(cfg.get('screen_mode', 'primary'))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle('FlyPet')
        self._prev_mask = None

        # 编号发号器必须在第一只虫出生前就绪（register_fly 依赖它）
        self.next_fid = 1
        self.lineage = []
        self.flies = []
        for i in range(max(1, int(cfg.get('count', 1)))):
            self.flies.append(self.register_fly(PetFly(
                self.w * 0.5 + random.uniform(-140, 140),
                self.h * 0.45 + random.uniform(-100, 100))))
        self.foods = []      # {'x','y','e'}
        self.fx = []         # {'x','y','age','color'}
        self.pher = []       # 世界级报警信息素 {'x','y','age'}
        self.cursor = (self.w / 2, self.h / 2)
        self.cursorVel = (0.0, 0.0)
        self.cursorThreat = 0.0
        self.agi = 0.0
        self.skins = load_skins()
        self.skin_name = cfg['skin'] if cfg['skin'] in self.skins else '_procedural'
        self.skin_frame = 0.0
        # 皮肤中文名映射（标签用）
        self.skin_disp = {}
        for base in SKINS_DIRS:
            try:
                with open(os.path.join(base, 'names.json'), encoding='utf-8') as f:
                    self.skin_disp.update(json.load(f))
            except Exception:
                pass
        self.skin_disp.setdefault('_procedural', '果蝇')
        # 放置模式：选好种类后点击画布放置
        self.pending_place = False
        self.pending_skin = None
        self.pending_size = 1.0     # 放置尺寸：0.7 / 1.0 / 1.5
        self.placed_count = 0       # 已放置数（驱动巨型彩蛋概率）
        self.pressT = None
        self.pressPos = None
        self.pressed_fly = None
        self._prev_dirty = QRegion()
        self._prev_mask = None    # 上次 setMask 的区域，不变则跳过（setMask 是最大开销）
        self._dbg = dbg_log
        self.idleT = 0.0    # 鼠标静默时长（秒），用于打盹
        self.sleep_after = max(60.0, cfg.get('sleep_minutes', 5) * 60.0)
        # 笼子 / 捕捉 / 提醒
        self.cage = None            # {'x','y','locked'}
        self.capture_mode = False
        self.cage_drag = False
        self.cage_drag_pos = None   # 拖动中的窗口内坐标
        self.cage_grab_off = (0, 0)  # 抓取点相对笼心的偏移
        self.need_mouse = False     # 交互期临时开放全屏 mask
        self.drag_hover = False     # 文件正拖在笼子上方（高亮提示）
        self.drop_fly_hover = None  # 文件正拖在某只虫身上（收纳目标）
        # 报时虫编号（镜像一份到实例上，帧循环里被每只虫高频读取）
        self.clock_fid = int((cfg.get('clock') or {}).get('fid', 0) or 0)
        self.reminders = []         # [{'at': monotonic, 'text': str}]
        self.announce = None        # (text, until_monotonic)
        # ---- 遗传 / 繁殖 / 图鉴 ----
        self.eggs = []              # [{'x','y','age','gene','skin'}]
        self.codex = {'species': {}, 'best_gen': 0, 'hatched': 0,
                      'grades': {'普通': 0, '优良': 0, '稀有': 0, '传说': 0}}
        self.birth_log = []         # 最近诞生的虫（托盘提示用）
        self.lineage = []           # 谱系：最近孵化记录 [{'fid','gen','p1','p2','grade',...}]
        # ---- 番茄钟 ----
        self.focus = None           # {'until': monotonic, 'mins': int}
        self.focus_corner = random.choice(FOCUS_SPOTS)
        # ---- 剪贴板小助手 ----
        self.clipboard_on = False
        self.last_clip = ''
        self.clipT = 0.0
        # ---- 系统监视 ----
        self.sys_mem_pct = 0.0
        self.sys_disk_pct = 0.0
        self.sysmon_on = True
        self.monT = 0.0
        self.edge_behavior = True
        self.leader = None          # 领头虫（最胆大的那只）
        self.setAcceptDrops(True)
        self.setMouseTracking(True)  # 不按键也要收 mouseMove，才能做光标形状反馈

        # 代谢速率由 hunger_minutes 配置推导：满能量→饥饿阈的时间
        span = E_START - HUNGRY_AT
        total = max(120.0, cfg['hunger_minutes'] * 60.0)
        # 平均运动附加项 ≈ drain_move*(v/SURGE)*2 ≈ 0.05（巡航经验值）
        self.drain_base = max(0.01, span / total - 0.045)
        self.drain_move = 0.0225

        self.cpu = CpuMeter()
        self.clock = QElapsedTimer()
        self.clock.start()
        self.prev_rects = []

        self.loop = QTimer(self)
        self.loop.timeout.connect(self.tick)
        self.loop.start(16)
        self.saveTimer = QTimer(self)
        self.saveTimer.timeout.connect(self.save)
        self.saveTimer.start(20000)
        self.cpuTimer = QTimer(self)
        self.cpuTimer.timeout.connect(self.poll_cpu)
        self.cpuTimer.start(2000)
        self.poll_cpu()
        self.load()

    # ---------- 帧循环 ----------
    def tick(self):
        """QTimer 回调。异常必须自己兜住并记日志——
        Qt 会静默吞掉槽函数里的异常，否则一次 KeyError 就让整个宠物无声卡死。"""
        try:
            self._tick()
        except Exception:
            dbg_log('tick 异常\n' + traceback.format_exc())
            self._tick_errors = int(getattr(self, '_tick_errors', 0)) + 1
            if self._tick_errors > 200:
                self.loop.stop()      # 反复炸就停下，别空转烧 CPU
                dbg_log('tick 连续异常 %d 次，已停止帧循环' % self._tick_errors)

    def _world_step(self, dt):
        """一帧的"世界模拟"：移动 / 衰老 / 繁殖 / 代谢 / 孵化 / 特效。

        单独抽出来是为了让"暂停"可测：测试直接断言"暂停时虫的坐标不变"，
        不用去跑 Qt 定时器。"""
        for fly in self.flies:
            fly.update(self, dt)
        # 衰老 / 传说：只在"刚跨过门槛"那一次说一句话，别每帧刷屏
        for fly in self.flies:
            if fly.is_elder() and not getattr(fly, 'elderSaid', False):
                fly.elderSaid = True
                self.say(fly, 'elder')
            elif not fly.is_elder():
                fly.elderSaid = False
        # 蛋孵化
        self.update_eggs(dt)
        # 剪贴板 / 系统监视（低频轮询）
        self.poll_clipboard(dt)
        self.poll_sysmon(dt)
        # 抓取判定：按住超时
        if self.pressT is not None and self.pressed_fly is not None \
                and not self.pressed_fly.grabbed:
            if time.monotonic() - self.pressT > GRAB_DELAY:
                self.pressed_fly.grabbed = True
                self.say(self.pressed_fly, 'grabbed')
        # 糖块变质
        for f in self.foods:
            f['e'] -= FOOD_DECAY * dt
        self.foods = [f for f in self.foods if f['e'] > 1]
        # 特效 / 信息素
        for e in self.fx:
            e['age'] += dt
        self.fx = [e for e in self.fx if e['age'] < e.get('life', 0.7)]
        for p in self.pher:
            p['age'] += dt
        self.pher = [p for p in self.pher if p['age'] < PHER_TAU * 4]

    def _tick(self):
        dt = min(0.05, self.clock.restart() / 1000.0)
        m = QCursor.pos()
        px, py = self.cursor
        vx, vy = m.x() - px, m.y() - py
        v = math.hypot(vx, vy) / max(dt, 1e-3)
        self.cursorVel = (vx / max(dt, 1e-3), vy / max(dt, 1e-3))
        self.cursor = (m.x(), m.y())
        # 静默计时：鼠标明显移动即清零（打盹用）
        if v > 60 or self.foods or self.pher:
            self.idleT = 0.0
        else:
            self.idleT += dt
        # 光标是否在逼近（以最近的果蝇为准）
        if self.flies:
            fly = min(self.flies,
                      key=lambda fl: math.hypot(fl.x - m.x(), fl.y - m.y()))
            tofly = (fly.x - m.x(), fly.y - m.y())
            tl = math.hypot(*tofly) or 1.0
            toward = (self.cursorVel[0] * tofly[0] + self.cursorVel[1] * tofly[1]) / (v * tl) if v > 1 else 0
            self.cursorThreat = clamp(max(0.0, toward) * clamp(v / 1500.0, 0.0, 1.0), 0.0, 1.0)

        # 世界模拟：移动 / 衰老 / 繁殖 / 代谢 / 孵化。**暂停时整块跳过**
        if not self.cfg.get('paused'):
            self._world_step(dt)
        # 笼子拖动：用拖动过程中记下的窗口内坐标（不能用 QCursor.pos()，
        # 那是全局屏幕坐标，窗口不在原点时会把笼子甩到错位置）
        if self.cage_drag and self.cage is not None:
            cw = self.cage.get('w', CAGE_W) / 2
            ch = self.cage.get('h', CAGE_H) / 2
            dx, dy = getattr(self, 'cage_grab_off', (0, 0))
            tx = getattr(self, 'cage_drag_pos', None)
            if tx is not None:
                self.cage['x'] = clamp(tx[0] - dx, cw + 4, self.w - cw - 4)
                self.cage['y'] = clamp(tx[1] - dy, ch + 4, self.h - ch - 4)
        # 定时提醒：到点 → 果蝇集合到屏幕中上方"举牌"
        now = time.monotonic()
        # 番茄钟：到点自动结束并喊人
        if self.focus:
            self.idleT = 0.0        # 专注期间不许打盹
            if now >= self.focus['until']:
                self.stop_focus()
        due = [r for r in self.reminders if r['at'] <= now]
        if due:
            self.reminders = [r for r in self.reminders if r['at'] > now]
            self.announce = ('；'.join(r['text'] for r in due), now + 14.0)
        if self.announce:
            self.idleT = 0.0    # 提醒期间不许睡觉
            text, until = self.announce
            if now > until:
                self.announce = None
            elif self.flies:
                fly = min(self.flies, key=lambda fl:
                          math.hypot(fl.x - self.w * 0.5, fl.y - self.h * 0.3))
                if math.hypot(fly.x - self.w * 0.5, fly.y - self.h * 0.3) < 150 \
                        and (fly.bubble is None or fly.bubble[0] != text):
                    fly.bubble = [text, 0.0, 3.2]
        # 社交：靠近的同类偶尔碰触角打招呼（每 0.5s 检查一次，够省）
        self.socialT = getattr(self, 'socialT', 0.0) + dt
        if self.socialT >= 0.5 and not self.cfg.get('paused'):
            self.socialT = 0.0
            fs = self.flies
            for i in range(len(fs)):
                a = fs[i]
                if a.socialCd > 0 or a.grabbed or a.eating or a.escapeT > 0:
                    continue
                for j in range(i + 1, len(fs)):
                    b2 = fs[j]
                    if b2.socialCd > 0 or b2.grabbed or b2.eating or b2.escapeT > 0:
                        continue
                    if math.hypot(a.x - b2.x, a.y - b2.y) < 42:
                        if random.random() < 0.5:
                            self.say(a, 'social')
                            self.say(b2, 'social')
                            self.spawn_fx((a.x + b2.x) / 2, (a.y + b2.y) / 2,
                                          (255, 230, 150), life=0.9)
                            a.socialCd = b2.socialCd = random.uniform(8, 16)
                            # 两只性成熟且吃得饱的虫碰面 → 有机会产一枚蛋
                            if self.try_breed(a, b2):
                                break
                        # 抢糖：两只都趴在同一块糖上 → 壮的把弱的挤走
                        if a.eating and b2.eating and a.foodPatch is not None \
                                and a.foodPatch is b2.foodPatch:
                            loser, winner = (a, b2) if a.gene.get('siz', 1) < \
                                b2.gene.get('siz', 1) else (b2, a)
                            loser.eating = False
                            loser.escapeT = max(loser.escapeT, 0.3)
                            loser.socialCd = winner.socialCd = random.uniform(4, 9)
                            self.spawn_fx((a.x + b2.x) / 2, (a.y + b2.y) / 2,
                                          (255, 170, 120), life=0.8)
                            if random.random() < 0.5:
                                self.say(winner, 'contest')
                            break
                        # 打架：两只胆大的凑一起偶尔互怼
                        if a.gene.get('bold', 0.5) > 0.62 and \
                                b2.gene.get('bold', 0.5) > 0.62 and \
                                random.random() < 0.18:
                            self.spawn_fx((a.x + b2.x) / 2, (a.y + b2.y) / 2,
                                          (255, 120, 120), life=0.7)
                            a.escapeT = b2.escapeT = 0.2
                            a.socialCd = b2.socialCd = random.uniform(10, 20)
                            if random.random() < 0.6:
                                self.say(a, 'fight')
                            break
                        break
        # 领头虫：最胆大的那只当"领队"，其他虫偶尔跟着它飞
        if not self.cfg.get('paused'):
            self.pick_leader(dt)
        # 脏区重绘：只刷新本帧内容 ∪ 上一帧内容（旧像素需要清除）
        region = self.build_mask()
        dirty = region | self._prev_dirty
        self._prev_dirty = QRegion(region)
        self.update(dirty)
        want = self.frame_interval()
        if self.loop.interval() != want:
            self.loop.setInterval(want)

    def frame_interval(self):
        """本帧该用多长的定时器间隔，单位**毫秒**（不是 fps）。

        抽成纯函数是为了能被断言。这是全项目唯一一处"单位混用会让 CPU
        暴涨 30 倍却一声不吭"的地方：这行以前写的是 `want = 6`，按 fps
        读是 6fps 挺合理，可它实际是 6ms = **167fps**，比活动态（16ms）
        还费 2.7 倍。实测暂停态 165.6 fps vs 活动态 61.4 fps —— 注释写着
        "暂停时更低"，行为却是全场最高。用户在"暂停了放着不管"的时候
        最烧电，而且不报错、界面也正常，只能靠数帧才看得出来。

          · 活动     16ms ≈ 62fps
          · 打盹     50ms ≈ 20fps（鼠标静默超 sleep_after 且无糖）
          · 暂停    200ms =  5fps（世界整块不模拟，只剩时钟牌要更）
        """
        if self.cfg.get('paused'):
            # 暂停不等于不再交互：拖笼子时位置是在 tick 里才落到实处的
            # （mouseMoveEvent 只记 cage_drag_pos），按住期间必须保留快帧，
            # 否则拖动"不跟手"。need_mouse 正是"手正按着"这个语义。
            return 16 if self.need_mouse else 200
        if self.idleT > self.sleep_after and not self.foods:
            return 50
        return 16

    # ---------- 系统监视：内存 / 磁盘 ----------
    def poll_sysmon(self, dt):
        self.monT += dt
        if self.monT < 2.0:
            return
        self.monT = 0.0
        if not getattr(self, 'sysmon_on', True):
            return
        try:
            class MEMSTATUS(ctypes.Structure):
                _fields_ = [('dwLength', wintypes.DWORD),
                            ('dwMemoryLoad', wintypes.DWORD),
                            ('ullTotalPhys', ctypes.c_ulonglong),
                            ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong),
                            ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong),
                            ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            ms = MEMSTATUS()
            ms.dwLength = ctypes.sizeof(MEMSTATUS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                self.sys_mem_pct = ms.dwMemoryLoad / 100.0
        except Exception:
            pass
        try:
            import shutil
            drive = os.path.splitdrive(APP)[0] or 'C:'
            u = shutil.disk_usage(drive + os.sep)
            self.sys_disk_pct = u.used / max(1, u.total)
        except Exception:
            pass
        # 内存吃紧：果蝇发蔫、偶尔喘口气
        if self.sys_mem_pct > 0.88 and self.flies and \
                random.random() < 0.25 and not getattr(self, 'focus', None):
            self.say(random.choice(self.flies), 'tired')

    # ---------- 剪贴板小助手 ----------
    def poll_clipboard(self, dt):
        if not getattr(self, 'clipboard_on', False) or not self.flies:
            return
        self.clipT += dt
        if self.clipT < 0.8:
            return
        self.clipT = 0.0
        try:
            txt = QGuiApplication.clipboard().text() or ''
        except Exception:
            return
        txt = txt.strip()
        if not txt or txt == self.last_clip or len(txt) > 4000:
            return
        self.last_clip = txt
        show = ' '.join(txt.split())
        if len(show) > 42:
            show = show[:42] + '…'
        # 挑一只离屏幕中心最近的虫来"叼"这段话
        fly = min(self.flies, key=lambda f: math.hypot(f.x - self.w / 2,
                                                       f.y - self.h / 2))
        fly.bubble = ['剪贴板：' + show, 0.0, 4.2]

    # ---------- 谱系 ----------
    def register_fly(self, fly, parents=()):
        """给新虫分配唯一编号并记下亲代（谱系树的原材料）"""
        fly.fid = int(self.next_fid)
        self.next_fid = int(self.next_fid) + 1
        fly.parents = tuple(int(p) for p in parents if p)
        if not fly.lifespan and fly.gene:
            fly.lifespan = BASE_LIFESPAN * fly.gene.get('lon', 1.0)
        return fly

    # ---------- 繁殖 ----------
    def try_breed(self, a, b):
        """两只性成熟、吃得饱、未年老、未在冷却的虫碰面 → 产一枚蛋"""
        if len(self.flies) + len(self.eggs) >= int(self.cfg.get('max_flies', 30)):
            return False
        for f in (a, b):
            if f.age < BREED_AGE or f.energy < E_MAX * BREED_ENERGY:
                return False
            if f.eggCd > 0 or f.inCage or f.grabbed:
                return False
            if f.is_elder():        # 老了就不生了
                return False
        gene = breed_gene(a.gene, b.gene)
        ex, ey = (a.x + b.x) / 2, (a.y + b.y) / 2
        self.eggs.append({'x': ex, 'y': ey, 'age': 0.0, 'gene': gene,
                          'skin': random.choice([a.skin, b.skin]),
                          'p1': a.fid, 'p2': b.fid,     # 谱系：记住爹妈编号
                          'g1': a.gene.get('gen', 1),
                          'g2': b.gene.get('gen', 1)})
        # 生育力 fer 越高，冷却越短（0.45~2.2 → 约 58~12 秒）
        cd = EGG_CD / max(0.45, a.gene.get('fer', 1.0))
        a.eggCd = b.eggCd = cd
        a.energy = min(E_MAX, a.energy * 0.92)   # 生育耗能
        b.energy = min(E_MAX, b.energy * 0.92)
        self.spawn_fx(ex, ey, (200, 240, 200), life=1.2)
        self.say(a, 'lay')
        return True

    def update_eggs(self, dt):
        """蛋随时间孵化出新虫（继承双亲基因 + 变异）"""
        alive = []
        for e in self.eggs:
            e['age'] += dt
            if e['age'] >= EGG_TIME:
                if len(self.flies) >= int(self.cfg.get('max_flies', 30)):
                    alive.append(e)      # 满了就先留着，不硬塞
                    continue
                g = e['gene']
                nf = PetFly(clamp(e['x'], 30, self.w - 30),
                            clamp(e['y'], 30, self.h - 30),
                            skin=e.get('skin'), gene=g)
                nf.labelT = 10.0
                nf.energy = E_START * 0.7
                nf.eggCd = EGG_CD
                # 谱系：分配编号 + 记亲代（老档的蛋没有 p1/p2，交给 register_fly 过滤）
                self.register_fly(nf, parents=(e.get('p1', 0), e.get('p2', 0)))
                self.flies.append(nf)
                for _ in range(5):
                    self.spawn_fx(nf.x + random.uniform(-24, 24),
                                  nf.y + random.uniform(-18, 18),
                                  (200, 255, 210), life=1.1)
                self.record_codex(nf, '孵化')
                self.lineage.append({
                    'fid': nf.fid, 'gen': nf.gene.get('gen', 1),
                    'p1': nf.parents[0] if len(nf.parents) > 0 else 0,
                    'p2': nf.parents[1] if len(nf.parents) > 1 else 0,
                    'grade': gene_grade(g), 'skin': nf.skin or self.skin_name,
                    't': time.monotonic(),
                })
                del self.lineage[:-LINEAGE_KEEP]
                self.birth_log.append((time.monotonic(),
                                       nf.skin or self.skin_name,
                                       gene_grade(g), nf.traits_text()))
            else:
                alive.append(e)
        self.eggs = alive

    def record_codex(self, fly, how):
        """记进图鉴：物种计数 + 最佳代数 + 稀有度统计"""
        sp = fly.skin or self.skin_name
        c = self.codex.setdefault('species', {})
        c[sp] = int(c.get(sp, 0)) + 1
        self.codex['hatched'] = int(self.codex.get('hatched', 0)) + 1
        self.codex['best_gen'] = max(int(self.codex.get('best_gen', 0)),
                                     int(fly.gene.get('gen', 1)))
        gr = gene_grade(fly.gene)
        gd = self.codex.setdefault('grades', {'普通': 0, '优良': 0, '稀有': 0, '传说': 0})
        gd[gr] = int(gd.get(gr, 0)) + 1

    def codex_text(self):
        """图鉴正文（纯字符串，方便测试与将来导出）"""
        cx = self.codex
        lines = []
        lines.append('累计诞生：%d 只    最高世代：第 %d 代' %
                     (int(cx.get('hatched', 0)), int(cx.get('best_gen', 0))))
        gd = cx.get('grades', {})
        lines.append('稀有度：' + '  '.join(
            '%s×%d' % (k, int(gd.get(k, 0))) for k in ('普通', '优良', '稀有', '传说')))
        lines.append('')
        lines.append('— 物种记录 —')
        if cx.get('species'):
            for name, cnt in sorted(cx['species'].items(), key=lambda kv: -kv[1]):
                lines.append('  %-10s ×%d' % (self.skin_disp.get(name, name), cnt))
        else:
            lines.append('  （还没有孵出过新虫：喂饱两只成年虫，让它们碰面）')
        lines.append('')
        lines.append('— 现役个体 —')
        for f in self.flies[:14]:
            lines.append('  #%-3d %-8s %-6s 第%2d代  %-6s %s' % (
                int(getattr(f, 'fid', 0)),
                self.skin_disp.get(f.skin or self.skin_name, '果蝇'),
                gene_grade(f.gene), f.gene.get('gen', 1),
                '年老' if f.is_elder() else '壮年', f.traits_text()))
        if len(self.flies) > 14:
            lines.append('  …另有 %d 只' % (len(self.flies) - 14))
        if self.eggs:
            left = min(EGG_TIME - e['age'] for e in self.eggs)
            lines.append('')
            lines.append('正在孵化：%d 枚（最近的还有 %.0f 秒）' %
                         (len(self.eggs), max(0, left)))
        # 谱系：最近孵化的虫 + 它的亲代编号
        if self.lineage:
            lines.append('')
            lines.append('— 最近谱系（新 → 旧）—')
            for r in reversed(self.lineage[-8:]):
                p1, p2 = int(r.get('p1', 0)), int(r.get('p2', 0))
                par = ('亲代 #%d × #%d' % (p1, p2)) if p1 and p2 else '亲代不明'
                lines.append('  #%-3d 第%d代 %-4s %s' % (
                    int(r.get('fid', 0)), int(r.get('gen', 1)),
                    r.get('grade', ''), par))
        return '\n'.join(lines)

    # ---------- 报时虫（头顶顶一块时钟牌，可轮播待办） ----------
    def clock_fly(self):
        """负责报时的那只虫；没配置或那只已经不在就返回 None"""
        fid = int((self.cfg.get('clock') or {}).get('fid', 0) or 0)
        if fid <= 0:
            return None
        for f in self.flies:
            if getattr(f, 'fid', 0) == fid:
                return f
        return None

    def clock_perch(self):
        """报时虫的驻守点：右下角偏内（避开常见任务栏区域）"""
        return (self.w - 170.0, self.h - 150.0)

    def clock_texts(self, now=None):
        """报时牌上的文字行，[时间, 周几, 待办…]（纯数据，方便测试）"""
        now = time.localtime() if now is None else now
        lines = ['%02d:%02d' % (now.tm_hour, now.tm_min)]
        clk = self.cfg.get('clock') or {}
        if clk.get('show_title', True):
            # 注意下标基准：time.struct_time.tm_wday 是 **周一=0**，
            # 而 '日一二三四五六' 这套字符串是 **周日=0**。直接拿 tm_wday 当下标
            # 会让星期几**每天都差一天**（2026-09-25 是周五，却显示成"周四"）。
            # 所以必须用以周一起头的字符串。
            wd = '一二三四五六日'[now.tm_wday % 7]
            lines.append('%d月%d日 周%s' % (now.tm_mon, now.tm_mday, wd))
        todos = [str(t).strip() for t in (clk.get('todos') or []) if str(t).strip()]
        if todos:
            # 每 6 秒轮一条，长时间挂在桌面上也不会只看到第一条
            i = int(time.monotonic() / 6.0) % len(todos)
            lines.append('待办：%s' % todos[i])
        return lines

    def clock_board_rect(self, fly):
        """时钟牌的矩形（build_mask 与 paint 共用，保证牌面可被 mask 覆盖）"""
        lines = self.clock_texts()
        fh = 22
        w = 128
        for i, t in enumerate(lines):
            w = max(w, QFontMetrics(QFont('Microsoft YaHei', 16 if i == 0 else 9))
                    .horizontalAdvance(t) + 26)
        h = 30 + fh * (len(lines) - 1) + 8
        x = clamp(fly.x - w / 2, 6, max(6, self.w - w - 6))
        y = fly.y - 46 * self.cfg['scale'] * fly.size_factor() - h - 6
        if y < 6:
            y = fly.y + 46 * self.cfg['scale'] * fly.size_factor() + 6
        return QRect(int(x), int(y), int(w), int(h))

    def draw_clock_board(self, p):
        fly = self.clock_fly()
        if fly is None:
            return
        rc = self.clock_board_rect(fly)
        lines = self.clock_texts()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(16, 22, 32, 214))
        p.drawRoundedRect(rc, 9, 9)
        p.setPen(QPen(QColor(120, 190, 255, 150), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rc.adjusted(0, 0, -1, -1), 9, 9)
        # 时间（大号，等宽字体对齐数字）
        f0 = QFont('Consolas', 15)
        f0.setBold(True)
        p.setFont(f0)
        p.setPen(QColor(178, 226, 255, 245))
        p.drawText(QRectF(rc.x(), rc.y() + 5, rc.width(), 26),
                   Qt.AlignCenter, lines[0])
        if len(lines) > 1:
            p.setFont(QFont('Microsoft YaHei', 8))
            for i, t in enumerate(lines[1:]):
                p.setPen(QColor(150, 176, 205, 235) if i == 0
                         else QColor(235, 214, 150, 245))
                p.drawText(QRectF(rc.x(), rc.y() + 32 + i * 22, rc.width(), 20),
                           Qt.AlignCenter, t)

    def fly_detail_text(self, fly):
        """单只虫的基因卡片（纯字符串）。fid<=0 表示世界外构造的虫，照样能出卡。"""
        g = fly.gene
        name = self.skin_disp.get(fly.skin or self.skin_name, '果蝇')
        L = []
        L.append('#%d  %s' % (int(getattr(fly, 'fid', 0)), name))
        L.append('第 %d 代 · %s · %s' %
                 (int(g.get('gen', 1)), gene_grade(g), fly.age_text()))
        L.append('')
        L.append('— 外显基因（决定评级）—')
        L.append('  速度 spd  %5.2f' % g.get('spd', 1.0))
        L.append('  体型 siz  %5.2f' % g.get('siz', 1.0))
        L.append('  胆量 bold %5.2f' % g.get('bold', 0.5))
        L.append('  色相 hue  %5.2f' % g.get('hue', 0.5))
        L.append('')
        L.append('— 生活史基因 —')
        L.append('  寿命 lon  %5.2f   → 总寿命约 %.0f 分钟' %
                 (g.get('lon', 1.0), fly.lifespan / 60.0))
        L.append('  食欲 app  %5.2f' % g.get('app', 1.0))
        L.append('  生育力 fer %5.2f  → 产卵冷却约 %.0f 秒' %
                 (g.get('fer', 1.0), EGG_CD / max(0.45, g.get('fer', 1.0))))
        L.append('')
        L.append('性状：%s' % fly.traits_text())
        L.append('活力：%.0f%%%s' % (
            100 * fly.vitality(),
            '（年老后飞行变慢、不再生育）' if fly.is_elder() else ''))
        if fly.parents:
            L.append('亲代：#%d × #%d' % (fly.parents[0],
                                        fly.parents[1] if len(fly.parents) > 1 else 0))
        else:
            L.append('亲代：野生（放置或初始个体）')
        if fly.inCage:
            L.append('状态：关在笼子里')
        elif fly.is_legendary():
            L.append('✦ 传说个体：身上有金色光晕')
        return '\n'.join(L)

    # ---------- 领头虫 ----------
    def pick_leader(self, dt):
        self.leader = None
        cands = [f for f in self.flies
                 if not f.grabbed and not f.inCage and f.escapeT <= 0
                 and f.age > 8.0]
        if len(cands) < 3:
            return
        lead = max(cands, key=lambda f: f.gene.get('bold', 0.5))
        if lead.gene.get('bold', 0.5) < 0.55:
            return          # 一群胆小鬼，没有领队
        self.leader = lead
        # 跟飞：其他虫轻微朝领队靠拢（形成小队形）
        for f in cands:
            if f is lead or f.hunger > 0.5:
                continue
            dx, dy = lead.x - f.x, lead.y - f.y
            d = math.hypot(dx, dy) or 1.0
            if d > 260:
                f.dir += clamp(math.atan2(dy, dx) - f.dir, -1.2 * dt, 1.2 * dt)

    def focus_spot(self):
        """番茄钟期间虫子的集合点（某个角落）"""
        pad = 120.0
        c = self.focus_corner
        return (self.w - pad if 'right' in c else pad,
                self.h - pad if 'bottom' in c else pad)

    def start_focus(self, mins):
        self.focus = {'until': time.monotonic() + mins * 60, 'mins': mins}
        self.focus_corner = random.choice(FOCUS_SPOTS)
        for f in self.flies:
            f.bubble = None
        return self.focus

    def stop_focus(self, silent=False):
        if not self.focus:
            return
        self.focus = None
        if not silent:
            self.announce = ('专注结束 · 起来活动一下', time.monotonic() + 12.0)

    def focus_left(self):
        if not self.focus:
            return None
        return max(0, int(self.focus['until'] - time.monotonic()))


    def poll_cpu(self):
        u = self.cpu.poll()
        self.agi = clamp((u - 0.55) / 0.45, 0.0, 1.0)

    # ---------- 点击穿透 mask + 脏区重绘 ----------
    def interactive_fullscreen(self):
        """是否处于"需要全屏接鼠标"的交互态。
        mask 把空白区做成穿透，好处是平时不挡桌面点击；
        但放置/捕捉/拖动这些操作恰恰要点空白、要跨空白拖动 ——
        此时必须临时放开整屏，否则事件直接穿透到下层窗口，
        表现就是"点了没反应 / 拖不动 / 拖一半断了"。"""
        return bool(getattr(self, 'pending_place', False)
                    or getattr(self, 'capture_mode', False)
                    or self.cage_drag
                    or getattr(self, 'pressed_fly', None) is not None
                    or getattr(self, 'need_mouse', False)
                    # 文件正拖在笼子/虫子上方：要开着全屏，否则微动一下
                    # 掉出 mask 范围就收不到 drop，表现为"有时拖不进去"
                    or self.drag_hover
                    or getattr(self, 'drop_fly_hover', None) is not None)

    def apply_screen_geometry(self, mode=None):
        """按配置决定覆盖范围：
        primary = 只盖主屏（最不打扰）；all = 盖住整个虚拟桌面（多显示器）
        可运行时切换：改 w/h → setGeometry → 重新算 mask，并把越界的虫拉回来。
        """
        if mode is None:
            mode = self.cfg.get('screen_mode', 'primary')
        mode = 'all' if str(mode).lower() == 'all' else 'primary'
        self.screen_mode = mode
        scr = (QGuiApplication.primaryScreen().virtualGeometry()
               if mode == 'all'
               else QGuiApplication.primaryScreen().geometry())
        old_w, old_h = getattr(self, 'w', 0), getattr(self, 'h', 0)
        self.w, self.h = scr.width(), scr.height()
        self.setGeometry(scr)
        self._prev_mask = None            # 尺寸变了，缓存的 mask 必须作废
        resized = bool(old_w and old_h and (old_w, old_h) != (self.w, self.h))
        # 越界的虫一律拉回来（不能只在尺寸变化时才做：拔掉一块显示器后
        # 尺寸可能不变，但坐标留在窗口外的虫会永远看不见、也点不到）
        # 注意：__init__ 里第一次调用时这些容器还不存在，必须 getattr 兜底
        for fly in getattr(self, 'flies', ()) or ():
            if resized:
                fly.x = fly.x * self.w / max(1, old_w)
                fly.y = fly.y * self.h / max(1, old_h)
            fly.x = clamp(fly.x, 40, max(40, self.w - 40))
            fly.y = clamp(fly.y, 40, max(40, self.h - 40))
        if getattr(self, 'cage', None) is not None:
            self.cage['x'] = clamp(float(self.cage.get('x', self.w / 2)),
                                   40, max(40, self.w - 40))
            self.cage['y'] = clamp(float(self.cage.get('y', self.h / 2)),
                                   40, max(40, self.h - 40))
        for f in getattr(self, 'foods', ()) or ():
            f['x'] = clamp(float(f.get('x', 0)), 8, max(8, self.w - 8))
            f['y'] = clamp(float(f.get('y', 0)), 8, max(8, self.h - 8))
        return scr

    def on_settings_changed(self, changed=()):
        """设置面板保存后，把**需要立刻生效**的键落实到位。

        只做"改完就能看到效果"的部分；像投喂快捷键那种必须重新注册系统热键的，
        留给界面提示"重启后生效"，避免在这里做半吊子的热插拔。
        """
        changed = set(changed or ())
        if 'screen_mode' in changed:
            self.apply_screen_geometry(self.cfg.get('screen_mode'))
        if 'count' in changed or 'max_flies' in changed:
            cap = max(1, int(self.cfg.get('max_flies', 30)))
            n = max(1, min(int(self.cfg.get('count', 1)), cap))
            self.cfg['count'] = n
            while len(self.flies) < n:
                self.flies.append(self.register_fly(PetFly(
                    random.uniform(80, max(81, self.w - 80)),
                    random.uniform(80, max(81, self.h - 80)))))
            while len(self.flies) > n:
                self.flies.pop()
        if 'skin' in changed:
            want = self.cfg.get('skin')
            if want in self.skins:
                self.skin_name = want
        if 'file_stash.default_dir' in changed:
            d = self.cfg['file_stash'].get('default_dir')
            self.announce = ('收纳兜底目录：%s' % d if d else '收纳兜底目录已清空',
                             time.monotonic() + 5.0)
        return sorted(changed)

    # ---------- 绘制几何的"唯一真相源" ----------
    #
    # 下面两个函数被 **绘制** 与 **build_mask** 同时调用。
    #
    # 为什么必须共用：mask 在这个产品里是双用途的 —— 既决定点击穿透范围，
    # 又是 setMask 的可见区域（QWidget.grab() 也吃它）。于是"绘制写一套数、
    # mask 写另一套数"的代价不是"画错"，而是**被静默裁掉**：元素在 mask 之外
    # 就根本看不见，同时那块脏区不含它 → 拖动残影。而且它对现有两类测试
    # 都是隐形的：基线图看不出一致性，逻辑测试只验点击。
    #
    # 实测踩到的两处（_mask_check.py 有断言守着）：
    #   ① 传说光晕：绘制 `20+22*sm` 不乘 cfg['scale']，mask `46*scale*ss*sm` 乘了。
    #      两套数只在 scale≈1 时凑巧吻合 → scale 调到 0.70 时外溢 1256 px，
    #      光晕被切成方角（用户把窗口缩放调小就会看到）。
    #   ② 气泡：绘制宽度随文字变长（advance+18）还会夹到窗口内，
    #      mask 却写死 180px 宽、以 fly.x 为中心 → 长气泡（收纳/提醒文案）
    #      左右两端被切，实测外溢 3912 px。

    def fly_paint_radius(self, fly):
        """这只虫本帧可能画到的最大世界半径（身体/皮肤贴图、传说光晕取大）。"""
        skin = self.skins.get(fly.skin) or self.skins.get(self.skin_name)
        ss = skin.get('size_scale', 1.0) if skin else 1.0
        sm = fly.size_factor()
        k = self.cfg['scale'] * ss           # 与 _paint 里 p.scale(scale*ss*sm) 对应
        r = 46.0 * k * sm                    # 身体+腿+翅；56px 贴图对角线 ≈ 40，留余量
        if fly.is_legendary():
            # 光晕最外那圈 k=1.0，半径就是 aura 本身（见 _paint）。
            # ⚠ aura 公式里**已经含了 sm**（20 + 22*sm），这里不能再乘一次。
            r = max(r, (20.0 + 22.0 * sm) * k)
        return r

    def bubble_rect(self, fly):
        """气泡矩形（世界坐标，已按窗口边界夹紧）。返回 None 表示这次不画。"""
        if not fly.bubble:
            return None
        fm = QFontMetrics(QFont('Microsoft YaHei', 9))
        tw = fm.horizontalAdvance(fly.bubble[0]) + 18
        th = fm.height() + 10
        bx = clamp(fly.x - tw / 2, 6, self.w - tw - 6)
        by = fly.y - 40 * self.cfg['scale'] - th
        if by < 4:                       # 顶上放不下就翻到虫下方
            by = fly.y + 40 * self.cfg['scale']
        return QRectF(bx, by, tw, th)

    def build_mask(self):
        """返回本帧所有可见内容的 QRegion（mask 之外完全点击穿透）"""
        # 交互态：整屏开放，保证空白处的点击/拖动也能收到
        if self.interactive_fullscreen():
            full = QRegion(QRect(0, 0, self.w, self.h))
            self.setMask_skip(full)
            return full
        region = QRegion()
        for fly in self.flies:
            # 半径与绘制共用 fly_paint_radius（皮肤体型倍率 + 个体尺寸倍率 + 传说光晕）
            rf = int(self.fly_paint_radius(fly))
            region |= QRegion(QRect(int(fly.x) - rf, int(fly.y) - rf, rf * 2, rf * 2))
            lbl = self.fly_label_rect(fly)
            if lbl is not None:
                region |= QRegion(lbl.adjusted(-2, -2, 2, 2))
            # 气泡：矩形与 draw_bubble 共用 bubble_rect，不再写死 180px
            br = self.bubble_rect(fly)
            if br is not None:
                # 上下各多留 8px：尾巴画在矩形下沿之外
                region |= QRegion(br.adjusted(-2, -2, 2, 8).toAlignedRect())
        for f in self.foods:
            region |= QRegion(QRect(int(f['x']) - 24, int(f['y']) - 24, 48, 48))
        # 报时牌也要进 mask，否则牌面区域会点击穿透（看着在那里却点不到）
        _cf = self.clock_fly()
        if _cf is not None:
            region |= QRegion(self.clock_board_rect(_cf).adjusted(-2, -2, 2, 2))
        for e in self.eggs:
            region |= QRegion(QRect(int(e['x']) - 20, int(e['y']) - 20, 40, 44))
        for e in self.fx:
            if e.get('char'):   # z 字粒子会上浮 ~27px，mask 要覆盖整段行程
                region |= QRegion(QRect(int(e['x']) - 20, int(e['y']) - 56, 40, 76))
            else:
                region |= QRegion(QRect(int(e['x']) - 20, int(e['y']) - 20, 40, 40))
        # 笼子：mask 必须覆盖"可交互矩形"（含底座/锁点），
        # 否则拖到底座那一条时系统根本不给我们发拖放事件 → 显示禁止符
        chr_ = self.cage_hit_rect()
        if chr_ is not None:
            if self.drag_hover:
                # 已经拖在笼上：再放宽一圈，容忍手抖，并覆盖"松手就喂"提示条
                chr_ = chr_.adjusted(-28, -28, 28, 28)
                cr2 = self.cage_rect()
                if cr2 is not None:
                    chr_ = chr_.united(
                        QRect(cr2.left() - 160, cr2.bottom() + 14, cr2.width() + 320, 42))
                    chr_ = chr_.united(
                        QRect(cr2.left() - 160, cr2.top() - 46, cr2.width() + 320, 42))
            region |= QRegion(chr_)
        for p in self.pher:
            rr = int(30 * math.exp(-p['age'] / PHER_TAU)) + 22
            region |= QRegion(QRect(int(p['x']) - rr, int(p['y']) - rr, rr * 2, rr * 2))
        # 模式提示条（与 paintEvent 同宽：文案最长的那种按最宽估）
        if getattr(self, 'pending_place', False) or getattr(self, 'capture_mode', False):
            region |= QRegion(QRect(int(self.w / 2) - 260, 10, 520, 42))
        # 番茄钟计时条
        if getattr(self, 'focus', None):
            region |= QRegion(QRect(int(self.w / 2) - 130, 10, 260, 34))
        self.setMask_skip(region)
        return region

    def setMask_skip(self, region):
        """setMask 有内核态开销，区域没变就跳过"""
        if self._prev_mask is None or region != self._prev_mask:
            self.setMask(region)
            self._prev_mask = QRegion(region)

    def apply_mode_mask(self):
        """切换放置/捕捉模式后立刻刷新 mask（不能等下一帧，
        否则用户点第一下时窗口还是穿透的，表现为"第一次点没反应"）"""
        self.build_mask()

    # ---------- 交互 ----------
    def _nearest_fly(self, gx, gy):
        best, bd = None, 1e9
        for fly in self.flies:
            d = math.hypot(gx - fly.x, gy - fly.y)
            if d < bd:
                best, bd = fly, d
        return best, bd

    def mousePressEvent(self, ev):
        gx = ev.position().x() + self.x()
        gy = ev.position().y() + self.y()
        # 交互期全程放开 mask：否则拖动经过空白区时事件会穿透丢失，
        # 表现为"拖一半断掉 / 松手没反应"
        self.need_mouse = True
        self.apply_mode_mask()
        chr_ = self.cage_hit_rect()
        if ev.button() == Qt.LeftButton:
            # 笼子优先：按在笼上 = 拖动笼子（否则笼内虫子总抢先命中，笼子拖不动）
            # 用 hit_rect：底座/锁点这些看得见的地方也都能拖，做到所见即所得
            if chr_ is not None and chr_.contains(QPoint(int(gx), int(gy))):
                self.cage_drag = True
                # 记下光标相对笼心的偏移，拖动时保持手感（不会一跳把笼心吸到光标）
                self.cage_grab_off = (gx - self.cage['x'], gy - self.cage['y'])
                self.cage_drag_pos = (gx, gy)
                self.setCursor(Qt.ClosedHandCursor)
                return
            fly, d = self._nearest_fly(gx, gy)
            # 放置模式：点哪儿放哪儿（优先于抓虫/拍虫，否则点到虫身上会"没反应"）
            if getattr(self, 'pending_place', False):
                self.pending_place = False
                self.place_fly(gx, gy, self.pending_skin)
                self.need_mouse = False
                self.apply_mode_mask()
                return
            if fly is not None and d < 40 * self.cfg['scale']:
                if getattr(self, 'capture_mode', False):
                    self.cage_fly(fly)   # 捕捉模式：点谁谁进笼
                    self.need_mouse = False
                    self.apply_mode_mask()
                    return
                self.pressed_fly = fly
                self.pressT = time.monotonic()
                self.pressPos = (ev.globalPosition().x(), ev.globalPosition().y())
        elif ev.button() == Qt.RightButton:
            self.need_mouse = False
            # 放置/捕捉模式：右键取消（提示条上是这么写的，必须真能取消）
            if getattr(self, 'pending_place', False):
                self.pending_place = False
                self.apply_mode_mask()
                return
            if getattr(self, 'capture_mode', False):
                self.capture_mode = False
                a = getattr(self, 'capture_mode_act', None)
                if a is not None:
                    a.blockSignals(True)
                    a.setChecked(False)
                    a.blockSignals(False)
                self.apply_mode_mask()
                return
            if chr_ is not None and chr_.contains(QPoint(int(gx), int(gy))):
                self.cage_menu(ev.globalPosition().toPoint())
                return
            for f in list(self.foods):
                d = math.hypot(gx - f['x'], gy - f['y'])
                if d < 26:
                    self.foods.remove(f)
                    self.spawn_fx(f['x'], f['y'], (180, 180, 190))

    def mouseDoubleClickEvent(self, ev):
        """双击一只虫 → 它给你打个滚（纯粹的玩）"""
        gx = ev.position().x() + self.x()
        gy = ev.position().y() + self.y()
        fly, d = self._nearest_fly(gx, gy)
        if fly is not None and d < 46 * self.cfg['scale']:
            fly.spin()
            fly.labelT = max(fly.labelT, 2.0)
            self.spawn_fx(fly.x, fly.y, (255, 220, 150), life=0.8)
            return
        # 双击空白处：扔一颗糖（比右键菜单快）
        self.feed(gx, gy)
        ev.accept()

    def mouseMoveEvent(self, ev):
        """拖动笼子时实时跟随鼠标（不能只靠 tick，否则不跟手）"""
        gx = ev.position().x() + self.x()
        gy = ev.position().y() + self.y()
        if self.cage_drag and self.cage is not None:
            self.cage_drag_pos = (gx, gy)
        # 光标形状反馈：可抓/可拖的地方给手型（与可见范围一致）
        chr_ = self.cage_hit_rect()
        if not self.cage_drag and chr_ is not None \
                and chr_.contains(QPoint(int(gx), int(gy))):
            self.setCursor(Qt.OpenHandCursor)
        elif not self.cage_drag:
            self.unsetCursor()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        self.cage_drag = False
        self.cage_drag_pos = None
        self.unsetCursor()
        gx = ev.position().x() + self.x()
        gy = ev.position().y() + self.y()
        fly = self.pressed_fly
        if fly is not None and fly.grabbed:
            fly.release_grab()
            # 抓着丢进笼子：判定范围 = 高亮范围（绿色高亮亮起的地方松手一定成功）
            chr_ = self.cage_hit_rect()
            if chr_ is not None and chr_.contains(QPoint(int(gx), int(gy))):
                self.cage_fly(fly)
        elif fly is not None and self.pressT is not None \
                and time.monotonic() - self.pressT <= GRAB_DELAY:
            fly.swat(self)
        self.pressT = None
        self.pressPos = None
        self.pressed_fly = None
        # 交互结束，收敛回点击穿透（放置/捕捉模式仍保持全屏开放）
        self.need_mouse = False
        self.apply_mode_mask()

    def say(self, fly, key):
        bub = self.cfg['bubbles']
        if not bub.get('enabled'):
            return
        # 安静模式：日常闲聊一律闭嘴，但"你刚做了个操作"的反馈要留着 ——
        # 否则你拖完文件不知道到底收没收进去。
        if self.cfg.get('quiet') and key not in QUIET_KEEP:
            return
        texts = bub.get('texts', {}).get(key) \
            or DEFAULT_SETTINGS['bubbles']['texts'].get(key, [])
        if not texts:
            return
        fly.bubble = [pick(texts), 0.0, float(bub.get('show_seconds', 2.8))]

    def spawn_fx(self, x, y, color, life=0.7, char=None):
        self.fx.append({'x': x, 'y': y, 'age': 0.0, 'color': color,
                        'life': life, 'char': char})

    # ---------- 笼子 ----------
    def cage_rect(self):
        c = getattr(self, 'cage', None)
        if not c:
            return None
        w = c.get('w', CAGE_W)
        h = c.get('h', CAGE_H)
        return QRect(int(c['x'] - w / 2), int(c['y'] - h / 2), int(w), int(h))

    def cage_hit_rect(self):
        """笼子的"可交互矩形" = draw_cage 实际画出来的外轮廓 + 少许余量。

        必须与可见范围一致，否则会出现"看着在笼子上、拖进去却是禁止符"：
        底座比笼身宽 6px、锁点比笼身高 9px，旧代码只用笼身判定，
        于是拖到底座/边缘时 mask 收不到事件、contains() 也为 False。
        所有命中判定（拖动/放虫/拖文件/mask/右键菜单/高亮）统一走这里。"""
        cr = self.cage_rect()
        if cr is None:
            return None
        r = QRect(cr)
        # 底座：draw_cage 里是 QRect(left-6, bottom-14, width+12, 16)
        r = r.united(QRect(cr.left() - 6, cr.bottom() - 14, cr.width() + 12, 16))
        # 锁点：draw_cage 里是 QRect(right-22, top-9, 15, 15)
        r = r.united(QRect(cr.right() - 22, cr.top() - 9, 15, 15))
        # 外描边 + 手感余量
        return r.adjusted(-8, -8, 8, 8)

    def cage_fly(self, fly):
        if self.cage is None:
            return
        fly.inCage = True
        fly.grabbed = False
        fly.x = self.cage['x'] + random.uniform(-32, 32)
        fly.y = self.cage['y'] + random.uniform(-20, 20)
        self.say(fly, 'caged')
        self.spawn_fx(fly.x, fly.y, (170, 220, 255))

    def place_fly(self, gx, gy, skin):
        """放置模式落虫：应用当前选择的尺寸；放得多了有概率巨型化（彩蛋）"""
        if len(self.flies) >= int(self.cfg.get('max_flies', 12)):
            return
        nf = self.register_fly(PetFly(gx, gy, skin=skin))
        nf.size_mult = getattr(self, 'pending_size', 1.0)
        nf.labelT = 8.0
        self.flies.append(nf)
        self.spawn_fx(gx, gy, (170, 220, 255), life=0.9)
        self.placed_count = getattr(self, 'placed_count', 0) + 1
        # 彩蛋：越放越可能出现巨型个体（同样受上限约束，不放爆）
        if len(self.flies) < int(self.cfg.get('max_flies', 12)) and \
                random.random() < min(0.4, 0.08 * self.placed_count):
            big = self.register_fly(PetFly(
                gx + random.uniform(-90, 90),
                gy + random.uniform(-70, 70),
                skin=random.choice([n for n in self.skins
                                    if n != '_procedural'] or ['pixel'])))
            big.size_mult = 2.8
            big.labelT = 9.0
            self.flies.append(big)
            self.placed_count = 0
            for _ in range(6):
                self.spawn_fx(big.x + random.uniform(-50, 50),
                              big.y + random.uniform(-40, 40),
                              (255, 214, 120), life=1.2)
            big.bubble = ['（我长大了！）', 0.0, 3.0]

    def cage_menu(self, gpos):
        m = QMenu(self)
        locked = self.cage.get('locked')
        a_lock = QAction('解锁（放它们出来）' if locked else '上锁（关住它们）', m)
        a_out = QAction('放出全部果蝇', m)
        a_sugar = QAction('笼里放糖（糖诱捕捉）', m)
        pop_size = QMenu('笼子尺寸', m)
        a_rm = QAction('收走笼子', m)
        for a in (a_lock, a_out, a_sugar):
            m.addAction(a)
        m.addMenu(pop_size)
        m.addAction(a_rm)

        def set_size(w, h):
            self.cage['w'], self.cage['h'] = w, h
        for label, w, h in [('小（110×80）', 110, 80),
                            ('中（150×110）', 150, 110),
                            ('大（220×160）', 220, 160)]:
            a = QAction(label, pop_size)
            a.setCheckable(True)
            a.setChecked(self.cage.get('w', CAGE_W) == w and
                         self.cage.get('h', CAGE_H) == h)
            a.triggered.connect(lambda checked=False, w_=w, h_=h: set_size(w_, h_))
            pop_size.addAction(a)

        chosen = m.exec(gpos)
        if chosen is a_lock:
            self.cage['locked'] = not locked
            # 原来写的是 `if not locked:` —— 条件反了。
            # 它实际上是在**上锁**那一瞬间把虫全放出来，而**解锁**时什么都不做，
            # 于是"解锁（放它们出来）"点完，虫身上的 inCage 还挂着：
            # 笼子虽然不夹它们了，但这只虫从此不繁殖（update 里跳过 inCage）、
            # 永远当不了领队（pick_leader 排除）、详情里还写着"在笼中"、
            # 吃文件也照样领能量。笼子一旦上锁又会把它重新夹住，行为完全说不通。
            # 正确语义：原来是锁着的 → 这次是解锁 → 才要放它们出来。
            if locked:
                for fly in self.flies:
                    fly.inCage = False
        elif chosen is a_out:
            for fly in self.flies:
                fly.inCage = False
        elif chosen is a_sugar:
            self.foods.append({'x': float(self.cage['x']),
                               'y': float(self.cage['y']), 'e': FOOD_E0})
        elif chosen is a_rm:
            self.cage = None

    # ---------- 文件拖进笼子 = 吃掉（进回收站，可还原）----------
    def _drag_over_cage(self, ev):
        """拖放命中判定：只看"可交互矩形"，与可见范围一致"""
        r = self.cage_hit_rect()
        return r is not None and r.contains(ev.position().toPoint())

    def dragEnterEvent(self, ev):
        if self._drag_over_cage(ev):
            self.drag_hover = True      # 高亮笼子 + 提示"松手就喂"
            self.drop_fly_hover = None
            self.apply_mode_mask()      # 顺手扩一点 mask，防止手抖掉出范围
            ev.acceptProposedAction()
            return
        # 拖到某只虫身上 = 收纳到该虫的目录（不是吃掉！别把用户文件删了）
        f = self.drop_fly_at(ev.position().x(), ev.position().y())
        if f is not None and (self.cfg.get('file_stash') or {}).get('enabled', True):
            self.drag_hover = False
            self.drop_fly_hover = f
            self.apply_mode_mask()
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        r = self.cage_hit_rect()
        px, py = ev.position().x(), ev.position().y()
        was = (self.drag_hover, id(self.drop_fly_hover))
        # 一旦开始悬停在笼上，就放宽到"笼子周围一大圈"，
        # 避免用户在笼子边缘小幅晃动时突然变成禁止符
        if r is not None and self.drag_hover:
            ok_cage = r.adjusted(-28, -28, 28, 28).contains(
                ev.position().toPoint())
        else:
            ok_cage = self._drag_over_cage(ev)
        f = None
        if not ok_cage and (self.cfg.get('file_stash') or {}).get('enabled', True):
            f = self.drop_fly_at(px, py)
        self.drag_hover = bool(ok_cage)
        self.drop_fly_hover = f
        if ok_cage or f is not None:
            ev.acceptProposedAction()
        else:
            ev.ignore()
        if (self.drag_hover, id(self.drop_fly_hover)) != was:
            self.apply_mode_mask()

    def dragLeaveEvent(self, ev):
        self.drag_hover = False
        self.drop_fly_hover = None
        self.apply_mode_mask()

    def dropEvent(self, ev):
        px, py = ev.position().x(), ev.position().y()
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        r = self.cage_hit_rect()
        over_cage = (r is not None
                     and r.adjusted(-28, -28, 28, 28).contains(
                         ev.position().toPoint()))
        fly = None if over_cage else self.drop_fly_at(px, py)
        self.drag_hover = False
        self.drop_fly_hover = None
        if over_cage and paths:
            self.eat_files(paths, self.cage_rect())
        elif fly is not None and paths:
            self.stash_files(paths, fly)
        else:
            self.apply_mode_mask()
            ev.ignore()
            return
        self.apply_mode_mask()
        ev.acceptProposedAction()

    # ---------- 文件收纳：拖到某只虫身上 → 移动到指定文件夹 ----------
    def fly_hit_rect(self, fly):
        """拖放命中区（比虫身大一圈，方便瞄准；mask 与命中测试共用这一份）"""
        rf = int(52 * self.cfg['scale'] * fly.size_factor())
        return QRect(int(fly.x) - rf, int(fly.y) - rf, rf * 2, rf * 2)

    def drop_fly_at(self, gx, gy):
        """落点命中的虫；多只重叠时取离得最近的那只"""
        best, bd = None, 1e9
        for fly in self.flies:
            r = self.fly_hit_rect(fly)
            if r.contains(int(gx), int(gy)):
                d = math.hypot(gx - fly.x, gy - fly.y)
                if d < bd:
                    best, bd = fly, d
        return best

    def stash_target_for(self, path, fly=None):
        """决定某个文件该放哪。顺序：该虫专属目录 → 扩展名规则 → 兜底目录。
        都没配就返回 None —— 调用方必须"什么都不做"，绝不能退化成删除。"""
        cfg = self.cfg.get('file_stash') or {}
        if not cfg.get('enabled', True):
            return None
        if fly is not None:
            d = (self.cfg.get('fly_stash') or {}).get(str(getattr(fly, 'fid', 0)))
            if d:
                return str(d)
        ext = os.path.splitext(path)[1].lower()
        for k, v in (cfg.get('rules') or {}).items():
            if str(k).lower() == ext and v:
                return str(v)
        d = cfg.get('default_dir')
        return str(d) if d else None

    def move_file(self, src, dest_dir, mode='move'):
        """把 src 放进 dest_dir。同名自动加 " (2)"，**绝不覆盖**。
        返回落地路径；无需处理（不存在/已在目标目录/出错）返回 None。"""
        try:
            if not src or not os.path.isfile(src):
                return None
            dest_dir = os.path.abspath(str(dest_dir))
            # 已经在目标目录里：移动等于原地不动，交给上层算作"跳过"
            if os.path.abspath(os.path.dirname(src)) == dest_dir:
                return None
            os.makedirs(dest_dir, exist_ok=True)
            base = os.path.basename(src)
            stem, ext = os.path.splitext(base)
            dst = os.path.join(dest_dir, base)
            n = 2
            while os.path.exists(dst):
                dst = os.path.join(dest_dir, '%s (%d)%s' % (stem, n, ext))
                n += 1
                if n > 999:
                    return None
            if str(mode).lower() == 'copy':
                shutil.copy2(src, dst)
            else:
                shutil.move(src, dst)
            return dst
        except Exception:
            dbg_log('move_file 失败 %s → %s\n%s'
                    % (src, dest_dir, traceback.format_exc()))
            return None

    def route_files(self, paths, fly=None):
        """把一批文件分流到各自的目标目录。返回 (done, failed, skipped)。"""
        cfg = self.cfg.get('file_stash') or {}
        mode = 'copy' if str(cfg.get('mode', 'move')).lower() == 'copy' else 'move'
        done, failed, skipped = [], [], []
        for p in paths:
            dest = self.stash_target_for(p, fly)
            if not dest:
                skipped.append(p)
            elif not os.path.isfile(p):
                skipped.append(p)
            elif os.path.abspath(os.path.dirname(p)) == os.path.abspath(dest):
                skipped.append(p)          # 已经在那儿了
            else:
                out = self.move_file(p, dest, mode=mode)
                (done if out else failed).append(out or p)
        return done, failed, skipped

    def stash_files(self, paths, fly):
        """拖到虫身上松手：按要求收纳，并给出可见反馈"""
        done, failed, skipped = self.route_files(paths, fly)
        if done:
            self.spawn_fx(fly.x, fly.y, (150, 220, 255), life=1.1)
            self.spawn_fx(fly.x, fly.y, (255, 255, 255), life=0.8)
            self.say(fly, 'stash')
            self.announce = ('收纳 %d 个文件 → %s'
                             % (len(done), os.path.dirname(done[0])),
                             time.monotonic() + 5.0)
            fly.energy = min(E_MAX, fly.energy + 4.0)   # 干活给点奖励
        elif skipped:
            self.say(fly, 'stash_no')
            self.announce = ('%d 个文件没有收纳目录（托盘菜单 →「文件收纳」可指派）'
                             % len(skipped), time.monotonic() + 6.0)
        elif failed:
            self.announce = ('收纳失败，详见 _debug.log', time.monotonic() + 6.0)
        return done, failed, skipped

    def eat_files(self, paths, cr):
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [('hwnd', wintypes.HWND),
                            ('wFunc', wintypes.UINT),
                            ('pFrom', wintypes.LPCWSTR),
                            ('pTo', wintypes.LPCWSTR),
                            ('fFlags', wintypes.WORD),
                            ('fAnyOperationsAborted', wintypes.BOOL),
                            ('hNameMappings', ctypes.c_void_p),
                            ('lpszProgressTitle', wintypes.LPCWSTR)]

            FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT = 3, 0x40, 0x10, 0x4
            op = SHFILEOPSTRUCTW()
            op.hwnd = None
            op.wFunc = FO_DELETE
            op.pFrom = '\0'.join(paths) + '\0'
            op.pTo = None
            op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            if rc == 0 and not op.fAnyOperationsAborted:
                self.spawn_fx(cr.center().x(), cr.center().y(), (140, 230, 140), life=1.0)
                self.spawn_fx(cr.center().x(), cr.center().y(), (250, 220, 140), life=1.0)
                for fly in self.flies:
                    if fly.inCage:
                        fly.energy = min(E_MAX, fly.energy + 25)
                        fly.bubble = [pick(DEFAULT_SETTINGS['bubbles']['texts']['ate_file']),
                                      0.0, 2.8]
        except Exception:
            pass

    def feed(self, x=None, y=None):
        if x is None or y is None:
            m = QCursor.pos()
            x, y = float(m.x()), float(m.y())
        if self._dbg:
            self._dbg('feed() 调用，投放于 %d,%d' % (x, y))
        self.foods.append({'x': float(x), 'y': float(y), 'e': FOOD_E0})
        self.spawn_fx(x, y, (250, 220, 140))
        self.spawn_fx(x, y, (255, 255, 255))
        # 闻到新糖味的果蝇兴奋喊一嗓子
        for fly in self.flies:
            d = math.hypot(fly.x - x, fly.y - y)
            if d < FOOD_L * 2.2 and not fly.eating:
                fly.bubble = None
                self.say(fly, 'food_in')

    # ---------- 绘制 ----------
    def fly_label_text(self, fly):
        """种类标签文案（含传说/年老标记）。rect 与 paint 必须共用这一份，
        否则量宽度用的字符串和实际画的字符串不一致，标签框就会错位。"""
        name = self.skin_disp.get(fly.skin or self.skin_name)
        if not name:
            return None
        if fly.is_legendary():
            name = '✦ ' + name
        if fly.is_elder():
            name = name + ' · 老'
        return name

    def fly_label_rect(self, fly):
        """种类标签的矩形；不显示时返回 None（build_mask 与 paint 共用）"""
        if not self.cfg.get('show_labels', True) and fly.labelT <= 0:
            return None
        name = self.fly_label_text(fly)
        if not name:
            return None
        fm = QFontMetrics(QFont('Microsoft YaHei', 8))
        tw = fm.horizontalAdvance(name) + 10
        skin = self.skins.get(fly.skin or self.skin_name)
        ss = skin.get('size_scale', 1.0) if skin else 1.0
        sm = fly.size_factor()
        lx = clamp(fly.x - tw / 2, 4, self.w - tw - 4)
        ly = fly.y + 44 * self.cfg['scale'] * ss * sm + 8
        return QRect(int(lx), int(ly), tw, fm.height() + 5)

    def paintEvent(self, _ev):
        """同样：Qt 静默吞绘制异常，一次 KeyError 的代价是"整屏不见"。
        兜住并写日志，至少让故障可查（QPainter 是局部变量，异常退出时会自动 end()）。"""
        try:
            self._paint(_ev)
        except Exception:
            dbg_log('paint 异常\n' + traceback.format_exc())
            self._paint_errors = int(getattr(self, '_paint_errors', 0)) + 1

    def _paint(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 报警信息素云（世界级）
        for ph in self.pher:
            a = math.exp(-ph['age'] / PHER_TAU)
            rr = 18 + 26 * a
            g = QColor(255, 70, 90, int(60 * a))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(ph['x'], ph['y']), rr, rr)
        # 笼子
        cr = self.cage_rect()
        if cr is not None:
            self.draw_cage(p, cr)
        # 糖块
        for f in self.foods:
            self.draw_sugar(p, f)
        # 虫卵（等待孵化）
        for e in self.eggs:
            self.draw_egg(p, e)
        # 特效（char 类型 = 上升的字母粒子，如打盹的 z）
        for e in self.fx:
            life = e.get('life', 0.7)
            a = 1.0 - e['age'] / life
            if e.get('char'):
                p.setPen(QPen(QColor(*e['color'], int(220 * a)), 2))
                p.setFont(QFont('Segoe UI', 11))
                p.drawText(QPointF(e['x'], e['y'] - e['age'] * 16), e['char'])
            else:
                c = QColor(*e['color'], int(200 * a))
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                rr = 3 + 8 * a
                p.drawEllipse(QPointF(e['x'], e['y']), rr, rr)
        # 所有果蝇（每只可用专属皮肤+体型+基因色相，None=跟随全局）
        for fly in self.flies:
            skin = self.skins.get(fly.skin) or self.skins.get(self.skin_name)
            ss = skin.get('size_scale', 1.0) if skin else 1.0
            sm = fly.size_factor()
            # 传说个体：身后一层金色光晕（收集感的直观回报）
            # ★ 半径必须跟虫体一起被 cfg['scale']/皮肤体型缩放，且与
            # fly_paint_radius 里的算法一致 —— 否则窗口缩放调小后光晕
            # 比 mask 大，会被 setMask 静默裁成方角（实测 scale=0.70 外溢 1256 px）。
            if fly.is_legendary():
                aura = (20.0 + 22.0 * sm) * self.cfg['scale'] * ss
                pulse = 0.75 + 0.25 * math.sin(time.monotonic() * 2.2 + fly.castSeed)
                p.setPen(Qt.NoPen)
                for k, al in ((1.0, 26), (0.62, 46), (0.34, 74)):
                    p.setBrush(QColor(255, 214, 120, int(al * pulse)))
                    r = aura * k
                    p.drawEllipse(QPointF(fly.x, fly.y), r, r)
            p.save()
            p.translate(fly.x, fly.y)
            p.rotate(math.degrees(fly.dir))
            p.scale(self.cfg['scale'] * ss * sm, self.cfg['scale'] * ss * sm)
            if skin and skin['frames']:
                self.draw_skin(p, skin, fly)
            else:
                self.draw_procedural(p, fly)
            # 基因色相：给 sprite 叠一层色调（SourceAtop 只染已有像素，不糊背景）
            tint = fly.tint_color()
            if tint is not None:
                p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                p.setPen(Qt.NoPen)
                p.setBrush(tint)
                p.drawRect(QRectF(-30, -30, 60, 60))
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            # 年老：压一层灰（同样只作用于已有像素），老虫一眼能认出来
            if fly.is_elder():
                p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(190, 196, 205, int(96 * (1.0 - fly.vitality())
                                                      / max(1e-6, 1.0 - ELDER_MIN_VITALITY))))
                p.drawRect(QRectF(-30, -30, 60, 60))
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.restore()
        # 种类名称标签
        show_lbl = self.cfg.get('show_labels', True)
        for fly in self.flies:
            if not show_lbl and fly.labelT <= 0:
                continue
            rc = self.fly_label_rect(fly)
            if rc is None:
                continue
            name = self.fly_label_text(fly) or '果蝇'
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(18, 24, 32, 195))
            p.drawRoundedRect(rc, 4, 4)
            p.setPen(QColor(206, 228, 246, 240))
            p.setFont(QFont('Microsoft YaHei', 8))
            p.drawText(rc, Qt.AlignCenter, name)
        # 气泡
        for fly in self.flies:
            if fly.bubble:
                self.draw_bubble(p, fly)
        # 报时虫：头顶一块时钟牌（跟着虫走，像它举着的牌子）
        self.draw_clock_board(p)
        # 模式提示条：放置/捕捉模式下常驻屏幕顶部，避免"点了没反应"的错觉
        hint = None
        if getattr(self, 'pending_place', False):
            nm = self.skin_disp.get(self.pending_skin or '', '默认（跟随换肤）')
            hint = '放置模式 · %s · 点屏幕空白处放下（右键取消）' % nm
        elif getattr(self, 'capture_mode', False):
            hint = '捕捉模式 · 点一只虫就把它关进笼子（再选一次关闭）'
        if hint:
            p.setFont(QFont('Microsoft YaHei', 10))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(hint) + 28
            rx = (self.w - tw) / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(24, 34, 48, 225))
            p.drawRoundedRect(QRectF(rx, 14, tw, 32), 16, 16)
            p.setPen(QColor(150, 220, 190, 245))
            p.drawText(QRectF(rx, 14, tw, 32), Qt.AlignCenter, hint)
        # 文件拖到笼上：在笼子下方标出"松手就喂"，避免用户不确定能不能放
        if getattr(self, 'drag_hover', False):
            cr2 = self.cage_rect()
            if cr2 is not None:
                t = '松手 → 喂给果蝇（移入回收站，可还原）'
                p.setFont(QFont('Microsoft YaHei', 9))
                fm2 = p.fontMetrics()
                tw2 = fm2.horizontalAdvance(t) + 24
                bx = clamp(cr2.center().x() - tw2 / 2, 8, max(8, self.w - tw2 - 8))
                by = cr2.bottom() + 22
                if by > self.h - 40:
                    by = cr2.top() - 40
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(26, 60, 40, 235))
                p.drawRoundedRect(QRectF(bx, by, tw2, 28), 14, 14)
                p.setPen(QColor(150, 235, 185, 250))
                p.drawText(QRectF(bx, by, tw2, 28), Qt.AlignCenter, t)
        # 文件拖到某只虫身上：标出"松手收纳到哪"，并给目标虫套个高亮圈
        _df = getattr(self, 'drop_fly_hover', None)
        if _df is not None:
            tgt = self.stash_target_for('x.tmp', _df) or '（未指派目录）'
            hit = self.fly_hit_rect(_df)
            p.setPen(QPen(QColor(120, 200, 255, 230), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(_df.x, _df.y),
                          hit.width() / 2, hit.height() / 2)
            t = '松手 → 收纳到 %s' % tgt
            p.setFont(QFont('Microsoft YaHei', 9))
            fm3 = p.fontMetrics()
            tw3 = fm3.horizontalAdvance(t) + 24
            bx3 = clamp(_df.x - tw3 / 2, 8, max(8, self.w - tw3 - 8))
            by3 = clamp(hit.bottom() + 14, 8, max(8, self.h - 36))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(22, 44, 78, 236))
            p.drawRoundedRect(QRectF(bx3, by3, tw3, 28), 14, 14)
            p.setPen(QColor(168, 214, 255, 250))
            p.drawText(QRectF(bx3, by3, tw3, 28), Qt.AlignCenter, t)
        # 番茄钟：屏幕顶部中央显示剩余时间 + 进度条
        left = self.focus_left()
        if left is not None:
            mm, ss = divmod(int(left), 60)
            t = '专注中 · %02d:%02d' % (mm, ss)
            p.setFont(QFont('Microsoft YaHei', 10))
            fmb = p.fontMetrics()
            bw = fmb.horizontalAdvance(t) + 40
            bx = (self.w - bw) / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(22, 30, 44, 230))
            p.drawRoundedRect(QRectF(bx, 10, bw, 34), 17, 17)
            # 进度
            total = max(1, self.focus['mins'] * 60)
            frac = clamp(1.0 - left / total, 0.0, 1.0)
            p.setBrush(QColor(90, 200, 160, 90))
            p.drawRoundedRect(QRectF(bx + 4, 10 + 4, max(6, (bw - 8) * frac), 26), 13, 13)
            p.setPen(QColor(175, 240, 210, 250))
            p.drawText(QRectF(bx, 10, bw, 34), Qt.AlignCenter, t)
        p.end()

    def draw_egg(self, p, e):
        """虫卵：随孵化进度从白变深，会轻轻晃动；快孵化时冒裂纹"""
        prog = clamp(e['age'] / EGG_TIME, 0.0, 1.0)
        wob = math.sin(e['age'] * 4.0) * (1.0 - prog) * 2.0
        r = 7.5 + 2.2 * prog
        cx, cy = e['x'] + wob, e['y']
        p.setPen(Qt.NoPen)
        # 阴影
        p.setBrush(QColor(20, 26, 34, 90))
        p.drawEllipse(QRectF(cx - r * 1.1, cy + r * 0.55, r * 2.2, r * 0.7))
        # 蛋体：越接近孵化越偏米黄
        body = QColor(int(245 - 25 * prog), int(238 - 30 * prog), int(215 - 35 * prog))
        p.setBrush(body)
        p.setPen(QPen(QColor(150, 140, 120, 200), 1.0))
        p.drawEllipse(QRectF(cx - r * 0.78, cy - r, r * 1.56, r * 2.0))
        # 高光
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawEllipse(QRectF(cx - r * 0.42, cy - r * 0.62, r * 0.42, r * 0.55))
        # 快孵化了：裂缝
        if prog > 0.75:
            p.setPen(QPen(QColor(120, 110, 95, 210), 1.0))
            for k in range(3):
                yy = cy - r * 0.3 + k * r * 0.45
                p.drawLine(QPointF(cx - r * 0.5, yy),
                           QPointF(cx - r * 0.05, yy + r * 0.22))
                p.drawLine(QPointF(cx - r * 0.05, yy + r * 0.22),
                           QPointF(cx + r * 0.42, yy - r * 0.05))

    def draw_sugar(self, p, f):
        # 用 .get 取能量：paintEvent 里的异常会被 Qt 静默吞掉，
        # 一处 KeyError 代价是"整屏空白"而不只是少画一块糖，不值得为省一个 .get 冒险
        er = clamp(f.get('e', FOOD_E0) / FOOD_E0, 0.15, 1.0)
        s = 9.0 + 9.0 * er
        p.setPen(QPen(QColor('#b8862e'), 1.4))
        p.setBrush(QColor('#f2cd72'))
        p.drawRoundedRect(QRectF(f['x'] - s, f['y'] - s * 0.72, s * 2, s * 1.44), 3.5, 3.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 130))
        p.drawRoundedRect(QRectF(f['x'] - s * 0.55, f['y'] - s * 0.5, s * 0.7, s * 0.4), 2, 2)

    def draw_cage(self, p, cr):
        p.setRenderHint(QPainter.Antialiasing)
        # 高亮条件：① 有虫被抓着悬在笼上（松手就关进去）
        #           ② 文件正拖在笼上（松手就喂掉）
        hit_r = self.cage_hit_rect() or cr
        hover = getattr(self, 'drag_hover', False) or \
            any(f.grabbed and hit_r.contains(QPoint(int(f.x), int(f.y)))
                for f in self.flies)
        bar_c = QColor(126, 220, 160, 240) if hover else QColor(154, 167, 181, 230)
        if hover:
            # 外发光：明确告诉用户"现在是有效目标"
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(126, 220, 160, 46))
            p.drawRoundedRect(cr.adjusted(-7, -7, 7, 7), 13, 13)
        # 笼身（半透明暗底 + 竖栏杆）
        p.setPen(QPen(bar_c, 3))
        p.setBrush(QColor(28, 34, 44, 120))
        p.drawRoundedRect(cr, 10, 10)
        p.setPen(QPen(QColor(154, 167, 181, 150), 2))
        for k in range(1, 5):
            x = cr.left() + cr.width() * k // 5
            p.drawLine(x, cr.top() + 5, x, cr.bottom() - 12)
        # 底座
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(74, 85, 104, 230))
        p.drawRoundedRect(QRect(cr.left() - 6, cr.bottom() - 14,
                                cr.width() + 12, 16), 4, 4)
        # 锁指示（右上角橙点 = 锁定）
        if self.cage.get('locked'):
            p.setBrush(QColor('#e26a2a'))
            p.drawEllipse(QRect(cr.right() - 22, cr.top() - 9, 15, 15))
        else:
            p.setBrush(QColor('#4fae5c'))
            p.drawEllipse(QRect(cr.right() - 22, cr.top() - 9, 15, 15))

    def draw_skin(self, p, skin, fly):
        n = len(skin['frames'])
        if skin['fps'] > 0:
            fly.skinT = getattr(fly, 'skinT', random.random() * 10.0) \
                + (16.0 + fly.speed * 0.12) / 1000.0 * skin['fps']
            idx = int(fly.skinT) % n
        else:
            idx = 0
        pm = skin['frames'][idx]
        if skin.get('facing') == 'up':
            p.rotate(90.0)
        size = skin.get('size', 56)
        p.drawPixmap(QRectF(-size / 2, -size / 2, size, size), pm, QRectF(pm.rect()))

    def draw_procedural(self, p, fly):
        flap = math.sin(fly.wingPhase)
        # 腿
        p.setPen(QPen(QColor(45, 45, 54), 1.0))
        for s in (-1, 1):
            for k, base in enumerate((-0.45, 0.05, 0.55)):
                a = base + math.sin(fly.age * 11 + k) * 0.12
                x0, y0 = 2 + k * 2 - 4, s * 3.5
                x1 = x0 + math.cos(a) * 7
                y1 = y0 + s * abs(math.sin(a)) * 7
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        # 翅膀
        for s in (-1, 1):
            p.save()
            p.translate(3, s * 2.5)
            p.rotate(s * (-24 + flap * 26))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(205, 224, 255, 105))
            p.drawEllipse(QRectF(-15, -3.2, 17, 6.4))
            p.restore()
        # 腹部
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#26262e'))
        p.drawEllipse(QRectF(-16, -5.5, 19, 11))
        p.setBrush(QColor('#3d3d4a'))
        p.drawEllipse(QRectF(-9.5, -5.0, 5.5, 10))
        p.drawEllipse(QRectF(-14.5, -5.2, 4.5, 10.4))
        # 胸
        p.setBrush(QColor('#35353f'))
        p.drawEllipse(QRectF(0, -5, 11, 10))
        # 头
        p.setBrush(QColor('#2a2a33'))
        p.drawEllipse(QRectF(9, -4, 8.4, 8))
        # 复眼
        p.setBrush(QColor('#8e2432'))
        p.drawEllipse(QRectF(12.4, -4.6, 5.4, 5.0))
        p.drawEllipse(QRectF(12.4, -0.4, 5.4, 5.0))
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawEllipse(QRectF(14.6, -3.6, 1.6, 1.6))
        p.drawEllipse(QRectF(14.6, 0.2, 1.6, 1.6))
        # 取食喙
        if fly.eating:
            p.setPen(QPen(QColor('#c9a05a'), 1.6))
            p.drawLine(QPointF(16, 0), QPointF(21, 0))

    def draw_bubble(self, p, fly):
        # 几何全部来自 bubble_rect —— 与 build_mask 共用，避免"画得到但被 mask 裁掉"
        br = self.bubble_rect(fly)
        if br is None:
            return
        text = fly.bubble[0]
        alpha = clamp(fly.bubble[2] / 0.4, 0.0, 1.0)
        p.setFont(QFont('Microsoft YaHei', 9))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 30, 40, int(225 * alpha)))
        p.drawRoundedRect(br, 8, 8)
        # 尾巴：底边两个点 + 下方一个尖，组成真正的三角形。
        # 原来三个点全在 y = by+th 上 → 零面积，只画出一条 12px 横线
        # （纯横向、不指向虫，看着像渲染瑕疵）。
        bx, by, tw, th = br.x(), br.y(), br.width(), br.height()
        apex = clamp(fly.x, bx + 10, bx + tw - 10)
        p.drawPolygon(QPolygonFp(
            QPointF(apex - 6, by + th - 1),
            QPointF(apex + 6, by + th - 1),
            QPointF(apex, by + th + 7)))
        p.setPen(QColor(235, 240, 248, int(255 * alpha)))
        p.drawText(br, Qt.AlignCenter, text)

    # ---------- 存档（v4：+寿命基因/谱系编号；原子写 + .bak 兜底）----------
    def save(self):
        try:
            pl_idx = [e for e in range(NET['E']) if NET['PL'][e]]
            data = {
                'version': 4,
                'foods': self.foods,
                'cage': self.cage,
                'eggs': self.eggs,
                'codex': self.codex,
                'lineage': self.lineage,
                'next_fid': self.next_fid,
                'flies': [{
                    'energy': fly.energy,
                    'x': fly.x, 'y': fly.y, 'dir': fly.dir,
                    'skin': fly.skin,
                    'gene': fly.gene,
                    'age': fly.age,
                    'fid': getattr(fly, 'fid', 0),
                    'parents': list(getattr(fly, 'parents', ()) or ()),
                    'size_mult': getattr(fly, 'size_mult', 1.0),
                    'weights': [fly.brain.w[e] for e in pl_idx],
                    'markers': fly.markers,
                } for fly in self.flies],
            }
            tmp = SAVE_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            # 原子轮换：旧档留作 .bak（主档损坏时可回退）
            try:
                if os.path.isfile(SAVE_PATH):
                    os.replace(SAVE_PATH, SAVE_PATH + '.bak')
            except OSError:
                pass
            os.replace(tmp, SAVE_PATH)
            self._save_err_said = False
        except Exception:
            # 存档失败绝不能静默：那意味着"这一局的繁殖/图鉴白玩"
            dbg_log('save 失败\n' + traceback.format_exc())
            if not getattr(self, '_save_err_said', False):
                self._save_err_said = True
                self.announce = ('存档写入失败（详见 _debug.log）',
                                 time.monotonic() + 8.0)

    @staticmethod
    def _read_json(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def load(self):
        data = self._read_json(SAVE_PATH)
        if data is None:
            data = self._read_json(SAVE_PATH + '.bak')
        if not isinstance(data, dict):
            return
        self.foods = [f for f in data.get('foods', []) if isinstance(f, dict)]
        # 虫卵 + 图鉴（v3 起保存）
        if isinstance(data.get('eggs'), list):
            self.eggs = [e for e in data['eggs'] if isinstance(e, dict)
                         and 'gene' in e][:24]
        cd = data.get('codex')
        if isinstance(cd, dict):
            self.codex = {
                'species': {k: int(v) for k, v in (cd.get('species') or {}).items()},
                'best_gen': int(cd.get('best_gen', 0)),
                'hatched': int(cd.get('hatched', 0)),
                'grades': {k: int(v) for k, v in (cd.get('grades') or {}).items()},
            }
            for k in ('普通', '优良', '稀有', '传说'):
                self.codex['grades'].setdefault(k, 0)
        # 谱系（v4 起）：读回编号发号器与最近诞生记录
        lin = data.get('lineage')
        if isinstance(lin, list):
            self.lineage = [r for r in lin if isinstance(r, dict)][-LINEAGE_KEEP:]
        nf_id = data.get('next_fid')
        if isinstance(nf_id, int) and nf_id > 0:
            self.next_fid = nf_id
        c = data.get('cage')
        if isinstance(c, dict) and all(k in c for k in ('x', 'y')):
            self.cage = {'x': float(c['x']), 'y': float(c['y']),
                         'locked': bool(c.get('locked', True))}
        else:
            self.cage = None
        pl_idx = [e for e in range(NET['E']) if NET['PL'][e]]
        # v2 多只；v1 单只 → 兼容成列表
        fly_list = data.get('flies') if isinstance(data.get('flies'), list) \
            else [data] if 'energy' in data else []
        for i, fd in enumerate(fly_list):
            if not isinstance(fd, dict):
                continue
            if i < len(self.flies):
                fly = self.flies[i]
            elif len(self.flies) < self.cfg.get('max_flies', 12):
                fly = self.register_fly(PetFly(self.w * 0.5, self.h * 0.45))
                self.flies.append(fly)
            else:
                break
            fly.energy = clamp(float(fd.get('energy', E_START)), DESP_AT * 0.5, E_MAX)
            fly.x = clamp(float(fd.get('x', fly.x)), 2, self.w - 2)
            fly.y = clamp(float(fd.get('y', fly.y)), 2, self.h - 2)
            fly.dir = float(fd.get('dir', fly.dir))
            fly.skin = fd.get('skin') or None
            # 基因（v3 起）：旧档没有就现场生成一份，保证老存档也能继续玩
            g = fd.get('gene')
            fly.gene = g if isinstance(g, dict) and 'spd' in g else new_gene()
            for k in ('spd', 'siz', 'bold', 'hue'):
                fly.gene.setdefault(k, 1.0 if k != 'bold' and k != 'hue' else 0.5)
            # 生活史基因（v4 起）：旧档没有 → 一律按标准个体 1.0，行为不变
            for k in GENE_LIFE_KEYS:
                try:
                    fly.gene[k] = clamp(float(fly.gene.get(k, 1.0)), *GENE_CLAMP)
                except (TypeError, ValueError):
                    fly.gene[k] = 1.0
            fly.gene['gen'] = int(fly.gene.get('gen', 1))
            fly.age = float(fd.get('age', 30.0))
            fly.lifespan = BASE_LIFESPAN * fly.gene.get('lon', 1.0)
            fly.size_mult = float(fd.get('size_mult', 1.0))
            # 谱系编号：旧档没有就用发号器补一个（不能留 0，否则图鉴里一排 #0）
            fid = fd.get('fid')
            if isinstance(fid, int) and fid > 0:
                fly.fid = fid
                self.next_fid = max(int(self.next_fid), fid + 1)
            elif not getattr(fly, 'fid', 0):
                # 新虫在构造时已由 register_fly 发过号，这里不能再发一次（会跳号）
                fly.fid = int(self.next_fid)
                self.next_fid = int(self.next_fid) + 1
            pr = fd.get('parents')
            fly.parents = tuple(int(p) for p in pr if isinstance(p, int) and p > 0) \
                if isinstance(pr, list) else ()
            for e, w in zip(pl_idx, fd.get('weights', [])):
                try:
                    fly.brain.w[e] = float(w)
                except Exception:
                    pass
            fly.markers = [m for m in fd.get('markers', []) if isinstance(m, dict)]


def QPolygonFp(*points):
    from PySide6.QtGui import QPolygonF
    poly = QPolygonF()
    for pt in points:
        poly.append(pt)
    return poly


# ----------------------------- 主程序 -----------------------------
def main():
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('FlyPet')

    # 自检模式（FLYPET_SELFTEST=menu）：把配置与存档指到临时目录，
    # 免得自检把交付目录的 settings.json / 存档写花，也免得跟正在运行的实例
    # 抢同一把单实例锁。详见文件末尾的菜单自检块。
    # 注意：selftest_mode 保留原始取值，selftest 是"是否处于自检"的布尔。
    # 别拿布尔去跟 'menu' 比（`True == 'menu'` 恒为 False，会把点击分支整块跳过）。
    selftest_mode = os.environ.get('FLYPET_SELFTEST', '')
    selftest = selftest_mode in ('menu', 'inventory')
    if selftest:
        global SETTINGS_PATH, SAVE_PATH
        _td = tempfile.mkdtemp(prefix='flypet_selftest_')
        SETTINGS_PATH = os.path.join(_td, 'settings.json')
        SAVE_PATH = os.path.join(_td, 'pet.json')

    # 单实例锁：防止两个 FlyPet 抢同一份存档
    if not selftest and hasattr(ctypes, 'windll'):
        ctypes.windll.kernel32.CreateMutexW(None, False, 'FlyPet_SingleInstance_Mutex')
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)

    cfg = load_settings()
    # 回写完整配置：settings.json 必须是"照着改就能用"的完整模板
    sync_settings_file(cfg)
    win = Overlay(cfg)

    # 托盘
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    tp = QPainter(pm)
    tp.setRenderHint(QPainter.Antialiasing)
    tp.setPen(Qt.NoPen)
    tp.setBrush(QColor('#3a3a46'))
    tp.drawEllipse(6, 12, 20, 10)
    tp.setBrush(QColor('#8e2432'))
    tp.drawEllipse(20, 11, 8, 8)
    tp.setBrush(QColor(205, 224, 255, 170))
    tp.save()
    tp.translate(12, 12)
    tp.rotate(-28)
    tp.drawEllipse(-2, -12, 5, 13)
    tp.drawEllipse(-9, -12, 5, 13)
    tp.restore()
    tp.end()
    icon = QIcon(pm)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip('FlyPet · 连接组脑桌宠')
    menu = QMenu()

    act_feed = QAction('投喂糖块 · 鼠标处 (%s)' % cfg['feed_hotkey'].upper(), menu)
    act_feed.triggered.connect(win.feed)
    menu.addAction(act_feed)

    menu.addSeparator()
    # ---- 开关型状态：勾选状态与 settings.json 同步 ----
    act_pause = QAction('暂停（冻住不动）', menu)
    act_pause.setCheckable(True)
    act_pause.setChecked(bool(cfg.get('paused')))
    act_pause.setToolTip('虫不动、不饿、不繁殖；已设的提醒和番茄钟照常计时')

    def toggle_pause(checked):
        win.cfg['paused'] = bool(checked)
        persist_settings(win.cfg)
        win.announce = ('已暂停 · 虫都停住了（提醒照常）' if checked
                        else '继续飞了',
                        time.monotonic() + 4.0)

    act_pause.toggled.connect(toggle_pause)
    menu.addAction(act_pause)

    act_quiet = QAction('安静模式（不闲聊）', menu)
    act_quiet.setCheckable(True)
    act_quiet.setChecked(bool(cfg.get('quiet')))
    act_quiet.setToolTip('屏蔽饿/社交/打盹等日常气泡；投喂、收纳等操作反馈照常')

    def toggle_quiet(checked):
        win.cfg['quiet'] = bool(checked)
        persist_settings(win.cfg)

    act_quiet.toggled.connect(toggle_quiet)
    menu.addAction(act_quiet)

    act_set = QAction('设置…', menu)
    act_set.setToolTip('图形化改所有设置（也能打开 settings.json 手改）')

    def open_settings():
        skins = [(n, win.skin_disp.get(n, n)) for n in sorted(win.skins)]
        dlg = SettingsDialog(win.cfg, dyn_opts={'skin': skins})
        if dlg.exec() != QDialog.Accepted:
            return                      # 取消：cfg 一点没动
        changed = list(dlg.saved or [])
        if not changed:
            return
        persist_settings(win.cfg)
        win.on_settings_changed(changed)
        refresh_menu_state()
        if 'feed_hotkey' in changed:
            tray.showMessage('FlyPet', '投喂快捷键需要重启后才能生效',
                             QSystemTrayIcon.Information, 5000)

    act_set.triggered.connect(open_settings)
    menu.addAction(act_set)

    menu.addSeparator()
    pop_menu = menu.addMenu('数量（%d 只）' % len(win.flies))
    pop_actions = []

    def set_count(n):
        n = max(1, min(int(n), int(win.cfg.get('max_flies', 12))))
        while len(win.flies) < n:
            win.flies.append(win.register_fly(PetFly(
                random.uniform(80, win.w - 80), random.uniform(80, win.h - 80))))
        while len(win.flies) > n:
            win.flies.pop()
        pop_menu.setTitle('数量（%d 只）' % len(win.flies))
        for i, a in enumerate(pop_actions):
            a.setChecked(i + 1 == len(win.flies))
        win.cfg['count'] = len(win.flies)
        persist_settings(win.cfg)

    for i in range(1, int(win.cfg.get('max_flies', 12)) + 1):
        a = QAction('%d 只' % i, pop_menu)
        a.setCheckable(True)
        a.setChecked(i == len(win.flies))
        a.triggered.connect(lambda checked=False, n=i: set_count(n))
        pop_menu.addAction(a)
        pop_actions.append(a)

    menu.addSeparator()
    skin_menu = menu.addMenu('皮肤')
    skin_group = []

    def make_skin_action(name, display):
        a = QAction(display, skin_menu)
        a.setCheckable(True)
        a.setChecked(win.skin_name == name)
        # 名字存在 action 自己身上：刷新勾选时不用再维护一份"并行列表"。
        # （原来 set_skin 里写的是 `for a, n in skin_group`，而这里 append 的是裸
        #  QAction —— 一改皮肤就抛 TypeError，被 Qt 静默吞掉，结果是"皮肤换了但
        #  没存进 settings.json，重启又变回去"。）
        a.setProperty('skin_name', name)
        # 菜单项缩略图：皮肤第 0 帧
        sk = win.skins.get(name)
        if sk and sk['frames']:
            try:
                a.setIcon(QIcon(sk['frames'][0].scaled(
                    28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            except Exception:
                pass
        a.triggered.connect(lambda checked=False, n=name: set_skin(n))
        skin_menu.addAction(a)
        skin_group.append(a)

    def set_skin(name):
        win.skin_name = name
        win.skin_frame = 0.0
        for a in skin_group:
            a.setChecked(a.property('skin_name') == name)
        win.cfg['skin'] = name
        persist_settings(win.cfg)

    disp = {'_procedural': '程序绘制（默认）'}
    try:
        with open(os.path.join(BUNDLE, 'skins', 'names.json'), 'r', encoding='utf-8') as f:
            disp.update(json.load(f))
    except Exception:
        pass
    make_skin_action('_procedural', disp['_procedural'])
    for name in win.skins:
        if name != '_procedural':
            make_skin_action(name, disp.get(name, name))

    def refresh_menu_state():
        """设置面板改过东西之后，把托盘菜单的勾选状态同步回来。
        不同步的话会出现"面板里改了 9 只，菜单还勾着 2 只"这种自相矛盾的界面。"""
        pop_menu.setTitle('数量（%d 只）' % len(win.flies))
        for i, a in enumerate(pop_actions):
            a.setChecked(i + 1 == len(win.flies))
        for a in skin_group:
            a.setChecked(a.property('skin_name') == win.skin_name)
        # blockSignals：这里是"照着 cfg 刷显示"，不该反过来再触发一次 toggle 写盘
        for act, key in ((act_pause, 'paused'), (act_quiet, 'quiet')):
            act.blockSignals(True)
            act.setChecked(bool(win.cfg.get(key)))
            act.blockSignals(False)

    menu.addSeparator()
    panel = BrainPanel(win)
    panel.hide()
    act_panel = QAction('脑活动面板', menu)
    act_panel.setCheckable(True)
    act_panel.toggled.connect(lambda on: panel.setVisible(on))
    menu.addAction(act_panel)

    act_reset = QAction('清除记忆（全部）', menu)
    act_reset.setProperty('selftest_skip', '破坏性（会清空所有记忆）')
    act_reset.triggered.connect(lambda: [fly.clear_memory() for fly in win.flies])
    menu.addAction(act_reset)

    act_auto = QAction('开机自启', menu)
    act_auto.setProperty('selftest_skip', '会写注册表')
    act_auto.setCheckable(True)
    act_auto.setChecked(autostart_enabled())
    act_auto.toggled.connect(lambda on: set_autostart(on))
    menu.addAction(act_auto)

    menu.addSeparator()

    # ---------- 放置虫子 / 种类标签 ----------
    def pick_place(name):
        win.pending_skin = name
        win.pending_place = True
        win.apply_mode_mask()   # 立刻开放全屏，否则第一次点击被穿透
        disp = win.skin_disp.get(name, '默认（跟随换肤）')
        tray.showMessage('FlyPet 放置模式',
                         '点击屏幕空白处放置：%s' % disp,
                         QSystemTrayIcon.Information, 2500)

    pop_place = QMenu('放置虫子（点击画布）', menu)
    a_def = QAction('默认（跟随换肤）', pop_place)
    a_def.triggered.connect(lambda: pick_place(None))
    pop_place.addAction(a_def)
    for name in win.skins:
        if name == '_procedural':
            continue
        a = QAction(win.skin_disp.get(name, name), pop_place)
        a.triggered.connect(lambda checked=False, n=name: pick_place(n))
        pop_place.addAction(a)
    menu.addMenu(pop_place)

    pop_psize = QMenu('放置尺寸', menu)

    def pick_size(mult):
        win.pending_size = mult
        tray.showMessage('FlyPet 放置尺寸',
                         '下次放置：%s' % {0.7: '小', 1.0: '中', 1.5: '大'}.get(mult, '?'),
                         QSystemTrayIcon.Information, 2000)
    for mult, label in [(0.7, '小（0.7x）'), (1.0, '中（1.0x）'), (1.5, '大（1.5x）')]:
        a = QAction(label, pop_psize)
        a.setCheckable(True)
        a.setChecked(abs(win.pending_size - mult) < 0.01)
        a.triggered.connect(lambda checked=False, m_=mult: pick_size(m_))
        pop_psize.addAction(a)
    menu.addMenu(pop_psize)

    act_lbl = QAction('常显种类标签', menu)
    act_lbl.setCheckable(True)
    act_lbl.setChecked(bool(win.cfg.get('show_labels', True)))
    act_lbl.toggled.connect(lambda on: (win.cfg.__setitem__('show_labels', on),
                                        persist_settings(win.cfg)))
    menu.addAction(act_lbl)

    # ---------- 图鉴（遗传收集）----------
    def show_codex():
        QMessageBox.information(None, 'FlyPet 图鉴', win.codex_text())

    act_codex = QAction('图鉴（遗传与收集）', menu)
    act_codex.setProperty('selftest_skip', '会弹模态框（自检会卡住）')
    act_codex.triggered.connect(show_codex)
    menu.addAction(act_codex)

    def show_fly_detail():
        """看离鼠标最近那只虫的基因卡片（七维 + 世代 + 年龄 + 亲代）"""
        if not win.flies:
            QMessageBox.information(None, 'FlyPet 基因详情', '屏幕上还没有虫。')
            return
        mc = QCursor.pos()
        fly, _d = win._nearest_fly(mc.x(), mc.y())
        if fly is None:
            fly = win.flies[0]
        QMessageBox.information(None, 'FlyPet 基因详情', win.fly_detail_text(fly))

    act_detail = QAction('查看最近的虫（基因详情）', menu)
    act_detail.setProperty('selftest_skip', '会弹模态框（自检会卡住）')
    act_detail.triggered.connect(show_fly_detail)
    menu.addAction(act_detail)

    # ---------- 文件收纳（拖到虫身上 = 移动到指定文件夹）----------
    pop_stash = QMenu('文件收纳（把文件拖到虫身上）', menu)

    def _save_cfg():
        persist_settings(win.cfg)

    def nearest_fly_now():
        if not win.flies:
            return None
        mc = QCursor.pos()
        f, _d = win._nearest_fly(mc.x(), mc.y())
        return f or win.flies[0]

    def assign_stash():
        f = nearest_fly_now()
        if f is None:
            QMessageBox.information(None, '文件收纳', '屏幕上还没有虫。')
            return
        d = QFileDialog.getExistingDirectory(
            None, '把「#%d %s」的收纳目录设为：' % (f.fid, f.skin or win.skin_name))
        if not d:
            return
        win.cfg.setdefault('fly_stash', {})[str(f.fid)] = d
        _save_cfg()
        win.announce = ('#%d 的收纳目录已设为 %s' % (f.fid, d),
                        time.monotonic() + 5.0)
        tray.showMessage('文件收纳', '#%d 现在负责收纳到：\n%s' % (f.fid, d),
                         QSystemTrayIcon.Information, 4000)

    a_assign = QAction('给最近的虫指派收纳目录…', pop_stash)
    a_assign.triggered.connect(assign_stash)
    pop_stash.addAction(a_assign)

    def clear_stash():
        win.cfg['fly_stash'] = {}
        _save_cfg()
        tray.showMessage('文件收纳', '已清除所有单虫指派（改用规则/兜底目录）',
                         QSystemTrayIcon.Information, 3000)

    a_clear = QAction('清除所有指派', pop_stash)
    a_clear.triggered.connect(clear_stash)
    pop_stash.addAction(a_clear)

    def set_default_dir():
        d = QFileDialog.getExistingDirectory(None, '兜底收纳目录（没匹配规则就放这）')
        if not d:
            return
        win.cfg.setdefault('file_stash', {})['default_dir'] = d
        _save_cfg()
        tray.showMessage('文件收纳', '兜底目录：\n%s' % d,
                         QSystemTrayIcon.Information, 3500)

    a_defdir = QAction('设置兜底目录…', pop_stash)
    a_defdir.triggered.connect(set_default_dir)
    pop_stash.addAction(a_defdir)

    def show_rules():
        fs = win.cfg.get('file_stash') or {}
        st = win.cfg.get('fly_stash') or {}
        lines = ['当前收纳状态', '']
        lines.append('开关：%s    方式：%s' % (
            '已启用' if fs.get('enabled', True) else '已关闭',
            '复制' if str(fs.get('mode', 'move')).lower() == 'copy' else '移动'))
        lines.append('兜底目录：%s' % (fs.get('default_dir') or '（未设置）'))
        lines.append('')
        lines.append('单虫指派：')
        if st:
            for fid, d in st.items():
                lines.append('  #%s → %s' % (fid, d))
        else:
            lines.append('  （无）')
        lines.append('')
        lines.append('扩展名规则（在 settings.json 里改 file_stash.rules）：')
        rules = fs.get('rules') or {}
        if rules:
            for k, v in rules.items():
                lines.append('  %s → %s' % (k, v))
        else:
            lines.append('  （无）示例：{".png": "D:/图片", ".pdf": "D:/文档"}')
        lines.append('')
        lines.append('匹配顺序：该虫专属目录 → 扩展名规则 → 兜底目录')
        lines.append('三者都没有 → 不做任何事（绝不会把文件删掉）')
        QMessageBox.information(None, 'FlyPet 文件收纳', '\n'.join(lines))

    a_rules = QAction('查看当前规则', pop_stash)
    a_rules.setProperty('selftest_skip', '会弹模态框（自检会卡住）')
    a_rules.triggered.connect(show_rules)
    pop_stash.addAction(a_rules)

    act_stash = QAction('启用文件收纳', pop_stash)
    act_stash.setCheckable(True)
    act_stash.setChecked(bool((win.cfg.get('file_stash') or {}).get('enabled', True)))

    def _stash_toggled(on):
        win.cfg.setdefault('file_stash', {})['enabled'] = on
        _save_cfg()
    act_stash.toggled.connect(_stash_toggled)
    pop_stash.addAction(act_stash)
    menu.addMenu(pop_stash)

    # ---------- 报时虫 ----------
    pop_clock = QMenu('报时虫（头顶顶时钟）', menu)

    def set_clock(fly):
        win.clock_fid = int(getattr(fly, 'fid', 0)) if fly else 0
        win.cfg.setdefault('clock', {})['fid'] = win.clock_fid
        _save_cfg()
        if fly:
            tray.showMessage('报时虫', '#%d 开始报时（会守在右下角）' % win.clock_fid,
                             QSystemTrayIcon.Information, 3000)
            win.announce = ('#%d 开始报时' % win.clock_fid, time.monotonic() + 4.0)
        else:
            tray.showMessage('报时虫', '已关闭报时', QSystemTrayIcon.Information, 2500)

    a_cclose = QAction('关闭', pop_clock)
    a_cclose.triggered.connect(lambda: set_clock(None))
    pop_clock.addAction(a_cclose)
    a_cnear = QAction('让最近的虫报时', pop_clock)
    a_cnear.triggered.connect(lambda: set_clock(nearest_fly_now()))
    pop_clock.addAction(a_cnear)

    def rotate_clock():
        if not win.flies:
            return
        cur = win.clock_fly()
        i = win.flies.index(cur) if cur in win.flies else -1
        set_clock(win.flies[(i + 1) % len(win.flies)])

    a_crot = QAction('换一只', pop_clock)
    a_crot.triggered.connect(rotate_clock)
    pop_clock.addAction(a_crot)

    def edit_todos():
        cur = '\n'.join((win.cfg.get('clock') or {}).get('todos') or [])
        text, ok = QInputDialog.getMultiLineText(
            None, '待办清单', '每行一条，会轮流显示在报时牌上：', cur)
        if not ok:
            return
        win.cfg.setdefault('clock', {})['todos'] = [
            ln.strip() for ln in text.splitlines() if ln.strip()]
        _save_cfg()

    a_ctodo = QAction('待办清单…', pop_clock)
    a_ctodo.triggered.connect(edit_todos)
    pop_clock.addAction(a_ctodo)
    menu.addMenu(pop_clock)

    # ---------- 多显示器 ----------
    act_allscreen = QAction('覆盖所有显示器', menu)
    act_allscreen.setCheckable(True)
    act_allscreen.setChecked(str(win.cfg.get('screen_mode', 'primary')).lower() == 'all')

    def _allscreen_toggled(on):
        win.cfg['screen_mode'] = 'all' if on else 'primary'
        _save_cfg()
        win.apply_screen_geometry(win.cfg['screen_mode'])
        win.apply_mode_mask()

    act_allscreen.toggled.connect(_allscreen_toggled)
    menu.addAction(act_allscreen)

    menu.addSeparator()

    # ---------- 番茄钟 / 剪贴板 / 系统监视 / 边缘行为 ----------
    pop_focus = QMenu('番茄钟（专注）', menu)

    def begin_focus(mins):
        win.start_focus(mins)
        tray.showMessage('FlyPet 番茄钟',
                         '专注 %d 分钟：果蝇会躲到角落安静趴着，到点集体来喊你' % mins,
                         QSystemTrayIcon.Information, 4000)

    for mins in (15, 25, 45):
        a = QAction('%d 分钟' % mins, pop_focus)
        a.triggered.connect(lambda checked=False, m_=mins: begin_focus(m_))
        pop_focus.addAction(a)
    a_fcustom = QAction('自定义…', pop_focus)
    a_fcustom.triggered.connect(
        lambda: (lambda r: begin_focus(r[0]) if r[1] else None)(
            QInputDialog.getInt(None, '番茄钟', '专注多少分钟？',
                               int(win.cfg.get('pomodoro_min', 25)), 1, 240)))
    pop_focus.addAction(a_fcustom)
    a_fstop = QAction('结束专注', pop_focus)
    a_fstop.triggered.connect(lambda: win.stop_focus(silent=True))
    pop_focus.addAction(a_fstop)
    menu.addMenu(pop_focus)

    act_clip = QAction('剪贴板小助手（复制的文字让虫子叼给你看）', menu)
    act_clip.setCheckable(True)
    act_clip.setChecked(bool(getattr(win, 'clipboard_on', False)))

    def _clip_toggled(on):
        win.clipboard_on = on
        if on:
            win.last_clip = ''
            tray.showMessage('FlyPet 剪贴板助手',
                             '已开启：复制一段文字，会有虫子叼过来显示',
                             QSystemTrayIcon.Information, 3000)
    act_clip.toggled.connect(_clip_toggled)
    menu.addAction(act_clip)

    act_sys = QAction('系统状态监视（内存吃紧时会发蔫）', menu)
    act_sys.setCheckable(True)
    act_sys.setChecked(bool(getattr(win, 'sysmon_on', True)))
    act_sys.toggled.connect(lambda on: setattr(win, 'sysmon_on', on))
    menu.addAction(act_sys)

    act_edge = QAction('屏幕边缘行为（空闲时贴边爬）', menu)
    act_edge.setCheckable(True)
    act_edge.setChecked(bool(getattr(win, 'edge_behavior', True)))
    act_edge.toggled.connect(lambda on: setattr(win, 'edge_behavior', on))
    menu.addAction(act_edge)

    menu.addSeparator()

    # ---------- 笼子 / 捕捉 / 定时提醒 ----------
    def toggle_cage():
        if win.cage is None:
            win.cage = {'x': win.w / 2, 'y': win.h * 0.42,
                        'w': CAGE_W, 'h': CAGE_H, 'locked': True}
            act_cage.setText('收起笼子')
        else:
            win.cage = None
            for fly in win.flies:
                fly.inCage = False
            act_cage.setText('放笼子（文件拖进笼=喂掉）')

    act_cage = QAction('放笼子（文件拖进笼=喂掉）', menu)
    act_cage.triggered.connect(lambda: toggle_cage())
    menu.addAction(act_cage)

    act_cap = QAction('捕捉模式（点谁谁进笼）', menu)
    act_cap.setCheckable(True)

    def _cap_toggled(on):
        win.capture_mode = on
        win.apply_mode_mask()   # 同上：立刻放开全屏才能点到任意位置的虫

    act_cap.toggled.connect(_cap_toggled)
    # 画布上右键取消时，把托盘勾选状态同步回来
    win.capture_mode_act = act_cap
    menu.addAction(act_cap)

    pop_rem = QMenu('定时提醒', menu)

    def ask_reminder(mins=None):
        if mins is None:
            mins, ok = QInputDialog.getInt(None, '定时提醒', '多少分钟后提醒？', 10, 1, 720)
            if not ok:
                return
        text, ok = QInputDialog.getText(None, '定时提醒',
                                        '%d 分钟后提醒什么？' % mins)
        if not ok or not text.strip():
            return
        win.reminders.append({'at': time.monotonic() + mins * 60,
                              'text': text.strip()})
        tray.showMessage('FlyPet 定时提醒',
                         '%d 分钟后：%s' % (mins, text.strip()),
                         QSystemTrayIcon.Information, 3000)

    for mins, label in [(5, '5 分钟后'), (25, '25 分钟后'), (60, '1 小时后')]:
        a = QAction(label, pop_rem)
        # 注意：这几项**不带省略号**，但一样会弹输入框问"提醒什么"——
        # 所以自检不能靠"文案里有 …"来判断会不会弹框，必须逐项显式标记。
        a.setProperty('selftest_skip', '会弹输入框（自检会卡住）')
        a.triggered.connect(lambda checked=False, m_=mins: ask_reminder(m_))
        pop_rem.addAction(a)
    a_custom = QAction('自定义…', pop_rem)
    a_custom.setProperty('selftest_skip', '会弹输入框（自检会卡住）')
    a_custom.triggered.connect(lambda: ask_reminder(None))
    pop_rem.addAction(a_custom)
    menu.addMenu(pop_rem)

    menu.addSeparator()
    act_quit = QAction('退出', menu)
    act_quit.setProperty('selftest_skip', '会退出程序')
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.show()

    # 托盘左键/双击也能唤出菜单（Windows 习惯就是双击托盘图标，只做右键会以为程序没功能）
    def _tray_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            menu.popup(QCursor.pos())

    tray.activated.connect(_tray_activated)

    # 首次运行引导：告诉他们功能都在托盘右键里，别自己找
    if not cfg.get('_guided'):
        def _guide():
            tray.showMessage(
                'FlyPet 已就位',
                '右键任务栏这个图标 → 全部功能都在菜单里\n'
                '（笼子、定时提醒、放置虫子、脑活动面板…）\n'
                '要改设置：菜单第一组里的「设置…」\n'
                '把文件拖到虫身上 = 收纳到指定文件夹（菜单里可指派）\n'
                '左键双击我也可以唤出菜单',
                QSystemTrayIcon.Information, 12000)
        QTimer.singleShot(1200, _guide)
        cfg['_guided'] = True
        try:
            persist_settings(cfg)
        except Exception:
            pass

    # 管理员权限下 Windows 会拦截"从资源管理器拖文件进来"（UIPI/完整性级别），
    # 表现为红色禁止符。这是"拖不进笼子"的常见外因，主动提示一次。
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            QTimer.singleShot(2600, lambda: tray.showMessage(
                'FlyPet 提示',
                '当前以管理员身份运行。Windows 会阻止从资源管理器拖文件进来，\n'
                '「拖文件喂果蝇」会一直显示禁止符。改用普通权限启动即可正常拖放。',
                QSystemTrayIcon.Information, 9000))
    except Exception:
        pass

    # 全局快捷键投喂
    hk = parse_hotkey(cfg['feed_hotkey'])
    dbg_log('hotkey 配置=%r 解析=%r' % (cfg['feed_hotkey'], hk))
    filt = None
    if hk:
        mods, key = hk
        ok = ctypes.windll.user32.RegisterHotKey(None, 1, mods, key)
        if ok:
            # 注意：成功时**不要**打印 GetLastError —— 它只在调用失败时才有意义，
            # 成功却打出"GetLastError=2"会把"注册成功"记成一条看着像故障的日志。
            dbg_log('RegisterHotKey 成功：%r -> %r' % (cfg['feed_hotkey'], hk))
            filt = HotkeyFilter(win.feed, log=dbg_log)
            app.installNativeEventFilter(filt)
        else:
            # 注册失败（多为热键被其他程序占用）：退回托盘菜单投喂，不打断运行
            err = ctypes.windll.kernel32.GetLastError()
            dbg_log('RegisterHotKey 失败 err=%s (0x%X)' % (err, err))
            tray.showMessage('FlyPet', '快捷键 %s 注册失败，可能被其他程序占用；可从托盘菜单投喂' % cfg['feed_hotkey'],
                             QSystemTrayIcon.Information, 4000)

    app.aboutToQuit.connect(lambda: (win.save(),
                                     ctypes.windll.user32.UnregisterHotKey(None, 1) if hk else None))
    win.show()

    # 菜单自检 / 清点钩子：FLYPET_SELFTEST=menu → 逐项点一遍；=inventory → 只导出清单。
    #
    # 为什么需要它：**Qt 会静默吞掉信号处理函数里的异常**，异常既不终止进程也不冒泡，
    # 只会被 PySide6 打到 stderr —— 所以"进程还活着"根本证明不了"菜单点得动"。
    # 皮肤菜单就栽在这上面：set_skin 里解包脱节抛 TypeError，表现是
    # "皮肤换了、但没存进 settings.json，重启又变回去"，肉眼和冒烟测试都看不出来。
    # 这里逐项捕获 stderr：一旦有 traceback 就说明这一项点坏了。
    if selftest:
        import io as _io

        # 看门狗：万一某一项弹出模态框（自检会卡在它的事件循环里出不来），
        # 就报出"卡在哪一项"并立刻退出 —— 否则整个自检会无声挂死，看不出是谁干的。
        # 模态对话框有自己的事件循环，QTimer 在里面照样会触发，所以这招管用。
        _hung = {'at': None}
        _watch = QTimer()
        _watch.setSingleShot(True)

        def _on_hung():
            print('SELFTEST_MENU_HUNG=%s' % (_hung['at'] or '?'), flush=True)
            os._exit(2)

        _watch.timeout.connect(_on_hung)

        def _walk_menu(acts, out, path='', click=False, seen=None):
            """遍历菜单树。out 收集清单条目；click=True 时顺带触发可勾选项并抓 stderr。"""
            for act in acts:
                label = path + act.text()
                sub = act.menu()
                if sub is not None:
                    out.append({'kind': 'menu', 'path': label})
                    _walk_menu(sub.actions(), out, label + ' ▸ ', click, seen)
                    continue
                entry = {
                    'kind': 'action', 'path': label,
                    'checkable': bool(act.isCheckable()),
                    'enabled': bool(act.isEnabled()),
                    'text': act.text(),
                }
                out.append(entry)
                if not click:
                    continue
                # 该不该点：默认"可以点"，危险的是**显式标出来**的（见各处 setProperty）。
                # 用属性而不是匹配文案 —— 改个菜单文字不该让某一项偷偷溜出自检。
                skip_why = act.property('selftest_skip')
                if skip_why or '…' in act.text():
                    entry['skipped'] = skip_why or '会弹对话框'
                    continue
                if seen is not None and act.text().strip():
                    seen.append(label)      # 分隔线不算"点过一项"，别把数字撑虚
                buf = _io.StringIO()
                _er = sys.stderr
                sys.stderr = buf
                _hung['at'] = label
                _watch.start(2500)
                try:
                    if act.isCheckable():
                        act.setChecked(not act.isChecked())
                    act.trigger()
                except BaseException as exc:
                    buf.write('trigger raised %r\n' % (exc,))
                finally:
                    _watch.stop()
                    sys.stderr = _er
                if buf.getvalue().strip():
                    entry['broken'] = buf.getvalue().strip().splitlines()[-1]

        _inv = []
        _bad = []
        _click_it = (selftest_mode == 'menu')
        _seen = []
        _walk_menu(menu.actions(), _inv, click=_click_it, seen=_seen)
        _bad = [(e['path'], e['broken']) for e in _inv if e.get('broken')]

        _out_path = os.environ.get('FLYPET_AUDIT_OUT')
        if _out_path:
            try:
                with open(_out_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'menu': _inv,
                        'settings_keys': [r[1] for r in SETTINGS_SPEC],
                        'settings_groups': sorted({r[0] for r in SETTINGS_SPEC}),
                        'save_version': 4,
                        'save_top_keys': ['version', 'foods', 'cage', 'eggs',
                                          'codex', 'lineage', 'next_fid', 'flies'],
                        'fly_keys': ['energy', 'x', 'y', 'dir', 'skin', 'gene',
                                     'age', 'fid', 'parents', 'size_mult',
                                     'weights', 'markers'],
                    }, f, ensure_ascii=False, indent=1)
                print('AUDIT_DUMP=%s' % _out_path)
            except Exception:
                print('AUDIT_DUMP_FAILED')

        print('SELFTEST_MENU_TOTAL=%d' % len(_inv))
        print('SELFTEST_MENU_CLICKED=%d' % len(_seen))
        print('SELFTEST_MENU_BAD=%d' % len(_bad))
        for _t, _m in _bad:
            print('  点坏了: %s -> %s' % (_t, _m))
        sys.exit(1 if _bad else 0)

    # 自动化测试钩子：FLYPET_TEST=1 → 4s 后在屏幕中心放糖，18s 后存档退出
    if os.environ.get('FLYPET_TEST'):
        def _autotest():
            win.feed(win.w * 0.5, win.h * 0.5)

        def _finish():
            win.save()
            print('TEST_FOODS=%d FLY_COUNT=%d POS=%s' % (
                len(win.foods), len(win.flies),
                [(round(f.x), round(f.y)) for f in win.flies]))
            app.quit()
        QTimer.singleShot(4000, _autotest)
        QTimer.singleShot(18000, _finish)

    # 场景验收钩子：FLYPET_SCENE=1 → 摆出 6 物种+笼子+顶边翻转气泡的静止画面
    if os.environ.get('FLYPET_SCENE'):
        def _scene():
            win.cfg['speed_scale'] = 0.0   # 定格便于截图
            win.cage = {'x': win.w * 0.28, 'y': win.h * 0.42, 'locked': True}
            win.flies = []
            names = ['rocket', 'ufo', 'dragonfly', 'butterfly',
                     'paperplane', 'hummingbird']
            for k, nm in enumerate(names):
                fly = win.register_fly(PetFly(win.w * (0.12 + 0.13 * k),
                                              win.h * (0.30 + 0.10 * (k % 2)),
                                              skin=nm))
                fly.labelT = 30.0
                win.flies.append(fly)
            top = win.register_fly(PetFly(win.w * 0.72, win.h * 0.018, skin='bee'))
            top.bubble = ['我在最顶上，气泡往下翻', 0.0, 30.0]
            top.labelT = 30.0
            win.flies.append(top)
            win.foods.append({'x': win.cage['x'], 'y': win.cage['y'],
                              'e': FOOD_E0})
        QTimer.singleShot(2500, _scene)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
