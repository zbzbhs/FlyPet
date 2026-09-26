# -*- coding: utf-8 -*-
"""全屏截图工具：python snap.py out.png"""
import sys
from PySide6.QtCore import QBuffer
from PySide6.QtGui import QGuiApplication


def main():
    app = QGuiApplication(sys.argv[:1])
    out = sys.argv[1] if len(sys.argv) > 1 else '_shot.png'
    scr = QGuiApplication.primaryScreen()
    pm = scr.grabWindow(0)
    pm.save(out)
    print('saved', out, pm.width(), 'x', pm.height())


if __name__ == '__main__':
    main()
