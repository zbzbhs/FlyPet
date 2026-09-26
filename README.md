# FlyPet · 会学习的果蝇群桌宠

<p align="center">
  <img src="assets/demo.gif" alt="FlyPet 演示" width="640">
</p>

**FlyPet** 是一只养在桌面上的果蝇群。每只虫都带着一个模拟果蝇**蘑菇体**（mushroom body）的小型神经网络：它们会觅食、社交、繁殖、记住危险的地方，也会老化与死亡。你只需要投喂、观察，偶尔拍一下捣蛋的虫——剩下的交给它们自己。

纯 Python + PySide6 编写，**免安装、离线运行**，Windows 下载即用。

[English](README.en.md) · [完整使用手册（中文）](MANUAL.md)

---

## 特性

- **可学习的脑**：每只虫内置 KC→MBON 蘑菇体模型，奖励与惩罚会真实改变它们的行为——被拍过的地方下次绕着走
- **遗传与繁殖**：吃得饱的虫会产卵，后代继承基因（食量 / 速度 / 生育力 / 体型）并变异；攒出**传说个体**时会有金色呼吸光晕
- **9 种皮肤**：果蝇 / 蜜蜂 / 蝴蝶 / 蜻蜓 / 萤火虫 / 蜂鸟 / 纸飞机 / 火箭 / UFO / 像素风，支持自定义皮肤目录
- **桌面工具集**：番茄钟、定时提醒（到点虫群聚队举牌）、报时虫、剪贴板历史、系统监视、文件收纳（把文件拖到虫身上自动归档）
- **图鉴与谱系**：每一代的编号、亲代、基因都有记录
- **克制的资源占用**：打盹自动降帧、暂停 5fps、长时间挂机内存/句柄零增长（有实测数据）

## 快速开始

**方式一：下载 exe（推荐）**

到 [Releases](../../releases) 下载 `FlyPet.exe`，双击运行。免安装，托盘图标右键即是全部菜单。

**方式二：源码运行**

```bash
pip install PySide6
python pet.py
```

要求：Windows 10+，Python 3.11+。

**打包自己的 exe**

```bash
pip install pyinstaller
pyinstaller FlyPet.spec
```

## 测试网（本项目的一个执念）

这个项目维护着一套相当较真的测试网，全部可复现：

| 工具 | 断言数 | 测什么 |
|---|---|---|
| `_test_paths.py` | 295 | 逻辑断言，覆盖 99% 的函数 |
| `_golden.py` | 41 | 12 张绘制基线图**逐字节比对**，带渲染环境指纹守卫 |
| `_mask_check.py` | 21 | mask 不得裁掉任何画出来的内容 |
| `_fps_probe.py` | — | 数 tick 实测三种状态的真实帧率 |
| `_inject_check.py` | 12 例 | 反向注入：把修好的 Bug 塞回去，证明测试真的会红 |
| `_longrun.py` | — | 长挂观测：内存/CPU/句柄/GDI 采样 |

运行测试（需与绘制基线同版本的 PySide6，环境不对会被指纹守卫拦下并给出指引）：

```bash
python _test_paths.py
python _golden.py
python _mask_check.py
```

## 自定义皮肤

往 `skins/` 里新建一个文件夹，放好帧图与 `skin.json`（`{"fps":18,"size":56,"facing":"right", ...}`），重启即出现在托盘皮肤菜单。`gen_skin.py` 可以从单张立绘生成多帧皮肤，`import_skin.py` 负责导入。

## 许可证

[MIT](LICENSE) —— 随意使用、修改、二创；如果它也是你的第一只"数字昆虫"，欢迎回来说一声。
