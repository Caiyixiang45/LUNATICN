"""模组文本翻译 — 默认显示译文，可切回原文。

翻译链：磁盘缓存 → gtx 批量（一行多条，保持行数）→ mymemory 逐条兜底。
线程安全：可在 async_task 工作线程调用，结果写入磁盘缓存。
"""
from __future__ import annotations

import json
import re
import threading

import requests

from .settings import DATA_DIR

CACHE_PATH = DATA_DIR / "translations.json"

# gtx 证书验证在部分网络环境失败 → verify=False；抑制告警
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:  # noqa: BLE001
    pass

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LUNATICN/1.0"
_CJK_RE = re.compile("[぀-ヿ一-鿿가-힯]")

_lock = threading.Lock()
_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_locked() -> None:
    try:
        CACHE_PATH.write_text(
            json.dumps(_cache or {}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def is_translatable(text: str) -> bool:
    """英/外文文本才翻；空、过短、已含 CJK 的跳过。"""
    s = str(text or "").strip()
    if len(s) < 2:
        return False
    if _CJK_RE.search(s):
        return False
    return bool(re.search(r"[A-Za-z]", s))


def _gtx_batch(lines: list[str]) -> list[str] | None:
    """gtx 批量翻译，按 \\n 分行；行数不一致返回 None（回退逐条）。"""
    try:
        resp = requests.post(
            "https://translate.google.com/translate_a/single",
            data={"client": "gtx", "sl": "auto", "tl": "zh-CN",
                  "dt": "t", "q": "\n".join(lines)},
            headers={"User-Agent": _UA}, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        parts = data[0] or []
        joined = "".join(seg[0] for seg in parts if isinstance(seg, list)
                         and seg and isinstance(seg[0], str))
        got = joined.split("\n")
        if len(got) == len(lines):
            return [g.strip() or orig for g, orig in zip(got, lines)]
        return None
    except Exception:  # noqa: BLE001
        return None


def _mymemory(text: str) -> str | None:
    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": "en|zh-CN"},
            headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        got = ((resp.json().get("responseData") or {})
               .get("translatedText") or "").strip()
        if got and "MYMEMORY WARNING" not in got.upper():
            return got
    except Exception:  # noqa: BLE001
        pass
    return None


def translate_many(texts) -> dict[str, str]:
    """批量翻译，返回 原文 -> 译文（已缓存/失败的不含在内）。"""
    todo: list[str] = []
    out: dict[str, str] = {}
    with _lock:
        cache = _load()
        seen: set[str] = set()
        for t in texts:
            s = str(t or "")
            if not s or s in seen or not is_translatable(s):
                continue
            seen.add(s)
            if s in cache:
                out[s] = cache[s]
            else:
                todo.append(s)
    if not todo:
        return out

    results: dict[str, str] = {}
    batchable = [t for t in todo if "\n" not in t and len(t) < 900]
    if batchable:
        got = _gtx_batch(batchable)
        if got:
            results.update(zip(batchable, got))
    for t in todo:
        if t in results:
            continue
        m = _mymemory(t)
        if m:
            results[t] = m

    with _lock:
        _load()
        for t, v in results.items():
            if not _CJK_RE.search(v):   # 译文仍无中文 → 视为失败不缓存
                continue
            _cache[t] = v
            out[t] = v
        _save_locked()
    return out


def translate_text(text: str) -> str:
    """单条翻译（同步），失败返回原文。"""
    return translate_many([text]).get(str(text), str(text))
