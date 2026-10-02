"""世界（存档）管理：目录 CRUD 与 world.mt 读写。

注意：Luanti Windows 版命令行用窄字符解析，--world 路径含中文会报
"Cannot read world.mt!" → 目录名强制 ASCII，world_name 保留中文显示名；
存量中文目录在 list_worlds 时自动迁移。
"""
from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

from .settings import DATA_DIR

WORLDS_ROOT = DATA_DIR / "worlds"
WORLDS_ROOT.mkdir(parents=True, exist_ok=True)

_INVALID = set('<>:"/\\|?*')


def read_settings(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        out[line[:eq].strip()] = line[eq + 1:].strip()
    return out


def write_settings(path: Path, data: dict[str, str]) -> None:
    lines = [f"{k} = {v}" for k, v in data.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sanitize(name: str) -> str:
    """生成 ASCII 目录名（Luanti 命令行限制）；中文等字符剔除。"""
    out = re.sub(r"[^A-Za-z0-9_\-. ]", "", name).strip().replace(" ", "_")
    out = out.strip("._-")
    if not out:
        out = "world_" + hashlib.sha1(
            name.encode("utf-8")).hexdigest()[:6]
    return out[:48]


def _unique_dir(base: str) -> str:
    if not (WORLDS_ROOT / base).exists():
        return base
    for i in range(2, 200):
        cand = f"{base}_{i}"
        if not (WORLDS_ROOT / cand).exists():
            return cand
    return f"{base}_{datetime.now().strftime('%H%M%S')}"


def ensure_ascii_dir(dir_path: Path) -> Path:
    """存量非 ASCII 目录 → 自愈迁移（world_name 保留原显示名）。"""
    if all(ord(c) < 128 for c in dir_path.name):
        return dir_path
    if not dir_path.exists():
        return dir_path
    mt = dir_path / "world.mt"
    s = read_settings(mt) if mt.exists() else {}
    display = s.get("world_name") or dir_path.name
    new_name = _unique_dir(_sanitize(display))
    target = dir_path.parent / new_name
    try:
        dir_path.rename(target)
    except OSError:
        return dir_path
    if mt.exists():
        s["world_name"] = display
        write_settings(target / "world.mt", s)
    return target


def read_world(dir_path: Path) -> dict | None:
    mt = dir_path / "world.mt"
    if not mt.exists():
        return None
    s = read_settings(mt)
    enabled = [k[10:] for k, v in s.items() if k.startswith("load_mod_") and v == "true"]
    size = sum(f.stat().st_size for f in dir_path.iterdir() if f.is_file())
    last_played = datetime.fromtimestamp(0)
    world_map = dir_path / "map.sqlite"
    if world_map.exists():
        last_played = datetime.fromtimestamp(world_map.stat().st_mtime)
        size += world_map.stat().st_size
    screenshot = next(
        (str(dir_path / n) for n in ("screenshot.png", "screenshot.jpg", "screenshot.jpeg")
         if (dir_path / n).exists()), None)
    return {
        "dir_name": dir_path.name,
        "name": s.get("world_name", dir_path.name),
        "gameid": s.get("gameid", ""),
        "creative": s.get("creative_mode", "false") == "true",
        "damage": s.get("enable_damage", "true") == "true",
        "last_played": last_played,
        "size_bytes": size,
        "screenshot": screenshot,
        "enabled_mods": enabled,
    }


def list_worlds() -> list[dict]:
    worlds = []
    for d in sorted(WORLDS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        d = ensure_ascii_dir(d)
        if w := read_world(d):
            worlds.append(w)
    worlds.sort(key=lambda w: w["last_played"], reverse=True)
    return worlds


def create_world(name: str, gameid: str, creative: bool = False,
                 damage: bool = True, seed: str = "") -> dict:
    dir_name = _unique_dir(_sanitize(name))
    target = WORLDS_ROOT / dir_name
    target.mkdir(parents=True, exist_ok=True)
    lines = [
        f"gameid = {gameid}",
        f"world_name = {name}",
        f"enable_damage = {'true' if damage else 'false'}",
        f"creative_mode = {'true' if creative else 'false'}",
        "backend = sqlite3",
        "player_backend = sqlite3",
        "auth_backend = sqlite3",
        "mod_storage_backend = sqlite3",
        "server_announce = false",
    ]
    if seed.strip():
        lines.append(f"seed = {seed.strip()}")
    # 默认模组自动加载：模组库中的全部模组随新存档自动启用（依赖自动纳入）
    try:
        from .mods import list_mods, resolve_dependencies
        names = [m["name"] for m in list_mods()]
        if names:
            _sel, order, _miss = resolve_dependencies(names)
            for mod_name in (order or _sel):
                lines.append(f"load_mod_{mod_name} = true")
    except Exception:  # noqa: BLE001 — 模组解析失败不影响建图
        pass
    (target / "world.mt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_world(target)


def copy_world(src_dir_name: str, new_name: str) -> dict:
    src = WORLDS_ROOT / src_dir_name
    if not src.exists():
        raise FileNotFoundError("源存档不存在")
    dst = WORLDS_ROOT / _unique_dir(_sanitize(new_name))
    if dst.exists():
        raise ValueError("同名存档已存在")
    shutil.copytree(src, dst)
    mt = dst / "world.mt"
    s = read_settings(mt)
    s["world_name"] = new_name
    write_settings(mt, s)
    return read_world(dst)


def delete_world(dir_name: str) -> None:
    target = WORLDS_ROOT / dir_name
    if not target.exists():
        raise FileNotFoundError("存档不存在")
    shutil.rmtree(target)


def set_mod_enabled(dir_name: str, mod_name: str, enabled: bool) -> None:
    mt = WORLDS_ROOT / dir_name / "world.mt"
    s = read_settings(mt)
    s[f"load_mod_{mod_name}"] = "true" if enabled else "false"
    write_settings(mt, s)


def apply_mods(dir_name: str, enabled_mods: list[str]) -> None:
    mt = WORLDS_ROOT / dir_name / "world.mt"
    s = read_settings(mt)
    enabled = {m.lower() for m in enabled_mods}
    for key in [k for k in s if k.startswith("load_mod_")]:
        s[key] = "true" if key[10:].lower() in enabled else "false"
    for mod in enabled_mods:
        s.setdefault(f"load_mod_{mod}", "true")
    write_settings(mt, s)
