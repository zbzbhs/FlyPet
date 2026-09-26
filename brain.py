# -*- coding: utf-8 -*-
"""
FlyPet 脑内核 —— 连接组约简 LIF 脉冲神经网络
移植自 fly-sim (github.com/sjy20100819mc-cmyk/fly-sim) src/brain.js
数据源：FlyEM 雄性果蝇 CNS v1.0（2026-09, HHMI Janelia / Cambridge / Google）
  165,122 神经元 / 25,568,639 突触 → 按细胞类型归并 25 群 / 145 条连接
  （MCNS = 直接实测 119 条；inf = 实测缺失的工程桥接 26 条，均已标注）
动力学：cuLIF，τm=20ms / τsyn=5ms / 2ms 不应期，flybench/Shiu2024 口径
可塑性：PPL1 多巴胺→KC→MBON_av 惩罚学习；PAM→KC→MBON_app 奖赏学习；无惩罚则消退
"""
import math
import random

# ----------------------------- 工具 -----------------------------
def clamp(v, a, b):
    return a if v < a else (b if v > b else v)

def randn():
    return (random.random() + random.random() + random.random() - 1.5) * 1.15

def angdiff(a, b):
    d = (a - b) % (2.0 * math.pi)
    if d > math.pi:
        d -= 2.0 * math.pi
    return d

# ----------------------------- 脑参数 -----------------------------
BRAIN = dict(
    dt=0.01,          # 仿真步长 (s)
    wSyn=0.275,       # 单突触权重基准 (mV)
    gain=0.42,        # 全局增益（flybench 反射通过区 0.40-0.45）
    K=5.0,            # 权重尺度
    adapt=0.18,       # 放电频率适应
    tauAdapt=0.10,
    tauM=0.020, tauSyn=0.005, tauR=0.20,
    vThr=1.0, vReset=0.0, vRefrac=0.002,
    noise=0.028,      # 自发噪声
    lr=0.15,          # 多巴胺学习率
    extinct=0.5,      # 消退系数
    daThresh=3.0,     # 多巴胺门控阈值 (Hz)
    wMax=3.2,         # 可塑权重上限（倍）
    plasticTau=0.35,  # KC 资格迹时间常数 (s)
)

# ------------------- 细胞类型 [名, 群, 递质符号, 数量, 注] -------------------
CTYPE = [
    ('ORN_food',    'Sensory',  1, 5, '食物气味感受 · 实测 2,115 个 / ACh'),
    ('ORN_ferm',    'Sensory',  1, 1, '发酵气味感受 · 实测 316 个 / ACh'),
    ('ORN_alarm',   'Sensory',  1, 1, '信息素感受 · 实测 204 个 / ACh'),
    ('GRN_sugar',   'Sensory',  1, 1, '糖味觉感受 · 实测 100 个 / ACh'),
    ('mechano',     'Sensory',  1, 3, '机械/听觉(JO) · 实测 672 个 / ACh'),
    ('visual',      'Sensory', -1, 5, '光感受器 · 实测 4,114 个 / 组胺'),
    ('Hugin',       'Drives',  -1, 1, '饥饿驱动(Hugin) · 实测 4 个 / 谷氨酸+肽'),
    ('NPF',         'Drives',   1, 1, '取食促进(NPF) · 实测 2 个 / 肽'),
    ('FB_energy',   'Drives',  -1, 2, '饱足(扇形体) · 实测 601 个 / GABA'),
    ('LN_al',       'Central', -1, 1, '触角叶局部 · 实测 28 个 / GABA'),
    ('PN',          'Central',  1, 3, '投射神经元 · 实测 808 个 / ACh'),
    ('LHON',        'Central',  1, 5, '侧角输出 · 实测 1,975 个 / ACh'),
    ('KC',          'Central',  1, 5, '蘑菇体Kenyon · 实测 4,064 个 / ACh'),
    ('APL',         'Central', -1, 1, '蘑菇体反馈 · 实测 2 个 / GABA'),
    ('MBON_app',    'Central',  1, 1, 'MBON03 食欲性输出 · 实测 2 个 / 谷氨酸'),
    ('MBON_av',     'Central', -1, 1, 'MBON11 厌恶性输出 · 实测 2 个 / 谷氨酸'),
    ('PPL1',        'Central',  0, 1, '惩罚多巴胺 · 实测 16 个 / 多巴胺'),
    ('PAM',         'Central',  0, 1, '奖赏多巴胺 · 实测 316 个 / 多巴胺'),
    ('ring_EB',     'Central',  1, 1, '椭球体ring · 实测 278 个 / ACh'),
    ('PFN',         'Central',  1, 2, '桥神经元 · 实测 456 个 / ACh'),
    ('DN_escape',   'Central',  1, 1, '巨纤维逃逸 · 实测 6 个 / ACh'),
    ('DN_walk',     'Central',  1, 1, '下行行进 · 实测 10 个 / ACh'),
    ('MN_feed',     'Motor',    1, 1, 'MN9 喙伸展 · 实测 2 个 / ACh'),
    ('MN_walk',     'Motor',    1, 2, '腿部运动 · 实测 485 个 / ACh'),
    ('MN_oviposit', 'Motor',    1, 1, '腹部运动 · 实测 214 个 / ACh'),
]

# ------------------- 连接 [前, 后, 归一化强度, 可塑性, 来源] -------------------
CONNECTIONS = [
    ('APL', 'APL', 0.171, None, 'MCNS*'),
    ('APL', 'KC', 2.759, None, 'MCNS'),
    ('APL', 'LHON', 0.040, None, 'MCNS'),
    ('APL', 'MBON_app', 4.085, None, 'MCNS'),
    ('APL', 'MBON_av', 4.780, None, 'MCNS'),
    ('APL', 'PAM', 0.172, None, 'MCNS'),
    ('APL', 'PN', 0.737, None, 'MCNS'),
    ('APL', 'PPL1', 2.555, None, 'MCNS'),
    ('DN_escape', 'DN_escape', 0.021, None, 'MCNS*'),
    ('DN_escape', 'DN_walk', 0.132, None, 'MCNS'),
    ('DN_escape', 'MN_oviposit', 0.083, None, 'MCNS'),
    ('DN_escape', 'MN_walk', 0.526, None, 'MCNS'),
    ('DN_walk', 'DN_escape', 1.057, None, 'MCNS'),
    ('DN_walk', 'MN_oviposit', 0.014, None, 'MCNS'),
    ('DN_walk', 'MN_walk', 0.111, None, 'MCNS'),
    ('FB_energy', 'FB_energy', 0.750, None, 'MCNS*'),
    ('FB_energy', 'LHON', 0.050, None, 'MCNS'),
    ('FB_energy', 'LN_al', 2.526, None, 'MCNS'),
    ('FB_energy', 'PAM', 0.408, None, 'MCNS'),
    ('FB_energy', 'PFN', 3.197, None, 'MCNS'),
    ('FB_energy', 'PPL1', 3.382, None, 'MCNS'),
    ('FB_energy', 'ring_EB', 0.011, None, 'MCNS'),
    ('GRN_sugar', 'GRN_sugar', 0.307, None, 'MCNS*'),
    ('GRN_sugar', 'PN', 0.006, None, 'MCNS'),
    ('KC', 'APL', 5.000, None, 'MCNS'),
    ('KC', 'FB_energy', 0.002, None, 'MCNS'),
    ('KC', 'KC', 0.429, None, 'MCNS*'),
    ('KC', 'LHON', 0.135, None, 'MCNS'),
    ('KC', 'MBON_app', 5.000, 'app', 'MCNS'),
    ('KC', 'MBON_av', 5.000, 'av', 'MCNS'),
    ('KC', 'PAM', 3.041, None, 'MCNS'),
    ('KC', 'PN', 0.008, None, 'MCNS'),
    ('KC', 'PPL1', 5.000, None, 'MCNS'),
    ('LHON', 'APL', 5.000, None, 'MCNS'),
    ('LHON', 'DN_escape', 2.997, None, 'MCNS'),
    ('LHON', 'DN_walk', 0.365, None, 'MCNS'),
    ('LHON', 'FB_energy', 1.622, None, 'MCNS'),
    ('LHON', 'KC', 0.463, None, 'MCNS'),
    ('LHON', 'LHON', 0.675, None, 'MCNS*'),
    ('LHON', 'LN_al', 1.236, None, 'MCNS'),
    ('LHON', 'MBON_app', 1.791, None, 'MCNS'),
    ('LHON', 'PAM', 0.903, None, 'MCNS'),
    ('LHON', 'PN', 3.166, None, 'MCNS'),
    ('LHON', 'PPL1', 4.466, None, 'MCNS'),
    ('LHON', 'ring_EB', 0.414, None, 'MCNS'),
    ('LN_al', 'FB_energy', 0.792, None, 'MCNS'),
    ('LN_al', 'LHON', 0.003, None, 'MCNS'),
    ('LN_al', 'LN_al', 0.643, None, 'MCNS*'),
    ('LN_al', 'MN_oviposit', 0.141, None, 'MCNS'),
    ('LN_al', 'PFN', 2.939, None, 'MCNS'),
    ('LN_al', 'PN', 1.329, None, 'MCNS'),
    ('MBON_app', 'APL', 1.865, None, 'MCNS'),
    ('MBON_app', 'FB_energy', 0.006, None, 'MCNS'),
    ('MBON_app', 'KC', 0.001, None, 'MCNS'),
    ('MBON_app', 'LHON', 0.141, None, 'MCNS'),
    ('MBON_app', 'PAM', 0.094, None, 'MCNS'),
    ('MBON_av', 'APL', 5.000, None, 'MCNS'),
    ('MBON_av', 'FB_energy', 0.038, None, 'MCNS'),
    ('MBON_av', 'KC', 0.002, None, 'MCNS'),
    ('MBON_av', 'LHON', 0.033, None, 'MCNS'),
    ('MBON_av', 'MBON_app', 3.348, None, 'MCNS'),
    ('MBON_av', 'MBON_av', 0.466, None, 'MCNS*'),
    ('MBON_av', 'PAM', 0.174, None, 'MCNS'),
    ('MBON_av', 'PPL1', 2.456, None, 'MCNS'),
    ('MN_feed', 'MN_feed', 0.067, None, 'MCNS*'),
    ('MN_oviposit', 'MN_oviposit', 0.215, None, 'MCNS*'),
    ('MN_walk', 'MN_walk', 0.077, None, 'MCNS*'),
    ('NPF', 'LHON', 0.002, None, 'MCNS'),
    ('ORN_alarm', 'ORN_alarm', 0.150, None, 'MCNS*'),
    ('ORN_alarm', 'PN', 2.591, None, 'MCNS'),
    ('ORN_ferm', 'LN_al', 0.705, None, 'MCNS'),
    ('ORN_ferm', 'ORN_ferm', 0.276, None, 'MCNS*'),
    ('ORN_ferm', 'ORN_food', 0.001, None, 'MCNS'),
    ('ORN_ferm', 'PN', 3.092, None, 'MCNS'),
    ('ORN_food', 'LHON', 0.001, None, 'MCNS'),
    ('ORN_food', 'LN_al', 4.051, None, 'MCNS'),
    ('ORN_food', 'ORN_alarm', 0.004, None, 'MCNS'),
    ('ORN_food', 'ORN_ferm', 0.024, None, 'MCNS'),
    ('ORN_food', 'ORN_food', 0.345, None, 'MCNS*'),
    ('ORN_food', 'PN', 5.000, None, 'MCNS'),
    ('PAM', 'APL', 5.000, None, 'MCNS'),
    ('PAM', 'FB_energy', 0.005, None, 'MCNS'),
    ('PAM', 'KC', 0.559, None, 'MCNS'),
    ('PAM', 'LHON', 0.001, None, 'MCNS'),
    ('PAM', 'MBON_app', 5.000, None, 'MCNS'),
    ('PAM', 'MBON_av', 2.808, None, 'MCNS'),
    ('PAM', 'PAM', 0.062, None, 'MCNS*'),
    ('PAM', 'PPL1', 1.186, None, 'MCNS'),
    ('PFN', 'FB_energy', 1.949, None, 'MCNS'),
    ('PFN', 'LN_al', 5.000, None, 'MCNS'),
    ('PFN', 'PFN', 0.545, None, 'MCNS*'),
    ('PN', 'APL', 5.000, None, 'MCNS'),
    ('PN', 'FB_energy', 0.544, None, 'MCNS'),
    ('PN', 'KC', 3.632, None, 'MCNS'),
    ('PN', 'LHON', 4.536, None, 'MCNS'),
    ('PN', 'LN_al', 3.559, None, 'MCNS'),
    ('PN', 'MBON_app', 0.880, None, 'MCNS'),
    ('PN', 'NPF', 0.783, None, 'MCNS'),
    ('PN', 'ORN_alarm', 0.019, None, 'MCNS'),
    ('PN', 'ORN_ferm', 0.237, None, 'MCNS'),
    ('PN', 'ORN_food', 0.162, None, 'MCNS'),
    ('PN', 'PAM', 0.128, None, 'MCNS'),
    ('PN', 'PN', 0.650, None, 'MCNS*'),
    ('PN', 'PPL1', 2.472, None, 'MCNS'),
    ('PN', 'ring_EB', 0.409, None, 'MCNS'),
    ('PPL1', 'APL', 5.000, None, 'MCNS'),
    ('PPL1', 'FB_energy', 0.282, None, 'MCNS'),
    ('PPL1', 'KC', 0.672, None, 'MCNS'),
    ('PPL1', 'LHON', 0.083, None, 'MCNS'),
    ('PPL1', 'MBON_av', 5.000, None, 'MCNS'),
    ('PPL1', 'PAM', 0.152, None, 'MCNS'),
    ('PPL1', 'PN', 0.001, None, 'MCNS'),
    ('PPL1', 'PPL1', 0.433, None, 'MCNS*'),
    ('mechano', 'DN_escape', 4.837, None, 'MCNS'),
    ('mechano', 'PN', 0.125, None, 'MCNS'),
    ('mechano', 'mechano', 0.066, None, 'MCNS*'),
    ('ring_EB', 'FB_energy', 0.006, None, 'MCNS'),
    ('ring_EB', 'ring_EB', 0.750, None, 'MCNS*'),
    ('visual', 'visual', 0.189, None, 'MCNS*'),
    # ---- 工程桥接（实测缺失，为保留行为而推断，已标注 inf）----
    ('Hugin', 'PN', 30.00, None, 'inf'),
    ('Hugin', 'MN_walk', 40.00, None, 'inf'),
    ('Hugin', 'MBON_av', 30.00, None, 'inf'),
    ('NPF', 'MN_feed', 25.00, None, 'inf'),
    ('NPF', 'MN_oviposit', 40.00, None, 'inf'),
    ('GRN_sugar', 'MN_feed', 45.00, None, 'inf'),
    ('GRN_sugar', 'NPF', 40.00, None, 'inf'),
    ('GRN_sugar', 'PAM', 30.00, None, 'inf'),
    ('FB_energy', 'MN_feed', 40.00, None, 'inf'),
    ('FB_energy', 'Hugin', 35.00, None, 'inf'),
    ('FB_energy', 'MN_oviposit', 30.00, None, 'inf'),
    ('visual', 'DN_escape', 45.00, None, 'inf'),
    ('visual', 'ring_EB', 30.00, None, 'inf'),
    ('ORN_alarm', 'DN_escape', 40.00, None, 'inf'),
    ('ORN_alarm', 'PPL1', 40.00, None, 'inf'),
    ('ORN_alarm', 'MBON_av', 60.00, None, 'inf'),
    ('ring_EB', 'PFN', 40.00, None, 'inf'),
    ('PFN', 'DN_walk', 35.00, None, 'inf'),
    ('PFN', 'MN_walk', 35.00, None, 'inf'),
    ('LHON', 'MN_feed', 8.00, None, 'inf'),
    ('MBON_app', 'DN_walk', 35.00, None, 'inf'),
    ('MBON_av', 'DN_walk', 35.00, None, 'inf'),
    ('MBON_av', 'MN_feed', 300.00, None, 'inf'),
    ('MBON_av', 'NPF', 150.00, None, 'inf'),
    ('mechano', 'MN_walk', 30.00, None, 'inf'),
    ('LHON', 'PFN', 30.00, None, 'inf'),
]


def compile_net():
    """展开连接表为逐神经元边表（拓扑全局共享，各脑只存可塑权重副本）"""
    ct, idx = {}, 0
    for name, group, sign, count, _desc in CTYPE:
        ct[name] = {'start': idx, 'n': count, 'group': group, 'sign': sign}
        idx += count
    n = idx
    S, D, W0, PL = [], [], [], []
    for a, b, norm, pl, _src in CONNECTIONS:
        A, Bq = ct[a], ct[b]
        # 多巴胺是神经调质：DAN 出边不产生突触电流，只门控可塑性
        is_mod = a in ('PPL1', 'PAM')
        w = 0.0 if is_mod else BRAIN['wSyn'] * BRAIN['gain'] * BRAIN['K'] * norm * A['sign']
        p = 1 if pl == 'av' else (2 if pl == 'app' else 0)
        for i in range(A['n']):
            si = A['start'] + i
            for j in range(Bq['n']):
                S.append(si)
                D.append(Bq['start'] + j)
                W0.append(w)
                PL.append(p)
    out = [[] for _ in range(n)]
    for e in range(len(S)):
        out[S[e]].append((D[e], e))
    return {'n': n, 'ct': ct, 'S': S, 'D': D, 'W0': W0, 'PL': PL,
            'E': len(S), 'out': out}


NET = compile_net()


class Brain:
    """单只个体的 LIF 脑（拓扑共享，可塑权重独立）"""

    def __init__(self):
        n = NET['n']
        self.n = n
        self.v = [0.0] * n
        self.I = [0.0] * n       # 突触电流
        self.ext = [0.0] * n     # 外部（感觉/驱动）电流
        self.r = [0.0] * n       # 放电率 (Hz)
        self.refr = [0.0] * n
        self.ad = [0.0] * n      # 适应电流
        self.w = NET['W0'][:]    # 可塑权重副本
        self.w0 = NET['W0'][:]
        kc = NET['ct']['KC']
        self.kcBase = kc['start']
        self.kcN = kc['n']
        self.kcTrace = [0.0] * self.kcN
        self.lastSpikes = 0

    def rate(self, name):
        c = NET['ct'][name]
        s = 0.0
        r = self.r
        for i in range(c['start'], c['start'] + c['n']):
            s += r[i]
        return s / c['n']

    def step(self, dt):
        c = BRAIN
        n = self.n
        v, I, ext, r, refr, ad = self.v, self.I, self.ext, self.r, self.refr, self.ad
        decI = math.exp(-dt / c['tauSyn'])
        decR = math.exp(-dt / c['tauR'])
        decA = math.exp(-dt / c['tauAdapt'])
        for i in range(n):
            I[i] *= decI
            r[i] *= decR
            ad[i] *= decA
        # 自发噪声：低概率给单个神经元瞬时驱动
        if c['noise'] > 0:
            kicks_f = c['noise'] * n * dt * 3
            k = int(kicks_f) + (1 if random.random() < kicks_f % 1 else 0)
            while k > 0:
                k -= 1
                I[random.randrange(n)] += 1.25
        # 积分 + 发放 + 传导
        dtM = dt / c['tauM']
        rGain = 1.0 / c['tauR']
        spikes = 0
        out = NET['out']
        kcB, kcN = self.kcBase, self.kcN
        kcTrace = self.kcTrace
        for i in range(n):
            if refr[i] > 0:
                refr[i] -= dt
                v[i] = 0.0
                continue
            vi = v[i] + dtM * (-v[i] + I[i] + ext[i] - ad[i])
            if vi >= c['vThr']:
                v[i] = c['vReset']
                refr[i] = c['vRefrac']
                ad[i] += c['adapt']
                spikes += 1
                r[i] += rGain
                if kcB <= i < kcB + kcN:
                    kcTrace[i - kcB] += 1.0
                for d, e in out[i]:
                    I[d] += self.w[e]
            else:
                v[i] = vi
        # 资格迹衰减
        decK = math.exp(-dt / c['plasticTau'])
        for i in range(kcN):
            kcTrace[i] *= decK
        # 多巴胺门控可塑性：PPL1→KC→MBON_av 惩罚 / PAM→KC→MBON_app 奖赏
        daP = self.rate('PPL1')
        daR = self.rate('PAM')
        dopP = clamp((daP - c['daThresh']) / 25.0, 0.0, 1.5)
        dopR = clamp((daR - c['daThresh']) / 25.0, 0.0, 1.5)
        PL, S, E = NET['PL'], NET['S'], NET['E']
        w, w0 = self.w, self.w0
        if dopP > 0 or dopR > 0:
            kP = c['lr'] * dopP * dt
            kR = c['lr'] * dopR * dt
            for e in range(E):
                p = PL[e]
                if not p:
                    continue
                tr = kcTrace[S[e] - kcB] / 6.0
                if tr > 1.2:
                    tr = 1.2
                if tr < 0.03:
                    continue
                b0 = w0[e]
                if p == 1 and kP > 0:
                    w[e] = clamp(w[e] + kP * tr * b0, 0.0, b0 * c['wMax'])
                elif p == 2 and kR > 0:
                    w[e] = clamp(w[e] + kR * tr * b0, 0.0, b0 * c['wMax'])
        else:
            # 消退：闻到气味但无惩罚 → 惩罚记忆缓慢回落
            kE = c['lr'] * c['extinct'] * dt
            for e in range(E):
                if PL[e] != 1:
                    continue
                tr = kcTrace[S[e] - kcB] / 6.0
                if tr > 1.2:
                    tr = 1.2
                if tr < 0.03:
                    continue
                b0 = w0[e]
                w[e] = clamp(w[e] - kE * tr * b0, b0 * 0.35, b0 * c['wMax'])
        # 遗忘：可塑权重缓慢回基线
        for e in range(E):
            if PL[e]:
                b0 = w0[e]
                w[e] += (b0 - w[e]) * dt * 0.03
        self.lastSpikes = spikes

    # ---- 行为读出（运动/下行神经元放电率 → 行为量）----
    def aversion(self):
        return clamp(self.rate('MBON_av') / 20.0, 0.0, 1.0)

    def attraction(self):
        return clamp(self.rate('MBON_app') / 8.0, 0.0, 1.0)

    def walkDrive(self):
        return self.rate('MN_walk') / 25.0

    def feedDrive(self):
        return self.rate('MN_feed')

    def steerBias(self):
        return (self.rate('PFN') - self.rate('ring_EB') * 0.4) / 25.0

    def escapeDrive(self):
        return self.rate('DN_escape')

    def learnIndex(self):
        """KC→MBON_av 惩罚记忆相对基线的平均倍数（1 = 未学习）"""
        s = c = 0.0
        PL = NET['PL']
        for e in range(NET['E']):
            if PL[e] != 1:
                continue
            s += self.w[e] / self.w0[e]
            c += 1
        return s / c if c else 1.0
