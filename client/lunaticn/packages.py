"""分享包 .lnpkg 打包/解包（zip + manifest.json + content/）。"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path


def build_from_world(world_dir: Path, manifest: dict, dest: str) -> str:
    """把存档目录打成 .lnpkg。"""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
        for f in world_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f"content/{f.relative_to(world_dir).as_posix()}")
    return dest


def build_from_mod(mod_dir: Path, manifest: dict, dest: str) -> str:
    """把模组目录打成 .lnpkg（type=mod，content/ 为模组根）。"""
    manifest = dict(manifest)
    manifest.setdefault("type", "mod")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
        for f in mod_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f"content/{f.relative_to(mod_dir).as_posix()}")
    return dest


def read_manifest(lnpkg_path: str) -> dict:
    with zipfile.ZipFile(lnpkg_path) as zf:
        return json.loads(zf.read("manifest.json"))


def extract_content(lnpkg_path: str, dest_dir: Path) -> Path:
    """解出 content/ 目录，返回世界目录（含 world.mt 的那层）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(lnpkg_path) as zf:
        zf.extractall(dest_dir)
    src = dest_dir / "content"
    if not src.exists():
        src = dest_dir
    if (src / "world.mt").exists():
        return src
    for sub in src.iterdir():
        if sub.is_dir() and (sub / "world.mt").exists():
            return sub
    raise ValueError("包内没有 world.mt")


def import_world_zip(zip_path: str, worlds_root: Path) -> str:
    """把 zip/.lnpkg 导入存档库，返回存档目录名。"""
    from .worlds import read_world  # 局部引用避免循环
    tmp = Path(tempfile.mkdtemp(prefix="lnimp_"))
    try:
        world_dir = extract_content(zip_path, tmp)
        name = world_dir.name
        dest = worlds_root / name
        if dest.exists():
            suffix = "".join(chr(ord(c) + 1) for c in "abcd")  # 保证有差异
            dest = worlds_root / f"{name}_{len(list(worlds_root.iterdir()))}"
            _ = suffix
        shutil.copytree(world_dir, dest, dirs_exist_ok=True)
        if read_world(dest) is None:
            raise ValueError("导入的存档缺少 world.mt")
        return dest.name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
