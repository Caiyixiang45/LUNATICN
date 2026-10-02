"""多镜像兜底下载器：按优先级逐个源尝试，流式下载带进度。

用于引擎包、ContentDB 游戏包、客户端更新包 —— 三者共用同一套镜像链逻辑。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import requests

# progress(percent 0-100, label)；status(text)
ProgressCb = Callable[[int, str], None]
StatusCb = Callable[[str], None]

UA = {"User-Agent": "LUNATICN/1.0 (+https://github.com/Caiyixiang45/LUNATICN)"}

# GitHub 镜像前缀（本机直连 GitHub 不可达，按顺序兜底）
GH_MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]


def gh_mirrors(url: str) -> list[str]:
    """GitHub 下载地址 → 镜像链：直连优先，随后逐个前缀镜像。"""
    if "github.com/" not in url:
        return [url]
    return [url] + [prefix + url for prefix in GH_MIRRORS]


def fetch(urls: list[str], dest: Path,
          progress: Optional[ProgressCb] = None,
          status: Optional[StatusCb] = None) -> str:
    """按顺序尝试 urls 下载到 dest，返回实际成功的 URL。

    单个源失败会删除半截文件并尝试下一个；全部失败抛 RuntimeError（含各源错误）。
    """
    if not urls:
        raise RuntimeError("没有可用的下载地址")
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for i, url in enumerate(urls):
        host = url.split("/")[2] if "//" in url else url
        if status and len(urls) > 1:
            status(f"尝试下载源 {i + 1}/{len(urls)} · {host}")
        try:
            _fetch_one(url, dest, progress)
            if progress:
                progress(100, "完成")
            return url
        except Exception as ex:  # noqa: BLE001 — 逐源收集错误
            errors.append(f"{host}: {ex}")
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
    raise RuntimeError("全部下载源均失败：\n" + "\n".join(errors))


def _fetch_one(url: str, dest: Path,
               progress: Optional[ProgressCb] = None) -> None:
    with requests.get(url, stream=True, timeout=(15, 600), headers=UA) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(1 << 16):
                if not chunk:
                    continue
                out.write(chunk)
                read += len(chunk)
                if progress and total > 0:
                    pct = min(99, read * 100 // total)
                    progress(pct, f"下载中 {read // 1048576}/{total // 1048576} MB")


def compare_ver(a: str, b: str) -> int:
    """比较 "1.2.3" 形式版本号：a>b 返回 1，a<b 返回 -1，相等返回 0。"""
    def parts(v: str) -> list[int]:
        out = []
        for seg in v.strip().lstrip("vV").split("."):
            n = 0
            for c in seg:
                if not c.isdigit():
                    break
                n = n * 10 + ord(c) - 48
            out.append(n)
        return out

    pa, pb = parts(a), parts(b)
    for i in range(max(len(pa), len(pb))):
        na = pa[i] if i < len(pa) else 0
        nb = pb[i] if i < len(pb) else 0
        if na != nb:
            return 1 if na > nb else -1
    return 0
