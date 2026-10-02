"""存储工具 — 目录体积计算与安全清理（日志轮转、临时文件、旧引擎）。"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .settings import DATA_DIR


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def dir_size_mb(path: Path) -> float:
    return dir_size(path) / 1048576.0


def storage_report() -> dict[str, float]:
    """各分区体积（MB），供设置页展示。"""
    return {
        "engine": dir_size_mb(DATA_DIR / "engine"),
        "worlds": dir_size_mb(DATA_DIR / "worlds"),
        "mods": dir_size_mb(DATA_DIR / "mods"),
        "logs": dir_size_mb(DATA_DIR / "logs"),
        "updates": dir_size_mb(DATA_DIR / "updates"),
        "tmp": dir_size_mb(DATA_DIR / "tmp"),
    }


def prune_logs(keep: int = 5) -> int:
    """日志轮转：只保留最新 keep 个 host_*.log，返回删除数。"""
    logs = DATA_DIR / "logs"
    if not logs.exists():
        return 0
    files = sorted(logs.glob("host_*.log"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def prune_tmp() -> int:
    """清理下载/分享临时文件（data/tmp 下全部内容）。"""
    tmp = DATA_DIR / "tmp"
    if not tmp.exists():
        return 0
    removed = 0
    for f in tmp.iterdir():
        try:
            if f.is_file():
                f.unlink()
                removed += 1
            elif f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed


def prune_engine_archives() -> int:
    """清理引擎目录下残留的 luanti-*.zip（下载中断产物）。"""
    eng = DATA_DIR / "engine"
    removed = 0
    if not eng.exists():
        return 0
    for f in eng.glob("*.zip"):
        try:
            if time.time() - f.stat().st_mtime > 3600:  # 1 小时前的才删
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def cleanup() -> dict[str, int]:
    """一键清理：日志轮转 + 临时文件 + 引擎残留 zip。"""
    return {
        "logs": prune_logs(),
        "tmp": prune_tmp(),
        "engine_zip": prune_engine_archives(),
    }
