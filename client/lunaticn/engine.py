"""Luanti 引擎托管：下载安装、游戏管理、模组同步、真实启动参数。

实测依据（Luanti 5.17.0 portable，RUN_IN_PLACE=1）：
  - 引擎 zip 顶层是版本目录（luanti-5.17.0-win64/…），解压后需拍平；
    zip 内不含 games/，必须另行安装游戏（5.10+ 不再捆绑 Minetest Game）。
  - 数据目录（user path）= 引擎根目录：模组放 <root>/mods/，
    world.mt 的 load_mod_<名> = true 即从这里加载。
  - 启动参数（实测 --help）：
      服务端   luanti.exe --server --world <绝对路径> --gameid <id> --port <n> --logfile <文件>
      单机     luanti.exe --go --world <绝对路径> --gameid <id>
      加入服务器 luanti.exe --go --address <host> --port <n> --name <昵称>
      （--address 不接受 host:port 合写，必须与 --port 分开）
      --gameid list 列游戏；--version 输出 "Luanti 5.17.0 (Windows)"。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Optional

from . import download, mods
from .settings import DATA_DIR, load as load_settings

ENGINE_ROOT = DATA_DIR / "engine"
DEFAULT_VERSION = "5.17.0"
USER_AGENT = download.UA

# progress(percent, label) / status(text)
ProgressCb = Callable[[int, str], None]
StatusCb = Callable[[str], None]

# ContentDB 上可安装的官方/社区游戏（gameid → (author, name)）
DEFAULT_GAME = "mineclonia"  # 主游戏：Mineclonia（ryvnf/mineclonia）
BUILTIN_GAMES = {
    "mineclonia": ("ryvnf", "mineclonia"),
    "minetest": ("Luanti", "minetest_game"),
}
CONTENTDB = "https://content.luanti.org"
CONTENTDB_MIRRORS = ["https://content.luanti.org", "https://content.luanti.ru"]
# ContentDB game 过滤 key（author/name）：模组中心只列适配该玩法的模组
CDB_GAME_KEYS = {"mineclonia": "ryvnf/mineclonia"}

_GIT_TAG_API = ("https://gh-proxy.com/https://api.github.com/"
                "repos/luanti-org/luanti/releases/latest")


# ---------- 状态 ----------

def installed_version() -> Optional[str]:
    marker = ENGINE_ROOT / "current.json"
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def engine_exe() -> Optional[str]:
    v = installed_version()
    if v is None:
        return None
    exe = ENGINE_ROOT / v / "bin" / "luanti.exe"
    return str(exe) if exe.exists() else None


def engine_root() -> Optional[Path]:
    exe = engine_exe()
    return Path(exe).parent.parent if exe else None


def probe_version(exe: Optional[str] = None) -> Optional[str]:
    """运行 --version 读取真实版本号（Luanti 5.17.0 (Windows)）。"""
    exe = exe or engine_exe()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=20, creationflags=0x08000000)
        m = re.search(r"Luanti\s+(\d+\.\d+\.\d+)",
                      (out.stdout or "") + (out.stderr or ""))
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def fetch_latest_version() -> str:
    """获取官方最新版本号；GitHub API 不可达时回退默认版本。"""
    try:
        import requests
        resp = requests.get(_GIT_TAG_API, timeout=15, headers=USER_AGENT)
        resp.raise_for_status()
        tag = (resp.json() or {}).get("tag_name", "")
        return tag.lstrip("vV") or DEFAULT_VERSION
    except Exception:  # noqa: BLE001
        return DEFAULT_VERSION


# ---------- 下载安装 ----------

def release_mirrors(version: str) -> list[str]:
    official = (f"https://github.com/luanti-org/luanti/releases/download/"
                f"{version}/luanti-{version}-win64.zip")
    return download.gh_mirrors(official)


def _normalize_layout(target: Path) -> None:
    """把 zip 顶层版本目录拍平成 <target>/bin/luanti.exe 结构。"""
    exe = target / "bin" / "luanti.exe"
    if exe.exists():
        return
    sub = next((d for d in target.iterdir()
                if d.is_dir() and (d / "bin").is_dir()), None)
    if sub is None:
        return
    for entry in sub.iterdir():
        dest = target / entry.name
        if entry.is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            entry.rename(dest)
        else:
            if dest.exists():
                dest.unlink()
            entry.rename(dest)
    shutil.rmtree(sub, ignore_errors=True)


def ensure_engine(version: Optional[str] = None,
                  progress: Optional[ProgressCb] = None,
                  status: Optional[StatusCb] = None) -> str:
    """确保引擎已安装，返回 luanti.exe 路径（多镜像兜底下载）。"""
    exe = engine_exe()
    if exe:
        return exe
    version = version or load_settings().get("engine_version") or DEFAULT_VERSION
    ENGINE_ROOT.mkdir(parents=True, exist_ok=True)
    zip_path = ENGINE_ROOT / f"luanti-{version}.zip"

    download.fetch(release_mirrors(version), zip_path,
                   progress=progress, status=status)

    target = ENGINE_ROOT / version
    if target.exists():
        shutil.rmtree(target)
    if status:
        status("正在解压引擎…")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    _normalize_layout(target)

    (ENGINE_ROOT / "current.json").write_text(
        json.dumps({"version": version}), encoding="utf-8")
    try:
        zip_path.unlink()
    except OSError:
        pass

    exe = engine_exe()
    if not exe:
        raise RuntimeError("引擎安装后仍不可用（zip 结构异常）")
    if status:
        status(f"引擎 {probe_version(exe) or version} 安装完成")
    return exe


def uninstall() -> None:
    v = installed_version()
    if v is None:
        return
    shutil.rmtree(ENGINE_ROOT / v, ignore_errors=True)
    marker = ENGINE_ROOT / "current.json"
    if marker.exists():
        marker.unlink()


def reinstall(progress: Optional[ProgressCb] = None,
              status: Optional[StatusCb] = None) -> str:
    uninstall()
    return ensure_engine(fetch_latest_version(), progress, status)


# ---------- 游戏管理（ContentDB） ----------

def list_games() -> list[dict]:
    """扫描 <engine_root>/games/<gameid>/game.conf。"""
    root = engine_root()
    if root is None:
        return []
    games_dir = root / "games"
    if not games_dir.exists():
        return []
    out: list[dict] = []
    for d in sorted(games_dir.iterdir()):
        if not d.is_dir():
            continue
        conf = d / "game.conf"
        info: dict = {"gameid": d.name, "title": d.name, "path": str(d)}
        if conf.exists():
            for raw in conf.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
                line = raw.strip()
                if not line or line[0] in "#;" or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
        out.append(info)
    return out


def has_game(gameid: str) -> bool:
    return any(g["gameid"] == gameid for g in list_games())


def _cdb_release_url(base: str, author: str, name: str, release: int) -> str:
    return f"{base}/packages/{author}/{name}/releases/{release}/download/"


def _cdb_latest_release(author: str, name: str) -> tuple[int, str]:
    """查询 ContentDB 包详情，返回 (release_id, title)。"""
    import requests
    last: Exception | None = None
    for base in CONTENTDB_MIRRORS:
        try:
            resp = requests.get(f"{base}/api/packages/{author}/{name}/",
                                timeout=20, headers=USER_AGENT)
            resp.raise_for_status()
            data = resp.json() or {}
            return int(data.get("release") or 0), str(data.get("title") or name)
        except Exception as ex:  # noqa: BLE001
            last = ex
    raise RuntimeError(f"ContentDB 查询失败: {last}")


def _extract_game_zip(zip_path: Path, gameid: str) -> Path:
    """把游戏 zip 解压到 <root>/games/<gameid>/（自动纠正顶层目录名）。"""
    root = engine_root()
    if root is None:
        raise RuntimeError("引擎未安装，无法安装游戏")
    games_dir = root / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    target = games_dir / gameid
    if target.exists():
        shutil.rmtree(target)

    with zipfile.ZipFile(zip_path) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        # zip 根部就有 game.conf → 需要自建目录
        root_has_conf = "game.conf" in names
        # 否则取顶层目录名
        top = next((n.split("/")[0] for n in names if n), "")
        if root_has_conf:
            target.mkdir(parents=True)
            zf.extractall(target)
        else:
            tmp = games_dir / (top or "_tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            zf.extractall(games_dir)
            if not (tmp / "game.conf").exists():
                shutil.rmtree(tmp, ignore_errors=True)
                raise RuntimeError("压缩包中未找到 game.conf，不是有效游戏")
            tmp.rename(target)
    if not (target / "game.conf").exists():
        raise RuntimeError("安装后缺少 game.conf")
    return target


def install_game(gameid: str = DEFAULT_GAME,
                 progress: Optional[ProgressCb] = None,
                 status: Optional[StatusCb] = None) -> dict:
    """从 ContentDB 下载并安装游戏（多镜像兜底）。"""
    if engine_root() is None:
        raise RuntimeError("请先安装引擎，再安装游戏")
    author, name = BUILTIN_GAMES.get(gameid, (gameid, gameid))
    if status:
        status(f"正在查询 ContentDB · {name} …")
    release, title = _cdb_latest_release(author, name)
    if release <= 0:
        raise RuntimeError(f"ContentDB 上找不到游戏 {name}")

    zip_path = ENGINE_ROOT / f"{name}-{release}.zip"
    urls = [_cdb_release_url(base, author, name, release)
            for base in CONTENTDB_MIRRORS]
    download.fetch(urls, zip_path, progress=progress, status=status)

    if status:
        status("正在安装游戏…")
    _extract_game_zip(zip_path, gameid)
    try:
        zip_path.unlink()
    except OSError:
        pass
    if status:
        status(f"游戏 {title} 安装完成")
    return {"gameid": gameid, "title": title}


def remove_game(gameid: str) -> None:
    root = engine_root()
    if root is None:
        return
    target = root / "games" / gameid
    if target.exists():
        shutil.rmtree(target)


# ---------- 模组同步 ----------

_SYNC_MANIFEST = ".lunaticn_synced.json"


def sync_mods(status: Optional[StatusCb] = None) -> None:
    """把模组库 data/mods 镜像到 <engine_root>/mods（引擎 user path）。

    只删除本工具同步过去的目录（依据清单），不会误删引擎自带内容。
    """
    root = engine_root()
    if root is None:
        return
    dest = root / "mods"
    dest.mkdir(parents=True, exist_ok=True)
    src = mods.MODS_ROOT

    managed: set[str] = set()
    mf = dest / _SYNC_MANIFEST
    if mf.exists():
        try:
            managed = set(json.loads(mf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            managed = set()

    src_names = {d.name for d in src.iterdir() if d.is_dir()}
    # 删除已卸载的
    for name in managed - src_names:
        shutil.rmtree(dest / name, ignore_errors=True)
    # 拷贝新增与变更
    for d in src.iterdir():
        if not d.is_dir():
            continue
        target = dest / d.name
        try:
            shutil.copytree(d, target, dirs_exist_ok=True)
        except OSError:
            if status:
                status(f"模组 {d.name} 同步失败")
    managed |= src_names
    mf.write_text(json.dumps(sorted(managed), ensure_ascii=False),
                  encoding="utf-8")


# ---------- 启动 ----------

def engine_arg(path_like) -> str:
    """转成传给 luanti 命令行的参数。

    Luanti Windows 版用窄字符解析 argv：参数值含非 ASCII（如中文目录）
    会报 "Cannot read world.mt!"。优先使用 8.3 短路径转 ASCII；
    短路径不可用时抛出带指引的错误。
    """
    s = str(path_like)
    if all(ord(c) < 128 for c in s):
        return s
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, 32768)
        if 0 < n < 32768 and all(ord(c) < 128 for c in buf.value):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(
        f"引擎参数路径含非 ASCII 字符且无法转换为短路径: {s}\n"
        "请把客户端数据目录移动到纯英文路径后重试。")


def _require_game(gameid: str) -> None:
    if not gameid:
        return
    if not has_game(gameid):
        raise RuntimeError(
            f"游戏 {gameid} 安装失败，请检查网络后重试")


def play_world(dir_name: str, gameid: str,
               status: Optional[StatusCb] = None) -> None:
    """单机进入存档：luanti.exe --go --world <绝对路径> --gameid <id>。"""
    from .worlds import WORLDS_ROOT
    exe = ensure_engine()
    if gameid and not has_game(gameid):
        # 游戏不显示在 UI：缺失时静默自动安装
        if status:
            status("正在安装游戏…")
        install_game(gameid, status=status)
    _require_game(gameid)
    sync_mods()
    world_path = WORLDS_ROOT / dir_name
    if not (world_path / "world.mt").exists():
        raise FileNotFoundError(f"存档不存在: {dir_name}")
    args = [exe, "--go", "--world", engine_arg(world_path)]
    if gameid:
        args += ["--gameid", gameid]
    subprocess.Popen(args, cwd=str(Path(exe).parent.parent),
                     creationflags=0x00000008)  # DETACHED_PROCESS
