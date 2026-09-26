# -*- coding: utf-8 -*-
"""
素材导入器：把网上下载的精灵图素材转成 FlyPet 皮肤
用法：
  1. 文件夹模式（一堆编号 PNG 帧）：
       python import_skin.py 蜜蜂某素材文件夹 --name bee_cute --fps 18 --size 56
  2. 雪碧图模式（一张大图切帧）：
       python import_skin.py sheet.png --name bee_cute --fw 32 --fh 32 --fps 18 --size 56
  3. zip 包模式（自动解压后按文件夹模式处理首个含 PNG 的目录）：
       python import_skin.py bugs.zip --name bee_cute
朝向说明：素材默认按"朝右"处理；若素材角色朝上，加 --facing up
"""
import os
import sys
import json
import shutil
import zipfile
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SKINS = os.path.join(HERE, 'skins')


def collect_pngs(path):
    return sorted(fn for fn in os.listdir(path) if fn.lower().endswith('.png'))


def find_png_dir(root):
    """zip 解压后找第一个直接含 PNG 的目录（广度优先）"""
    for cur, _dirs, files in os.walk(root):
        if any(f.lower().endswith('.png') for f in files):
            return cur
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', help='素材来源：文件夹 / 雪碧图 / zip')
    ap.add_argument('--name', required=True, help='皮肤名（英文，将显示在托盘菜单）')
    ap.add_argument('--fps', type=int, default=18)
    ap.add_argument('--size', type=float, default=56, help='桌面上显示的边长(px)')
    ap.add_argument('--facing', default='right', choices=['right', 'up'])
    ap.add_argument('--fw', type=int, help='雪碧图单帧宽')
    ap.add_argument('--fh', type=int, help='雪碧图单帧高')
    args = ap.parse_args()

    from PySide6.QtGui import QGuiApplication, QImage
    app = QGuiApplication(sys.argv[:1])

    src = os.path.abspath(args.source)
    tmp = None
    if src.lower().endswith('.zip'):
        tmp = src + '_unzipped'
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp)
        d = find_png_dir(tmp)
        if not d:
            print('zip 里没找到 PNG'); sys.exit(1)
    elif os.path.isdir(src):
        d = src
    elif src.lower().endswith('.png'):
        if not (args.fw and args.fh):
            print('雪碧图必须给 --fw --fh'); sys.exit(1)
        img = QImage(src)
        cols = img.width() // args.fw
        rows = img.height() // args.fh
        d = tmp = src + '_sliced'
        os.makedirs(d, exist_ok=True)
        n = 0
        for r in range(rows):
            for c in range(cols):
                fr = img.copy(c * args.fw, r * args.fh, args.fw, args.fh)
                if not fr.isNull():
                    fr.save(os.path.join(d, 'f_%03d.png' % n))
                    n += 1
        print('sliced %d frames' % n)
    else:
        print('不认识的来源:', src); sys.exit(1)

    frames = collect_pngs(d)
    if not frames:
        print('没找到 PNG 帧'); sys.exit(1)
    out = os.path.join(SKINS, args.name)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for i, fn in enumerate(frames):
        shutil.copy(os.path.join(d, fn), os.path.join(out, 'f_%03d.png' % i))
    with open(os.path.join(out, 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump({'fps': args.fps, 'size': args.size, 'facing': args.facing},
                  f, ensure_ascii=False, indent=2)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    print('OK ->', out, '(%d 帧，重启 FlyPet 生效)' % len(frames))


if __name__ == '__main__':
    main()
