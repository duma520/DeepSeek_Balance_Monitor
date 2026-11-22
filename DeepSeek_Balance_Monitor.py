# -*- coding: utf-8 -*-
"""
================================================================================
 DeepSeek 余额监控  (DeepSeek Balance Monitor)
--------------------------------------------------------------------------------
 作用：按用户设定的间隔定时查询 DeepSeek 官方接口 GET /user/balance，
       一旦「总可用余额」真的发生变化就记录一条（时间精确到毫秒），
       并可选通过 Windows 10/11 右下角原生弹窗（吐司通知）提醒扣费 / 充值。

 主程序：DeepSeek_Balance_Monitor.py  ← 唯一编译源，也是最终更新版
 文档  ：软件升级迭代记录.md          ← 唯一权威文档，每次改动必须同步更新
 备份  ：version\\DeepSeek_Balance_Monitor - <版本号> <说明>.py
 脚手架：_scaffold\\                   ← 自检 / 生成图标等工具，不参与编译
 密钥  ：.env                          ← API Key / 数据库密码，绝不硬编码进代码

 运行环境：Python 3.10+，PySide6 >= 6.5，requests >= 2.28
================================================================================
"""

from __future__ import annotations

__version__ = "1.5.0"


import base64
import csv
import json
import logging
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QEvent,
    QLockFile,
    QModelIndex,
    QObject,
    QPoint,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCloseEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# 一、全局常量（全部以 DSBM_ 开头，避免与任何其它模块 / 变量冲突）
# ==============================================================================

DSBM_APP_CN_NAME = "DeepSeek 余额监控"
DSBM_APP_EN_NAME = "DeepSeek Balance Monitor"
DSBM_APP_SHORT_NAME = "余额监控"
DSBM_APP_VERSION = __version__
DSBM_APP_ORG = "DSBM"
DSBM_APP_USER_AGENT = f"DeepSeekBalanceMonitor/{DSBM_APP_VERSION} (Windows GUI; PySide6)"

DSBM_ICON_FILENAME = "icon.ico"
DSBM_ENV_FILENAME = ".env"
DSBM_SETTINGS_FILENAME = "dsbm_settings.json"
DSBM_SQLITE_FILENAME = "dsbm_balance.db"
DSBM_LOCK_FILENAME = "dsbm_instance.lock"
DSBM_LOG_FILENAME = "dsbm_runtime.log"
DSBM_DATA_DIRNAME = "data"
DSBM_LOG_DIRNAME = "logs"
DSBM_VERSION_DIRNAME = "version"
DSBM_SCAFFOLD_DIRNAME = "_scaffold"
DSBM_BUILD_OUTPUT_DIRNAME = "build_output"

DSBM_MAIN_SCRIPT_NAME = "DeepSeek_Balance_Monitor.py"
DSBM_DOC_NAME = "软件升级迭代记录.md"

DSBM_API_DEFAULT_BASE = "https://api.deepseek.com"
DSBM_API_BALANCE_PATH = "/user/balance"
DSBM_API_DEFAULT_TIMEOUT = 20
DSBM_API_DEFAULT_RETRY = 2

DSBM_DB_TABLE_NAME = "dsbm_balance_records"
DSBM_DB_META_TABLE_NAME = "dsbm_meta"

DSBM_DEFAULT_INTERVAL_SECONDS = 60
DSBM_MIN_INTERVAL_SECONDS = 5
DSBM_MAX_INTERVAL_SECONDS = 86400
DSBM_DEFAULT_MAX_RECORDS = 500
DSBM_MIN_MAX_RECORDS = 20
DSBM_MAX_MAX_RECORDS = 50000
DSBM_SETTINGS_SAVE_DEBOUNCE_MS = 250
DSBM_CLOCK_TICK_MS = 200
DSBM_MAX_CONSECUTIVE_FAILURES_KEPT = 999

DSBM_SOURCE_SCHEDULED = "定时查询"
DSBM_SOURCE_MANUAL = "手动查询"
DSBM_SOURCE_STARTUP = "启动查询"
DSBM_SOURCE_TRAY = "托盘查询"
DSBM_SOURCE_BASELINE = "基准记录"

DSBM_COLUMN_TITLES = ("时间", "变化", "变化后余额", "来源")
DSBM_COLUMN_TIME = 0
DSBM_COLUMN_DELTA = 1
DSBM_COLUMN_BALANCE = 2
DSBM_COLUMN_SOURCE = 3

DSBM_COLOR_DEBIT = "#C0392B"      # 扣钱（余额减少）
DSBM_COLOR_CREDIT = "#0B8A3D"     # 充值（余额增加）
DSBM_COLOR_NEUTRAL = "#333333"
DSBM_COLOR_BRAND = "#4D6BFE"      # DeepSeek 主蓝
DSBM_COLOR_BRAND_DARK = "#182F9E"
DSBM_COLOR_OK = "#0B8A3D"
DSBM_COLOR_WARN = "#B7791F"
DSBM_COLOR_ERROR = "#C0392B"
DSBM_COLOR_MUTED = "#6B7280"
DSBM_COLOR_CARD_BG = "#F5F7FF"
DSBM_COLOR_CARD_BORDER = "#D6DCF7"

DSBM_UNIT_SECOND = "秒"
DSBM_UNIT_MINUTE = "分钟"
DSBM_UNIT_HOUR = "小时"
DSBM_UNIT_FACTORS = {DSBM_UNIT_SECOND: 1, DSBM_UNIT_MINUTE: 60, DSBM_UNIT_HOUR: 3600}

DSBM_NOTIFY_MODE_ALL = "all"
DSBM_NOTIFY_MODE_DEBIT = "debit"
DSBM_NOTIFY_MODE_CREDIT = "credit"
DSBM_NOTIFY_MODE_TITLES = {
    DSBM_NOTIFY_MODE_ALL: "余额变化就提示（扣费 + 充值）",
    DSBM_NOTIFY_MODE_DEBIT: "只提示扣费",
    DSBM_NOTIFY_MODE_CREDIT: "只提示充值",
}

DSBM_STORAGE_AUTO = "auto"
DSBM_STORAGE_SQLITE = "sqlite"
DSBM_STORAGE_MYSQL = "mysql"
DSBM_STORAGE_TITLES = {
    DSBM_STORAGE_AUTO: "自动（MySQL 可用则用 MySQL，否则 SQLite）",
    DSBM_STORAGE_SQLITE: "仅 SQLite（本地文件）",
    DSBM_STORAGE_MYSQL: "仅 MySQL（密码取自 .env）",
}

DSBM_UI_SCALE_CHOICES = (0.85, 1.0, 1.15, 1.3, 1.5)

# 记录表字体磅值范围（实际磅值 = table_font_size × ui_scale，行高不足时自动抬到不裁字）
DSBM_TABLE_FONT_MIN = 6.0
DSBM_TABLE_FONT_MAX = 24.0
DSBM_TABLE_FONT_DEFAULT = 9.0

DSBM_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 所有设置项的默认值。新增设置项必须在此登记，程序启动时自动合并补齐。
DSBM_SETTINGS_DEFAULTS: dict[str, Any] = {
    # ---------------- 查询 ----------------
    "query_interval_seconds": DSBM_DEFAULT_INTERVAL_SECONDS,
    "auto_query_on_start": True,
    "polling_paused": False,
    "preferred_currency": "",
    # ---------------- 通知 ----------------
    "notify_enabled": True,
    "notify_mode": DSBM_NOTIFY_MODE_ALL,
    "notify_threshold": 0.0,
    "notify_include_balance": True,
    "notify_on_repeated_failure": True,
    "notify_failure_threshold": 3,
    "tray_balloon_fallback": True,
    # ---------------- 记录 ----------------
    "max_records": DSBM_DEFAULT_MAX_RECORDS,
    "record_baseline": True,
    "only_debit_filter": False,
    "only_credit_filter": False,
    "csv_export_dir": "",
    "csv_export_visible_only": True,
    # ---------------- 存储 ----------------
    "storage_backend": DSBM_STORAGE_AUTO,
    "storage_enabled": True,
    # ---------------- 界面 ----------------
    "ui_scale": 1.0,
    "single_instance": True,
    "close_to_tray": True,
    "minimize_to_tray": False,
    "show_tray_icon": True,
    "use_builtin_icon_if_missing": True,
    "table_sort_column": DSBM_COLUMN_TIME,
    "table_sort_order": 1,
    "table_column_widths": [],
    "table_row_height": 22,
    "table_font_size": DSBM_TABLE_FONT_DEFAULT,
    "window_geometry": "",
    "window_state": "",
    "window_maximized": False,
    # ---------------- 运行记忆（跨启动保持逻辑连续，避免漏记 / 重复记账）----------------
    "settings_schema_version": 1,
    "last_balance": "",
    "last_balance_currency": "",
    "last_balance_time_ms": 0,
    "last_success_time_ms": 0,
    "last_query_duration_ms": 0,
    "last_query_attempts": 0,
    "total_query_count": 0,
    "failed_query_count": 0,
    "consecutive_failures": 0,
    "last_error_message": "",
}

# .env 模板：文件缺失时自动生成（不含真实密钥）
DSBM_ENV_TEMPLATE_LINES = [
    "# ============================================================",
    "# DeepSeek 余额监控 —— 敏感配置（请勿提交到公开仓库）",
    "# 本文件由程序与设置窗口共同维护：保留注释与顺序，只更新已存在的键值。",
    "# ============================================================",
    "",
    "# ---- DeepSeek 接口 ----",
    "DEEPSEEK_API_BASE=https://api.deepseek.com",
    "DEEPSEEK_API_KEY=sk-在此填写你的Key",
    "DEEPSEEK_TIMEOUT=20",
    "DEEPSEEK_MAX_RETRY=2",
    "",
    "# ---- 数据库（可选；默认使用本地 SQLite，不需要密码）----",
    "DSBM_DB_HOST=127.0.0.1",
    "DSBM_DB_PORT=3306",
    "DSBM_DB_USER=",
    "DSBM_DB_PASSWORD=",
    "DSBM_DB_NAME=",
    "DSBM_DB_CHARSET=utf8mb4",
    "",
]


# ==============================================================================
# 二、路径与通用小工具（全部以 dsbm_ 开头）
# ==============================================================================


def dsbm_project_dir() -> Path:
    """程序根目录：源码运行时＝脚本目录；Nuitka/PyInstaller 打包后＝exe 目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def dsbm_data_dir() -> Path:
    override = os.environ.get("DSBM_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return dsbm_project_dir() / DSBM_DATA_DIRNAME


def dsbm_log_dir() -> Path:
    override = os.environ.get("DSBM_LOG_DIR", "").strip()
    if override:
        return Path(override)
    return dsbm_project_dir() / DSBM_LOG_DIRNAME


def dsbm_version_dir() -> Path:
    return dsbm_project_dir() / DSBM_VERSION_DIRNAME


def dsbm_scaffold_dir() -> Path:
    return dsbm_project_dir() / DSBM_SCAFFOLD_DIRNAME


def dsbm_settings_path() -> Path:
    return dsbm_data_dir() / DSBM_SETTINGS_FILENAME


def dsbm_sqlite_path() -> Path:
    return dsbm_data_dir() / DSBM_SQLITE_FILENAME


def dsbm_lock_path() -> Path:
    return dsbm_data_dir() / DSBM_LOCK_FILENAME


def dsbm_icon_path() -> Path:
    return dsbm_project_dir() / DSBM_ICON_FILENAME


def dsbm_env_path() -> Path:
    override = os.environ.get("DSBM_ENV_FILE", "").strip()
    if override:
        return Path(override)
    return dsbm_project_dir() / DSBM_ENV_FILENAME


def dsbm_log_path() -> Path:
    return dsbm_log_dir() / DSBM_LOG_FILENAME


def dsbm_ensure_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - 极端权限问题
        print(f"[DSBM] 无法创建目录 {path}: {exc}", file=sys.stderr)
    return path


def dsbm_now_ms() -> int:
    return int(time.time() * 1000)


def dsbm_format_time_ms(epoch_ms: int) -> str:
    """把毫秒时间戳格式化成 2026-10-06 09:50:09.934。"""
    if not epoch_ms:
        return "-"
    try:
        moment = datetime.fromtimestamp(epoch_ms / 1000.0)
    except (OverflowError, OSError, ValueError):
        return "-"
    return moment.strftime("%Y-%m-%d %H:%M:%S") + f".{moment.microsecond // 1000:03d}"


def dsbm_format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.1f} 分钟"
    if seconds < 86400:
        return f"{seconds / 3600:.2f} 小时"
    return f"{seconds / 86400:.2f} 天"


def dsbm_to_decimal(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError, TypeError):
        return Decimal(default)


def dsbm_quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def dsbm_format_money(value: Any, digits: int = 2) -> str:
    text = f"{dsbm_to_decimal(value):.{digits}f}"
    if text.startswith("-") and dsbm_to_decimal(text) == 0:
        text = text.lstrip("-")
    return text


def dsbm_format_signed(value: Any) -> str:
    amount = dsbm_to_decimal(value)
    text = f"{amount:.2f}"
    if amount > 0:
        return "+" + text
    return text


def dsbm_money_brush(value: Decimal) -> QColor:
    if value < 0:
        return QColor(DSBM_COLOR_DEBIT)
    if value > 0:
        return QColor(DSBM_COLOR_CREDIT)
    return QColor(DSBM_COLOR_NEUTRAL)


def dsbm_mask_secret(secret: str, keep_head: int = 7, keep_tail: int = 4) -> str:
    """密钥脱敏显示：sk-e9ff...abcd。绝不在日志 / 界面显示完整密钥。"""
    secret = (secret or "").strip()
    if not secret:
        return "未配置"
    if len(secret) <= keep_head + keep_tail:
        return secret[0] + "*" * max(0, len(secret) - 1)
    return f"{secret[:keep_head]}...{secret[-keep_tail:]}"


def dsbm_interval_to_parts(seconds: int) -> tuple[int, str]:
    """把秒数换算成最合适的（数值, 单位），用于界面显示。"""
    seconds = int(max(DSBM_MIN_INTERVAL_SECONDS, min(DSBM_MAX_INTERVAL_SECONDS, seconds)))
    if seconds % 3600 == 0:
        return seconds // 3600, DSBM_UNIT_HOUR
    if seconds % 60 == 0:
        return seconds // 60, DSBM_UNIT_MINUTE
    return seconds, DSBM_UNIT_SECOND


def dsbm_parts_to_interval(amount: int, unit: str) -> int:
    factor = DSBM_UNIT_FACTORS.get(unit, 1)
    return int(max(DSBM_MIN_INTERVAL_SECONDS,
                   min(DSBM_MAX_INTERVAL_SECONDS, int(amount) * factor)))


def dsbm_elide_text(painter_metrics: QFontMetrics, text: str, width: int) -> str:
    return painter_metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(16, width))


def dsbm_draw_brand_pixmap(size: int) -> QPixmap:
    """程序内置绘制图标：圆角蓝渐变底 + 白色余额曲线。icon.ico 缺失时给托盘用。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(DSBM_COLOR_BRAND))
    gradient.setColorAt(1.0, QColor(DSBM_COLOR_BRAND_DARK))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    radius = max(2.0, size * 0.22)
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    pen = QPen(QColor(255, 255, 255))
    pen.setWidthF(max(1.2, size * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    margin = size * 0.22
    painter.drawPolyline([
        QPoint(int(margin), int(size - margin * 1.15)),
        QPoint(int(size * 0.42), int(size * 0.52)),
        QPoint(int(size * 0.60), int(size * 0.68)),
        QPoint(int(size - margin), int(margin * 1.05)),
    ])
    painter.end()
    return pixmap


def dsbm_load_app_icon(allow_builtin: bool = True) -> QIcon:
    """图标策略：icon.ico 存在就用它；不存在且允许内置绘制时用内置图标，否则返回空图标。"""
    icon_file = dsbm_icon_path()
    if icon_file.is_file():
        icon = QIcon(str(icon_file))
        if not icon.isNull():
            return icon
    if allow_builtin:
        icon = QIcon()
        for size in DSBM_ICON_SIZES:
            icon.addPixmap(dsbm_draw_brand_pixmap(size))
        return icon
    return QIcon()


# ==============================================================================
# 三、日志
# ==============================================================================

DSBM_LOGGER_NAME = "dsbm.runtime"
_DSBM_LOGGER_READY = False


def dsbm_setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化日志：同时输出到控制台（若存在）与 logs\\dsbm_runtime.log（滚动 2MB×3）。"""
    global _DSBM_LOGGER_READY
    logger = logging.getLogger(DSBM_LOGGER_NAME)
    if _DSBM_LOGGER_READY:
        return logger
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        dsbm_ensure_dir(dsbm_log_dir())
        file_handler = RotatingFileHandler(
            str(dsbm_log_path()), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover
        print(f"[DSBM] 日志文件不可写：{exc}", file=sys.stderr)
    if sys.stderr is not None and sys.stderr.isatty():
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    _DSBM_LOGGER_READY = True
    return logger


# ==============================================================================
# 四、.env 读写（API Key / 数据库密码只放这里，代码里永不硬编码）
# ==============================================================================

DSBM_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

DSBM_ENV_KEY_API_BASE = "DEEPSEEK_API_BASE"
DSBM_ENV_KEY_API_KEY = "***已脱敏***-apikey"
DSBM_ENV_KEY_TIMEOUT = "DEEPSEEK_TIMEOUT"
DSBM_ENV_KEY_MAX_RETRY = "DEEPSEEK_MAX_RETRY"
DSBM_ENV_KEY_DB_HOST = "DSBM_DB_HOST"
DSBM_ENV_KEY_DB_PORT = "DSBM_DB_PORT"
DSBM_ENV_KEY_DB_USER = "DSBM_DB_USER"
DSBM_ENV_KEY_DB_PASSWORD = "DSBM_DB_PASSWORD"
DSBM_ENV_KEY_DB_NAME = "DSBM_DB_NAME"
DSBM_ENV_KEY_DB_CHARSET = "DSBM_DB_CHARSET"


class DsbmEnvFileManager:
    """极简 .env 管理器：读取系统环境变量兜底，写入时保留注释 / 顺序 / 未知键。"""

    def __init__(self, env_file: Path | None = None) -> None:
        self.dsenv_path = Path(env_file) if env_file else dsbm_env_path()
        self.dsenv_cache: dict[str, str] = {}
        self.dsenv_logger = logging.getLogger(DSBM_LOGGER_NAME)
        self.dsenv_reload()

    # ---------------------------------------------------------------- 读取
    def dsenv_reload(self) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            if self.dsenv_path.is_file():
                raw = self.dsenv_path.read_text(encoding="utf-8-sig", errors="replace")
            else:
                raw = ""
        except OSError as exc:
            self.dsenv_logger.warning("读取 .env 失败：%s", exc)
            raw = ""
        for line in raw.splitlines():
            match = DSBM_ENV_LINE_RE.match(line)
            if not match:
                continue
            key = match.group(1)
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
        self.dsenv_cache = values
        return dict(values)

    def dsenv_get(self, key: str, default: str = "") -> str:
        value = self.dsenv_cache.get(key)
        if value is None or value == "":
            env_value = os.environ.get(key, "")
            if env_value:
                return env_value
            return default
        return value

    def dsenv_get_int(self, key: str, default: int, low: int, high: int) -> int:
        try:
            number = int(float(str(self.dsenv_get(key, str(default))).strip()))
        except (TypeError, ValueError):
            return default
        return int(max(low, min(high, number)))

    # ---------------------------------------------------------------- 写入
    def dsenv_ensure_file(self, template_lines: Sequence[str] | None = None) -> bool:
        if self.dsenv_path.is_file():
            return False
        lines = list(template_lines if template_lines is not None else DSBM_ENV_TEMPLATE_LINES)
        try:
            dsbm_ensure_dir(self.dsenv_path.parent)
            self.dsenv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            self.dsenv_logger.error("生成 .env 失败：%s", exc)
            return False
        self.dsenv_reload()
        return True

    def dsenv_set_many(self, mapping: dict[str, str]) -> bool:
        """原子写回：已存在的键就地更新，不存在的键追加到末尾，注释与顺序全部保留。"""
        mapping = {k: ("" if v is None else str(v)) for k, v in mapping.items()}
        if not mapping:
            return True
        try:
            if self.dsenv_path.is_file():
                original = self.dsenv_path.read_text(encoding="utf-8-sig", errors="replace")
            else:
                original = "\n".join(DSBM_ENV_TEMPLATE_LINES) + "\n"
        except OSError as exc:
            self.dsenv_logger.error("读取 .env 失败，无法写入：%s", exc)
            return False
        if "\r\n" in original:
            newline = "\r\n"
        else:
            newline = "\n"
        lines = original.replace("\r\n", "\n").split("\n")
        remaining = dict(mapping)
        for index, line in enumerate(lines):
            match = DSBM_ENV_LINE_RE.match(line)
            if not match:
                continue
            key = match.group(1)
            if key in remaining:
                lines[index] = f"{key}={remaining.pop(key)}"
        for key in list(remaining.keys()):
            lines.append(f"{key}={remaining.pop(key)}")
        text = newline.join(lines)
        if not text.endswith(newline):
            text += newline
        temp_path = self.dsenv_path.with_suffix(self.dsenv_path.suffix + ".tmp")
        try:
            dsbm_ensure_dir(self.dsenv_path.parent)
            temp_path.write_text(text, encoding="utf-8", newline="")
            os.replace(temp_path, self.dsenv_path)
        except OSError as exc:
            self.dsenv_logger.error("写入 .env 失败：%s", exc)
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            return False
        self.dsenv_reload()
        self.dsenv_logger.info("已更新 .env 中的键：%s", "、".join(mapping.keys()))
        return True

    # ---------------------------------------------------------------- 语义读取
    def dsenv_api_key(self) -> str:
        return self.dsenv_get(DSBM_ENV_KEY_API_KEY, "").strip()

    def dsenv_api_base(self) -> str:
        raw = self.dsenv_get(DSBM_ENV_KEY_API_BASE, DSBM_API_DEFAULT_BASE).strip()
        if not raw:
            raw = DSBM_API_DEFAULT_BASE
        return raw.rstrip("/")

    def dsenv_timeout(self) -> int:
        return self.dsenv_get_int(DSBM_ENV_KEY_TIMEOUT, DSBM_API_DEFAULT_TIMEOUT, 3, 120)

    def dsenv_max_retry(self) -> int:
        return self.dsenv_get_int(DSBM_ENV_KEY_MAX_RETRY, DSBM_API_DEFAULT_RETRY, 0, 10)

    def dsenv_db_config(self) -> dict[str, Any]:
        return {
            "host": self.dsenv_get(DSBM_ENV_KEY_DB_HOST, "127.0.0.1").strip(),
            "port": self.dsenv_get_int(DSBM_ENV_KEY_DB_PORT, 3306, 1, 65535),
            "user": self.dsenv_get(DSBM_ENV_KEY_DB_USER, "").strip(),
            "password": self.dsenv_get(DSBM_ENV_KEY_DB_PASSWORD, ""),
            "name": self.dsenv_get(DSBM_ENV_KEY_DB_NAME, "").strip(),
            "charset": self.dsenv_get(DSBM_ENV_KEY_DB_CHARSET, "utf8mb4").strip() or "utf8mb4",
        }

    def dsenv_db_configured(self) -> bool:
        config = self.dsenv_db_config()
        return bool(config["host"] and config["user"] and config["name"])

    def dsenv_masked_summary(self) -> dict[str, str]:
        config = self.dsenv_db_config()
        return {
            "api_base": self.dsenv_api_base(),
            "api_key": dsbm_mask_secret(self.dsenv_api_key()),
            "timeout": str(self.dsenv_timeout()),
            "max_retry": str(self.dsenv_max_retry()),
            "db_host": config["host"],
            "db_port": str(config["port"]),
            "db_user": config["user"] or "（未配置）",
            "db_password": "（已设置）" if config["password"] else "（未配置）",
            "db_name": config["name"] or "（未配置）",
        }


# ==============================================================================
# 五、设置管理（实时自动保存 + 重启自动加载）
# ==============================================================================


class DsbmSettingsManager(QObject):
    """JSON 设置仓库：任何一项改动 → 250ms 防抖后立即原子写盘，下次启动自动加载。"""

    dsgset_value_changed = Signal(str, object)

    def __init__(self, settings_file: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.dsgset_path = Path(settings_file) if settings_file else dsbm_settings_path()
        self.dsgset_logger = logging.getLogger(DSBM_LOGGER_NAME)
        self.dsgset_values: dict[str, Any] = dict(DSBM_SETTINGS_DEFAULTS)
        self.dsgset_save_timer = QTimer(self)
        self.dsgset_save_timer.setSingleShot(True)
        self.dsgset_save_timer.setInterval(DSBM_SETTINGS_SAVE_DEBOUNCE_MS)
        self.dsgset_save_timer.timeout.connect(self.dsgset_save_to_disk)
        self.dsgset_load_from_disk()

    # ------------------------------------------------------------------ 加载
    def dsgset_load_from_disk(self) -> bool:
        """读取设置文件并与默认值合并（补齐新增设置项，保留未知键以便向前兼容）。"""
        merged: dict[str, Any] = dict(DSBM_SETTINGS_DEFAULTS)
        existed = self.dsgset_path.is_file()
        if existed:
            try:
                raw = json.loads(self.dsgset_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        merged[key] = value
            except (OSError, ValueError) as exc:
                self.dsgset_logger.error("设置文件解析失败，已回退默认值：%s", exc)
                try:
                    broken = self.dsgset_path.with_suffix(".broken.json")
                    self.dsgset_path.replace(broken)
                    self.dsgset_logger.warning("损坏的设置已备份为：%s", broken.name)
                except OSError:
                    pass
        self.dsgset_values = merged
        self.dsgset_normalize()
        if not existed:
            self.dsgset_save_to_disk()
        self.dsgset_logger.info("设置已加载：%s", self.dsgset_path)
        return existed

    def dsgset_normalize(self) -> None:
        """把越界 / 类型异常的值纠正到合法区间，避免旧配置破坏程序。"""
        interval = self.dsgset_get_int("query_interval_seconds", DSBM_DEFAULT_INTERVAL_SECONDS)
        self.dsgset_values["query_interval_seconds"] = int(
            max(DSBM_MIN_INTERVAL_SECONDS, min(DSBM_MAX_INTERVAL_SECONDS, interval))
        )
        keep = self.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
        self.dsgset_values["max_records"] = int(
            max(DSBM_MIN_MAX_RECORDS, min(DSBM_MAX_MAX_RECORDS, keep))
        )
        scale = float(self.dsgset_get_float("ui_scale", 1.0) or 1.0)
        self.dsgset_values["ui_scale"] = float(max(0.75, min(2.0, scale)))
        if self.dsgset_get("notify_mode") not in DSBM_NOTIFY_MODE_TITLES:
            self.dsgset_values["notify_mode"] = DSBM_NOTIFY_MODE_ALL
        if self.dsgset_get("storage_backend") not in DSBM_STORAGE_TITLES:
            self.dsgset_values["storage_backend"] = DSBM_STORAGE_AUTO
        order = self.dsgset_get_int("table_sort_order", 1)
        self.dsgset_values["table_sort_order"] = 1 if order >= 1 else 0
        column = self.dsgset_get_int("table_sort_column", DSBM_COLUMN_TIME)
        self.dsgset_values["table_sort_column"] = int(
            max(0, min(len(DSBM_COLUMN_TITLES) - 1, column))
        )
        row_height = self.dsgset_get_int("table_row_height", 22)
        self.dsgset_values["table_row_height"] = int(max(16, min(48, row_height)))
        font_size = self.dsgset_get_float("table_font_size", DSBM_TABLE_FONT_DEFAULT)
        self.dsgset_values["table_font_size"] = float(
            max(DSBM_TABLE_FONT_MIN, min(DSBM_TABLE_FONT_MAX, font_size))
        )
        failure_limit = self.dsgset_get_int("notify_failure_threshold", 3)
        self.dsgset_values["notify_failure_threshold"] = int(max(1, min(99, failure_limit)))
        consecutive = self.dsgset_get_int("consecutive_failures", 0)
        self.dsgset_values["consecutive_failures"] = int(
            max(0, min(DSBM_MAX_CONSECUTIVE_FAILURES_KEPT, consecutive))
        )
        widths = self.dsgset_get("table_column_widths", [])
        if not isinstance(widths, list):
            self.dsgset_values["table_column_widths"] = []
        else:
            clean: list[int] = []
            for item in widths[: len(DSBM_COLUMN_TITLES)]:
                try:
                    clean.append(int(max(0, min(4000, int(item)))))
                except (TypeError, ValueError):
                    clean.append(0)
            self.dsgset_values["table_column_widths"] = clean

    # ------------------------------------------------------------------ 读取
    def dsgset_get(self, key: str, default: Any = None) -> Any:
        if key in self.dsgset_values:
            return self.dsgset_values[key]
        if key in DSBM_SETTINGS_DEFAULTS:
            return DSBM_SETTINGS_DEFAULTS[key]
        return default

    def dsgset_get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self.dsgset_get(key, default))

    def dsgset_get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.dsgset_get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def dsgset_get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.dsgset_get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def dsgset_get_str(self, key: str, default: str = "") -> str:
        value = self.dsgset_get(key, default)
        return default if value is None else str(value)

    def dsgset_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.dsgset_values, ensure_ascii=False, default=str))

    # ------------------------------------------------------------------ 写入
    def dsgset_set(self, key: str, value: Any, notify: bool = True) -> None:
        """设置一项并立即安排落盘（防抖 250ms），同时广播变更信号。"""
        if self.dsgset_values.get(key) == value:
            return
        self.dsgset_values[key] = value
        self.dsgset_save_timer.start()
        if notify:
            self.dsgset_value_changed.emit(key, value)

    def dsgset_update_many(self, mapping: dict[str, Any], notify: bool = True) -> None:
        changed: list[str] = []
        for key, value in mapping.items():
            if self.dsgset_values.get(key) == value:
                continue
            self.dsgset_values[key] = value
            changed.append(key)
        if not changed:
            return
        self.dsgset_save_timer.start()
        if notify:
            for key in changed:
                self.dsgset_value_changed.emit(key, self.dsgset_values[key])

    def dsgset_reset_to_defaults(self) -> None:
        geometry = self.dsgset_get("window_geometry", "")
        state = self.dsgset_get("window_state", "")
        self.dsgset_values = dict(DSBM_SETTINGS_DEFAULTS)
        self.dsgset_values["window_geometry"] = geometry
        self.dsgset_values["window_state"] = state
        self.dsgset_save_to_disk()
        self.dsgset_logger.info("设置已恢复默认值（窗口位置保留）")

    def dsgset_flush(self) -> None:
        """退出前强制落盘。"""
        if self.dsgset_save_timer.isActive():
            self.dsgset_save_timer.stop()
        self.dsgset_save_to_disk()

    @Slot()
    def dsgset_save_to_disk(self) -> bool:
        try:
            dsbm_ensure_dir(self.dsgset_path.parent)
            payload = json.dumps(
                self.dsgset_values, ensure_ascii=False, indent=2, default=str, sort_keys=True
            )
            temp_path = self.dsgset_path.with_suffix(self.dsgset_path.suffix + ".tmp")
            temp_path.write_text(payload, encoding="utf-8", newline="")
            os.replace(temp_path, self.dsgset_path)
            return True
        except OSError as exc:
            self.dsgset_logger.error("写入设置失败：%s", exc)
            return False

    # ------------------------------------------------------- 窗口几何 / 表头宽度
    def dsgset_store_geometry(self, geometry: QByteArray, state: QByteArray, maximized: bool) -> None:
        self.dsgset_set("window_geometry", bytes(geometry.toBase64()).decode("ascii"))
        self.dsgset_set("window_state", bytes(state.toBase64()).decode("ascii"))
        self.dsgset_set("window_maximized", bool(maximized))

    def dsgset_restore_geometry(self) -> tuple[QByteArray, QByteArray, bool]:
        def decode(text: str) -> QByteArray:
            if not text:
                return QByteArray()
            try:
                return QByteArray.fromBase64(text.encode("ascii"))
            except (ValueError, UnicodeEncodeError):
                return QByteArray()

        geometry = decode(self.dsgset_get_str("window_geometry"))
        state = decode(self.dsgset_get_str("window_state"))
        return geometry, state, self.dsgset_get_bool("window_maximized")

    def dsgset_store_column_widths(self, widths: Sequence[int]) -> None:
        self.dsgset_set("table_column_widths", [int(max(0, w)) for w in widths])


# ==============================================================================
# 六、记录数据结构
# ==============================================================================


@dataclass
class DsbmBalanceRecord:
    """一条余额变化记录。时间为毫秒级 epoch；金额用 Decimal 保证精度。"""

    dsrec_time_ms: int
    dsrec_delta: Decimal
    dsrec_balance: Decimal
    dsrec_currency: str
    dsrec_source: str

    def dsrec_as_csv_row(self) -> list[str]:
        return [
            dsbm_format_time_ms(self.dsrec_time_ms),
            f"{self.dsrec_delta:.2f}",
            f"{self.dsrec_balance:.2f}",
            self.dsrec_currency,
            self.dsrec_source,
        ]

    def dsrec_as_sql_tuple(self) -> tuple:
        return (
            int(self.dsrec_time_ms),
            f"{self.dsrec_delta:.2f}",
            f"{self.dsrec_balance:.2f}",
            self.dsrec_currency,
            self.dsrec_source,
        )


# ==============================================================================
# 七、记录表模型（QAbstractTableModel：排序 / 过滤 / 着色 / 统计）
# ==============================================================================


class DsbmRecordTableModel(QAbstractTableModel):
    """表格模型：只保存「余额真正变化」的记录，支持只看扣钱 / 只看增加、按列排序、正负着色。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.dmrec_records: list[DsbmBalanceRecord] = []
        self.dmrec_visible: list[DsbmBalanceRecord] = []
        self.dmrec_only_debit = False
        self.dmrec_only_credit = False
        self.dmrec_sort_column = DSBM_COLUMN_TIME
        self.dmrec_sort_order = 1
        self.dmrec_font_datetime = QFont()
        self.dmrec_font_datetime.setFamily("Consolas")
        self.dmrec_font_datetime.setPointSizeF(max(8.0, self.dmrec_font_datetime.pointSizeF() - 0.5))

    def dmrec_apply_font(self, base_font: QFont) -> None:
        """时间列用的等宽字体跟随列表字体：比基础磅值小 0.5 磅（最小 8 磅）。"""
        if base_font.pointSizeF() > 0:
            points = max(8.0, base_font.pointSizeF() - 0.5)
        else:
            points = 8.0
        font = QFont(base_font)
        font.setFamily("Consolas")
        font.setPointSizeF(points)
        self.dmrec_font_datetime = font
        if self.dmrec_visible:
            self.dataChanged.emit(
                self.index(0, DSBM_COLUMN_TIME),
                self.index(len(self.dmrec_visible) - 1, DSBM_COLUMN_TIME),
                [Qt.ItemDataRole.FontRole],
            )

    # ------------------------------------------------------------ 数据操作
    def dmrec_set_records(self, records: Iterable[DsbmBalanceRecord]) -> None:
        self.beginResetModel()
        self.dmrec_records = list(records)
        self.dmrec_rebuild_visible()
        self.endResetModel()

    def dmrec_append_record(self, record: DsbmBalanceRecord) -> int:
        """追加一条记录，返回它在可见列表中的行号（-1 表示被当前筛选隐藏）。"""
        row = len(self.dmrec_records)
        self.beginInsertRows(QModelIndex(), row, row)
        self.dmrec_records.append(record)
        self.endInsertRows()
        if not self.dmrec_matches_filter(record):
            self.dmrec_rebuild_visible()
            return -1
        self.dmrec_rebuild_visible()
        for index, item in enumerate(self.dmrec_visible):
            if item is record:
                return index
        return -1

    def dmrec_clear_records(self) -> None:
        self.beginResetModel()
        self.dmrec_records = []
        self.dmrec_visible = []
        self.endResetModel()

    def dmrec_delete_record_at(self, row: int) -> bool:
        if not (0 <= row < len(self.dmrec_visible)):
            return False
        victim = self.dmrec_visible[row]
        self.beginResetModel()
        try:
            self.dmrec_records.remove(victim)
        except ValueError:
            self.endResetModel()
            return False
        self.dmrec_rebuild_visible()
        self.endResetModel()
        return True

    def dmrec_set_only_debit(self, flag: bool) -> None:
        """只看扣钱：勾上即自动取消「只看增加」（两者互斥）。"""
        flag = bool(flag)
        self.dmrec_set_filter_sides(flag, False if flag else self.dmrec_only_credit)

    def dmrec_set_only_credit(self, flag: bool) -> None:
        """只看增加：勾上即自动取消「只看扣钱」（两者互斥）。"""
        flag = bool(flag)
        self.dmrec_set_filter_sides(False if flag else self.dmrec_only_debit, flag)

    def dmrec_set_filter_sides(self, debit: bool, credit: bool) -> None:
        """同时设置两个方向，并保证最多只有一个生效。"""
        debit, credit = bool(debit), bool(credit)
        if debit and credit:
            credit = False
        if debit == self.dmrec_only_debit and credit == self.dmrec_only_credit:
            return
        self.beginResetModel()
        self.dmrec_only_debit = debit
        self.dmrec_only_credit = credit
        self.dmrec_rebuild_visible()
        self.endResetModel()

    def dmrec_set_sort_state(self, column: int, order: int) -> None:
        self.beginResetModel()
        self.dmrec_sort_column = int(column)
        self.dmrec_sort_order = 1 if int(order) >= 1 else 0
        self.dmrec_rebuild_visible()
        self.endResetModel()

    def dmrec_matches_filter(self, record: DsbmBalanceRecord) -> bool:
        if self.dmrec_only_debit:
            return record.dsrec_delta < 0
        if self.dmrec_only_credit:
            return record.dsrec_delta > 0
        return True

    def dmrec_rebuild_visible(self) -> None:
        visible = [r for r in self.dmrec_records if self.dmrec_matches_filter(r)]
        column = self.dmrec_sort_column
        reverse = self.dmrec_sort_order == 1
        key_map = {
            DSBM_COLUMN_TIME: lambda r: r.dsrec_time_ms,
            DSBM_COLUMN_DELTA: lambda r: r.dsrec_delta,
            DSBM_COLUMN_BALANCE: lambda r: r.dsrec_balance,
            DSBM_COLUMN_SOURCE: lambda r: r.dsrec_source,
        }
        key_func = key_map.get(column, key_map[DSBM_COLUMN_TIME])
        visible.sort(key=lambda r: (key_func(r), r.dsrec_time_ms), reverse=reverse)
        self.dmrec_visible = visible

    def dmrec_visible_records(self) -> list[DsbmBalanceRecord]:
        return list(self.dmrec_visible)

    def dmrec_all_records(self) -> list[DsbmBalanceRecord]:
        return list(self.dmrec_records)

    def dmrec_record_at(self, row: int) -> DsbmBalanceRecord | None:
        if 0 <= row < len(self.dmrec_visible):
            return self.dmrec_visible[row]
        return None

    def dmrec_record_count(self) -> int:
        return len(self.dmrec_records)

    def dmrec_visible_count(self) -> int:
        return len(self.dmrec_visible)

    def dmrec_debit_count(self) -> int:
        return sum(1 for r in self.dmrec_records if r.dsrec_delta < 0)

    # ------------------------------------------------------------ 统计信息
    def dmrec_statistics(self) -> dict[str, Any]:
        debits = [r for r in self.dmrec_records if r.dsrec_delta < 0]
        credits = [r for r in self.dmrec_records if r.dsrec_delta > 0]
        debit_sum = sum((r.dsrec_delta for r in debits), Decimal("0"))
        credit_sum = sum((r.dsrec_delta for r in credits), Decimal("0"))
        latest = None
        if self.dmrec_records:
            latest = max(self.dmrec_records, key=lambda r: r.dsrec_time_ms)
        oldest_ms = min((r.dsrec_time_ms for r in self.dmrec_records), default=0)
        span_hours = 0.0
        rate_per_hour = Decimal("0")
        if latest is not None and oldest_ms and latest.dsrec_time_ms > oldest_ms:
            span_hours = (latest.dsrec_time_ms - oldest_ms) / 3600000.0
            if span_hours > 0 and debit_sum < 0:
                rate_per_hour = (abs(debit_sum) / Decimal(str(span_hours))).quantize(Decimal("0.0001"))
        return {
            "total": len(self.dmrec_records),
            "visible": len(self.dmrec_visible),
            "debit_count": len(debits),
            "debit_sum": debit_sum,
            "credit_count": len(credits),
            "credit_sum": credit_sum,
            "latest": latest,
            "oldest_ms": oldest_ms,
            "span_hours": span_hours,
            "rate_per_hour": rate_per_hour,
        }

    # ------------------------------------------------------------ Qt 接口
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.dmrec_visible)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(DSBM_COLUMN_TITLES)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        record = self.dmrec_record_at(index.row())
        if record is None:
            return None
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == DSBM_COLUMN_TIME:
                return dsbm_format_time_ms(record.dsrec_time_ms)
            if column == DSBM_COLUMN_DELTA:
                return dsbm_format_signed(record.dsrec_delta)
            if column == DSBM_COLUMN_BALANCE:
                suffix = f" {record.dsrec_currency}" if record.dsrec_currency else ""
                return f"{dsbm_format_money(record.dsrec_balance)}{suffix}"
            if column == DSBM_COLUMN_SOURCE:
                return record.dsrec_source
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == DSBM_COLUMN_DELTA:
                return QBrush(dsbm_money_brush(record.dsrec_delta))
            if column == DSBM_COLUMN_BALANCE:
                return QBrush(QColor(DSBM_COLOR_NEUTRAL))
            if column == DSBM_COLUMN_SOURCE:
                return QBrush(QColor(DSBM_COLOR_MUTED))
            return QBrush(QColor(DSBM_COLOR_NEUTRAL))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (DSBM_COLUMN_DELTA, DSBM_COLUMN_BALANCE):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column == DSBM_COLUMN_TIME:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.FontRole and column == DSBM_COLUMN_TIME:
            return self.dmrec_font_datetime
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"时间：{dsbm_format_time_ms(record.dsrec_time_ms)}\n"
                f"变化：{dsbm_format_signed(record.dsrec_delta)} {record.dsrec_currency}\n"
                f"变化后余额：{dsbm_format_money(record.dsrec_balance)} {record.dsrec_currency}\n"
                f"来源：{record.dsrec_source}"
            )
        if role == Qt.ItemDataRole.UserRole:
            return record
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(DSBM_COLUMN_TITLES):
                return DSBM_COLUMN_TITLES[section]
            return None
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.dmrec_set_sort_state(column, 1 if order == Qt.SortOrder.DescendingOrder else 0)


# ==============================================================================
# 八、记录持久化（SQLite 默认 / MySQL 可选，密码取自 .env）
# ==============================================================================


class DsbmRecordStore(QObject):
    """记录仓库。默认本地 SQLite；.env 配好 MySQL 且驱动可用时可切换（自动回退 SQLite）。"""

    dsdb_backend_changed = Signal(str)

    def __init__(
        self,
        settings_manager: DsbmSettingsManager,
        env_manager: DsbmEnvFileManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.dsdb_settings = settings_manager
        self.dsdb_env = env_manager
        self.dsdb_logger = logging.getLogger(DSBM_LOGGER_NAME)
        self.dsdb_backend = DSBM_STORAGE_SQLITE
        self.dsdb_sqlite_conn: sqlite3.Connection | None = None
        self.dsdb_mysql_conn: Any = None
        self.dsdb_mysql_module: Any = None
        self.dsdb_sqlite_path = dsbm_sqlite_path()
        self.dsdb_ready = False
        self.dsdb_status_text = "未初始化"
        self.dsdb_lock = threading.RLock()

    # ------------------------------------------------------------ 初始化
    def dsdb_initialize(self) -> tuple[bool, str]:
        """按设置选择后端并建表。返回（是否成功, 说明文本）。"""
        with self.dsdb_lock:
            self.dsdb_close_connections()
            if not self.dsdb_settings.dsgset_get_bool("storage_enabled", True):
                self.dsdb_backend = "memory"
                self.dsdb_ready = True
                self.dsdb_status_text = "内存模式（未写盘，重启即清空）"
                self.dsdb_backend_changed.emit(self.dsdb_status_text)
                return True, self.dsdb_status_text
            wanted = self.dsdb_settings.dsgset_get_str("storage_backend", DSBM_STORAGE_AUTO)
            mysql_ok = False
            if wanted in (DSBM_STORAGE_AUTO, DSBM_STORAGE_MYSQL):
                mysql_ok = self.dsdb_connect_mysql()
                if not mysql_ok and wanted == DSBM_STORAGE_MYSQL:
                    self.dsdb_logger.warning("MySQL 不可用，已自动回退 SQLite：%s", self.dsdb_mysql_hint)
            if mysql_ok:
                self.dsdb_backend = DSBM_STORAGE_MYSQL
                config = self.dsdb_env.dsenv_db_config()
                self.dsdb_status_text = (
                    f"MySQL {config['host']}:{config['port']}/{config['name']}"
                )
            else:
                if not self.dsdb_connect_sqlite():
                    self.dsdb_ready = False
                    self.dsdb_status_text = "SQLite 初始化失败（详见日志）"
                    self.dsdb_backend_changed.emit(self.dsdb_status_text)
                    return False, self.dsdb_status_text
                self.dsdb_backend = DSBM_STORAGE_SQLITE
                self.dsdb_status_text = f"SQLite {self.dsdb_sqlite_path.name}"
            self.dsdb_ready = True
            self.dsdb_backend_changed.emit(self.dsdb_status_text)
            self.dsdb_logger.info("记录仓库就绪：%s", self.dsdb_status_text)
            return True, self.dsdb_status_text

    def dsdb_connect_sqlite(self) -> bool:
        try:
            dsbm_ensure_dir(self.dsdb_sqlite_path.parent)
            self.dsdb_sqlite_conn = sqlite3.connect(
                str(self.dsdb_sqlite_path), timeout=10.0, check_same_thread=False
            )
            self.dsdb_sqlite_conn.execute("PRAGMA journal_mode=WAL")
            self.dsdb_sqlite_conn.execute("PRAGMA synchronous=NORMAL")
            self.dsdb_sqlite_conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {DSBM_DB_TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time_ms INTEGER NOT NULL,
                    delta TEXT NOT NULL,
                    balance TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    source TEXT NOT NULL
                )
                """
            )
            self.dsdb_sqlite_conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_dsbm_time ON {DSBM_DB_TABLE_NAME} (time_ms)"
            )
            self.dsdb_sqlite_conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {DSBM_DB_META_TABLE_NAME} (
                    meta_key TEXT PRIMARY KEY,
                    meta_value TEXT NOT NULL
                )
                """
            )
            self.dsdb_sqlite_conn.commit()
            return True
        except sqlite3.Error as exc:
            self.dsdb_logger.error("SQLite 连接失败：%s", exc)
            self.dsdb_sqlite_conn = None
            return False

    def dsdb_mysql_driver(self) -> Any:
        if self.dsdb_mysql_module is not None:
            return self.dsdb_mysql_module
        for module_name in ("pymysql", "mysql.connector"):
            try:
                module = __import__(module_name, fromlist=["connect"])
            except ImportError:
                continue
            self.dsdb_mysql_module = module
            self.dsdb_mysql_driver_name = module_name
            return module
        return None

    def dsdb_connect_mysql(self) -> bool:
        config = self.dsdb_env.dsenv_db_config()
        self.dsdb_mysql_hint = "未安装 pymysql / mysql-connector-python"
        if not self.dsdb_env.dsenv_db_configured():
            self.dsdb_mysql_hint = ".env 未填写 DSBM_DB_HOST / DSBM_DB_USER / DSBM_DB_NAME"
            return False
        module = self.dsdb_mysql_driver()
        if module is None:
            return False
        try:
            if getattr(module, "__name__", "") == "pymysql":
                connection = module.connect(
                    host=config["host"], port=config["port"], user=config["user"],
                    password=config["password"], database=config["name"],
                    charset=config["charset"], autocommit=True, connect_timeout=8,
                )
            else:
                connection = module.connect(
                    host=config["host"], port=config["port"], user=config["user"],
                    password=config["password"], database=config["name"],
                    charset=config["charset"], autocommit=True, connection_timeout=8,
                )
            cursor = connection.cursor()
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {DSBM_DB_TABLE_NAME} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    time_ms BIGINT NOT NULL,
                    delta VARCHAR(32) NOT NULL,
                    balance VARCHAR(32) NOT NULL,
                    currency VARCHAR(16) NOT NULL,
                    source VARCHAR(32) NOT NULL,
                    INDEX idx_dsbm_time (time_ms)
                ) CHARACTER SET {config['charset']}
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {DSBM_DB_META_TABLE_NAME} (
                    meta_key VARCHAR(64) PRIMARY KEY,
                    meta_value VARCHAR(255) NOT NULL
                ) CHARACTER SET {config['charset']}
                """
            )
            cursor.close()
            self.dsdb_mysql_conn = connection
            self.dsdb_mysql_hint = ""
            return True
        except Exception as exc:  # noqa: BLE001 - 驱动异常类型各家不同
            self.dsdb_mysql_hint = f"{type(exc).__name__}: {exc}"
            self.dsdb_logger.warning("MySQL 连接失败：%s", self.dsdb_mysql_hint)
            self.dsdb_mysql_conn = None
            return False

    def dsdb_close_connections(self) -> None:
        if self.dsdb_sqlite_conn is not None:
            try:
                self.dsdb_sqlite_conn.commit()
                self.dsdb_sqlite_conn.close()
            except sqlite3.Error as exc:
                self.dsdb_logger.warning("关闭 SQLite 失败：%s", exc)
            self.dsdb_sqlite_conn = None
        if self.dsdb_mysql_conn is not None:
            try:
                self.dsdb_mysql_conn.close()
            except Exception as exc:  # noqa: BLE001
                self.dsdb_logger.warning("关闭 MySQL 失败：%s", exc)
            self.dsdb_mysql_conn = None

    def dsdb_close(self) -> None:
        with self.dsdb_lock:
            self.dsdb_close_connections()
            self.dsdb_ready = False

    def dsdb_backend_name(self) -> str:
        return self.dsdb_status_text

    # ------------------------------------------------------------ 写入 / 读取
    def dsdb_append_record(self, record: DsbmBalanceRecord) -> bool:
        with self.dsdb_lock:
            if self.dsdb_backend == "memory":
                return True
            if self.dsdb_backend == DSBM_STORAGE_SQLITE and self.dsdb_sqlite_conn is not None:
                try:
                    self.dsdb_sqlite_conn.execute(
                        f"INSERT INTO {DSBM_DB_TABLE_NAME} "
                        "(time_ms, delta, balance, currency, source) VALUES (?, ?, ?, ?, ?)",
                        record.dsrec_as_sql_tuple(),
                    )
                    self.dsdb_sqlite_conn.commit()
                    return True
                except sqlite3.Error as exc:
                    self.dsdb_logger.error("写入 SQLite 失败：%s", exc)
                    return False
            if self.dsdb_backend == DSBM_STORAGE_MYSQL and self.dsdb_mysql_conn is not None:
                try:
                    cursor = self.dsdb_mysql_conn.cursor()
                    cursor.execute(
                        f"INSERT INTO {DSBM_DB_TABLE_NAME} "
                        "(time_ms, delta, balance, currency, source) VALUES (%s, %s, %s, %s, %s)",
                        record.dsrec_as_sql_tuple(),
                    )
                    cursor.close()
                    return True
                except Exception as exc:  # noqa: BLE001
                    self.dsdb_logger.error("写入 MySQL 失败：%s", exc)
                    return False
            return False

    def dsdb_row_to_record(self, row: Sequence[Any]) -> DsbmBalanceRecord:
        return DsbmBalanceRecord(
            dsrec_time_ms=int(row[0]),
            dsrec_delta=dsbm_to_decimal(row[1]),
            dsrec_balance=dsbm_to_decimal(row[2]),
            dsrec_currency=str(row[3]),
            dsrec_source=str(row[4]),
        )

    def dsdb_load_recent(self, limit: int) -> list[DsbmBalanceRecord]:
        limit = int(max(1, limit))
        with self.dsdb_lock:
            if self.dsdb_backend == "memory":
                return []
            try:
                if self.dsdb_backend == DSBM_STORAGE_SQLITE and self.dsdb_sqlite_conn is not None:
                    cursor = self.dsdb_sqlite_conn.execute(
                        f"SELECT time_ms, delta, balance, currency, source FROM {DSBM_DB_TABLE_NAME} "
                        "ORDER BY time_ms DESC LIMIT ?",
                        (limit,),
                    )
                    rows = cursor.fetchall()
                elif self.dsdb_backend == DSBM_STORAGE_MYSQL and self.dsdb_mysql_conn is not None:
                    cursor = self.dsdb_mysql_conn.cursor()
                    cursor.execute(
                        f"SELECT time_ms, delta, balance, currency, source FROM {DSBM_DB_TABLE_NAME} "
                        "ORDER BY time_ms DESC LIMIT %s",
                        (limit,),
                    )
                    rows = cursor.fetchall()
                    cursor.close()
                else:
                    return []
            except Exception as exc:  # noqa: BLE001
                self.dsdb_logger.error("读取历史记录失败：%s", exc)
                return []
            records = [self.dsdb_row_to_record(row) for row in rows]
            records.reverse()
            return records

    def dsdb_count_records(self) -> int:
        with self.dsdb_lock:
            try:
                if self.dsdb_backend == DSBM_STORAGE_SQLITE and self.dsdb_sqlite_conn is not None:
                    cursor = self.dsdb_sqlite_conn.execute(f"SELECT COUNT(*) FROM {DSBM_DB_TABLE_NAME}")
                    return int(cursor.fetchone()[0])
                if self.dsdb_backend == DSBM_STORAGE_MYSQL and self.dsdb_mysql_conn is not None:
                    cursor = self.dsdb_mysql_conn.cursor()
                    cursor.execute(f"SELECT COUNT(*) FROM {DSBM_DB_TABLE_NAME}")
                    value = int(cursor.fetchone()[0])
                    cursor.close()
                    return value
            except Exception as exc:  # noqa: BLE001
                self.dsdb_logger.error("统计记录条数失败：%s", exc)
            return 0

    def dsdb_delete_all(self) -> bool:
        with self.dsdb_lock:
            try:
                if self.dsdb_backend == DSBM_STORAGE_SQLITE and self.dsdb_sqlite_conn is not None:
                    self.dsdb_sqlite_conn.execute(f"DELETE FROM {DSBM_DB_TABLE_NAME}")
                    self.dsdb_sqlite_conn.commit()
                    return True
                if self.dsdb_backend == DSBM_STORAGE_MYSQL and self.dsdb_mysql_conn is not None:
                    cursor = self.dsdb_mysql_conn.cursor()
                    cursor.execute(f"DELETE FROM {DSBM_DB_TABLE_NAME}")
                    cursor.close()
                    return True
                if self.dsdb_backend == "memory":
                    return True
            except Exception as exc:  # noqa: BLE001
                self.dsdb_logger.error("清空记录失败：%s", exc)
            return False

    def dsdb_prune_records(self, keep: int) -> bool:
        """只保留最近 keep 条（时间倒序），多出来的旧记录删除。"""
        keep = int(max(1, keep))
        with self.dsdb_lock:
            try:
                if self.dsdb_backend == DSBM_STORAGE_SQLITE and self.dsdb_sqlite_conn is not None:
                    self.dsdb_sqlite_conn.execute(
                        f"DELETE FROM {DSBM_DB_TABLE_NAME} WHERE id NOT IN "
                        f"(SELECT id FROM {DSBM_DB_TABLE_NAME} ORDER BY time_ms DESC LIMIT ?)",
                        (keep,),
                    )
                    self.dsdb_sqlite_conn.commit()
                    return True
                if self.dsdb_backend == DSBM_STORAGE_MYSQL and self.dsdb_mysql_conn is not None:
                    cursor = self.dsdb_mysql_conn.cursor()
                    cursor.execute(
                        f"DELETE FROM {DSBM_DB_TABLE_NAME} WHERE id NOT IN "
                        f"(SELECT id FROM (SELECT id FROM {DSBM_DB_TABLE_NAME} "
                        "ORDER BY time_ms DESC LIMIT %s) AS keep_rows)",
                        (keep,),
                    )
                    cursor.close()
                    return True
            except Exception as exc:  # noqa: BLE001
                self.dsdb_logger.error("裁剪历史记录失败：%s", exc)
            return False

    def dsdb_export_csv(self, csv_path: Path, records: Sequence[DsbmBalanceRecord],
                        progress: Callable[[int, str], None] | None = None) -> int:
        """导出 CSV（UTF-8 BOM，Excel 直接双击不乱码）。progress 回调参数：(百分比, 文本)。"""
        total = len(records)
        dsbm_ensure_dir(csv_path.parent)
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["时间", "变化", "变化后余额", "货币", "来源"])
            for index, record in enumerate(records, start=1):
                writer.writerow(record.dsrec_as_csv_row())
                if progress is not None and (index % 25 == 0 or index == total):
                    percent = int(index * 100 / max(1, total))
                    progress(percent, f"正在写出第 {index}/{total} 条")
        if progress is not None:
            progress(100, f"导出完成，共 {total} 条")
        return total


# ==============================================================================
# 九、DeepSeek 接口客户端（GET /user/balance，不消耗 Token）
# ==============================================================================


class DsbmBalanceApiClient:
    """调用官方 /user/balance。密钥与超时全部来自 .env，绝不出现在代码里。"""

    def __init__(self, env_manager: DsbmEnvFileManager) -> None:
        self.dsapi_env = env_manager
        self.dsapi_logger = logging.getLogger(DSBM_LOGGER_NAME)
        self.dsapi_base = DSBM_API_DEFAULT_BASE
        self.dsapi_api_key = ""
        self.dsapi_timeout = DSBM_API_DEFAULT_TIMEOUT
        self.dsapi_max_retry = DSBM_API_DEFAULT_RETRY
        self.dsapi_requests = self.dsapi_import_requests()
        self.dsapi_reload_config()

    @staticmethod
    def dsapi_import_requests() -> Any:
        try:
            import requests  # noqa: PLC0415 - 可选依赖，缺失时用标准库兜底
            return requests
        except ImportError:
            return None

    def dsapi_reload_config(self) -> dict[str, Any]:
        self.dsapi_env.dsenv_reload()
        self.dsapi_base = self.dsapi_env.dsenv_api_base()
        self.dsapi_api_key = self.dsapi_env.dsenv_api_key()
        self.dsapi_timeout = self.dsapi_env.dsenv_timeout()
        self.dsapi_max_retry = self.dsapi_env.dsenv_max_retry()
        return self.dsapi_config_summary()

    def dsapi_config_summary(self) -> dict[str, Any]:
        return {
            "api_base": self.dsapi_base,
            "api_key_masked": dsbm_mask_secret(self.dsapi_api_key),
            "has_key": bool(self.dsapi_api_key) and not self.dsapi_api_key.startswith("sk-在此"),
            "timeout": self.dsapi_timeout,
            "max_retry": self.dsapi_max_retry,
            "client": "requests" if self.dsapi_requests is not None else "urllib",
        }

    def dsapi_http_get(self, url: str, headers: dict[str, str], timeout: int) -> tuple[int, str]:
        """返回（HTTP 状态码, 响应体文本）。状态码 -1 表示网络层失败。"""
        if self.dsapi_requests is not None:
            try:
                response = self.dsapi_requests.get(url, headers=headers, timeout=timeout)
                return int(response.status_code), response.text
            except Exception as exc:  # noqa: BLE001 - requests 异常层级较多
                return -1, f"{type(exc).__name__}: {exc}"
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            return int(exc.code), body
        except Exception as exc:  # noqa: BLE001
            return -1, f"{type(exc).__name__}: {exc}"

    def dsapi_query_balance(self, preferred_currency: str = "") -> dict[str, Any]:
        """查询余额。带重试（网络错误 / 5xx / 429 重试；401 等鉴权错误立即返回）。"""
        result: dict[str, Any] = {
            "ok": False,
            "error": "",
            "http_status": 0,
            "attempts": 0,
            "elapsed_ms": 0,
            "queried_ms": dsbm_now_ms(),
            "api_base": self.dsapi_base,
            "is_available": False,
            "all_infos": [],
        }
        started = time.perf_counter()
        if not self.dsapi_api_key or self.dsapi_api_key.startswith("sk-在此"):
            result["error"] = "尚未配置 API Key：请在 .env 里填写 DEEPSEEK_API_KEY，或用「设置 → 密钥与数据源」写入。"
            result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            return result
        url = f"{self.dsapi_base}{DSBM_API_BALANCE_PATH}"
        headers = {
            "Authorization": f"Bearer {self.dsapi_api_key}",
            "Accept": "application/json",
            "User-Agent": DSBM_APP_USER_AGENT,
        }
        payload: dict[str, Any] | None = None
        last_error = ""
        attempts = 0
        for attempt in range(self.dsapi_max_retry + 1):
            attempts = attempt + 1
            status, body = self.dsapi_http_get(url, headers, self.dsapi_timeout)
            if status == 200:
                try:
                    parsed = json.loads(body)
                except ValueError:
                    last_error = "接口返回内容不是合法 JSON"
                    break
                if isinstance(parsed, dict):
                    payload = parsed
                    break
                last_error = "接口返回结构异常"
                break
            if status in (401, 403):
                last_error = self.dsapi_error_text(status, body)
                break
            last_error = self.dsapi_error_text(status, body)
            if status == -1 or status >= 500 or status == 429:
                if attempt < self.dsapi_max_retry:
                    sleep_seconds = min(6.0, 0.8 * (2 ** attempt))
                    self.dsapi_logger.warning(
                        "查询失败（第 %s 次）：%s，%.1f 秒后重试", attempts, last_error, sleep_seconds
                    )
                    time.sleep(sleep_seconds)
                    continue
            break
        result["attempts"] = attempts
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        if payload is None:
            result["error"] = last_error or "未知错误"
            return result
        result.update(self.dsapi_extract_balance_info(payload, preferred_currency))
        result["ok"] = True
        result["raw"] = payload
        return result

    def dsapi_extract_balance_info(self, payload: dict[str, Any],
                                   preferred_currency: str = "") -> dict[str, Any]:
        infos_raw = payload.get("balance_infos") or []
        infos: list[dict[str, Any]] = []
        if isinstance(infos_raw, list):
            for item in infos_raw:
                if not isinstance(item, dict):
                    continue
                infos.append({
                    "currency": str(item.get("currency", "") or ""),
                    "total": dsbm_to_decimal(item.get("total_balance", "0")),
                    "granted": dsbm_to_decimal(item.get("granted_balance", "0")),
                    "topped_up": dsbm_to_decimal(item.get("topped_up_balance", "0")),
                })
        chosen = None
        if preferred_currency:
            wanted = preferred_currency.strip().upper()
            chosen = next((i for i in infos if i["currency"].upper() == wanted), None)
        if chosen is None:
            chosen = next((i for i in infos if i["currency"].upper() == "CNY"), None)
        if chosen is None and infos:
            chosen = infos[0]
        if chosen is None:
            chosen = {"currency": "", "total": Decimal("0"),
                      "granted": Decimal("0"), "topped_up": Decimal("0")}
        return {
            "is_available": bool(payload.get("is_available", False)),
            "currency": chosen["currency"],
            "total": chosen["total"],
            "granted": chosen["granted"],
            "topped_up": chosen["topped_up"],
            "all_infos": infos,
        }

    def dsapi_error_text(self, status: int, body: str) -> str:
        if status == -1:
            return f"网络请求失败：{body[:200]}"
        detail = ""
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                error = parsed.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message", ""))[:200]
                elif error:
                    detail = str(error)[:200]
                if not detail:
                    detail = str(parsed.get("message", ""))[:200]
        except ValueError:
            detail = body.strip()[:200]
        mapping = {
            400: "请求格式错误（400）",
            401: "API Key 无效或已失效（401）",
            402: "账户余额不足（402）",
            403: "无权限访问该接口（403）",
            404: "接口地址不存在（404），请检查 DEEPSEEK_API_BASE",
            429: "请求过于频繁，已被限流（429）",
        }
        prefix = mapping.get(status, f"HTTP {status}" if status > 0 else "网络异常")
        return f"{prefix}：{detail}" if detail else prefix


# ==============================================================================
# 十、后台线程（多线程：查询 / 导出 / 通知，全部不阻塞界面）
# ==============================================================================


class DsbmBalanceQueryThread(QThread):
    """后台查询线程：一次只跑一个实例，避免定时与手动查询互相覆盖。"""

    dsqth_succeeded = Signal(object)
    dsqth_failed = Signal(str, object)

    def __init__(self, api_client: DsbmBalanceApiClient, source_label: str,
                 preferred_currency: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.dsqth_client = api_client
        self.dsqth_source_label = source_label
        self.dsqth_preferred_currency = preferred_currency
        self.dsqth_logger = logging.getLogger(DSBM_LOGGER_NAME)
        self.dsqth_result: dict[str, Any] = {}

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            outcome = self.dsqth_client.dsapi_query_balance(self.dsqth_preferred_currency)
        except Exception as exc:  # noqa: BLE001 - 线程内兜底，避免线程崩溃
            self.dsqth_logger.exception("查询线程异常")
            outcome = {"ok": False, "error": f"内部异常：{type(exc).__name__}: {exc}",
                       "elapsed_ms": 0, "attempts": 1, "queried_ms": dsbm_now_ms()}
        outcome["source"] = self.dsqth_source_label
        self.dsqth_result = outcome
        if outcome.get("ok"):
            self.dsqth_succeeded.emit(outcome)
        else:
            self.dsqth_failed.emit(str(outcome.get("error", "未知错误")), outcome)


class DsbmCsvExportThread(QThread):
    """后台导出 CSV 线程：边写边报进度。"""

    dsxth_progress = Signal(int, str)
    dsxth_finished = Signal(str, int)
    dsxth_failed = Signal(str)

    def __init__(self, store: DsbmRecordStore, csv_path: Path,
                 records: Sequence[DsbmBalanceRecord], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.dsxth_store = store
        self.dsxth_path = Path(csv_path)
        self.dsxth_records = list(records)
        self.dsxth_logger = logging.getLogger(DSBM_LOGGER_NAME)

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            written = self.dsxth_store.dsdb_export_csv(
                self.dsxth_path, self.dsxth_records,
                progress=lambda percent, text: self.dsxth_progress.emit(percent, text),
            )
        except Exception as exc:  # noqa: BLE001
            self.dsxth_logger.exception("导出 CSV 失败")
            self.dsxth_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.dsxth_finished.emit(str(self.dsxth_path), written)


# ==============================================================================
# 十一、Windows 右下角原生弹窗（吐司通知）
# ==============================================================================

DSBM_TOAST_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $template.GetElementsByTagName('text')
[void]$nodes.Item(0).AppendChild($template.CreateTextNode($env:DSBM_TOAST_TITLE))
[void]$nodes.Item(1).AppendChild($template.CreateTextNode($env:DSBM_TOAST_BODY))
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


class DsbmToastService:
    """吐司通知服务：独立守护线程 + 队列发送，绝不影响界面流畅度。

    后端按顺序尝试（第一个成功的即为当前后端）：
      winsdk（进程内 WinRT，最快）→ winotify → win10toast →
      内置 PowerShell WinRT（无需第三方库，绿色直用，已验证可用）。
    全部失败时由主窗口改用系统托盘气泡兜底。
    """

    DSBM_TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    DSBM_TOAST_PS_TIMEOUT = 20

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.dstoast_logger = logger or logging.getLogger(DSBM_LOGGER_NAME)
        self.dstoast_queue: "queue.Queue[tuple[str, str] | None]" = queue.Queue()
        self.dstoast_thread: threading.Thread | None = None
        self.dstoast_backends = self.dstoast_detect_backends()
        self.dstoast_active_backend = self.dstoast_backends[0] if self.dstoast_backends else "none"
        self.dstoast_attempted = list(self.dstoast_backends)
        self.dstoast_sent = 0
        self.dstoast_dispatch = {
            "winsdk": self.dstoast_send_winsdk,
            "winotify": self.dstoast_send_winotify,
            "win10toast": self.dstoast_send_win10toast,
            "powershell": self.dstoast_send_powershell,
        }

    def dstoast_detect_backends(self) -> list[str]:
        found: list[str] = []
        if self.dstoast_probe_winsdk():
            found.append("winsdk")
        try:
            import winotify  # noqa: F401,PLC0415
            found.append("winotify")
        except ImportError:
            pass
        try:
            import win10toast  # noqa: F401,PLC0415
            found.append("win10toast")
        except ImportError:
            pass
        if sys.platform.startswith("win"):
            found.append("powershell")
        return found or ["none"]

    @staticmethod
    def dstoast_probe_winsdk() -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            from winsdk.windows.ui.notifications import ToastNotificationManager  # noqa: F401,PLC0415
            return True
        except Exception:  # noqa: BLE001 - winsdk 是可选加速件，任何异常都视为不可用
            return False

    def dstoast_backend_name(self) -> str:
        return self.dstoast_active_backend

    def dstoast_is_available(self) -> bool:
        return bool(self.dstoast_backends) and self.dstoast_backends[0] != "none"

    def dstoast_start(self) -> None:
        if self.dstoast_thread is not None and self.dstoast_thread.is_alive():
            return
        self.dstoast_thread = threading.Thread(
            target=self.dstoast_worker_loop, name="DsbmToastWorker", daemon=True
        )
        self.dstoast_thread.start()

    def dstoast_stop(self) -> None:
        if self.dstoast_thread is None:
            return
        self.dstoast_queue.put(None)
        self.dstoast_thread.join(timeout=2.0)
        self.dstoast_thread = None

    def dstoast_worker_loop(self) -> None:
        while True:
            item = self.dstoast_queue.get()
            if item is None:
                break
            title, body = item
            try:
                self.dstoast_notify_blocking(title, body)
            except Exception as exc:  # noqa: BLE001 - 通知失败不能影响主流程
                self.dstoast_logger.warning("弹窗通知失败：%s", exc)

    def dstoast_notify_async(self, title: str, body: str) -> None:
        self.dstoast_start()
        self.dstoast_queue.put((title, body))

    def dstoast_notify_blocking(self, title: str, body: str) -> bool:
        """同步发送（供自检脚本与设置窗口的「测试通知」使用）。任一后端成功即返回 True。"""
        for backend in self.dstoast_backends:
            sender = self.dstoast_dispatch.get(backend)
            if sender is None:
                continue
            try:
                if sender(title, body):
                    self.dstoast_active_backend = backend
                    self.dstoast_sent += 1
                    self.dstoast_logger.info(
                        "已弹出通知（%s）：%s / %s", backend, title, body.replace("\n", " ")
                    )
                    return True
            except Exception as exc:  # noqa: BLE001
                self.dstoast_logger.warning("通知后端 %s 异常：%s", backend, exc)
        self.dstoast_logger.warning("所有弹窗后端均失败：%s", "、".join(self.dstoast_backends))
        return False

    def dstoast_send_winsdk(self, title: str, body: str) -> bool:
        """进程内直接调用 Windows Runtime 吐司（最快，需安装 winsdk）。"""
        try:
            from winsdk.windows.data.xml.dom import XmlDocument  # noqa: PLC0415
            from winsdk.windows.ui.notifications import (  # noqa: PLC0415
                ToastNotification,
                ToastNotificationManager,
            )
        except ImportError:
            return False
        from xml.sax.saxutils import escape as xml_escape

        document = XmlDocument()
        document.load_xml(
            '<toast duration="short"><visual><binding template="ToastText02">'
            f'<text id="1">{xml_escape(title)}</text>'
            f'<text id="2">{xml_escape(body)}</text>'
            "</binding></visual></toast>"
        )
        notifier = ToastNotificationManager.create_toast_notifier(self.DSBM_TOAST_APP_ID)
        notifier.show(ToastNotification(document))
        return True

    def dstoast_send_winotify(self, title: str, body: str) -> bool:
        try:
            from winotify import Notification, audio  # noqa: PLC0415
            toast = Notification(app_id=DSBM_APP_CN_NAME, title=title, msg=body)
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            return True
        except Exception as exc:  # noqa: BLE001
            self.dstoast_logger.warning("winotify 发送失败：%s", exc)
            return False

    def dstoast_send_win10toast(self, title: str, body: str) -> bool:
        try:
            from win10toast import ToastNotifier  # noqa: PLC0415
            notifier = ToastNotifier()
            notifier.show_toast(title, body, duration=6, threaded=True)
            return True
        except Exception as exc:  # noqa: BLE001
            self.dstoast_logger.warning("win10toast 发送失败：%s", exc)
            return False

    def dstoast_send_powershell(self, title: str, body: str) -> bool:
        """用 Windows PowerShell 5.1 调 WinRT 吐司：不依赖任何第三方库，绿色直用。"""
        if not sys.platform.startswith("win"):
            return False
        encoded = base64.b64encode(DSBM_TOAST_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
        env = dict(os.environ)
        env["DSBM_TOAST_TITLE"] = title
        env["DSBM_TOAST_BODY"] = body
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        shell = os.environ.get("SystemRoot", r"C:\Windows")
        candidates = [
            str(Path(shell) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
            "powershell.exe",
        ]
        for executable in candidates:
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    [executable, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                     "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                    capture_output=True, env=env, timeout=self.DSBM_TOAST_PS_TIMEOUT,
                    creationflags=creation_flags,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.dstoast_logger.warning("调用 PowerShell 失败：%s", exc)
                continue
            if completed.returncode == 0:
                self.dstoast_logger.info(
                    "PowerShell 弹窗成功（用时 %.2f 秒）", time.perf_counter() - started
                )
                return True
            self.dstoast_logger.warning(
                "PowerShell 弹窗返回 %s：%s", completed.returncode,
                completed.stderr.decode("utf-8", "replace").strip()[:300],
            )
        return False


# ==============================================================================
# 十二、系统托盘
# ==============================================================================


class DsbmTrayController(QObject):
    """托盘控制器：图标菜单 + 双击唤出 + 气泡兜底提醒。"""

    dstray_show_requested = Signal()
    dstray_query_requested = Signal()
    dstray_toggle_pause_requested = Signal()
    dstray_exit_requested = Signal()

    def __init__(self, tray_icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.dstray_icon = tray_icon
        self.dstray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.dstray_tray: QSystemTrayIcon | None = None
        self.dstray_menu: QMenu | None = None
        self.dstray_action_show: QAction | None = None
        self.dstray_action_query: QAction | None = None
        self.dstray_action_pause: QAction | None = None
        self.dstray_action_exit: QAction | None = None
        self.dstray_logger = logging.getLogger(DSBM_LOGGER_NAME)

    def dstray_is_supported(self) -> bool:
        return bool(self.dstray_available and not self.dstray_icon.isNull())

    def dstray_build(self) -> bool:
        if not self.dstray_is_supported():
            return False
        if self.dstray_tray is not None:
            return True
        self.dstray_tray = QSystemTrayIcon(self.dstray_icon, self)
        self.dstray_tray.setToolTip(f"{DSBM_APP_CN_NAME} v{DSBM_APP_VERSION}")
        self.dstray_menu = QMenu()
        self.dstray_action_show = self.dstray_menu.addAction("显示主窗口(&S)")
        self.dstray_action_show.triggered.connect(self.dstray_show_requested.emit)
        self.dstray_action_query = self.dstray_menu.addAction("立即查询(&Q)")
        self.dstray_action_query.triggered.connect(self.dstray_query_requested.emit)
        self.dstray_action_pause = self.dstray_menu.addAction("暂停定时查询(&P)")
        self.dstray_action_pause.triggered.connect(self.dstray_toggle_pause_requested.emit)
        self.dstray_menu.addSeparator()
        self.dstray_action_exit = self.dstray_menu.addAction("退出程序(&X)")
        self.dstray_action_exit.triggered.connect(self.dstray_exit_requested.emit)
        self.dstray_tray.setContextMenu(self.dstray_menu)
        self.dstray_tray.activated.connect(self.dstray_on_activated)
        return True

    def dstray_show(self) -> None:
        if self.dstray_build() and self.dstray_tray is not None:
            self.dstray_tray.show()

    def dstray_hide(self) -> None:
        if self.dstray_tray is not None:
            self.dstray_tray.hide()

    def dstray_set_paused(self, paused: bool, interval_seconds: int) -> None:
        if self.dstray_action_pause is not None:
            self.dstray_action_pause.setText("继续定时查询(&P)" if paused else "暂停定时查询(&P)")
        if self.dstray_tray is not None:
            state = "已暂停" if paused else f"每 {dsbm_format_duration(interval_seconds)} 查询一次"
            self.dstray_tray.setToolTip(f"{DSBM_APP_CN_NAME} v{DSBM_APP_VERSION} ｜ {state}")

    def dstray_show_message(self, title: str, body: str, msecs: int = 6000) -> bool:
        if self.dstray_tray is None:
            return False
        self.dstray_tray.showMessage(
            title, body, QSystemTrayIcon.MessageIcon.Information, msecs
        )
        return True

    @Slot(QSystemTrayIcon.ActivationReason)
    def dstray_on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.dstray_show_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.dstray_query_requested.emit()


# ==============================================================================
# 十三、顶部余额卡片（余额总览 + 定时查询控制 + 全部进度条）
# ==============================================================================


class DsbmElidedLabel(QLabel):
    """会自动加省略号的标签：宽度不够时右侧显示「…」，完整内容放进 ToolTip。

    `minimumSizeHint()` 的宽度固定为 0，因此长文本（接口地址、统计信息等）
    不会再顶大窗口的最小宽度，窗口可以放心缩小；`sizeHint()` 依旧按完整文本计算，
    窗口变宽后会自动恢复显示全文。`text()` 始终返回完整文本，方便日志与自检读取。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.delab_full = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt 覆盖
        self.delab_full = str(text or "")
        self.setToolTip(self.delab_full)
        self.delab_refresh()

    def text(self) -> str:  # noqa: N802 - Qt 覆盖
        return self.delab_full

    def delab_refresh(self) -> None:
        """按当前宽度重新计算显示文本（布局尚未完成时先按原文显示）。"""
        available = self.width() - 2
        if available <= 8:
            super().setText(self.delab_full)
        else:
            super().setText(dsbm_elide_text(self.fontMetrics(), self.delab_full, available))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 覆盖
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 覆盖
        metrics = QFontMetrics(self.font())
        return QSize(metrics.horizontalAdvance(self.delab_full) + 2, super().sizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt 覆盖
        super().resizeEvent(event)
        self.delab_refresh()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt 覆盖
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.delab_refresh()


class DsbmBalanceCardWidget(QWidget):
    """紧凑型总览卡片：当前余额、账户状态、倒计时进度、查询间隔设置与操作按钮。"""

    dcard_query_requested = Signal()
    dcard_pause_toggled = Signal(bool)
    dcard_settings_requested = Signal()
    dcard_interval_changed = Signal(int)

    def __init__(self, settings_manager: DsbmSettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dcard_settings = settings_manager
        self.dcard_syncing = False
        self.dcard_button_query: QPushButton | None = None
        self.dcard_button_pause: QPushButton | None = None
        self.dcard_button_settings: QPushButton | None = None
        self.dcard_spin_interval: QSpinBox | None = None
        self.dcard_combo_unit: QComboBox | None = None
        self.dcard_progress_countdown: QProgressBar | None = None
        self.dcard_progress_task: QProgressBar | None = None
        self.dcard_label_balance: QLabel | None = None
        self.dcard_label_meta: DsbmElidedLabel | None = None
        self.dcard_label_status: DsbmElidedLabel | None = None
        self.dcard_label_countdown: DsbmElidedLabel | None = None
        self.dcard_label_task: DsbmElidedLabel | None = None
        self.dcard_label_env: DsbmElidedLabel | None = None
        self.dcard_build_ui()
        self.dcard_apply_scale(float(self.dcard_settings.dsgset_get_float("ui_scale", 1.0) or 1.0))
        self.dcard_apply_settings()

    # ------------------------------------------------------------------ 构建
    def dcard_build_ui(self) -> None:
        self.setObjectName("dsbmBalanceCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(5)

        # 第 1 行：标题 + 定时查询控制（唯一的横向控件行，窗口缩小时也不会被裁）
        head = QHBoxLayout()
        head.setSpacing(6)
        caption = QLabel("当前总可用余额")
        caption.setObjectName("dsbmCardCaption")
        head.addWidget(caption)
        head.addSpacing(12)
        head.addWidget(QLabel("查询间隔"))
        self.dcard_spin_interval = QSpinBox()
        self.dcard_spin_interval.setRange(1, 1440)
        self.dcard_spin_interval.setAccelerated(True)
        self.dcard_spin_interval.setSuffix("")
        self.dcard_spin_interval.setFixedWidth(84)
        self.dcard_spin_interval.setToolTip("每隔多久查一次余额（5 秒 ~ 24 小时），改动立刻保存并生效")
        head.addWidget(self.dcard_spin_interval)
        self.dcard_combo_unit = QComboBox()
        self.dcard_combo_unit.addItems([DSBM_UNIT_SECOND, DSBM_UNIT_MINUTE, DSBM_UNIT_HOUR])
        self.dcard_combo_unit.setFixedWidth(78)
        head.addWidget(self.dcard_combo_unit)
        self.dcard_button_query = QPushButton("立即查询")
        self.dcard_button_query.setToolTip("立刻查询一次（快捷方式 Ctrl+R）")
        head.addWidget(self.dcard_button_query)
        self.dcard_button_pause = QPushButton("暂停查询")
        self.dcard_button_pause.setCheckable(True)
        self.dcard_button_pause.setToolTip("暂停 / 继续定时查询（快捷方式 Ctrl+P）")
        head.addWidget(self.dcard_button_pause)
        self.dcard_button_settings = QPushButton("设置")
        self.dcard_button_settings.setToolTip("打开设置（所有改动即时生效并自动保存）")
        head.addWidget(self.dcard_button_settings)
        head.addStretch(1)
        outer.addLayout(head)

        # 第 2 行：余额 + 账户摘要（过长自动「…」，完整内容见 ToolTip）
        value_row = QHBoxLayout()
        value_row.setSpacing(8)
        self.dcard_label_balance = QLabel("--")
        self.dcard_label_balance.setObjectName("dsbmCardBalance")
        self.dcard_label_balance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value_row.addWidget(self.dcard_label_balance)
        self.dcard_label_meta = DsbmElidedLabel("等待首次查询")
        self.dcard_label_meta.setObjectName("dsbmCardMeta")
        self.dcard_label_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value_row.addWidget(self.dcard_label_meta, 1)
        outer.addLayout(value_row)

        # 第 3 行：密钥 / 接口 / 通知后端摘要 + 下次查询倒计时
        env_row = QHBoxLayout()
        env_row.setSpacing(8)
        self.dcard_label_env = DsbmElidedLabel("")
        self.dcard_label_env.setObjectName("dsbmCardHint")
        self.dcard_label_env.setWordWrap(False)
        self.dcard_label_env.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        env_row.addWidget(self.dcard_label_env, 3)
        self.dcard_progress_countdown = QProgressBar()
        self.dcard_progress_countdown.setRange(0, 1000)
        self.dcard_progress_countdown.setValue(0)
        self.dcard_progress_countdown.setFormat("%p%")
        self.dcard_progress_countdown.setFixedHeight(14)
        self.dcard_progress_countdown.setMinimumWidth(110)
        self.dcard_progress_countdown.setToolTip("距离下次定时查询的进度")
        env_row.addWidget(self.dcard_progress_countdown, 2)
        self.dcard_label_countdown = DsbmElidedLabel("--")
        self.dcard_label_countdown.setObjectName("dsbmCardHint")
        env_row.addWidget(self.dcard_label_countdown)
        outer.addLayout(env_row)

        # 第 4 行：状态 + 任务进度（没有任务时只显示状态）
        task_row = QHBoxLayout()
        task_row.setSpacing(8)
        self.dcard_label_status = DsbmElidedLabel("就绪")
        self.dcard_label_status.setObjectName("dsbmCardStatus")
        task_row.addWidget(self.dcard_label_status, 1)
        self.dcard_label_task = DsbmElidedLabel("")
        self.dcard_label_task.setObjectName("dsbmCardHint")
        task_row.addWidget(self.dcard_label_task)
        self.dcard_progress_task = QProgressBar()
        self.dcard_progress_task.setRange(0, 100)
        self.dcard_progress_task.setValue(0)
        self.dcard_progress_task.setFixedHeight(14)
        self.dcard_progress_task.setTextVisible(True)
        self.dcard_progress_task.setFormat("%p%")
        self.dcard_progress_task.setMinimumWidth(110)
        task_row.addWidget(self.dcard_progress_task, 1)
        outer.addLayout(task_row)

        self.dcard_connect_signals()
        self.dcard_apply_compact_style()

    def dcard_connect_signals(self) -> None:
        self.dcard_button_query.clicked.connect(self.dcard_query_requested.emit)
        self.dcard_button_settings.clicked.connect(self.dcard_settings_requested.emit)
        self.dcard_button_pause.toggled.connect(self.dcard_on_pause_toggled)
        self.dcard_spin_interval.valueChanged.connect(self.dcard_on_interval_edited)
        self.dcard_combo_unit.currentIndexChanged.connect(self.dcard_on_interval_edited)

    def dcard_apply_compact_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#dsbmBalanceCard {{
                background-color: {DSBM_COLOR_CARD_BG};
                border: 1px solid {DSBM_COLOR_CARD_BORDER};
                border-radius: 8px;
            }}
            QLabel#dsbmCardCaption {{ color: {DSBM_COLOR_MUTED}; font-size: 12px; }}
            QLabel#dsbmCardBalance {{ color: {DSBM_COLOR_BRAND_DARK}; font-weight: 700; }}
            QLabel#dsbmCardMeta {{ color: #303030; }}
            QLabel#dsbmCardHint {{ color: {DSBM_COLOR_MUTED}; font-size: 12px; }}
            QLabel#dsbmCardStatus {{ font-weight: 600; }}
            """
        )

    # ------------------------------------------------------------------ 设置同步
    def dcard_apply_settings(self) -> None:
        settings = self.dcard_settings
        self.dcard_syncing = True
        try:
            interval = settings.dsgset_get_int("query_interval_seconds", DSBM_DEFAULT_INTERVAL_SECONDS)
            amount, unit = dsbm_interval_to_parts(interval)
            self.dcard_spin_interval.setRange(1, 1440 if unit != DSBM_UNIT_SECOND else 86400)
            self.dcard_spin_interval.setValue(int(amount))
            index = self.dcard_combo_unit.findText(unit)
            if index >= 0:
                self.dcard_combo_unit.setCurrentIndex(index)
            paused = settings.dsgset_get_bool("polling_paused", False)
            self.dcard_button_pause.setChecked(paused)
            self.dcard_button_pause.setText("继续查询" if paused else "暂停查询")
        finally:
            self.dcard_syncing = False

    def dcard_apply_scale(self, scale: float) -> None:
        balance_font = QFont(self.font())
        balance_font.setPointSizeF(max(13.0, 20.0 * scale))
        balance_font.setBold(True)
        self.dcard_label_balance.setFont(balance_font)
        meta_font = QFont(self.font())
        meta_font.setPointSizeF(max(8.5, 9.5 * scale))
        self.dcard_label_meta.setFont(meta_font)
        for label in (self.dcard_label_env, self.dcard_label_status,
                      self.dcard_label_countdown, self.dcard_label_task):
            small_font = QFont(self.font())
            small_font.setPointSizeF(max(7.5, 9.0 * scale))
            label.setFont(small_font)

    # ------------------------------------------------------------------ 交互
    @Slot()
    def dcard_on_interval_edited(self) -> None:
        if self.dcard_syncing:
            return
        unit = self.dcard_combo_unit.currentText()
        amount = int(self.dcard_spin_interval.value())
        seconds = dsbm_parts_to_interval(amount, unit)
        self.dcard_interval_changed.emit(seconds)

    @Slot(bool)
    def dcard_on_pause_toggled(self, paused: bool) -> None:
        self.dcard_button_pause.setText("继续查询" if paused else "暂停查询")
        if not self.dcard_syncing:
            self.dcard_pause_toggled.emit(bool(paused))

    def dcard_set_pause_state(self, paused: bool) -> None:
        self.dcard_syncing = True
        try:
            self.dcard_button_pause.setChecked(bool(paused))
            self.dcard_button_pause.setText("继续查询" if paused else "暂停查询")
        finally:
            self.dcard_syncing = False

    def dcard_set_query_busy(self, busy: bool) -> None:
        self.dcard_button_query.setEnabled(not busy)
        self.dcard_button_query.setText("查询中…" if busy else "立即查询")

    # ------------------------------------------------------------------ 展示
    def dcard_set_balance_view(self, payload: dict[str, Any], queried_text: str) -> None:
        currency = str(payload.get("currency", "") or "")
        self.dcard_label_balance.setText(dsbm_format_money(payload.get("total", 0)))
        accent = DSBM_COLOR_BRAND_DARK if payload.get("is_available", False) else DSBM_COLOR_ERROR
        self.dcard_label_balance.setStyleSheet(f"color: {accent};")
        state = "账户可用" if payload.get("is_available", False) else "账户不可用 / 已欠费"
        self.dcard_label_meta.setText(
            f"{currency or '—'}　｜　{state}　｜　赠金 {dsbm_format_money(payload.get('granted', 0))}"
            f"　｜　充值余额 {dsbm_format_money(payload.get('topped_up', 0))}"
            f"　｜　查询耗时 {payload.get('elapsed_ms', 0)} ms（{queried_text}）"
        )

    def dcard_set_env_text(self, text: str) -> None:
        self.dcard_label_env.setText(text)

    def dcard_set_status(self, text: str, level: str = "info") -> None:
        colors = {
            "info": DSBM_COLOR_MUTED,
            "ok": DSBM_COLOR_OK,
            "warn": DSBM_COLOR_WARN,
            "error": DSBM_COLOR_ERROR,
            "busy": DSBM_COLOR_BRAND,
        }
        self.dcard_label_status.setText(text)
        self.dcard_label_status.setStyleSheet(
            f"color: {colors.get(level, DSBM_COLOR_MUTED)}; font-weight: 600;"
        )

    def dcard_set_countdown(self, remaining_seconds: float, total_seconds: float,
                            paused: bool) -> None:
        if paused:
            self.dcard_progress_countdown.setValue(0)
            self.dcard_progress_countdown.setFormat("已暂停")
            self.dcard_label_countdown.setText("已暂停定时查询")
            return
        total = max(1.0, float(total_seconds))
        remaining = max(0.0, min(total, float(remaining_seconds)))
        percent = int((total - remaining) * 1000 / total)
        self.dcard_progress_countdown.setValue(percent)
        self.dcard_progress_countdown.setFormat(f"{100 - percent / 10:.0f}%")
        text = dsbm_format_duration(remaining)
        self.dcard_label_countdown.setText(f"下次查询 {text} 后")

    def dcard_set_task_progress(self, percent: int | None, text: str,
                                busy: bool = False, visible: bool = True) -> None:
        self.dcard_label_task.setText(text)
        self.dcard_progress_task.setVisible(visible)
        if not visible:
            return
        if percent is None:
            self.dcard_progress_task.setRange(0, 0)
            self.dcard_progress_task.setFormat("进行中…")
        else:
            self.dcard_progress_task.setRange(0, 100)
            self.dcard_progress_task.setValue(int(max(0, min(100, percent))))
            self.dcard_progress_task.setFormat(f"{int(max(0, min(100, percent)))}%")
        self.dcard_progress_task.setStyleSheet(
            "" if not busy else f"QProgressBar::chunk {{ background-color: {DSBM_COLOR_BRAND}; }}"
        )


# ==============================================================================
# 十四、设置对话框（所有改动即时生效 + 自动保存）
# ==============================================================================


class DsbmSettingsDialog(QDialog):
    """分页设置窗口。每一项改动立即写入 data\\dsbm_settings.json；密钥类写 .env。"""

    dsdlg_open_data_dir_requested = Signal()
    dsdlg_open_csv_dir_requested = Signal()
    dsdlg_clear_records_requested = Signal()
    dsdlg_store_reinit_requested = Signal()
    dsdlg_probe_requested = Signal()
    dsdlg_toast_test_requested = Signal()

    def __init__(
        self,
        settings_manager: DsbmSettingsManager,
        env_manager: DsbmEnvFileManager,
        api_client: DsbmBalanceApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.dsdlg_settings = settings_manager
        self.dsdlg_env = env_manager
        self.dsdlg_client = api_client
        self.dsdlg_syncing = False
        self.dsdlg_widgets: dict[str, QWidget] = {}
        self.setWindowTitle(f"设置 — {DSBM_APP_CN_NAME} v{DSBM_APP_VERSION}")
        self.setMinimumSize(640, 500)
        self.dsdlg_build_ui()
        self.dsdlg_load_values()

    # ------------------------------------------------------------------ 构建
    def dsdlg_build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        hint = QLabel("所有设置改动都会立即生效并自动保存到 data\\dsbm_settings.json，下次启动自动沿用；"
                      "API Key / 数据库密码保存在项目根目录 .env 中。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        root.addWidget(hint)

        self.dsdlg_tabs = QTabWidget()
        self.dsdlg_tabs.addTab(self.dsdlg_build_tab_query(), "查询")
        self.dsdlg_tabs.addTab(self.dsdlg_build_tab_notify(), "通知")
        self.dsdlg_tabs.addTab(self.dsdlg_build_tab_store(), "存储与数据")
        self.dsdlg_tabs.addTab(self.dsdlg_build_tab_secret(), "密钥与数据源")
        self.dsdlg_tabs.addTab(self.dsdlg_build_tab_ui(), "界面")
        root.addWidget(self.dsdlg_tabs, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.dsdlg_label_saved = QLabel("设置已自动保存")
        self.dsdlg_label_saved.setStyleSheet(f"color: {DSBM_COLOR_OK};")
        bottom.addWidget(self.dsdlg_label_saved)
        bottom.addStretch(1)
        button_defaults = QPushButton("恢复默认值")
        button_defaults.clicked.connect(self.dsdlg_on_restore_defaults)
        bottom.addWidget(button_defaults)
        button_close = QPushButton("关闭")
        button_close.setDefault(True)
        button_close.clicked.connect(self.accept)
        bottom.addWidget(button_close)
        root.addLayout(bottom)

    def dsdlg_wrap_scroll(self, inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(inner)
        return area

    def dsdlg_register(self, key: str, widget: QWidget) -> QWidget:
        self.dsdlg_widgets[key] = widget
        return widget

    # ---------------------------------------------------------- 各分页构建
    def dsdlg_build_tab_query(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group = QGroupBox("定时查询")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(6)

        interval_row = QWidget()
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.setSpacing(6)
        self.dsdlg_spin_interval = QSpinBox()
        self.dsdlg_spin_interval.setRange(1, 86400)
        self.dsdlg_spin_interval.setAccelerated(True)
        interval_layout.addWidget(self.dsdlg_spin_interval)
        self.dsdlg_combo_unit = QComboBox()
        self.dsdlg_combo_unit.addItems([DSBM_UNIT_SECOND, DSBM_UNIT_MINUTE, DSBM_UNIT_HOUR])
        interval_layout.addWidget(self.dsdlg_combo_unit)
        interval_layout.addStretch(1)
        form.addRow("查询间隔", interval_row)
        self.dsdlg_spin_interval.valueChanged.connect(self.dsdlg_on_interval_changed)
        self.dsdlg_combo_unit.currentIndexChanged.connect(self.dsdlg_on_interval_changed)

        self.dsdlg_check_auto_start = QCheckBox("程序启动后立刻查询一次（用于建立基准余额）")
        self.dsdlg_check_auto_start.toggled.connect(
            lambda value: self.dsdlg_store_bool("auto_query_on_start", value)
        )
        form.addRow("", self.dsdlg_check_auto_start)
        self.dsdlg_register("auto_query_on_start", self.dsdlg_check_auto_start)

        self.dsdlg_check_paused = QCheckBox("启动后处于「暂停定时查询」状态")
        self.dsdlg_check_paused.toggled.connect(
            lambda value: self.dsdlg_store_bool("polling_paused", value)
        )
        form.addRow("", self.dsdlg_check_paused)
        self.dsdlg_register("polling_paused", self.dsdlg_check_paused)

        self.dsdlg_edit_currency = QLineEdit()
        self.dsdlg_edit_currency.setPlaceholderText("留空 = 自动（优先 CNY）")
        self.dsdlg_edit_currency.setMaxLength(8)
        self.dsdlg_edit_currency.textEdited.connect(
            lambda text: self.dsdlg_store_text("preferred_currency", text.strip().upper())
        )
        form.addRow("首选货币", self.dsdlg_edit_currency)
        self.dsdlg_register("preferred_currency", self.dsdlg_edit_currency)
        layout.addWidget(group)

        group_record = QGroupBox("记录规则")
        form_record = QFormLayout(group_record)
        form_record.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_record.setSpacing(6)

        self.dsdlg_spin_max_records = QSpinBox()
        self.dsdlg_spin_max_records.setRange(DSBM_MIN_MAX_RECORDS, DSBM_MAX_MAX_RECORDS)
        self.dsdlg_spin_max_records.setSingleStep(50)
        self.dsdlg_spin_max_records.valueChanged.connect(
            lambda value: self.dsdlg_store_int("max_records", int(value))
        )
        form_record.addRow("最多保留记录（条）", self.dsdlg_spin_max_records)
        self.dsdlg_register("max_records", self.dsdlg_spin_max_records)

        self.dsdlg_check_baseline = QCheckBox("首次查询（或清空后）写入一条「基准记录」")
        self.dsdlg_check_baseline.toggled.connect(
            lambda value: self.dsdlg_store_bool("record_baseline", value)
        )
        form_record.addRow("", self.dsdlg_check_baseline)
        self.dsdlg_register("record_baseline", self.dsdlg_check_baseline)

        self.dsdlg_check_only_debit = QCheckBox("表格默认只看扣钱（只显示余额减少的记录）")
        self.dsdlg_check_only_debit.toggled.connect(self.dsdlg_on_only_debit_toggled)
        form_record.addRow("", self.dsdlg_check_only_debit)
        self.dsdlg_register("only_debit_filter", self.dsdlg_check_only_debit)

        self.dsdlg_check_only_credit = QCheckBox("表格默认只看增加（只显示余额增加的记录，与上一项互斥）")
        self.dsdlg_check_only_credit.toggled.connect(self.dsdlg_on_only_credit_toggled)
        form_record.addRow("", self.dsdlg_check_only_credit)
        self.dsdlg_register("only_credit_filter", self.dsdlg_check_only_credit)
        layout.addWidget(group_record)
        layout.addStretch(1)
        return self.dsdlg_wrap_scroll(page)

    def dsdlg_build_tab_notify(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group = QGroupBox("Windows 右下角弹窗（吐司通知）")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(6)

        self.dsdlg_check_notify = QCheckBox("余额变化时弹出右下角提示")
        self.dsdlg_check_notify.toggled.connect(
            lambda value: self.dsdlg_store_bool("notify_enabled", value)
        )
        form.addRow("", self.dsdlg_check_notify)
        self.dsdlg_register("notify_enabled", self.dsdlg_check_notify)

        self.dsdlg_combo_notify_mode = QComboBox()
        for mode, title in DSBM_NOTIFY_MODE_TITLES.items():
            self.dsdlg_combo_notify_mode.addItem(title, mode)
        self.dsdlg_combo_notify_mode.currentIndexChanged.connect(self.dsdlg_on_notify_mode_changed)
        form.addRow("提示范围", self.dsdlg_combo_notify_mode)
        self.dsdlg_register("notify_mode", self.dsdlg_combo_notify_mode)

        self.dsdlg_spin_threshold = QDoubleSpinBox()
        self.dsdlg_spin_threshold.setRange(0.0, 100000.0)
        self.dsdlg_spin_threshold.setDecimals(2)
        self.dsdlg_spin_threshold.setSingleStep(0.1)
        self.dsdlg_spin_threshold.setSuffix(" 元")
        self.dsdlg_spin_threshold.setToolTip("变化金额小于该值时不提示；0 = 只要变化就提示")
        self.dsdlg_spin_threshold.valueChanged.connect(
            lambda value: self.dsdlg_store_float("notify_threshold", float(value))
        )
        form.addRow("提示阈值（|变化| ≥）", self.dsdlg_spin_threshold)
        self.dsdlg_register("notify_threshold", self.dsdlg_spin_threshold)

        self.dsdlg_check_include_balance = QCheckBox("通知正文包含变化后的余额")
        self.dsdlg_check_include_balance.toggled.connect(
            lambda value: self.dsdlg_store_bool("notify_include_balance", value)
        )
        form.addRow("", self.dsdlg_check_include_balance)
        self.dsdlg_register("notify_include_balance", self.dsdlg_check_include_balance)

        self.dsdlg_check_failure_notify = QCheckBox("连续查询失败时提醒（避免 Key 失效后一直不知道）")
        self.dsdlg_check_failure_notify.toggled.connect(
            lambda value: self.dsdlg_store_bool("notify_on_repeated_failure", value)
        )
        form.addRow("", self.dsdlg_check_failure_notify)
        self.dsdlg_register("notify_on_repeated_failure", self.dsdlg_check_failure_notify)

        self.dsdlg_spin_failure_threshold = QSpinBox()
        self.dsdlg_spin_failure_threshold.setRange(1, 99)
        self.dsdlg_spin_failure_threshold.setSuffix(" 次")
        self.dsdlg_spin_failure_threshold.valueChanged.connect(
            lambda value: self.dsdlg_store_int("notify_failure_threshold", int(value))
        )
        form.addRow("连续失败达到", self.dsdlg_spin_failure_threshold)
        self.dsdlg_register("notify_failure_threshold", self.dsdlg_spin_failure_threshold)

        self.dsdlg_check_tray_fallback = QCheckBox("弹窗失败时用托盘气泡兜底")
        self.dsdlg_check_tray_fallback.toggled.connect(
            lambda value: self.dsdlg_store_bool("tray_balloon_fallback", value)
        )
        form.addRow("", self.dsdlg_check_tray_fallback)
        self.dsdlg_register("tray_balloon_fallback", self.dsdlg_check_tray_fallback)
        layout.addWidget(group)

        test_row = QHBoxLayout()
        button_test = QPushButton("发送测试通知")
        button_test.clicked.connect(self.dsdlg_toast_test_requested.emit)
        test_row.addWidget(button_test)
        self.dsdlg_label_toast_backend = QLabel("")
        self.dsdlg_label_toast_backend.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        test_row.addWidget(self.dsdlg_label_toast_backend, 1)
        layout.addLayout(test_row)
        layout.addStretch(1)
        return self.dsdlg_wrap_scroll(page)

    def dsdlg_build_tab_store(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group = QGroupBox("记录持久化")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(6)
        self.dsdlg_check_storage = QCheckBox("启用持久化（关闭后仅内存保存，重启即清空）")
        self.dsdlg_check_storage.toggled.connect(self.dsdlg_on_storage_toggled)
        form.addRow("", self.dsdlg_check_storage)
        self.dsdlg_register("storage_enabled", self.dsdlg_check_storage)

        self.dsdlg_combo_backend = QComboBox()
        for backend, title in DSBM_STORAGE_TITLES.items():
            self.dsdlg_combo_backend.addItem(title, backend)
        self.dsdlg_combo_backend.currentIndexChanged.connect(self.dsdlg_on_backend_changed)
        form.addRow("存储后端", self.dsdlg_combo_backend)
        self.dsdlg_register("storage_backend", self.dsdlg_combo_backend)

        self.dsdlg_label_backend_state = QLabel("")
        self.dsdlg_label_backend_state.setWordWrap(True)
        self.dsdlg_label_backend_state.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        form.addRow("当前后端", self.dsdlg_label_backend_state)
        layout.addWidget(group)

        group_csv = QGroupBox("CSV 导出")
        form_csv = QFormLayout(group_csv)
        form_csv.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_csv.setSpacing(6)
        csv_row = QWidget()
        csv_layout = QHBoxLayout(csv_row)
        csv_layout.setContentsMargins(0, 0, 0, 0)
        csv_layout.setSpacing(6)
        self.dsdlg_edit_csv_dir = QLineEdit()
        self.dsdlg_edit_csv_dir.setPlaceholderText("留空 = 导出到程序目录 data\\exports")
        self.dsdlg_edit_csv_dir.textEdited.connect(
            lambda text: self.dsdlg_store_text("csv_export_dir", text.strip())
        )
        csv_layout.addWidget(self.dsdlg_edit_csv_dir, 1)
        button_browse = QPushButton("浏览…")
        button_browse.clicked.connect(self.dsdlg_on_browse_csv_dir)
        csv_layout.addWidget(button_browse)
        form_csv.addRow("导出目录", csv_row)
        self.dsdlg_register("csv_export_dir", self.dsdlg_edit_csv_dir)

        self.dsdlg_check_export_visible = QCheckBox("只导出当前筛选结果（未勾选则导出全部记录）")
        self.dsdlg_check_export_visible.toggled.connect(
            lambda value: self.dsdlg_store_bool("csv_export_visible_only", value)
        )
        form_csv.addRow("", self.dsdlg_check_export_visible)
        self.dsdlg_register("csv_export_visible_only", self.dsdlg_check_export_visible)

        csv_buttons = QHBoxLayout()
        button_open_data = QPushButton("打开数据目录")
        button_open_data.clicked.connect(self.dsdlg_open_data_dir_requested.emit)
        csv_buttons.addWidget(button_open_data)
        button_open_csv = QPushButton("打开导出目录")
        button_open_csv.clicked.connect(self.dsdlg_open_csv_dir_requested.emit)
        csv_buttons.addWidget(button_open_csv)
        button_clear = QPushButton("清空全部记录…")
        button_clear.clicked.connect(self.dsdlg_clear_records_requested.emit)
        csv_buttons.addWidget(button_clear)
        csv_buttons.addStretch(1)
        form_csv.addRow("", self.dsdlg_wrap_buttons(csv_buttons))
        layout.addWidget(group_csv)
        layout.addStretch(1)
        return self.dsdlg_wrap_scroll(page)

    def dsdlg_wrap_buttons(self, layout: QHBoxLayout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def dsdlg_build_tab_secret(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group_api = QGroupBox("DeepSeek 接口（写入项目根目录 .env）")
        form_api = QFormLayout(group_api)
        form_api.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_api.setSpacing(6)
        self.dsdlg_edit_api_base = QLineEdit()
        self.dsdlg_edit_api_base.setPlaceholderText(DSBM_API_DEFAULT_BASE)
        form_api.addRow("API 地址", self.dsdlg_edit_api_base)
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)
        self.dsdlg_edit_api_key = QLineEdit()
        self.dsdlg_edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.dsdlg_edit_api_key.setPlaceholderText("sk-…")
        key_layout.addWidget(self.dsdlg_edit_api_key, 1)
        self.dsdlg_button_toggle_key = QPushButton("显示")
        self.dsdlg_button_toggle_key.setCheckable(True)
        self.dsdlg_button_toggle_key.setFixedWidth(60)
        self.dsdlg_button_toggle_key.toggled.connect(self.dsdlg_on_toggle_key_echo)
        key_layout.addWidget(self.dsdlg_button_toggle_key)
        form_api.addRow("API Key", key_row)
        self.dsdlg_spin_timeout = QSpinBox()
        self.dsdlg_spin_timeout.setRange(3, 120)
        self.dsdlg_spin_timeout.setSuffix(" 秒")
        form_api.addRow("请求超时", self.dsdlg_spin_timeout)
        self.dsdlg_spin_retry = QSpinBox()
        self.dsdlg_spin_retry.setRange(0, 10)
        self.dsdlg_spin_retry.setSuffix(" 次")
        form_api.addRow("失败重试", self.dsdlg_spin_retry)
        layout.addWidget(group_api)

        group_db = QGroupBox("MySQL（可选；不填则使用本地 SQLite，无需密码）")
        form_db = QFormLayout(group_db)
        form_db.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_db.setSpacing(6)
        self.dsdlg_edit_db_host = QLineEdit()
        form_db.addRow("主机", self.dsdlg_edit_db_host)
        self.dsdlg_spin_db_port = QSpinBox()
        self.dsdlg_spin_db_port.setRange(1, 65535)
        form_db.addRow("端口", self.dsdlg_spin_db_port)
        self.dsdlg_edit_db_user = QLineEdit()
        form_db.addRow("用户名", self.dsdlg_edit_db_user)
        self.dsdlg_edit_db_password = QLineEdit()
        self.dsdlg_edit_db_password.setEchoMode(QLineEdit.EchoMode.Password)
        form_db.addRow("密码", self.dsdlg_edit_db_password)
        self.dsdlg_edit_db_name = QLineEdit()
        form_db.addRow("数据库名", self.dsdlg_edit_db_name)
        layout.addWidget(group_db)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        button_save_env = QPushButton("保存到 .env 并重新连接")
        button_save_env.clicked.connect(self.dsdlg_on_save_env)
        action_row.addWidget(button_save_env)
        self.dsdlg_button_probe = QPushButton("测试连接（查询一次）")
        self.dsdlg_button_probe.clicked.connect(self.dsdlg_on_probe)
        action_row.addWidget(self.dsdlg_button_probe)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.dsdlg_progress_probe = QProgressBar()
        self.dsdlg_progress_probe.setRange(0, 100)
        self.dsdlg_progress_probe.setValue(0)
        self.dsdlg_progress_probe.setFixedHeight(14)
        layout.addWidget(self.dsdlg_progress_probe)
        self.dsdlg_label_probe = QLabel("尚未测试")
        self.dsdlg_label_probe.setWordWrap(True)
        self.dsdlg_label_probe.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        layout.addWidget(self.dsdlg_label_probe)
        layout.addStretch(1)
        return self.dsdlg_wrap_scroll(page)

    def dsdlg_build_tab_ui(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group = QGroupBox("界面与窗口")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(6)
        self.dsdlg_combo_scale = QComboBox()
        for scale in DSBM_UI_SCALE_CHOICES:
            self.dsdlg_combo_scale.addItem(f"{int(scale * 100)}%", float(scale))
        self.dsdlg_combo_scale.setEditable(False)
        self.dsdlg_combo_scale.currentIndexChanged.connect(self.dsdlg_on_scale_changed)
        form.addRow("界面缩放", self.dsdlg_combo_scale)
        self.dsdlg_register("ui_scale", self.dsdlg_combo_scale)

        self.dsdlg_spin_row_height = QSpinBox()
        self.dsdlg_spin_row_height.setRange(16, 48)
        self.dsdlg_spin_row_height.setSuffix(" 像素")
        self.dsdlg_spin_row_height.valueChanged.connect(
            lambda value: self.dsdlg_store_int("table_row_height", int(value))
        )
        form.addRow("表格行高", self.dsdlg_spin_row_height)
        self.dsdlg_register("table_row_height", self.dsdlg_spin_row_height)

        self.dsdlg_spin_table_font = QDoubleSpinBox()
        self.dsdlg_spin_table_font.setRange(DSBM_TABLE_FONT_MIN, DSBM_TABLE_FONT_MAX)
        self.dsdlg_spin_table_font.setSingleStep(0.5)
        self.dsdlg_spin_table_font.setDecimals(1)
        self.dsdlg_spin_table_font.setSuffix(" 磅")
        self.dsdlg_spin_table_font.setToolTip(
            "只调整记录表（含表头）的字体大小，不影响其他界面元素；"
            "实际大小还会叠加「界面缩放」，行高不够时会自动放大行"
        )
        self.dsdlg_spin_table_font.valueChanged.connect(
            lambda value: self.dsdlg_store_float("table_font_size", float(value))
        )
        form.addRow("列表字体", self.dsdlg_spin_table_font)
        self.dsdlg_register("table_font_size", self.dsdlg_spin_table_font)

        self.dsdlg_check_tray_icon = QCheckBox("显示系统托盘图标")
        self.dsdlg_check_tray_icon.toggled.connect(self.dsdlg_on_tray_icon_toggled)
        form.addRow("", self.dsdlg_check_tray_icon)
        self.dsdlg_register("show_tray_icon", self.dsdlg_check_tray_icon)

        self.dsdlg_check_close_tray = QCheckBox("点击关闭按钮时最小化到托盘（不退出）")
        self.dsdlg_check_close_tray.toggled.connect(
            lambda value: self.dsdlg_store_bool("close_to_tray", value)
        )
        form.addRow("", self.dsdlg_check_close_tray)
        self.dsdlg_register("close_to_tray", self.dsdlg_check_close_tray)

        self.dsdlg_check_min_tray = QCheckBox("最小化时隐藏到托盘")
        self.dsdlg_check_min_tray.toggled.connect(
            lambda value: self.dsdlg_store_bool("minimize_to_tray", value)
        )
        form.addRow("", self.dsdlg_check_min_tray)
        self.dsdlg_register("minimize_to_tray", self.dsdlg_check_min_tray)

        self.dsdlg_check_builtin_icon = QCheckBox("icon.ico 不存在时使用内置绘制图标（仅用于托盘，窗口图标保持为空）")
        self.dsdlg_check_builtin_icon.toggled.connect(
            lambda value: self.dsdlg_store_bool("use_builtin_icon_if_missing", value)
        )
        form.addRow("", self.dsdlg_check_builtin_icon)
        self.dsdlg_register("use_builtin_icon_if_missing", self.dsdlg_check_builtin_icon)

        self.dsdlg_check_single_instance = QCheckBox("同一时间只允许运行一个实例")
        self.dsdlg_check_single_instance.toggled.connect(
            lambda value: self.dsdlg_store_bool("single_instance", value)
        )
        form.addRow("", self.dsdlg_check_single_instance)
        self.dsdlg_register("single_instance", self.dsdlg_check_single_instance)
        layout.addWidget(group)
        layout.addStretch(1)
        return self.dsdlg_wrap_scroll(page)

    # ------------------------------------------------------------------ 读写
    def dsdlg_load_values(self) -> None:
        settings = self.dsdlg_settings
        self.dsdlg_syncing = True
        try:
            interval = settings.dsgset_get_int("query_interval_seconds", DSBM_DEFAULT_INTERVAL_SECONDS)
            amount, unit = dsbm_interval_to_parts(interval)
            self.dsdlg_spin_interval.setValue(int(amount))
            index = self.dsdlg_combo_unit.findText(unit)
            if index >= 0:
                self.dsdlg_combo_unit.setCurrentIndex(index)
            self.dsdlg_check_auto_start.setChecked(settings.dsgset_get_bool("auto_query_on_start", True))
            self.dsdlg_check_paused.setChecked(settings.dsgset_get_bool("polling_paused", False))
            self.dsdlg_edit_currency.setText(settings.dsgset_get_str("preferred_currency", ""))
            self.dsdlg_spin_max_records.setValue(settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS))
            self.dsdlg_check_baseline.setChecked(settings.dsgset_get_bool("record_baseline", True))
            self.dsdlg_check_only_debit.setChecked(settings.dsgset_get_bool("only_debit_filter", False))
            self.dsdlg_check_only_credit.setChecked(
                settings.dsgset_get_bool("only_credit_filter", False)
            )

            self.dsdlg_check_notify.setChecked(settings.dsgset_get_bool("notify_enabled", True))
            mode_index = self.dsdlg_combo_notify_mode.findData(settings.dsgset_get_str("notify_mode"))
            if mode_index >= 0:
                self.dsdlg_combo_notify_mode.setCurrentIndex(mode_index)
            self.dsdlg_spin_threshold.setValue(settings.dsgset_get_float("notify_threshold", 0.0))
            self.dsdlg_check_include_balance.setChecked(
                settings.dsgset_get_bool("notify_include_balance", True)
            )
            self.dsdlg_check_failure_notify.setChecked(
                settings.dsgset_get_bool("notify_on_repeated_failure", True)
            )
            self.dsdlg_spin_failure_threshold.setValue(
                settings.dsgset_get_int("notify_failure_threshold", 3)
            )
            self.dsdlg_check_tray_fallback.setChecked(
                settings.dsgset_get_bool("tray_balloon_fallback", True)
            )

            self.dsdlg_check_storage.setChecked(settings.dsgset_get_bool("storage_enabled", True))
            backend_index = self.dsdlg_combo_backend.findData(
                settings.dsgset_get_str("storage_backend")
            )
            if backend_index >= 0:
                self.dsdlg_combo_backend.setCurrentIndex(backend_index)
            self.dsdlg_edit_csv_dir.setText(settings.dsgset_get_str("csv_export_dir", ""))
            self.dsdlg_check_export_visible.setChecked(
                settings.dsgset_get_bool("csv_export_visible_only", True)
            )

            self.dsdlg_check_tray_icon.setChecked(settings.dsgset_get_bool("show_tray_icon", True))
            self.dsdlg_check_close_tray.setChecked(settings.dsgset_get_bool("close_to_tray", True))
            self.dsdlg_check_min_tray.setChecked(settings.dsgset_get_bool("minimize_to_tray", False))
            self.dsdlg_check_builtin_icon.setChecked(
                settings.dsgset_get_bool("use_builtin_icon_if_missing", True)
            )
            self.dsdlg_check_single_instance.setChecked(settings.dsgset_get_bool("single_instance", True))
            self.dsdlg_spin_row_height.setValue(settings.dsgset_get_int("table_row_height", 22))
            self.dsdlg_spin_table_font.setValue(
                settings.dsgset_get_float("table_font_size", DSBM_TABLE_FONT_DEFAULT)
            )
            scale = float(settings.dsgset_get_float("ui_scale", 1.0) or 1.0)
            scale_index = self.dsdlg_combo_scale.findData(scale)
            if scale_index < 0:
                self.dsdlg_combo_scale.addItem(f"{int(scale * 100)}%", scale)
                scale_index = self.dsdlg_combo_scale.count() - 1
            self.dsdlg_combo_scale.setCurrentIndex(scale_index)
        finally:
            self.dsdlg_syncing = False
        self.dsdlg_reload_env_fields()
        self.dsdlg_sync_enabled_states()

    def dsdlg_reload_env_fields(self) -> None:
        env = self.dsdlg_env
        env.dsenv_reload()
        self.dsdlg_edit_api_base.setText(env.dsenv_api_base())
        self.dsdlg_edit_api_key.setText(env.dsenv_api_key())
        self.dsdlg_spin_timeout.setValue(env.dsenv_timeout())
        self.dsdlg_spin_retry.setValue(env.dsenv_max_retry())
        config = env.dsenv_db_config()
        self.dsdlg_edit_db_host.setText(config["host"])
        self.dsdlg_spin_db_port.setValue(config["port"])
        self.dsdlg_edit_db_user.setText(config["user"])
        self.dsdlg_edit_db_password.setText(config["password"])
        self.dsdlg_edit_db_name.setText(config["name"])

    def dsdlg_sync_enabled_states(self) -> None:
        notify_on = self.dsdlg_check_notify.isChecked()
        for widget in (self.dsdlg_combo_notify_mode, self.dsdlg_spin_threshold,
                       self.dsdlg_check_include_balance):
            widget.setEnabled(notify_on)
        failure_on = self.dsdlg_check_failure_notify.isChecked()
        self.dsdlg_spin_failure_threshold.setEnabled(failure_on)
        storage_on = self.dsdlg_check_storage.isChecked()
        self.dsdlg_combo_backend.setEnabled(storage_on)

    def dsdlg_set_backend_state(self, text: str, toast_backend: str = "") -> None:
        self.dsdlg_label_backend_state.setText(text)
        if toast_backend:
            self.dsdlg_label_toast_backend.setText(f"当前通知后端：{toast_backend}")

    def dsdlg_set_probe_state(self, percent: int | None, text: str, level: str = "info") -> None:
        if percent is None:
            self.dsdlg_progress_probe.setRange(0, 0)
        else:
            self.dsdlg_progress_probe.setRange(0, 100)
            self.dsdlg_progress_probe.setValue(int(max(0, min(100, percent))))
        colors = {"info": DSBM_COLOR_MUTED, "ok": DSBM_COLOR_OK,
                  "warn": DSBM_COLOR_WARN, "error": DSBM_COLOR_ERROR}
        self.dsdlg_label_probe.setText(text)
        self.dsdlg_label_probe.setStyleSheet(f"color: {colors.get(level, DSBM_COLOR_MUTED)};")

    # ------------------------------------------------------------------ 槽
    def dsdlg_mark_saved(self) -> None:
        self.dsdlg_label_saved.setText(f"已自动保存 · {dsbm_format_time_ms(dsbm_now_ms())[11:]}")
        self.dsdlg_label_saved.setStyleSheet(f"color: {DSBM_COLOR_OK};")

    def dsdlg_store_bool(self, key: str, value: bool) -> None:
        if self.dsdlg_syncing:
            return
        self.dsdlg_settings.dsgset_set(key, bool(value))
        self.dsdlg_mark_saved()
        self.dsdlg_sync_enabled_states()

    def dsdlg_store_int(self, key: str, value: int) -> None:
        if self.dsdlg_syncing:
            return
        self.dsdlg_settings.dsgset_set(key, int(value))
        self.dsdlg_mark_saved()

    def dsdlg_store_float(self, key: str, value: float) -> None:
        if self.dsdlg_syncing:
            return
        self.dsdlg_settings.dsgset_set(key, float(value))
        self.dsdlg_mark_saved()

    def dsdlg_store_text(self, key: str, value: str) -> None:
        if self.dsdlg_syncing:
            return
        self.dsdlg_settings.dsgset_set(key, str(value))
        self.dsdlg_mark_saved()

    @Slot()
    def dsdlg_on_interval_changed(self) -> None:
        if self.dsdlg_syncing:
            return
        seconds = dsbm_parts_to_interval(
            int(self.dsdlg_spin_interval.value()), self.dsdlg_combo_unit.currentText()
        )
        self.dsdlg_settings.dsgset_set("query_interval_seconds", int(seconds))
        self.dsdlg_mark_saved()
        self.dsdlg_sync_interval_widgets()

    def dsdlg_sync_interval_widgets(self) -> None:
        seconds = self.dsdlg_settings.dsgset_get_int("query_interval_seconds")
        amount, unit = dsbm_interval_to_parts(seconds)
        self.dsdlg_syncing = True
        try:
            self.dsdlg_spin_interval.setRange(1, 86400 if unit == DSBM_UNIT_SECOND else 1440)
            if int(amount) != int(self.dsdlg_spin_interval.value()):
                self.dsdlg_spin_interval.setValue(int(amount))
            index = self.dsdlg_combo_unit.findText(unit)
            if index >= 0 and index != self.dsdlg_combo_unit.currentIndex():
                self.dsdlg_combo_unit.setCurrentIndex(index)
        finally:
            self.dsdlg_syncing = False

    @Slot()
    def dsdlg_on_notify_mode_changed(self) -> None:
        mode = self.dsdlg_combo_notify_mode.currentData()
        if mode:
            self.dsdlg_store_text("notify_mode", str(mode))

    @Slot(bool)
    def dsdlg_on_only_debit_toggled(self, value: bool) -> None:
        self.dsdlg_store_bool("only_debit_filter", value)
        if value:
            self.dsdlg_check_only_credit.setChecked(False)

    @Slot(bool)
    def dsdlg_on_only_credit_toggled(self, value: bool) -> None:
        self.dsdlg_store_bool("only_credit_filter", value)
        if value:
            self.dsdlg_check_only_debit.setChecked(False)

    @Slot(bool)
    def dsdlg_on_storage_toggled(self, value: bool) -> None:
        self.dsdlg_store_bool("storage_enabled", value)
        if not self.dsdlg_syncing:
            self.dsdlg_store_reinit_requested.emit()

    @Slot()
    def dsdlg_on_backend_changed(self) -> None:
        backend = self.dsdlg_combo_backend.currentData()
        if not backend or self.dsdlg_syncing:
            return
        self.dsdlg_store_text("storage_backend", str(backend))
        self.dsdlg_store_reinit_requested.emit()

    @Slot(bool)
    def dsdlg_on_tray_icon_toggled(self, value: bool) -> None:
        self.dsdlg_store_bool("show_tray_icon", value)

    @Slot()
    def dsdlg_on_scale_changed(self) -> None:
        if self.dsdlg_syncing:
            return
        scale = self.dsdlg_combo_scale.currentData()
        if scale is None:
            return
        self.dsdlg_store_float("ui_scale", float(scale))

    @Slot(bool)
    def dsdlg_on_toggle_key_echo(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.dsdlg_edit_api_key.setEchoMode(mode)
        self.dsdlg_button_toggle_key.setText("隐藏" if shown else "显示")

    @Slot()
    def dsdlg_on_browse_csv_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.dsdlg_edit_csv_dir.text().strip() or str(dsbm_data_dir())
        chosen = QFileDialog.getExistingDirectory(self, "选择 CSV 导出目录", start)
        if chosen:
            self.dsdlg_edit_csv_dir.setText(chosen)
            self.dsdlg_store_text("csv_export_dir", chosen)

    @Slot()
    def dsdlg_on_save_env(self) -> None:
        mapping = {
            DSBM_ENV_KEY_API_BASE: self.dsdlg_edit_api_base.text().strip() or DSBM_API_DEFAULT_BASE,
            DSBM_ENV_KEY_API_KEY: self.dsdlg_edit_api_key.text().strip(),
            DSBM_ENV_KEY_TIMEOUT: str(int(self.dsdlg_spin_timeout.value())),
            DSBM_ENV_KEY_MAX_RETRY: str(int(self.dsdlg_spin_retry.value())),
            DSBM_ENV_KEY_DB_HOST: self.dsdlg_edit_db_host.text().strip(),
            DSBM_ENV_KEY_DB_PORT: str(int(self.dsdlg_spin_db_port.value())),
            DSBM_ENV_KEY_DB_USER: self.dsdlg_edit_db_user.text().strip(),
            DSBM_ENV_KEY_DB_PASSWORD: self.dsdlg_edit_db_password.text(),
            DSBM_ENV_KEY_DB_NAME: self.dsdlg_edit_db_name.text().strip(),
        }
        if self.dsdlg_env.dsenv_set_many(mapping):
            self.dsdlg_client.dsapi_reload_config()
            self.dsdlg_store_reinit_requested.emit()
            summary = self.dsdlg_env.dsenv_masked_summary()
            self.dsdlg_set_probe_state(
                100,
                f"已写入 .env：{DSBM_ENV_KEY_API_KEY}={summary['api_key']}，"
                f"数据库={summary['db_name']}",
                "ok",
            )
        else:
            self.dsdlg_set_probe_state(0, "写入 .env 失败，请检查文件权限（详见日志）", "error")

    @Slot()
    def dsdlg_on_probe(self) -> None:
        self.dsdlg_set_probe_state(None, "正在查询 /user/balance …", "info")
        self.dsdlg_probe_requested.emit()

    @Slot()
    def dsdlg_on_restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self, "恢复默认值",
            "确定把所有设置恢复为默认值吗？\n（记录数据、.env 密钥不会被删除）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.dsdlg_settings.dsgset_reset_to_defaults()
        self.dsdlg_load_values()
        self.dsdlg_mark_saved()

    def dsdlg_apply_external_change(self, key: str, value: Any) -> None:
        """主窗口改了某项设置（如全局快捷键 / 托盘暂停）时，把界面同步过来。"""
        if key not in self.dsdlg_widgets:
            if key == "query_interval_seconds":
                self.dsdlg_sync_interval_widgets()
            return
        widget = self.dsdlg_widgets[key]
        self.dsdlg_syncing = True
        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value) if not isinstance(value, float) else int(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        finally:
            self.dsdlg_syncing = False
        self.dsdlg_sync_enabled_states()


class DsbmInfoDialog(QDialog):
    """通用信息窗口：使用说明 / 关于 / 逻辑记忆。"""

    def __init__(self, title: str, html: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(620, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        layout.addWidget(browser, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        button_close = QPushButton("关闭")
        button_close.clicked.connect(self.accept)
        row.addWidget(button_close)
        layout.addLayout(row)


# ==============================================================================
# 十五、单实例锁
# ==============================================================================


class DsbmInstanceLock:
    """基于 QLockFile 的单实例锁，避免双开导致同一份设置 / 数据库被交叉写入。"""

    def __init__(self, lock_file: Path) -> None:
        dsbm_ensure_dir(lock_file.parent)
        self.dslock_file = QLockFile(str(lock_file))
        self.dslock_file.setStaleLockTime(30000)
        self.dslock_acquired = False

    def dslock_acquire(self) -> bool:
        self.dslock_acquired = bool(self.dslock_file.tryLock(200))
        return self.dslock_acquired

    def dslock_holder_text(self) -> str:
        try:
            pid, hostname, appname = self.dslock_file.getLockInfo()
        except (TypeError, ValueError):
            return "未知进程"
        return f"PID {pid}（{hostname} / {appname or '另一实例'}）"

    def dslock_release(self) -> None:
        if self.dslock_acquired:
            self.dslock_file.unlock()
            self.dslock_acquired = False


# ==============================================================================
# 十六、主窗口
# ==============================================================================


class DsbmMainWindow(QMainWindow):
    """主窗口：余额总览 + 变化记录表 + 定时调度 + 通知派发。"""

    dwin_shutdown_requested = Signal()

    def __init__(
        self,
        settings_manager: DsbmSettingsManager,
        env_manager: DsbmEnvFileManager,
        api_client: DsbmBalanceApiClient,
        record_store: DsbmRecordStore,
        toast_service: DsbmToastService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.dwin_settings = settings_manager
        self.dwin_env = env_manager
        self.dwin_client = api_client
        self.dwin_store = record_store
        self.dwin_toast = toast_service
        self.dwin_logger = logging.getLogger(DSBM_LOGGER_NAME)

        self.dwin_model = DsbmRecordTableModel(self)
        self.dwin_card: DsbmBalanceCardWidget | None = None
        self.dwin_table: QTableView | None = None
        self.dwin_check_debit: QCheckBox | None = None
        self.dwin_check_credit: QCheckBox | None = None
        self.dwin_button_refresh: QPushButton | None = None
        self.dwin_button_export: QPushButton | None = None
        self.dwin_button_clear: QPushButton | None = None
        self.dwin_button_settings: QPushButton | None = None
        self.dwin_button_close: QPushButton | None = None
        self.dwin_label_hint: QLabel | None = None
        self.dwin_label_stats: DsbmElidedLabel | None = None
        self.dwin_label_extra: DsbmElidedLabel | None = None
        self.dwin_progress_query: QProgressBar | None = None
        self.dwin_progress_capacity: QProgressBar | None = None
        self.dwin_progress_export: QProgressBar | None = None
        self.dwin_label_export: QLabel | None = None

        self.dwin_query_thread: DsbmBalanceQueryThread | None = None
        self.dwin_export_thread: DsbmCsvExportThread | None = None
        self.dwin_settings_dialog: DsbmSettingsDialog | None = None
        self.dwin_tray: DsbmTrayController | None = None
        self.dwin_app_icon = QIcon()
        self.dwin_clock_timer = QTimer(self)
        self.dwin_clock_timer.setInterval(DSBM_CLOCK_TICK_MS)
        self.dwin_clock_timer.timeout.connect(self.dwin_on_clock_tick)
        self.dwin_save_timer = QTimer(self)
        self.dwin_save_timer.setSingleShot(True)
        self.dwin_save_timer.setInterval(600)
        self.dwin_save_timer.timeout.connect(self.dwin_persist_window_state)
        self.dwin_next_due_ms = 0
        self.dwin_last_notify_signature = ""
        self.dwin_initializing = True
        self.dwin_init_steps: list[tuple[str, Callable[[], None]]] = []
        self.dwin_force_quit = False
        self.dwin_shutdown_done = False
        self.dwin_startup_error = ""

        self.setWindowTitle(f"{DSBM_APP_CN_NAME}  v{DSBM_APP_VERSION}")
        self.setMinimumSize(QSize(660, 420))
        self.dwin_build_ui()
        self.dwin_build_menus()
        self.dwin_build_status_bar()
        self.dwin_connect_signals()
        self.dwin_apply_ui_scale(float(self.dwin_settings.dsgset_get_float("ui_scale", 1.0) or 1.0))
        self.dwin_apply_row_height()
        self.dwin_restore_window_state()
        self.dwin_sync_interval_widgets()
        self.dwin_apply_filter_state()
        self.dwin_update_env_summary()
        self.dwin_build_tray()

    # ==================================================================
    # 构建界面
    # ==================================================================
    def dwin_build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.dwin_card = DsbmBalanceCardWidget(self.dwin_settings)
        layout.addWidget(self.dwin_card)

        self.dwin_label_hint = QLabel()
        self.dwin_label_hint.setWordWrap(True)
        self.dwin_label_hint.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        layout.addWidget(self.dwin_label_hint)
        self.dwin_refresh_hint_text()

        self.dwin_table = QTableView()
        self.dwin_table.setModel(self.dwin_model)
        self.dwin_table.setSortingEnabled(True)
        self.dwin_table.setAlternatingRowColors(True)
        self.dwin_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dwin_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.dwin_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dwin_table.setWordWrap(False)
        self.dwin_table.setShowGrid(True)
        self.dwin_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dwin_table.setCornerButtonEnabled(False)
        table_header = self.dwin_table.horizontalHeader()
        table_header.setStretchLastSection(True)
        table_header.setSectionsMovable(False)
        self.dwin_table.verticalHeader().setVisible(False)
        layout.addWidget(self.dwin_table, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.dwin_check_debit = QCheckBox("只看扣钱（0 条）")
        self.dwin_check_debit.setToolTip("只显示余额减少的记录；与「只看增加」互斥，勾选状态会自动保存")
        button_row.addWidget(self.dwin_check_debit)
        self.dwin_check_credit = QCheckBox("只看增加（0 条）")
        self.dwin_check_credit.setToolTip(
            "只显示余额增加的记录（充值 / 退款到账）；与「只看扣钱」互斥，勾选状态会自动保存"
        )
        button_row.addWidget(self.dwin_check_credit)
        button_row.addStretch(1)

        self.dwin_button_refresh = QPushButton("刷新")
        self.dwin_button_refresh.setToolTip("立刻查询一次余额并重新载入记录表（Ctrl+R）")
        button_row.addWidget(self.dwin_button_refresh)
        self.dwin_button_export = QPushButton("导出 CSV")
        self.dwin_button_export.setToolTip("导出记录为 CSV（Excel 可直接打开，Ctrl+E）")
        button_row.addWidget(self.dwin_button_export)
        self.dwin_button_clear = QPushButton("清空记录")
        self.dwin_button_clear.setToolTip("清空所有变化记录（需确认）")
        button_row.addWidget(self.dwin_button_clear)
        self.dwin_button_settings = QPushButton("设置")
        button_row.addWidget(self.dwin_button_settings)
        self.dwin_button_close = QPushButton("关闭")
        self.dwin_button_close.setToolTip("关闭窗口（按设置为最小化到托盘或退出程序）")
        button_row.addWidget(self.dwin_button_close)
        layout.addLayout(button_row)

        self.setCentralWidget(container)
        self.dwin_apply_table_defaults()

    def dwin_apply_table_defaults(self) -> None:
        header = self.dwin_table.horizontalHeader()
        widths = [int(w) for w in self.dwin_settings.dsgset_get("table_column_widths", [])]
        default_widths = [210, 110, 170, 130]
        for section in range(len(DSBM_COLUMN_TITLES)):
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)
            width = widths[section] if section < len(widths) and widths[section] > 40 else default_widths[section]
            self.dwin_table.setColumnWidth(section, width)
        self.dwin_table.setColumnWidth(DSBM_COLUMN_DELTA, widths[1] if len(widths) > 1 and widths[1] > 40 else 100)

    def dwin_build_menus(self) -> None:
        menu_file = self.menuBar().addMenu("文件(&F)")
        action_export = QAction("导出 CSV(&E)…", self)
        action_export.setShortcut(QKeySequence("Ctrl+E"))
        action_export.triggered.connect(self.dwin_export_csv)
        menu_file.addAction(action_export)
        action_open_data = QAction("打开数据目录(&D)", self)
        action_open_data.triggered.connect(self.dwin_open_data_dir)
        menu_file.addAction(action_open_data)
        menu_file.addSeparator()
        action_quit = QAction("退出(&Q)", self)
        action_quit.setShortcut(QKeySequence("Ctrl+Q"))
        action_quit.triggered.connect(self.dwin_request_quit)
        menu_file.addAction(action_quit)

        menu_query = self.menuBar().addMenu("查询(&Q)")
        action_query_now = QAction("立即查询(&R)", self)
        action_query_now.setShortcut(QKeySequence("Ctrl+R"))
        action_query_now.triggered.connect(lambda: self.dwin_request_query(DSBM_SOURCE_MANUAL, True))
        menu_query.addAction(action_query_now)
        action_pause = QAction("暂停 / 继续定时查询(&P)", self)
        action_pause.setShortcut(QKeySequence("Ctrl+P"))
        action_pause.triggered.connect(self.dwin_toggle_pause)
        menu_query.addAction(action_pause)
        menu_query.addSeparator()
        for seconds in (30, 60, 120, 300, 600, 1800, 3600):
            action_preset = QAction(f"间隔 {dsbm_format_duration(seconds)}", self)
            action_preset.triggered.connect(
                lambda _checked=False, value=seconds: self.dwin_on_interval_changed(value)
            )
            menu_query.addAction(action_preset)

        menu_settings = self.menuBar().addMenu("设置(&S)")
        action_settings = QAction("打开设置窗口(&O)…", self)
        action_settings.setShortcut(QKeySequence("Ctrl+,"))
        action_settings.triggered.connect(self.dwin_open_settings_dialog)
        menu_settings.addAction(action_settings)
        action_clear = QAction("清空所有记录(&C)…", self)
        action_clear.triggered.connect(self.dwin_clear_records)
        menu_settings.addAction(action_clear)
        action_reinit = QAction("重新连接存储(&R)", self)
        action_reinit.triggered.connect(self.dwin_reinitialize_store)
        menu_settings.addAction(action_reinit)

        menu_help = self.menuBar().addMenu("帮助(&H)")
        action_help = QAction("使用说明(&H)…", self)
        action_help.triggered.connect(self.dwin_show_help_dialog)
        menu_help.addAction(action_help)
        action_about = QAction("关于(&A)…", self)
        action_about.triggered.connect(self.dwin_show_about_dialog)
        menu_help.addAction(action_about)

    def dwin_build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(True)
        self.setStatusBar(bar)

        self.dwin_label_stats = DsbmElidedLabel("共 0 条")
        self.dwin_label_extra = DsbmElidedLabel("")
        self.dwin_label_extra.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        bar.addWidget(self.dwin_label_stats, 1)
        bar.addWidget(self.dwin_label_extra, 1)

        self.dwin_label_export = QLabel("导出")
        self.dwin_label_export.setStyleSheet(f"color: {DSBM_COLOR_MUTED};")
        self.dwin_progress_export = QProgressBar()
        self.dwin_progress_export.setRange(0, 100)
        self.dwin_progress_export.setValue(0)
        self.dwin_progress_export.setFixedWidth(140)
        self.dwin_progress_export.setFixedHeight(14)
        self.dwin_progress_export.setVisible(False)
        self.dwin_label_export.setVisible(False)
        bar.addPermanentWidget(self.dwin_label_export)
        bar.addPermanentWidget(self.dwin_progress_export)

        self.dwin_progress_query = QProgressBar()
        self.dwin_progress_query.setRange(0, 100)
        self.dwin_progress_query.setValue(0)
        self.dwin_progress_query.setFixedWidth(140)
        self.dwin_progress_query.setFixedHeight(14)
        self.dwin_progress_query.setToolTip("本次查询进度 / 闲时显示距离下次查询的进度")
        bar.addPermanentWidget(QLabel("查询"))
        bar.addPermanentWidget(self.dwin_progress_query)

        self.dwin_progress_capacity = QProgressBar()
        self.dwin_progress_capacity.setRange(0, 100)
        self.dwin_progress_capacity.setValue(0)
        self.dwin_progress_capacity.setFixedWidth(140)
        self.dwin_progress_capacity.setFixedHeight(14)
        self.dwin_progress_capacity.setToolTip("记录容量占用（当前条数 / 最多保留条数）")
        bar.addPermanentWidget(QLabel("容量"))
        bar.addPermanentWidget(self.dwin_progress_capacity)

    def dwin_connect_signals(self) -> None:
        self.dwin_card.dcard_query_requested.connect(
            lambda: self.dwin_request_query(DSBM_SOURCE_MANUAL, True)
        )
        self.dwin_card.dcard_settings_requested.connect(self.dwin_open_settings_dialog)
        self.dwin_card.dcard_pause_toggled.connect(self.dwin_on_pause_toggled)
        self.dwin_card.dcard_interval_changed.connect(self.dwin_on_interval_changed)
        self.dwin_check_debit.toggled.connect(self.dwin_on_filter_toggled)
        self.dwin_check_credit.toggled.connect(self.dwin_on_credit_filter_toggled)
        self.dwin_button_refresh.clicked.connect(
            lambda: self.dwin_request_query(DSBM_SOURCE_MANUAL, True)
        )
        self.dwin_button_export.clicked.connect(self.dwin_export_csv)
        self.dwin_button_clear.clicked.connect(self.dwin_clear_records)
        self.dwin_button_settings.clicked.connect(self.dwin_open_settings_dialog)
        self.dwin_button_close.clicked.connect(self.close)
        self.dwin_table.customContextMenuRequested.connect(self.dwin_show_table_menu)
        self.dwin_table.horizontalHeader().sortIndicatorChanged.connect(self.dwin_on_sort_changed)
        self.dwin_table.horizontalHeader().sectionResized.connect(self.dwin_on_column_resized)
        self.dwin_settings.dsgset_value_changed.connect(self.dwin_on_setting_value_changed)

    # ==================================================================
    # 初始化流程（带总进度条）
    # ==================================================================
    def dwin_start_initialization(self) -> None:
        self.dwin_init_steps = [
            ("① 读取设置与 .env 配置", self.dwin_step_settings_ready),
            ("② 连接记录存储", self.dwin_step_store_ready),
            ("③ 载入历史记录", self.dwin_step_history_ready),
            ("④ 准备通知通道", self.dwin_step_toast_ready),
            ("⑤ 首次余额查询", self.dwin_step_first_query),
        ]
        self.dwin_card.dcard_set_task_progress(0, "正在初始化…", True)
        self.dwin_clock_timer.start()
        QTimer.singleShot(60, self.dwin_run_next_init_step)

    def dwin_run_next_init_step(self) -> None:
        total = len(self.dwin_init_steps)
        if not self.dwin_init_steps:
            self.dwin_initializing = False
            self.dwin_card.dcard_set_task_progress(100, "初始化完成", False, True)
            QTimer.singleShot(1200, lambda: self.dwin_card.dcard_set_task_progress(0, "", False, False))
            self.dwin_refresh_statistics()
            return
        percent = int((total - len(self.dwin_init_steps)) * 100 / total)
        text, step = self.dwin_init_steps.pop(0)
        self.dwin_card.dcard_set_task_progress(percent, text, True)
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - 初始化步骤失败也要继续
            self.dwin_logger.exception("初始化步骤失败：%s", text)
            self.dwin_startup_error = f"{text} 失败：{type(exc).__name__}: {exc}"
            self.dwin_card.dcard_set_status(self.dwin_startup_error, "error")
        QTimer.singleShot(120, self.dwin_run_next_init_step)

    def dwin_step_settings_ready(self) -> None:
        summary = self.dwin_client.dsapi_reload_config()
        self.dwin_update_env_summary()
        self.dwin_logger.info(
            "读取配置完成：api_base=%s, key=%s, client=%s",
            summary["api_base"], summary["api_key_masked"], summary["client"],
        )
        if not summary["has_key"]:
            self.dwin_card.dcard_set_status("未配置 API Key（打开「设置 → 密钥与数据源」填写 .env）", "warn")

    def dwin_step_store_ready(self) -> None:
        ok, text = self.dwin_store.dsdb_initialize()
        self.dwin_update_env_summary()
        if not ok:
            self.dwin_card.dcard_set_status(f"存储初始化失败：{text}", "error")

    def dwin_step_history_ready(self) -> None:
        keep = self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
        records = self.dwin_store.dsdb_load_recent(keep)
        self.dwin_model.dmrec_set_records(records)
        self.dwin_store.dsdb_prune_records(keep)
        self.dwin_model.dmrec_set_sort_state(
            self.dwin_settings.dsgset_get_int("table_sort_column", DSBM_COLUMN_TIME),
            self.dwin_settings.dsgset_get_int("table_sort_order", 1),
        )
        self.dwin_sync_sort_indicator()
        self.dwin_refresh_statistics()

    def dwin_step_toast_ready(self) -> None:
        self.dwin_toast.dstoast_start()

    def dwin_step_first_query(self) -> None:
        last_balance = self.dwin_settings.dsgset_get_str("last_balance", "")
        if last_balance:
            self.dwin_restore_last_balance_view()
        if self.dwin_settings.dsgset_get_bool("auto_query_on_start", True):
            self.dwin_request_query(DSBM_SOURCE_STARTUP, True)
        else:
            self.dwin_schedule_next_query()

    # ==================================================================
    # 定时调度与查询
    # ==================================================================
    def dwin_schedule_next_query(self, from_ms: int | None = None) -> None:
        interval_ms = self.dwin_settings.dsgset_get_int("query_interval_seconds",
                                                        DSBM_DEFAULT_INTERVAL_SECONDS) * 1000
        base = dsbm_now_ms() if from_ms is None else int(from_ms)
        self.dwin_next_due_ms = base + interval_ms

    def dwin_on_clock_tick(self) -> None:
        interval_ms = self.dwin_settings.dsgset_get_int("query_interval_seconds",
                                                        DSBM_DEFAULT_INTERVAL_SECONDS) * 1000
        paused = self.dwin_settings.dsgset_get_bool("polling_paused", False)
        busy = self.dwin_query_is_busy()
        now_ms = dsbm_now_ms()
        remaining = (self.dwin_next_due_ms - now_ms) / 1000.0 if self.dwin_next_due_ms else interval_ms / 1000.0
        self.dwin_card.dcard_set_countdown(remaining, interval_ms / 1000.0, paused)
        if busy:
            self.dwin_progress_query.setRange(0, 0)
            self.dwin_progress_query.setFormat("查询中…")
        else:
            total = max(1.0, interval_ms / 1000.0)
            done = max(0.0, min(total, total - remaining))
            self.dwin_progress_query.setRange(0, 100)
            self.dwin_progress_query.setValue(int(done * 100 / total))
            self.dwin_progress_query.setFormat("%p%")
        if paused or busy or self.dwin_initializing:
            return
        if self.dwin_next_due_ms and now_ms >= self.dwin_next_due_ms:
            self.dwin_request_query(DSBM_SOURCE_SCHEDULED, False)

    def dwin_query_is_busy(self) -> bool:
        return self.dwin_query_thread is not None and self.dwin_query_thread.isRunning()

    def dwin_request_query(self, source_label: str, manual: bool) -> None:
        if self.dwin_query_is_busy():
            if manual:
                self.dwin_card.dcard_set_status("上一次查询还在进行中…", "busy")
            return
        self.dwin_schedule_next_query()
        self.dwin_card.dcard_set_query_busy(True)
        self.dwin_card.dcard_set_status(f"{source_label}中…", "busy")
        if manual:
            self.dwin_card.dcard_set_task_progress(None, f"正在{source_label} /user/balance", True)
        preferred = self.dwin_settings.dsgset_get_str("preferred_currency", "")
        thread = DsbmBalanceQueryThread(self.dwin_client, source_label, preferred, self)
        thread.dsqth_succeeded.connect(self.dwin_on_query_succeeded)
        thread.dsqth_failed.connect(self.dwin_on_query_failed)
        thread.finished.connect(self.dwin_on_query_thread_finished)
        self.dwin_query_thread = thread
        thread.start()

    @Slot()
    def dwin_on_query_thread_finished(self) -> None:
        self.dwin_card.dcard_set_query_busy(False)
        if self.dwin_query_thread is not None:
            self.dwin_query_thread.deleteLater()
            self.dwin_query_thread = None
        if not self.dwin_initializing:
            self.dwin_card.dcard_set_task_progress(0, "", False, False)

    @Slot(object)
    def dwin_on_query_succeeded(self, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}
        settings = self.dwin_settings
        total_queries = settings.dsgset_get_int("total_query_count", 0) + 1
        settings.dsgset_update_many({
            "total_query_count": total_queries,
            "last_success_time_ms": int(data.get("queried_ms", dsbm_now_ms())),
            "last_query_duration_ms": int(data.get("elapsed_ms", 0)),
            "last_query_attempts": int(data.get("attempts", 1)),
            "consecutive_failures": 0,
            "last_error_message": "",
            "last_balance_currency": str(data.get("currency", "")),
        })
        self.dwin_card.dcard_set_balance_view(data, dsbm_format_time_ms(int(data.get("queried_ms", 0))))
        self.dwin_card.dcard_set_status("查询成功", "ok")
        self.dwin_process_balance_change(data)
        self.dwin_refresh_statistics()

    def dwin_process_balance_change(self, data: dict[str, Any]) -> None:
        settings = self.dwin_settings
        currency = str(data.get("currency", "") or "")
        new_total = dsbm_to_decimal(data.get("total", "0"))
        prev_text = settings.dsgset_get_str("last_balance", "")
        source_label = str(data.get("source", DSBM_SOURCE_SCHEDULED))
        queried_ms = int(data.get("queried_ms", dsbm_now_ms()))
        appended: DsbmBalanceRecord | None = None
        if not prev_text:
            if settings.dsgset_get_bool("record_baseline", True):
                appended = DsbmBalanceRecord(
                    dsrec_time_ms=queried_ms,
                    dsrec_delta=Decimal("0"),
                    dsrec_balance=new_total,
                    dsrec_currency=currency,
                    dsrec_source=DSBM_SOURCE_BASELINE,
                )
        else:
            previous = dsbm_to_decimal(prev_text)
            delta = new_total - previous
            if dsbm_quantize_money(delta) != Decimal("0.00"):
                appended = DsbmBalanceRecord(
                    dsrec_time_ms=queried_ms,
                    dsrec_delta=delta,
                    dsrec_balance=new_total,
                    dsrec_currency=currency,
                    dsrec_source=source_label,
                )
        if appended is not None:
            self.dwin_append_record(appended)
            if appended.dsrec_delta != 0:
                self.dwin_notify_balance_change(appended)
        settings.dsgset_update_many({
            "last_balance": f"{new_total:.2f}",
            "last_balance_time_ms": queried_ms,
            "last_balance_currency": currency,
        })
        if prev_text and not self.dwin_model.dmrec_record_count():
            self.dwin_logger.info("记录为空但已有历史余额，本次未产生变化记录")

    def dwin_append_record(self, record: DsbmBalanceRecord) -> None:
        self.dwin_store.dsdb_append_record(record)
        self.dwin_model.dmrec_append_record(record)
        keep = self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
        if self.dwin_model.dmrec_record_count() > keep:
            self.dwin_store.dsdb_prune_records(keep)
            records = self.dwin_store.dsdb_load_recent(keep)
            self.dwin_model.dmrec_set_records(records)
        self.dwin_scroll_to_latest()
        self.dwin_refresh_statistics()
        self.dwin_logger.info(
            "新增记录：%s 变化 %s 余额 %s %s 来源 %s",
            dsbm_format_time_ms(record.dsrec_time_ms), dsbm_format_signed(record.dsrec_delta),
            dsbm_format_money(record.dsrec_balance), record.dsrec_currency, record.dsrec_source,
        )

    def dwin_scroll_to_latest(self) -> None:
        if self.dwin_model.dmrec_visible_count() <= 0:
            return
        latest = max(self.dwin_model.dmrec_visible_records(), key=lambda r: r.dsrec_time_ms)
        try:
            row = self.dwin_model.dmrec_visible_records().index(latest)
        except ValueError:
            return
        target = self.dwin_model.index(row, 0)
        self.dwin_table.scrollTo(target, QAbstractItemView.ScrollHint.EnsureVisible)

    def dwin_notify_balance_change(self, record: DsbmBalanceRecord) -> None:
        settings = self.dwin_settings
        if not settings.dsgset_get_bool("notify_enabled", True):
            return
        mode = settings.dsgset_get_str("notify_mode", DSBM_NOTIFY_MODE_ALL)
        if mode == DSBM_NOTIFY_MODE_DEBIT and record.dsrec_delta >= 0:
            return
        if mode == DSBM_NOTIFY_MODE_CREDIT and record.dsrec_delta <= 0:
            return
        threshold = dsbm_to_decimal(settings.dsgset_get_float("notify_threshold", 0.0))
        if threshold > 0 and abs(record.dsrec_delta) < threshold:
            return
        signature = f"{record.dsrec_time_ms}|{record.dsrec_delta}|{record.dsrec_balance}"
        if signature == self.dwin_last_notify_signature:
            return
        self.dwin_last_notify_signature = signature
        is_debit = record.dsrec_delta < 0
        title = f"{DSBM_APP_CN_NAME} ｜ {'扣费提醒' if is_debit else '余额增加'}"
        action = "扣费" if is_debit else "增加"
        lines = [
            f"{action} {abs(record.dsrec_delta):.2f} {record.dsrec_currency}",
        ]
        if settings.dsgset_get_bool("notify_include_balance", True):
            lines.append(f"余额 {dsbm_format_money(record.dsrec_balance)} {record.dsrec_currency}")
        lines.append(dsbm_format_time_ms(record.dsrec_time_ms))
        body = "\n".join(lines)
        self.dwin_toast.dstoast_notify_async(title, body)
        self.dwin_logger.info("已派发通知：%s / %s", title, body.replace("\n", " "))
        if self.dwin_tray is not None and settings.dsgset_get_bool("tray_balloon_fallback", True):
            self.dwin_tray.dstray_show_message(title, body)

    @Slot(str, object)
    def dwin_on_query_failed(self, message: str, payload: object) -> None:
        settings = self.dwin_settings
        failures = settings.dsgset_get_int("consecutive_failures", 0) + 1
        settings.dsgset_update_many({
            "failed_query_count": settings.dsgset_get_int("failed_query_count", 0) + 1,
            "consecutive_failures": failures,
            "last_error_message": message,
        })
        self.dwin_card.dcard_set_status(f"查询失败（连续 {failures} 次）：{message}", "error")
        self.dwin_logger.warning("查询失败：%s", message)
        self.dwin_refresh_statistics()
        data = dict(payload) if isinstance(payload, dict) else {}
        elapsed = int(data.get("elapsed_ms", 0))
        attempts = int(data.get("attempts", 1))
        if not self.dwin_initializing:
            self.dwin_card.dcard_set_task_progress(
                0, f"查询失败（重试 {attempts} 次 / 用时 {elapsed} ms）", False, True
            )
            QTimer.singleShot(4000, lambda: self.dwin_card.dcard_set_task_progress(0, "", False, False))
        threshold = max(1, settings.dsgset_get_int("notify_failure_threshold", 3))
        if settings.dsgset_get_bool("notify_on_repeated_failure", True) and failures >= threshold:
            if failures == threshold or failures % (threshold * 5) == 0:
                hint = "常见原因：API Key 失效、网络不通、余额接口限流。"
                if "401" in message:
                    hint = "API Key 无效，请在「设置 → 密钥与数据源」里更新 .env 中的 DEEPSEEK_API_KEY。"
                self.dwin_toast.dstoast_notify_async(
                    f"{DSBM_APP_CN_NAME} ｜ 查询连续失败 {failures} 次",
                    f"{message}\n{hint}",
                )

    @Slot()
    def dwin_toggle_pause(self) -> None:
        paused = not self.dwin_settings.dsgset_get_bool("polling_paused", False)
        self.dwin_settings.dsgset_set("polling_paused", paused)
        self.dwin_card.dcard_set_pause_state(paused)
        if not paused:
            self.dwin_schedule_next_query()
        self.dwin_refresh_statistics()

    @Slot(bool)
    def dwin_on_pause_toggled(self, paused: bool) -> None:
        self.dwin_settings.dsgset_set("polling_paused", bool(paused))
        if not paused:
            self.dwin_schedule_next_query()
        self.dwin_refresh_statistics()

    @Slot(int)
    def dwin_on_interval_changed(self, seconds: int) -> None:
        seconds = int(max(DSBM_MIN_INTERVAL_SECONDS, min(DSBM_MAX_INTERVAL_SECONDS, seconds)))
        self.dwin_settings.dsgset_set("query_interval_seconds", seconds)
        self.dwin_schedule_next_query()
        self.dwin_sync_interval_widgets()
        self.dwin_refresh_statistics()

    def dwin_sync_interval_widgets(self) -> None:
        self.dwin_card.dcard_apply_settings()
        if self.dwin_tray is not None:
            self.dwin_tray.dstray_set_paused(
                self.dwin_settings.dsgset_get_bool("polling_paused", False),
                self.dwin_settings.dsgset_get_int("query_interval_seconds", DSBM_DEFAULT_INTERVAL_SECONDS),
            )
        if self.dwin_settings_dialog is not None:
            self.dwin_settings_dialog.dsdlg_apply_external_change(
                "query_interval_seconds",
                self.dwin_settings.dsgset_get_int("query_interval_seconds"),
            )

    # ==================================================================
    # 记录表 / 统计 / 进度
    # ==================================================================
    def dwin_apply_filter_state(self) -> None:
        """按设置恢复「只看扣钱 / 只看增加」勾选与过滤（两者互斥，重启后依然生效）。"""
        debit = self.dwin_settings.dsgset_get_bool("only_debit_filter", False)
        credit = self.dwin_settings.dsgset_get_bool("only_credit_filter", False) and not debit
        if credit != self.dwin_settings.dsgset_get_bool("only_credit_filter", False):
            self.dwin_settings.dsgset_set("only_credit_filter", credit)
        if self.dwin_check_debit.isChecked() != debit:
            self.dwin_check_debit.setChecked(debit)
        if self.dwin_check_credit.isChecked() != credit:
            self.dwin_check_credit.setChecked(credit)
        self.dwin_model.dmrec_set_filter_sides(debit, credit)
        self.dwin_refresh_statistics()

    def dwin_refresh_hint_text(self) -> None:
        keep = self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
        self.dwin_label_hint.setText(
            "每次「总可用余额」真的变了就记一条，时间精确到毫秒。查余额走的是 /user/balance，"
            f"不消耗 Token。最多保留最近 {keep} 条。"
        )

    @Slot(bool)
    def dwin_on_filter_toggled(self, flag: bool) -> None:
        self.dwin_settings.dsgset_set("only_debit_filter", bool(flag))
        self.dwin_model.dmrec_set_only_debit(bool(flag))
        self.dwin_refresh_statistics()

    @Slot(bool)
    def dwin_on_credit_filter_toggled(self, flag: bool) -> None:
        self.dwin_settings.dsgset_set("only_credit_filter", bool(flag))
        self.dwin_model.dmrec_set_only_credit(bool(flag))
        self.dwin_refresh_statistics()

    def dwin_on_sort_changed(self, column: int, order: int) -> None:
        self.dwin_settings.dsgset_update_many({
            "table_sort_column": int(column),
            "table_sort_order": 1 if order == 1 else 0,
        })
        self.dwin_model.dmrec_set_sort_state(int(column), int(order))

    def dwin_sync_sort_indicator(self) -> None:
        column = self.dwin_settings.dsgset_get_int("table_sort_column", DSBM_COLUMN_TIME)
        order = self.dwin_settings.dsgset_get_int("table_sort_order", 1)
        header = self.dwin_table.horizontalHeader()
        header.blockSignals(True)
        header.setSortIndicator(column, Qt.SortOrder.DescendingOrder if order else Qt.SortOrder.AscendingOrder)
        header.blockSignals(False)

    def dwin_on_column_resized(self, section: int, old_size: int, new_size: int) -> None:
        # 列宽变化很频繁，这里只更新内存并交给 dwin_save_timer 防抖落盘
        widths: list[int] = []
        for index in range(len(DSBM_COLUMN_TITLES)):
            widths.append(int(self.dwin_table.columnWidth(index)))
        self.dwin_settings.dsgset_store_column_widths(widths)
        self.dwin_save_timer.start()

    def dwin_refresh_statistics(self) -> None:
        stats = self.dwin_model.dmrec_statistics()
        latest = stats["latest"]
        latest_text = "暂无记录"
        if latest is not None:
            latest_text = f"{dsbm_format_time_ms(latest.dsrec_time_ms)} {dsbm_format_signed(latest.dsrec_delta)}"
        self.dwin_label_stats.setText(
            f"共 {stats['total']} 条 | 扣钱 {stats['debit_count']} 次 合计 "
            f"{dsbm_format_money(stats['debit_sum'])} CNY"
            + (f" | 充值 {stats['credit_count']} 次 合计 +{dsbm_format_money(stats['credit_sum'])} CNY"
               if stats["credit_count"] else "")
            + f" | 最近一次: {latest_text}"
        )
        extra_parts = [f"筛选后 {stats['visible']} 条"]
        if stats["debit_count"]:
            extra_parts.append(f"平均消耗 {stats['rate_per_hour']} CNY/小时")
        else:
            extra_parts.append("暂无扣费样本")
        last_balance = dsbm_to_decimal(self.dwin_settings.dsgset_get_str("last_balance", "0"))
        if stats["rate_per_hour"] > 0 and last_balance > 0:
            hours_left = last_balance / stats["rate_per_hour"]
            extra_parts.append(f"预计可用 {dsbm_format_duration(float(hours_left) * 3600)}")
        extra_parts.append(
            f"上次成功 {dsbm_format_time_ms(self.dwin_settings.dsgset_get_int('last_success_time_ms', 0))}"
        )
        extra_parts.append(f"存储 {self.dwin_store.dsdb_backend_name()}")
        self.dwin_label_extra.setText(" ｜ ".join(extra_parts))

        max_records = max(1, self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS))
        percent = int(min(100, stats["total"] * 100 / max_records))
        self.dwin_progress_capacity.setValue(percent)
        self.dwin_progress_capacity.setFormat(f"{stats['total']}/{max_records}")
        self.dwin_progress_capacity.setToolTip(f"记录容量占用 {percent}%（{stats['total']}/{max_records}）")

        self.dwin_check_debit.setText(f"只看扣钱（{stats['debit_count']} 条）")
        self.dwin_check_credit.setText(f"只看增加（{stats['credit_count']} 条）")
        paused = self.dwin_settings.dsgset_get_bool("polling_paused", False)
        failures = self.dwin_settings.dsgset_get_int("consecutive_failures", 0)
        if failures:
            self.dwin_card.dcard_set_status(f"定时查询已暂停 ｜ 连续失败 {failures} 次" if paused
                                            else f"连续失败 {failures} 次", "warn")
        elif paused:
            self.dwin_card.dcard_set_status("定时查询已暂停（点击「继续查询」恢复）", "warn")

    def dwin_restore_last_balance_view(self) -> None:
        last_balance = self.dwin_settings.dsgset_get_str("last_balance", "")
        currency = self.dwin_settings.dsgset_get_str("last_balance_currency", "")
        time_ms = self.dwin_settings.dsgset_get_int("last_balance_time_ms", 0)
        if not last_balance:
            return
        self.dwin_card.dcard_set_balance_view(
            {
                "total": dsbm_to_decimal(last_balance),
                "granted": Decimal("0"),
                "topped_up": dsbm_to_decimal(last_balance),
                "currency": currency,
                "is_available": True,
                "elapsed_ms": self.dwin_settings.dsgset_get_int("last_query_duration_ms", 0),
            },
            f"上次记录 {dsbm_format_time_ms(time_ms)}",
        )

    def dwin_update_env_summary(self) -> None:
        summary = self.dwin_client.dsapi_config_summary()
        db_note = "MySQL 已配置" if self.dwin_env.dsenv_db_configured() else "SQLite 本地库"
        self.dwin_card.dcard_set_env_text(
            f"API Key {summary['api_key_masked']} ｜ 接口 {summary['api_base']} ｜ "
            f"通知后端 {self.dwin_toast.dstoast_backend_name()} ｜ 存储 {db_note} ｜ .env {dsbm_env_path().name}"
        )

    # ==================================================================
    # 设置联动
    # ==================================================================
    @Slot(str, object)
    def dwin_on_setting_value_changed(self, key: str, value: object) -> None:
        if key == "only_debit_filter":
            if self.dwin_check_debit.isChecked() != bool(value):
                self.dwin_check_debit.setChecked(bool(value))
            if value:
                self.dwin_settings.dsgset_set("only_credit_filter", False)
            self.dwin_model.dmrec_set_only_debit(bool(value))
        elif key == "only_credit_filter":
            if self.dwin_check_credit.isChecked() != bool(value):
                self.dwin_check_credit.setChecked(bool(value))
            if value:
                self.dwin_settings.dsgset_set("only_debit_filter", False)
            self.dwin_model.dmrec_set_only_credit(bool(value))
        elif key == "ui_scale":
            self.dwin_apply_ui_scale(float(value or 1.0))
        elif key == "table_row_height":
            self.dwin_apply_row_height()
        elif key == "table_font_size":
            self.dwin_apply_table_font()
        elif key == "max_records":
            self.dwin_refresh_hint_text()
            keep = self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
            if self.dwin_model.dmrec_record_count() > keep:
                self.dwin_store.dsdb_prune_records(keep)
                self.dwin_model.dmrec_set_records(self.dwin_store.dsdb_load_recent(keep))
            self.dwin_refresh_statistics()
        elif key in ("show_tray_icon", "close_to_tray", "minimize_to_tray",
                     "use_builtin_icon_if_missing"):
            self.dwin_build_tray()
        elif key == "polling_paused" and self.dwin_card is not None:
            self.dwin_card.dcard_set_pause_state(bool(value))
        elif key == "csv_export_dir":
            pass
        elif key in ("preferred_currency",):
            self.dwin_update_env_summary()
        if self.dwin_settings_dialog is not None:
            self.dwin_settings_dialog.dsdlg_apply_external_change(key, value)

    def dwin_apply_ui_scale(self, scale: float) -> None:
        scale = float(max(0.75, min(2.0, scale)))
        base_font = QFont(QApplication.font())
        base_font.setPointSizeF(max(7.5, 9.0 * scale))
        QApplication.setFont(base_font)
        self.dwin_card.dcard_apply_scale(scale)
        if self.dwin_table is not None:
            self.dwin_apply_table_font()
        for button in (self.dwin_button_refresh, self.dwin_button_export, self.dwin_button_clear,
                       self.dwin_button_settings, self.dwin_button_close):
            if button is not None:
                button_font = QFont(base_font)
                button_font.setPointSizeF(max(7.5, 9.0 * scale))
                button.setFont(button_font)
        menu_font = QFont(base_font)
        menu_font.setPointSizeF(max(7.5, 9.0 * scale))
        self.menuBar().setFont(menu_font)

    def dwin_apply_table_font(self) -> None:
        """记录表字体：table_font_size 磅值 × 界面缩放；表头同步，行高不足时自动抬高。"""
        settings = self.dwin_settings
        scale = float(settings.dsgset_get_float("ui_scale", 1.0) or 1.0)
        scale = max(0.75, min(2.0, scale))
        points = float(settings.dsgset_get_float("table_font_size", DSBM_TABLE_FONT_DEFAULT))
        points = max(DSBM_TABLE_FONT_MIN, min(DSBM_TABLE_FONT_MAX, points)) * scale
        table_font = QFont(QApplication.font())
        table_font.setPointSizeF(max(DSBM_TABLE_FONT_MIN, points))
        self.dwin_table.setFont(table_font)
        self.dwin_table.horizontalHeader().setFont(QFont(table_font))
        self.dwin_model.dmrec_apply_font(table_font)
        self.dwin_apply_row_height()
        self.dwin_apply_table_defaults()

    def dwin_apply_row_height(self) -> None:
        height = self.dwin_settings.dsgset_get_int("table_row_height", 22)
        row_font = self.dwin_table.font()
        minimum = max(16, int(QFontMetrics(row_font).height()) + 6)
        self.dwin_table.verticalHeader().setMinimumSectionSize(minimum)
        self.dwin_table.verticalHeader().setDefaultSectionSize(max(int(height), minimum))

    # ==================================================================
    # 托盘
    # ==================================================================
    def dwin_build_tray(self) -> None:
        want_tray = self.dwin_settings.dsgset_get_bool("show_tray_icon", True)
        allow_builtin = self.dwin_settings.dsgset_get_bool("use_builtin_icon_if_missing", True)
        self.dwin_app_icon = dsbm_load_app_icon(allow_builtin)
        if not self.dwin_app_icon.isNull():
            self.setWindowIcon(self.dwin_app_icon)
            QApplication.setWindowIcon(self.dwin_app_icon)
        if self.dwin_tray is None:
            self.dwin_tray = DsbmTrayController(self.dwin_app_icon, self)
            self.dwin_tray.dstray_show_requested.connect(self.dwin_show_and_raise)
            self.dwin_tray.dstray_query_requested.connect(
                lambda: self.dwin_request_query(DSBM_SOURCE_TRAY, True)
            )
            self.dwin_tray.dstray_toggle_pause_requested.connect(self.dwin_toggle_pause)
            self.dwin_tray.dstray_exit_requested.connect(self.dwin_request_quit)
        if not want_tray:
            self.dwin_tray.dstray_hide()
            return
        if not self.dwin_tray.dstray_is_supported():
            self.dwin_logger.warning("系统托盘不可用（或图标为空），已跳过托盘图标")
            return
        self.dwin_tray.dstray_show()
        self.dwin_tray.dstray_set_paused(
            self.dwin_settings.dsgset_get_bool("polling_paused", False),
            self.dwin_settings.dsgset_get_int("query_interval_seconds", DSBM_DEFAULT_INTERVAL_SECONDS),
        )

    def dwin_show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ==================================================================
    # 导出 / 清空 / 打开目录
    # ==================================================================
    def dwin_export_csv(self) -> None:
        if self.dwin_export_thread is not None and self.dwin_export_thread.isRunning():
            QMessageBox.information(self, "导出中", "上一次导出还在进行，请稍候。")
            return
        visible_only = self.dwin_settings.dsgset_get_bool("csv_export_visible_only", True)
        records = self.dwin_model.dmrec_visible_records() if visible_only else self.dwin_model.dmrec_all_records()
        if not records:
            QMessageBox.information(self, "没有可导出的数据", "当前没有符合条件的记录。")
            return
        target_dir = self.dwin_settings.dsgset_get_str("csv_export_dir", "").strip()
        base_dir = Path(target_dir) if target_dir else (dsbm_data_dir() / "exports")
        dsbm_ensure_dir(base_dir)
        scope = "筛选结果" if visible_only else "全部记录"
        default_name = f"DeepSeek余额记录_{scope}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = base_dir / default_name
        self.dwin_label_export.setVisible(True)
        self.dwin_progress_export.setVisible(True)
        self.dwin_progress_export.setValue(0)
        self.dwin_label_export.setText("导出中")
        thread = DsbmCsvExportThread(self.dwin_store, csv_path, records, self)
        thread.dsxth_progress.connect(self.dwin_on_export_progress)
        thread.dsxth_finished.connect(self.dwin_on_export_finished)
        thread.dsxth_failed.connect(self.dwin_on_export_failed)
        thread.finished.connect(self.dwin_on_export_thread_finished)
        self.dwin_export_thread = thread
        thread.start()

    @Slot(int, str)
    def dwin_on_export_progress(self, percent: int, text: str) -> None:
        self.dwin_progress_export.setValue(int(percent))
        self.dwin_label_export.setText(text[:40])

    @Slot(str, int)
    def dwin_on_export_finished(self, path: str, rows: int) -> None:
        self.dwin_progress_export.setValue(100)
        self.dwin_label_export.setText(f"已导出 {rows} 条")
        self.dwin_logger.info("导出完成：%s（%s 条）", path, rows)
        answer = QMessageBox.question(
            self, "导出完成",
            f"已导出 {rows} 条记录到：\n{path}\n\n是否立即打开该文件夹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.dwin_open_path(Path(path).parent)

    @Slot(str)
    def dwin_on_export_failed(self, message: str) -> None:
        self.dwin_label_export.setText("导出失败")
        QMessageBox.warning(self, "导出失败", f"导出 CSV 失败：\n{message}")

    @Slot()
    def dwin_on_export_thread_finished(self) -> None:
        if self.dwin_export_thread is not None:
            self.dwin_export_thread.deleteLater()
            self.dwin_export_thread = None
        QTimer.singleShot(6000, self.dwin_hide_export_progress)

    def dwin_hide_export_progress(self) -> None:
        self.dwin_progress_export.setVisible(False)
        self.dwin_label_export.setVisible(False)
        self.dwin_progress_export.setValue(0)

    def dwin_open_path(self, path: Path) -> bool:
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))  # noqa: S606 - Windows 专用，用于打开目录
            return True
        except (AttributeError, OSError) as exc:
            self.dwin_logger.warning("打开路径失败 %s：%s", path, exc)
            QMessageBox.warning(self, "无法打开", f"无法打开：{path}\n{exc}")
            return False

    def dwin_open_data_dir(self) -> None:
        self.dwin_open_path(dsbm_data_dir())

    def dwin_open_csv_dir(self) -> None:
        target_dir = self.dwin_settings.dsgset_get_str("csv_export_dir", "").strip()
        self.dwin_open_path(Path(target_dir) if target_dir else (dsbm_data_dir() / "exports"))

    @Slot()
    def dwin_clear_records(self) -> None:
        total = self.dwin_model.dmrec_record_count()
        if total == 0:
            QMessageBox.information(self, "清空记录", "当前没有记录可清空。")
            return
        answer = QMessageBox.question(
            self, "清空记录",
            f"确定要清空全部 {total} 条余额变化记录吗？\n"
            "清空后，下一次查询会重新写入一条「基准记录」。\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.dwin_store.dsdb_delete_all()
        self.dwin_model.dmrec_clear_records()
        self.dwin_settings.dsgset_update_many({"last_balance": "", "last_balance_time_ms": 0})
        self.dwin_refresh_statistics()
        self.dwin_card.dcard_set_status("记录已清空，等待下一次查询写入基准余额", "info")
        self.dwin_logger.info("用户清空了全部记录")

    @Slot()
    def dwin_reinitialize_store(self) -> None:
        ok, text = self.dwin_store.dsdb_initialize()
        if ok:
            keep = self.dwin_settings.dsgset_get_int("max_records", DSBM_DEFAULT_MAX_RECORDS)
            self.dwin_model.dmrec_set_records(self.dwin_store.dsdb_load_recent(keep))
            self.dwin_refresh_statistics()
        self.dwin_card.dcard_set_status(f"存储：{text}", "ok" if ok else "error")

    # ==================================================================
    # 设置窗口 / 帮助
    # ==================================================================
    def dwin_open_settings_dialog(self) -> None:
        if self.dwin_settings_dialog is None:
            self.dwin_settings_dialog = DsbmSettingsDialog(
                self.dwin_settings, self.dwin_env, self.dwin_client, self
            )
            self.dwin_settings_dialog.dsdlg_open_data_dir_requested.connect(self.dwin_open_data_dir)
            self.dwin_settings_dialog.dsdlg_open_csv_dir_requested.connect(self.dwin_open_csv_dir)
            self.dwin_settings_dialog.dsdlg_clear_records_requested.connect(self.dwin_clear_records)
            self.dwin_settings_dialog.dsdlg_store_reinit_requested.connect(self.dwin_reinitialize_store)
            self.dwin_settings_dialog.dsdlg_probe_requested.connect(self.dwin_probe_connection)
            self.dwin_settings_dialog.dsdlg_toast_test_requested.connect(self.dwin_send_test_toast)
            self.dwin_settings_dialog.finished.connect(self.dwin_on_settings_dialog_closed)
        self.dwin_settings_dialog.dsdlg_set_backend_state(
            f"{self.dwin_store.dsdb_backend_name()}（数据库文件：{dsbm_sqlite_path()}）",
            self.dwin_toast.dstoast_backend_name(),
        )
        self.dwin_settings_dialog.show()
        self.dwin_settings_dialog.raise_()
        self.dwin_settings_dialog.activateWindow()

    @Slot(int)
    def dwin_on_settings_dialog_closed(self, _result: int) -> None:
        self.dwin_settings.dsgset_flush()
        self.dwin_update_env_summary()

    def dwin_probe_connection(self) -> None:
        dialog = self.dwin_settings_dialog
        if dialog is not None:
            dialog.dsdlg_set_probe_state(None, "正在查询 /user/balance …", "info")
        self.dwin_client.dsapi_reload_config()

        def handle_result(payload: object) -> None:
            data = dict(payload) if isinstance(payload, dict) else {}
            if dialog is not None:
                dialog.dsdlg_set_probe_state(
                    100,
                    f"连接成功：{data.get('currency', '')} {dsbm_format_money(data.get('total', 0))}，"
                    f"账户{'可用' if data.get('is_available') else '不可用'}，"
                    f"耗时 {data.get('elapsed_ms', 0)} ms",
                    "ok",
                )
            self.dwin_card.dcard_set_status("测试连接成功", "ok")
            self.dwin_process_balance_change(data)
            self.dwin_card.dcard_set_balance_view(
                data, dsbm_format_time_ms(int(data.get("queried_ms", 0)))
            )

        def handle_failure(message: str) -> None:
            if dialog is not None:
                dialog.dsdlg_set_probe_state(100, f"连接失败：{message}", "error")
            self.dwin_card.dcard_set_status(f"测试连接失败：{message}", "error")

        if self.dwin_query_is_busy():
            if dialog is not None:
                dialog.dsdlg_set_probe_state(100, "已有一个查询在进行中，请稍后重试", "warn")
            return
        preferred = self.dwin_settings.dsgset_get_str("preferred_currency", "")
        thread = DsbmBalanceQueryThread(self.dwin_client, "测试连接", preferred, self)
        thread.dsqth_succeeded.connect(handle_result)
        thread.dsqth_failed.connect(lambda message, outcome: handle_failure(message))
        thread.finished.connect(self.dwin_on_query_thread_finished)
        self.dwin_query_thread = thread
        thread.start()

    def dwin_send_test_toast(self) -> None:
        ok = self.dwin_toast.dstoast_notify_blocking(
            f"{DSBM_APP_CN_NAME} · 通知测试",
            f"如果你在右下角看到这条消息，说明弹窗通知可用（后端："
            f"{self.dwin_toast.dstoast_backend_name()}）。",
        )
        if not ok and self.dwin_tray is not None:
            ok = self.dwin_tray.dstray_show_message(
                f"{DSBM_APP_CN_NAME} · 通知测试", "原生弹窗不可用，已改用托盘气泡。"
            )
        if self.dwin_settings_dialog is not None:
            self.dwin_settings_dialog.dsdlg_set_probe_state(
                100,
                "测试通知已发送，请查看屏幕右下角。" if ok else "通知发送失败，详见 logs\\dsbm_runtime.log",
                "ok" if ok else "error",
            )

    def dwin_show_help_dialog(self) -> None:
        DsbmInfoDialog(f"使用说明 — {DSBM_APP_CN_NAME}", dsbm_help_html(), self).exec()

    def dwin_show_about_dialog(self) -> None:
        DsbmInfoDialog(f"关于 — {DSBM_APP_CN_NAME}", dsbm_about_html(self.dwin_store, self.dwin_toast,
                                                                     self.dwin_client), self).exec()

    # ==================================================================
    # 右键菜单
    # ==================================================================
    @Slot(QPoint)
    def dwin_show_table_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("复制选中行", self.dwin_copy_selected_rows).setEnabled(
            bool(self.dwin_table.selectionModel().selectedRows())
        )
        menu.addAction("复制当前单元格", self.dwin_copy_current_cell)
        menu.addSeparator()
        action_delete = menu.addAction("删除选中行（仅删记录）", self.dwin_delete_selected_rows)
        action_delete.setEnabled(bool(self.dwin_table.selectionModel().selectedRows()))
        menu.addSeparator()
        menu.addAction("导出当前筛选结果…", self.dwin_export_csv)
        menu.addAction("立即查询最新余额", lambda: self.dwin_request_query(DSBM_SOURCE_MANUAL, True))
        menu.addAction("自动调整列宽", self.dwin_autosize_columns)
        menu.exec(self.dwin_table.viewport().mapToGlobal(position))

    def dwin_copy_selected_rows(self) -> None:
        rows = sorted(index.row() for index in self.dwin_table.selectionModel().selectedRows())
        if not rows:
            return
        lines: list[str] = []
        for row in rows:
            record = self.dwin_model.dmrec_record_at(row)
            if record is None:
                continue
            lines.append("\t".join(record.dsrec_as_csv_row()))
        QApplication.clipboard().setText("\n".join(lines))
        self.dwin_card.dcard_set_status(f"已复制 {len(lines)} 行到剪贴板", "info")

    def dwin_copy_current_cell(self) -> None:
        index = self.dwin_table.currentIndex()
        if not index.isValid():
            return
        text = str(self.dwin_model.data(index, Qt.ItemDataRole.DisplayRole) or "")
        QApplication.clipboard().setText(text)
        self.dwin_card.dcard_set_status("已复制当前单元格到剪贴板", "info")

    def dwin_delete_selected_rows(self) -> None:
        rows = sorted((index.row() for index in self.dwin_table.selectionModel().selectedRows()),
                      reverse=True)
        if not rows:
            return
        answer = QMessageBox.question(
            self, "删除记录",
            f"确定删除选中的 {len(rows)} 条记录吗？（仅从数据库删除，不影响账户余额）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        keep = self.dwin_model.dmrec_all_records()
        for row in rows:
            record = self.dwin_model.dmrec_record_at(row)
            if record is not None and record in keep:
                keep.remove(record)
        self.dwin_store.dsdb_delete_all()
        for record in keep:
            self.dwin_store.dsdb_append_record(record)
        self.dwin_model.dmrec_set_records(keep)
        self.dwin_refresh_statistics()

    def dwin_autosize_columns(self) -> None:
        self.dwin_table.resizeColumnsToContents()
        widths = [self.dwin_table.columnWidth(i) for i in range(len(DSBM_COLUMN_TITLES))]
        self.dwin_settings.dsgset_store_column_widths(widths)
        self.dwin_persist_window_state()

    # ==================================================================
    # 窗口状态持久化 / 关闭
    # ==================================================================
    def dwin_restore_window_state(self) -> None:
        geometry, state, maximized = self.dwin_settings.dsgset_restore_geometry()
        available = QGuiApplication.primaryScreen().availableGeometry()
        if not geometry.isEmpty():
            self.restoreGeometry(geometry)
            if self.width() > available.width() + 40 or self.height() > available.height() + 40:
                self.resize(
                    max(760, min(self.width(), available.width() - 40)),
                    max(460, min(self.height(), available.height() - 60)),
                )
        else:
            width = max(760, min(980, available.width() - 80))
            height = max(460, min(700, available.height() - 120))
            self.resize(width, height)
            self.move(
                available.x() + max(0, (available.width() - width) // 2),
                available.y() + max(0, (available.height() - height) // 3),
            )
        if maximized and not state.isEmpty():
            self.restoreState(state)
            self.showMaximized()
        self.dwin_apply_table_defaults()

    def dwin_persist_window_state(self) -> None:
        self.dwin_settings.dsgset_store_geometry(
            self.saveGeometry(), self.saveState(), self.isMaximized()
        )
        widths = [self.dwin_table.columnWidth(i) for i in range(len(DSBM_COLUMN_TITLES))]
        self.dwin_settings.dsgset_store_column_widths(widths)
        self.dwin_settings.dsgset_flush()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt 虚函数，必须叫这个名字
        self.dwin_handle_change_event(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 虚函数，必须叫这个名字
        self.dwin_handle_close_event(event)

    def dwin_handle_change_event(self, event: QEvent) -> None:
        if (event.type() == QEvent.Type.WindowStateChange
                and self.isMinimized()
                and self.dwin_settings.dsgset_get_bool("minimize_to_tray", False)
                and self.dwin_tray is not None
                and self.dwin_tray.dstray_is_supported()
                and self.dwin_settings.dsgset_get_bool("show_tray_icon", True)):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def dwin_handle_close_event(self, event: QCloseEvent) -> None:
        close_to_tray = self.dwin_settings.dsgset_get_bool("close_to_tray", True)
        tray_ready = (self.dwin_tray is not None and self.dwin_tray.dstray_is_supported()
                      and self.dwin_settings.dsgset_get_bool("show_tray_icon", True))
        if close_to_tray and tray_ready and not self.dwin_force_quit:
            event.ignore()
            self.hide()
            self.dwin_tray.dstray_show_message(
                f"{DSBM_APP_CN_NAME} 仍在后台运行",
                "定时查询继续进行；双击托盘图标可重新打开窗口，右键可退出。",
            )
            return
        # 未勾选「关闭时最小化到托盘」（或托盘不可用）→ 关窗口就是退出程序。
        # 注意：程序里 setQuitOnLastWindowClosed(False)（否则隐藏到托盘会被当成退出），
        # 所以这里必须自己调用 quit()，否则窗口关掉了、进程还在后台跑。
        self.dwin_settings.dsgset_flush()
        super().closeEvent(event)
        self.dwin_request_quit()

    def dwin_request_quit(self) -> None:
        self.dwin_force_quit = True
        self.dwin_shutdown()
        QApplication.instance().quit()

    def dwin_shutdown(self) -> None:
        """退出前的收尾：停止线程、落盘设置、关闭存储、停止通知线程。"""
        if self.dwin_shutdown_done:
            return
        self.dwin_shutdown_done = True
        self.dwin_clock_timer.stop()
        if self.dwin_query_thread is not None and self.dwin_query_thread.isRunning():
            self.dwin_query_thread.wait(3000)
        if self.dwin_export_thread is not None and self.dwin_export_thread.isRunning():
            self.dwin_export_thread.wait(6000)
        self.dwin_persist_window_state()
        self.dwin_store.dsdb_close()
        self.dwin_toast.dstoast_stop()
        if self.dwin_tray is not None:
            self.dwin_tray.dstray_hide()
        self.dwin_logger.info("程序已退出（累计查询 %s 次，失败 %s 次）",
                              self.dwin_settings.dsgset_get_int("total_query_count", 0),
                              self.dwin_settings.dsgset_get_int("failed_query_count", 0))


# ==============================================================================
# 十七、帮助 / 关于 HTML
# ==============================================================================


def dsbm_help_html() -> str:
    return f"""
    <h3>{DSBM_APP_CN_NAME} v{DSBM_APP_VERSION} · 使用说明</h3>
    <p><b>一句话说明：</b>按你设定的间隔定时查询 DeepSeek 官方 <code>/user/balance</code>，
    只要「总可用余额」真的变了就记一条（毫秒级时间戳），并可弹 Windows 右下角通知。</p>

    <h4>1. 记账规则（核心逻辑）</h4>
    <ul>
      <li>只有 <b>总可用余额</b> 与上一条记录不同（按分比较）才会写入一条新记录，余额没变不写。</li>
      <li>记录字段：<b>时间</b>（精确到毫秒）、<b>变化</b>（负数=扣费，正数=充值）、
          <b>变化后余额</b>、<b>来源</b>（定时查询 / 手动查询 / 启动查询 / 托盘查询 / 基准记录）。</li>
      <li>首次查询（或清空记录后）会写入一条 <b>基准记录</b>（变化 0.00），作为后续比较的起点。</li>
      <li>最多保留最近 N 条（默认 500，可在设置里改），超出后自动删除最旧的记录。</li>
      <li>余额接口 <code>GET /user/balance</code> <b>不消耗 Token</b>，可以放心高频查询。</li>
      <li>“上次余额”会跨启动保存，所以程序关闭期间发生的余额变化，下次启动查询时会照样记账。</li>
    </ul>

    <h4>2. 界面与进度</h4>
    <ul>
      <li>顶部卡片：当前余额、赠金 / 充值余额、账户是否可用、查询耗时、下次查询倒计时进度条。</li>
      <li>卡片第二行进度条：初始化步骤 / 手动查询进度。</li>
      <li>底部状态栏：统计文字、<b>查询进度</b>、<b>记录容量进度</b>；导出时右侧出现 <b>导出进度</b>。</li>
      <li>表格支持点击表头排序、多选、右键复制 / 删除 / 导出，列宽与排序状态都会记住。</li>
      <li>表格下方的 <b>「只看扣钱」/「只看增加」</b> 可只显示减少或只显示增加的记录（两者互斥，
          括号里是各自条数），勾选状态会记住，下次启动自动沿用。</li>
      <li>窗口缩小时，卡片与状态栏里的长信息会<b>自动省略成「…」</b>（鼠标悬停可看完整内容），
          窗口可以缩得很窄（声明最小 660×420），不会再把文字硬裁掉。</li>
      <li>「设置 → 界面」里可调整 <b>界面缩放</b>、<b>列表字体</b>（只改记录表，含表头与时间列）与
          <b>表格行高</b>；列表字体的实际磅值＝设定值 × 界面缩放，行高不够会自动抬高，文字不会被裁。</li>
    </ul>

    <h4>3. 快捷键</h4>
    <ul>
      <li><code>Ctrl+R</code> 立即查询　<code>Ctrl+P</code> 暂停 / 继续定时查询　
          <code>Ctrl+E</code> 导出 CSV　<code>Ctrl+,</code> 打开设置　<code>Ctrl+Q</code> 退出</li>
    </ul>

    <h4>4. 设置与持久化</h4>
    <ul>
      <li>所有设置改动 <b>立即生效并自动保存</b> 到 <code>data\\{DSBM_SETTINGS_FILENAME}</code>，
          下次启动自动加载；点击“关闭”不需要额外确认。</li>
      <li>勾选「点击关闭按钮时最小化到托盘（不退出）」→ 点「关闭」只隐藏窗口、查询继续在后台跑；
          <b>不勾选 → 点「关闭」就直接退出程序</b>（系统托盘不可用时同样直接退出）。</li>
      <li>API Key、数据库密码只写在项目根目录 <code>.env</code>，通过
          「设置 → 密钥与数据源」维护，绝不会硬编码进代码或写进设置文件。</li>
      <li>记录默认保存在 <code>data\\{DSBM_SQLITE_FILENAME}</code>（SQLite）；
          若在 .env 里配置了 MySQL 且安装了 pymysql，可切换为 MySQL，失败会自动回退 SQLite。</li>
      <li>图标：程序会自动检测项目根目录的 <code>icon.ico</code>，存在就用，不存在则窗口图标保持为空。</li>
    </ul>

    <h4>5. 通知</h4>
    <ul>
      <li>可在设置里选择：余额变化就提示 / 只提示扣费 / 只提示充值，并可设置金额阈值。</li>
      <li>后端优先级：winotify → win10toast → 内置 PowerShell WinRT 原生吐司（无需第三方库）。</li>
      <li>连续查询失败达到设定次数也会提醒，避免 Key 失效后毫无察觉。</li>
      <li>点击「发送测试通知」可立即验证右下角弹窗是否正常。</li>
    </ul>

    <h4>6. 常见问题</h4>
    <ul>
      <li><b>查询失败 401：</b>API Key 无效，请在「设置 → 密钥与数据源」更新 .env 中的
          <code>DEEPSEEK_API_KEY</code>。</li>
      <li><b>没有弹窗：</b>检查 Windows 通知是否被“专注助手 / 勿扰模式”拦截，或改用托盘气泡兜底。</li>
      <li><b>关闭后程序还在：</b>默认「关闭时最小化到托盘」，右键托盘图标 → 退出程序即可完全退出。</li>
      <li><b>日志：</b><code>logs\\{DSBM_LOG_FILENAME}</code>（滚动 2MB × 3）。</li>
    </ul>
    """


def dsbm_about_html(store: DsbmRecordStore, toast: DsbmToastService,
                    client: DsbmBalanceApiClient) -> str:
    summary = client.dsapi_config_summary()
    db_note = "MySQL（.env 已配置）" if client.dsapi_env.dsenv_db_configured() else "本地 SQLite"
    return f"""
    <h3>{DSBM_APP_CN_NAME}（{DSBM_APP_EN_NAME}）</h3>
    <p><b>版本：</b>v{DSBM_APP_VERSION}<br/>
    <b>主程序：</b>{DSBM_MAIN_SCRIPT_NAME}（唯一编译源）<br/>
    <b>文档：</b>{DSBM_DOC_NAME}（每次改动必须同步更新）</p>
    <p><b>接口：</b>{summary['api_base']}{DSBM_API_BALANCE_PATH}<br/>
    <b>API Key：</b>{summary['api_key_masked']}<br/>
    <b>HTTP 客户端：</b>{summary['client']}　<b>超时：</b>{summary['timeout']} 秒　
    <b>重试：</b>{summary['max_retry']} 次</p>
    <p><b>记录存储：</b>{store.dsdb_backend_name()}　（.env 数据库配置：{db_note}）<br/>
    <b>通知后端：</b>{toast.dstoast_backend_name()}<br/>
    <b>设置文件：</b>{dsbm_settings_path()}<br/>
    <b>密钥文件：</b>{dsbm_env_path()}<br/>
    <b>日志文件：</b>{dsbm_log_path()}<br/>
    <b>版本备份：</b>{dsbm_version_dir()}</p>
    <p style="color:{DSBM_COLOR_MUTED};">余额接口不消耗 Token；本程序不会读取或上传你的对话数据。</p>
    """


# ==============================================================================
# 十八、程序入口
# ==============================================================================


def dsbm_run_application() -> int:
    """创建 QApplication、装配各组件、进入事件循环。

    高 DPI 说明：Qt 6 默认已开启高 DPI 缩放，无需再设置 AA_EnableHighDpiScaling /
    AA_UseHighDpiPixmaps（它们已被 Qt 标记为废弃）；这里只设置小数缩放的取整策略为
    PassThrough，保证 125% / 150% 这类非整数缩放比例下的界面不糊、不错位。
    """
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(DSBM_APP_CN_NAME)
    app.setApplicationDisplayName(DSBM_APP_CN_NAME)
    app.setOrganizationName(DSBM_APP_ORG)
    app.setApplicationVersion(DSBM_APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    logger = dsbm_setup_logging()
    dsbm_ensure_dir(dsbm_data_dir())
    dsbm_ensure_dir(dsbm_log_dir())

    env_manager = DsbmEnvFileManager()
    env_manager.dsenv_ensure_file()
    settings_manager = DsbmSettingsManager()

    lock_guard = DsbmInstanceLock(dsbm_lock_path())
    if settings_manager.dsgset_get_bool("single_instance", True) and not lock_guard.dslock_acquire():
        logger.warning("检测到已有实例在运行：%s", lock_guard.dslock_holder_text())
        QMessageBox.information(
            None, f"{DSBM_APP_CN_NAME} 已在运行",
            f"已有实例正在运行（{lock_guard.dslock_holder_text()}）。\n\n"
            "如果你想同时打开多个窗口，请在设置里关闭「同一时间只允许运行一个实例」。",
        )
        return 2

    icon = dsbm_load_app_icon(settings_manager.dsgset_get_bool("use_builtin_icon_if_missing", True))
    if not icon.isNull():
        app.setWindowIcon(icon)
    else:
        logger.info("未找到 %s，按设置为不加载程序图标", DSBM_ICON_FILENAME)

    api_client = DsbmBalanceApiClient(env_manager)
    record_store = DsbmRecordStore(settings_manager, env_manager)
    toast_service = DsbmToastService(logger)

    window = DsbmMainWindow(settings_manager, env_manager, api_client, record_store, toast_service)
    logger.info(
        "%s v%s 启动｜Python %s｜数据目录 %s",
        DSBM_APP_CN_NAME, DSBM_APP_VERSION, sys.version.split()[0], dsbm_data_dir(),
    )
    window.show()
    window.dwin_start_initialization()

    auto_close_ms = os.environ.get("DSBM_AUTO_CLOSE_MS", "").strip()
    if auto_close_ms.isdigit() and int(auto_close_ms) > 0:
        logger.info("检测到 DSBM_AUTO_CLOSE_MS=%s，将自动关闭窗口（自检模式）", auto_close_ms)
        QTimer.singleShot(int(auto_close_ms), window.dwin_request_quit)

    app.aboutToQuit.connect(window.dwin_shutdown)
    exit_code = app.exec()
    lock_guard.dslock_release()
    return int(exit_code)


def main() -> int:
    return dsbm_run_application()


if __name__ == "__main__":
    sys.exit(main())

