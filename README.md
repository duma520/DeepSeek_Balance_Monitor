# DeepSeek_Balance_Monitor v1.5.0

> **一句话**：DeepSeek_Balance_Monitor —— 一个用 Python 写的 Windows 桌面程序，
> 主程序为 `DeepSeek_Balance_Monitor.py`，界面技术栈 PySide6（Qt6 官方 Python 绑定）。
>
> **适合谁**：想直接用现成工具、不想自己写代码的 Windows 用户。
>
> **解决什么问题**：把这件事做成开箱即用的程序 —— 下载解压、装上依赖、双击就能跑。

---

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 零基础入门（5 分钟跑起来）](#2-零基础入门5-分钟跑起来)
- [3. 功能与界面](#3-功能与界面)
- [4. 命令行参数](#4-命令行参数)
- [5. 配置文件与数据](#5-配置文件与数据)
- [6. 工作原理（技术参考）](#6-工作原理技术参考)
- [7. 排错手册](#7-排错手册)
- [8. 常见问题 FAQ](#8-常见问题-faq)
- [9. 目录结构](#9-目录结构)
- [10. 开发与构建](#10-开发与构建)
- [11. 已知限制与安全说明](#11-已知限制与安全说明)
- [12. 许可](#12-许可)

## 1. 这是什么

| 项目 | 说明 |
| --- | --- |
| 程序名 | `DeepSeek_Balance_Monitor` |
| 当前版本 | v1.5.0 |
| 主程序 | `DeepSeek_Balance_Monitor.py` |
| 界面技术 | PySide6（Qt6 官方 Python 绑定） |
| 语言 / 运行平台 | Python 3.10 / Windows |
| 源码规模 | 根目录及子模块共 8 个 .py 文件 |
| 仓库 | https://github.com/duma520/DeepSeek_Balance_Monitor |

## 2. 零基础入门（5 分钟跑起来）

### 第 1 步：装 Python

1. 打开 <https://www.python.org/downloads/windows/>，下载 Python 3.10 或更新版本。
2. 安装时**务必勾选** `Add python.exe to PATH`（安装向导第一页最下方）。
3. 装完按 `Win + R` 输入 `cmd`，敲 `python --version`，能看到版本号就成功了。

### 第 2 步：拿到源码

- **下载压缩包**：在本仓库 Releases 页下载 `DeepSeek_Balance_Monitor-*.zip`，解压到任意目录。
- **git 克隆**：`git clone https://github.com/duma520/DeepSeek_Balance_Monitor.git`

### 第 3 步：装依赖

在源码目录打开命令行，执行：

```
pip install Pillow PySide6 dataclasses requests win10toast winotify winsdk
```

> 清单是从源码的实际 import 汇总出来的；若某个包名不准确，以 pip 报错提示的正确包名为准。

### 第 4 步：启动

```bat
python DeepSeek_Balance_Monitor.py
```

目录里还带了 `1.bat`，双击等同于上面的命令（前提是 Python 在 PATH 里）。

## 3. 功能与界面

> 本节只列源码里能确认的事实；具体按钮与交互以运行后的界面为准。

| 维度 | 实际情况 |
| --- | --- |
| 界面框架 | PySide6（Qt6 官方 Python 绑定） |
| 是否有 main 入口 | 是，可直接 python 主程序.py 运行 |
| 第三方依赖数 | 7 个 |

### 版本变更（来自项目自带迭代记录）

| 版本 | 说明 |
| --- | --- |
| 3719 | 通知条件判定与派发（三行正文 + 去重签名） |
| 3751 | 失败计数、状态提示、连败通知 |
| 3876 | 状态栏统计、勾选框条数、容量进度 |
| 3950 | 设置变更联动（筛选互斥、缩放、行高、字体、托盘…） |
| 3988 | 界面缩放（应用字体 / 卡片 / 按钮 / 菜单，并联动列表字体） |
| 4006 | **列表字体**：设定磅值 × 缩放，同步表头与时间列，触发列宽重排 |
| 4021 | 行高：按当前列表字体给出防裁字下限 |
| 4535 | 入口：高 DPI、单实例、装配、事件循环 |

## 4. 命令行参数

主程序支持的参数（从 argparse 定义抽取）：

| 参数 | 说明 |
| --- | --- |
| `--visible` | 显示真实窗口（默认 offscreen） |
| `--shot` | 保存窗口截图到 _scaffold\\_shot.png |
| `--toast` | 额外发送一条右下角通知 |
| `--seconds` | 等待初始化完成的秒数 |
| `--no-network` | 跳过真实接口查询（只做界面自检） |
| `--font` | 临时把「列表字体」设为该磅值后再自检（用于人工核对字号） |
| `--repeat` | 连续查询次数 |
| `--interval` | 多次查询之间的间隔秒数 |
| `--no-error-path` | 跳过无效 Key 的错误路径测试 |
| `--title` | 通知标题 |
| `--body` | 通知正文 |
| `--seconds` | 等待弹窗出现的秒数 |

## 5. 配置文件与数据

程序把配置写在自身目录或用户目录下；.gitignore 已排除运行期产生的配置与日志，首次运行会自动生成。

## 6. 工作原理（技术参考）

```
用户操作 → PySide6 → 业务逻辑 → 结果输出
```

- 入口文件 `DeepSeek_Balance_Monitor.py`，带 if __name__ == '__main__' 保护。
- 依赖的第三方库：`Pillow`、`PySide6`、`dataclasses`、`requests`、`win10toast`、`winotify`、`winsdk`。
- 全部业务逻辑在仓库内可见，没有编译产物、没有联网下发代码。

## 7. 排错手册

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| python 不是内部或外部命令 | 安装时没勾 PATH | 重装 Python 并勾选 Add python.exe to PATH，或改用 py 命令 |
| ModuleNotFoundError: No module named xxx | 依赖没装 | 按第 3 步 pip install 对应包 |
| 双击 .bat 一闪而过 | 出错后窗口立即关闭 | 用 cmd 进入目录再执行命令，看清报错 |
| 界面显示乱码 | 控制台编码不是 UTF-8 | 先执行 chcp 65001，或用 python -X utf8 主程序.py |
| 杀毒软件拦截 | 未签名脚本被误判 | 加入信任/白名单；本项目只提供源码，可自行审阅 |

## 8. 常见问题 FAQ

**Q1：需要装 Visual Studio 之类的编译工具吗？**
A：不需要。这里只提供 Python 源码，pip 装的是预编译轮子。

**Q2：能在 macOS / Linux 上跑吗？**
A：本项目按 Windows 环境开发与验证；其他系统未测试，可能需要改路径与系统 API 调用。

**Q3：为什么 Releases 里只有源码 zip，没有 exe？**
A：只分发源码，避免二进制被误判；需要 exe 请按第 10 节自行打包。

**Q4：改了代码怎么运行？**
A：直接 python 主程序.py，改动立即生效，无需编译。

**Q5：数据存在哪？会不会被上传？**
A：只存在本机（程序目录或用户目录）。本程序不含上传逻辑。

**Q6：怎么反馈问题？**
A：到 https://github.com/duma520/DeepSeek_Balance_Monitor/issues 提 Issue，附上报错原文与复现步骤。

## 9. 目录结构

```
DeepSeek_Balance_Monitor.dist/
_scaffold/
build_output/
data/
logs/
.env
.env.example
.gitignore
0_nuitka_pyside6_clang_auto.bat
1.bat
DeepSeek_Balance_Monitor.py
README.md
icon.ico
requirements.txt
软件升级迭代记录.md
DeepSeek_Balance_Monitor.dist\PySide6/
DeepSeek_Balance_Monitor.dist\certifi/
DeepSeek_Balance_Monitor.dist\charset_normalizer/
DeepSeek_Balance_Monitor.dist\data/
DeepSeek_Balance_Monitor.dist\logs/
DeepSeek_Balance_Monitor.dist\shiboken6/
DeepSeek_Balance_Monitor.dist\simplejson/
DeepSeek_Balance_Monitor.dist\.env
DeepSeek_Balance_Monitor.dist\81d243bd2c585b0f4821__mypyc.pyd
DeepSeek_Balance_Monitor.dist\DeepSeek_Balance_Monitor.exe
DeepSeek_Balance_Monitor.dist\_asyncio.pyd
DeepSeek_Balance_Monitor.dist\_brotli.pyd
DeepSeek_Balance_Monitor.dist\_bz2.pyd
DeepSeek_Balance_Monitor.dist\_ctypes.pyd
DeepSeek_Balance_Monitor.dist\_decimal.pyd
DeepSeek_Balance_Monitor.dist\_hashlib.pyd
DeepSeek_Balance_Monitor.dist\_lzma.pyd
DeepSeek_Balance_Monitor.dist\_multiprocessing.pyd
DeepSeek_Balance_Monitor.dist\_overlapped.pyd
DeepSeek_Balance_Monitor.dist\_queue.pyd
DeepSeek_Balance_Monitor.dist\_socket.pyd
DeepSeek_Balance_Monitor.dist\_sqlite3.pyd
DeepSeek_Balance_Monitor.dist\_ssl.pyd
DeepSeek_Balance_Monitor.dist\icon.ico
DeepSeek_Balance_Monitor.dist\libcrypto-1_1.dll
DeepSeek_Balance_Monitor.dist\libffi-7.dll
DeepSeek_Balance_Monitor.dist\libssl-1_1.dll
DeepSeek_Balance_Monitor.dist\msvcp140.dll
DeepSeek_Balance_Monitor.dist\msvcp140_1.dll
DeepSeek_Balance_Monitor.dist\msvcp140_2.dll
```

## 10. 开发与构建

- 直接运行（开发态）：`python DeepSeek_Balance_Monitor.py`
- 语法自检：`python -m py_compile DeepSeek_Balance_Monitor.py`
- 打包 exe（可选）：装 pyinstaller 后执行 `pyinstaller -F -w DeepSeek_Balance_Monitor.py`

## 11. 已知限制与安全说明

- 只提供源码，不提供预编译二进制。
- 仓库不含任何凭据；.env / *.pem / *.key / 日志与运行期数据均在 .gitignore 中排除。
- 若程序需要联网，请在源码中确认目标地址后再运行。

## 12. 许可

MIT License，详见仓库根目录 LICENSE。
