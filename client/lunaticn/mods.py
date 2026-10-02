"""模组管理：扫描模组库、解析 mod.conf、依赖解析与 zip 安装。"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .settings import DATA_DIR
from .worlds import read_settings

MODS_ROOT = DATA_DIR / "mods"
MODS_ROOT.mkdir(parents=True, exist_ok=True)


def read_mod(dir_path: Path) -> dict | None:
    if not dir_path.is_dir():
        return None
    conf_path = dir_path / "mod.conf"
    has_conf = conf_path.exists()
    has_init = (dir_path / "init.lua").exists()
    has_pack = (dir_path / "modpack.conf").exists()
    if not (has_conf or has_init or has_pack):
        return None
    conf = read_settings(conf_path) if has_conf else {}
    return {
        "name": conf.get("name", dir_path.name),
        "title": conf.get("title", dir_path.name),
        "description": conf.get("description", ""),
        "author": conf.get("author", ""),
        "version": conf.get("version", ""),
        "path": str(dir_path),
        "is_modpack": has_pack,
        "depends": _split(conf.get("depends", "")),
        "optional_depends": _split(conf.get("optional_depends", "")),
    }


def _split(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def depends_summary(mod: dict) -> str:
    parts = []
    if mod["depends"]:
        parts.append("依赖: " + ", ".join(mod["depends"]))
    if mod["optional_depends"]:
        parts.append("可选: " + ", ".join(mod["optional_depends"]))
    return "    ".join(parts)


def list_mods() -> list[dict]:
    mods: list[dict] = []
    for d in sorted(MODS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        mod = read_mod(d)
        if mod:
            mods.append(mod)
            continue
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and (inner := read_mod(sub)):
                mods.append(inner)
    mods.sort(key=lambda m: m["name"])
    return mods


def find(name: str) -> dict | None:
    low = name.lower()
    return next((m for m in list_mods() if m["name"].lower() == low), None)


def resolve_dependencies(requested: list[str]) -> tuple[list[str], list[str], list[str]]:
    """返回 (选中模组, 加载顺序, 缺失依赖)。硬依赖自动纳入，拓扑排序在前。"""
    all_mods = {m["name"].lower(): m for m in list_mods()}
    selected: dict[str, dict] = {}
    missing: list[str] = []
    queue = list(requested)
    while queue:
        name = queue.pop(0)
        mod = all_mods.get(name.lower())
        if mod is None:
            if name.lower() not in {m.lower() for m in missing}:
                missing.append(name)
            continue
        if mod["name"] in selected:
            continue
        selected[mod["name"]] = mod
        queue.extend(d for d in mod["depends"]
                     if d.lower() not in {s.lower() for s in selected})

    state: dict[str, int] = {}
    order: list[str] = []

    def visit(name: str) -> bool:
        st = state.get(name)
        if st == 1:
            if f"循环依赖: {name}" not in missing:
                missing.append(f"循环依赖: {name}")
            return False
        if st == 2:
            return True
        state[name] = 1
        for dep in all_mods[name.lower()]["depends"]:
            if dep.lower() in {k.lower() for k in selected} and not visit(dep):
                return False
        state[name] = 2
        order.append(name)
        return True

    for mod in selected.values():
        visit(mod["name"])
    return [m["name"] for m in selected.values()], order, missing


def install_zip(zip_path: str) -> dict:
    """安装模组 zip 到模组库。"""
    with zipfile.ZipFile(zip_path) as zf:
        entries = [n for n in zf.namelist() if not n.endswith("/")]
        root_prefix = ""
        found = False
        for name in entries:
            norm = name.replace("\\", "/")
            if norm.endswith(("mod.conf", "init.lua", "modpack.conf")):
                idx = norm.rfind("/")
                root_prefix = norm[:idx + 1] if idx >= 0 else ""
                found = True
                break
        if not found:
            raise ValueError("压缩包中未找到 mod.conf 或 init.lua")

        # .lnpkg 分享包把模组根放在 content/ 下 → 目录名剥掉该层
        # （root_prefix 保留原样，供下方按前缀解压）
        name_prefix = root_prefix
        if name_prefix.startswith("content/"):
            name_prefix = name_prefix[len("content/"):]

        if "/" in name_prefix:
            target_name = name_prefix.split("/")[0]
        else:
            target_name = Path(zip_path).stem
        if not target_name or target_name in (".", ".."):
            target_name = Path(zip_path).stem
        target = MODS_ROOT / target_name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        for name in entries:
            norm = name.replace("\\", "/")
            if not norm.startswith(root_prefix):
                continue
            sub = norm[len(root_prefix):]
            if not sub:
                continue
            dest = target / sub
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)

    mod = read_mod(target)
    if not mod:
        # 可能解出的是模组包：找其子目录
        for sub in target.iterdir():
            if sub.is_dir() and (mod := read_mod(sub)):
                break
    if not mod:
        raise ValueError("解压后未找到有效模组")
    return mod


def uninstall(mod_name: str) -> None:
    mod = find(mod_name)
    if mod is None:
        raise FileNotFoundError("模组不存在")
    shutil.rmtree(mod["path"], ignore_errors=True)
