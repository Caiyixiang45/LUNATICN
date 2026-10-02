"""预览图缓存：内存 LRU + 磁盘，默认先查缓存，网络仅在未命中时发生。

磁盘缓存 <DATA_DIR>/thumbs/<sha1(url)>.img，有效期 DEFAULT_MAX_AGE；
超容量按修改时间从旧到新淘汰。线程安全，可在后台抓图线程直接调用。
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from pathlib import Path

import requests

from .settings import DATA_DIR

CACHE_DIR = Path(DATA_DIR) / "thumbs"
MAX_MEM = 128                 # 内存 LRU 条数
MAX_DISK_BYTES = 60 * 1024 * 1024   # 磁盘缓存上限 60MB
DEFAULT_MAX_AGE = 7 * 86400   # 缓存有效期 7 天

_lock = threading.Lock()
_mem: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _put_mem(key: str, data: bytes) -> None:
    with _lock:
        _mem[key] = (time.time(), data)
        _mem.move_to_end(key)
        while len(_mem) > MAX_MEM:
            _mem.popitem(last=False)


def _write_disk(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        return
    _enforce_disk_limit()


def _enforce_disk_limit() -> None:
    """磁盘超限：按 mtime 从旧到新删除，删到 80% 上限为止。"""
    try:
        files = [p for p in CACHE_DIR.glob("*.img") if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        if total <= MAX_DISK_BYTES:
            return
        target = int(MAX_DISK_BYTES * 0.8)
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files:
            if total <= target:
                break
            try:
                total -= p.stat().st_size
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _download(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=(6, 20))
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    return resp.content


def get(url: str, max_age: int = DEFAULT_MAX_AGE) -> bytes | None:
    """图片字节：内存 → 磁盘 → 网络（带回写）。未取到返回 None。"""
    if not url:
        return None
    key = _key(url)
    now = time.time()

    with _lock:
        hit = _mem.get(key)
        if hit and now - hit[0] <= max_age:
            _mem.move_to_end(key)
            return hit[1]

    path = CACHE_DIR / f"{key}.img"
    try:
        if path.exists() and now - path.stat().st_mtime <= max_age:
            data = path.read_bytes()
            if data:
                _put_mem(key, data)
                return data
    except OSError:
        pass

    data = _download(url)
    if data:
        _put_mem(key, data)
        _write_disk(path, data)
    return data


def cached_bytes(url: str) -> bytes | None:
    """只查缓存（内存 → 磁盘），不发网络请求。"""
    if not url:
        return None
    key = _key(url)
    with _lock:
        hit = _mem.get(key)
        if hit:
            _mem.move_to_end(key)
            return hit[1]
    path = CACHE_DIR / f"{key}.img"
    try:
        if path.exists():
            data = path.read_bytes()
            if data:
                _put_mem(key, data)
                return data
    except OSError:
        pass
    return None
