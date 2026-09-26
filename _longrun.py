# -*- coding: utf-8 -*-
"""长时间挂机体检：跑真 exe，按固定间隔采样资源占用 + 定时截图。

为什么不用 PowerShell：截图要 GUI 能力、资源计数要 ctypes，Python 一趟全有，
而且这台机器上 PySide6 就在 hermes venv 里，不用装任何新依赖。

用法：
    python _longrun.py --exe _run/FlyPet.exe --minutes 8 --out _longrun_out
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

# ── Windows 资源计数 ────────────────────────────────────────────────
psapi = ctypes.WinDLL('psapi', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('cb', wt.DWORD),
        ('PageFaultCount', wt.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [('low', wt.DWORD), ('high', wt.DWORD)]


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400


def ft_to_int(ft):
    return (ft.high << 32) | ft.low


def sample(pid):
    """返回一条资源采样；进程没了返回 None。"""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return None
    try:
        mc = PROCESS_MEMORY_COUNTERS()
        mc.cb = ctypes.sizeof(mc)
        psapi.GetProcessMemoryInfo(h, ctypes.byref(mc), mc.cb)

        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                ctypes.byref(k), ctypes.byref(u))
        cpu = (ft_to_int(k) + ft_to_int(u)) / 1e7   # 秒

        gdi = user32.GetGuiResources(h, 0)
        usr = user32.GetGuiResources(h, 1)
        return {
            'ws_mb': mc.WorkingSetSize / 1048576.0,
            'priv_mb': mc.PagefileUsage / 1048576.0,
            'cpu_s': cpu,
            'gdi': gdi,
            'user': usr,
        }
    finally:
        kernel32.CloseHandle(h)


def handles(pid):
    import ctypes.wintypes
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return -1
    try:
        n = wt.DWORD(0)
        kernel32.GetProcessHandleCount(h, ctypes.byref(n))
        return n.value
    finally:
        kernel32.CloseHandle(h)


# ── 找出"真正干活的那个"进程 ────────────────────────────────────────
# 坑：PyInstaller onefile 启动器会先起一个**父进程**负责解包，再派生子进程跑真程序。
# Popen 返回的 pid 是父进程 —— 它的 CPU 时间几乎不涨、工作集只有十几 MB，
# 拿它采样会得出"内存不增长、CPU 几乎为 0"的**假好消息**。
# 必须先认子进程：真实例线程数明显更多（实测 父 6 线程 vs 子 16 线程）。
TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
        ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD),
        ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
        ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),
    ]


def scan_named(exe_name):
    """返回 [(pid, ppid, threads), ...]"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = []
    if not snap or snap == -1:
        return out
    try:
        e = PROCESSENTRY32()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if (e.szExeFile or '').lower() == exe_name.lower():
                out.append((e.th32ProcessID, e.th32ParentProcessID, e.cntThreads))
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


def pick_target(launch_pid, exe_name):
    """优先取 launch_pid 的直接子进程；否则退化成"工作集最大的那个同名进程"。"""
    cands = scan_named(exe_name)
    kids = [c for c in cands if c[1] == launch_pid]
    pool = kids or cands
    if not pool:
        return None, len(cands)
    best, best_ws = None, -1
    for pid, _ppid, _th in pool:
        s = sample(pid)
        ws = s['ws_mb'] if s else -1
        if ws > best_ws:
            best, best_ws = pid, ws
    return best, len(cands)


def grab_screen(path):
    """截整屏。注意要先有 QGuiApplication，且不能在别的 Qt app 之后建。"""
    from PySide6.QtGui import QGuiApplication
    scr = QGuiApplication.primaryScreen()
    if scr is None:
        return False
    pm = scr.grabWindow(0)
    return bool(pm.save(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--minutes', type=float, default=8.0)
    ap.add_argument('--interval', type=float, default=15.0)
    ap.add_argument('--out', default='_longrun_out')
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    workdir = os.path.dirname(exe)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    # 先把 Qt 应用建起来（截图要用），但**不要**它抢焦点
    from PySide6.QtGui import QGuiApplication
    _qapp = QGuiApplication(sys.argv[:1])

    # 环境隔离：别污染真实存档目录
    env = dict(os.environ)
    env.pop('FLYPET_TEST', None)

    data_dir = os.path.join(workdir, 'data')
    petjson = os.path.join(data_dir, 'pet.json')

    def json_size():
        try:
            return os.path.getsize(petjson)
        except OSError:
            return 0

    p = subprocess.Popen([exe], cwd=workdir, env=env)
    launch_pid = p.pid
    exe_name = os.path.basename(exe)
    print('launched launcher pid=%d exe=%s' % (launch_pid, exe), flush=True)
    print('json0=%d B' % json_size(), flush=True)

    shots = {20.0: 'shot_020s.png', 300.0: 'shot_300s.png', 600.0: 'shot_600s.png'}
    t0 = time.time()
    rows = []
    try:
        while True:
            el = time.time() - t0
            if el > args.minutes * 60:
                break
            tgt, nproc = pick_target(launch_pid, exe_name)
            if tgt is None:
                print('!! 第 %.0f 秒已经找不到目标进程（崩溃或退出）' % el, flush=True)
                break
            s = sample(tgt)
            if s is None:
                print('!! 目标进程 %d 在第 %.0f 秒没了' % (tgt, el), flush=True)
                break
            s['t'] = el
            s['pid'] = tgt
            s['nproc'] = nproc
            s['hd'] = handles(tgt)
            s['json'] = json_size()
            rows.append(s)
            print('t=%6.1fs pid=%d 实例数=%d ws=%7.2fMB priv=%7.2fMB cpu=%7.2fs gdi=%4d user=%4d hd=%4d json=%dB'
                  % (el, tgt, nproc, s['ws_mb'], s['priv_mb'], s['cpu_s'], s['gdi'], s['user'], s['hd'], s['json']),
                  flush=True)

            for at, name in list(shots.items()):
                if el >= at:
                    path = os.path.join(out, name)
                    ok = grab_screen(path)
                    print('   [shot] %s ok=%s' % (name, ok), flush=True)
                    del shots[at]

            time.sleep(args.interval)
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        print('exit code:', p.returncode, flush=True)

    # ── 结论计算 ────────────────────────────────────────────────────
    if len(rows) >= 6:
        head = rows[:4]
        tail = rows[-4:]
        def avg(rs, k):
            return sum(r[k] for r in rs) / len(rs)
        d_ws = avg(tail, 'ws_mb') - avg(head, 'ws_mb')
        d_priv = avg(tail, 'priv_mb') - avg(head, 'priv_mb')
        span_min = (tail[-1]['t'] - head[0]['t']) / 60.0 or 1
        d_hd = avg(tail, 'hd') - avg(head, 'hd')
        d_gdi = avg(tail, 'gdi') - avg(head, 'gdi')
        cpu_pct = (rows[-1]['cpu_s'] - rows[0]['cpu_s']) / (rows[-1]['t'] - rows[0]['t']) * 100
        d_json = rows[-1]['json'] - rows[0]['json']
        print('\n=========== 汇总 ===========', flush=True)
        print('观测时长        : %.1f 分钟' % span_min)
        print('工作集变化      : %+.2f MB  (%+.2f MB/小时)' % (d_ws, d_ws / span_min * 60))
        print('私有内存变化    : %+.2f MB  (%+.2f MB/小时)' % (d_priv, d_priv / span_min * 60))
        print('句柄变化        : %+.1f' % d_hd)
        print('GDI 对象变化    : %+.1f' % d_gdi)
        print('平均单核 CPU    : %.1f%%' % cpu_pct)
        print('pet.json 增长   : %+d B' % d_json)
        print('进程实例数      : %s' % sorted(set(r['nproc'] for r in rows)))

        # 分段 CPU：帧率若在中途翻转（比如打盹降帧的判据写反），这里会看到台阶
        print('\n--- 分段 CPU（每 1/4 段）---', flush=True)
        n = len(rows)
        for k in range(4):
            seg = rows[k * n // 4:(k + 1) * n // 4]
            if len(seg) < 2:
                continue
            c = (seg[-1]['cpu_s'] - seg[0]['cpu_s']) / (seg[-1]['t'] - seg[0]['t']) * 100
            print('  第%d/4 段 (t=%5.0f~%5.0fs): CPU %.1f%%   ws %.1fMB   hd %d'
                  % (k + 1, seg[0]['t'], seg[-1]['t'], c,
                     sum(r['ws_mb'] for r in seg) / len(seg),
                     int(sum(r['hd'] for r in seg) / len(seg))))

        with open(os.path.join(out, 'samples.json'), 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
