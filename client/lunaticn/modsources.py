"""模组源动态解析 — 内置源 + 设置里的自定义源，UI 据此构建列表。

源结构（dict）：
    key    唯一标识（combo 的 userData）
    label  显示名
    kind   "local" | "community" | "cdb"
    base   可选，community 服务端地址 / ContentDB 镜像地址（空则用默认）
    sort   可选，ContentDB 排序（downloads / score / name …）
"""
from __future__ import annotations

from . import settings

# 内置源（顺序即展示顺序）
BUILTIN: list[dict] = [
    {"key": "community", "label": "社区自托管源（推荐）", "kind": "community"},
    {"key": "local", "label": "本地模组（已安装）", "kind": "local"},
    {"key": "cdb", "label": "ContentDB 最新", "kind": "cdb", "sort": ""},
    {"key": "cdb_hot", "label": "ContentDB 热门", "kind": "cdb", "sort": "downloads"},
    {"key": "cdb_score", "label": "ContentDB 高分", "kind": "cdb", "sort": "score"},
    {"key": "cdb_name", "label": "ContentDB 按名称", "kind": "cdb", "sort": "name"},
]


def list_sources() -> list[dict]:
    """内置源 + 设置中配置的自定义源（key 冲突时自定义覆盖内置）。

    ContentDB 源默认只列适配当前游戏的模组，标签上予以标注。
    """
    from . import engine
    gk = engine.CDB_GAME_KEYS.get(engine.DEFAULT_GAME, "")
    suffix = (f" · 适配 {gk.split('/')[-1].capitalize()}"
              if gk else "")
    out: dict[str, dict] = {}
    for s in BUILTIN:
        entry = dict(s)
        if entry.get("kind") == "cdb" and suffix:
            entry["label"] = entry["label"] + suffix
        out[entry["key"]] = entry
    for i, raw in enumerate(settings.get("mod_sources") or []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "community")
        if kind not in ("community", "cdb"):
            continue
        base = str(raw.get("base") or "").rstrip("/")
        if not base:
            continue
        key = str(raw.get("key") or f"custom_{i}")
        label = str(raw.get("label") or base)
        entry = {"key": key, "label": label, "kind": kind, "base": base}
        if kind == "cdb" and raw.get("sort"):
            entry["sort"] = str(raw.get("sort"))
        out[key] = entry
    return list(out.values())


def keys() -> list[str]:
    return [s["key"] for s in list_sources()]
