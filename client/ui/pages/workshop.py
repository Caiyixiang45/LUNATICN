"""分享工坊 — 作品卡片网格 / 搜索 / 下载地图与模组 / 我的作品管理。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from lunaticn import mods as modsvc, thumbcache, worlds
from lunaticn.api import api
from lunaticn.packages import import_world_zip, read_manifest
from lunaticn.settings import DATA_DIR
from ui import cards, theme, widgets
from ui.bridge import async_task, ui_call


def _kind_text(p: dict) -> str:
    return "地图" if p.get("type") == "map" else "模组"


class WorkshopPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._mine_mode = False
        self._gen = 0          # 渲染代次：过期的缩略图回调直接丢弃
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 10)
        lay.setSpacing(8)
        widgets.page_header(lay, "分享工坊",
                            "下载社区地图与模组，或发布你的作品")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_query = QLineEdit()
        self.ed_query.setPlaceholderText("搜索名称 / 简介")
        self.ed_query.setMinimumWidth(170)
        self.ed_query.setMaximumWidth(340)
        self.ed_query.returnPressed.connect(self._search)
        row.addWidget(self.ed_query)
        self.cb_kind = QComboBox()
        self.cb_kind.addItems(["全部", "地图", "模组"])
        self.cb_kind.setFixedWidth(90)
        row.addWidget(self.cb_kind)
        row.addWidget(widgets.button("搜索", self._search, variant="primary",
                                     width=76))
        row.addWidget(widgets.button("我的作品", self._mine, width=100))
        row.addStretch(1)
        lay.addLayout(row)

        self.grid = cards.CardGrid()
        lay.addWidget(self.grid, stretch=1)
        self.dlg_detail = cards.ItemDetailDialog(self)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        if not api.is_logged_in:
            self._mine_mode = False
            self._gen += 1
            self.grid.set_empty("登录后即可浏览与下载工坊作品")
            return
        self._load()

    def _search(self) -> None:
        self._mine_mode = False
        self._load()

    def _mine(self) -> None:
        if not api.is_logged_in:
            self.app.set_status("请先登录")
            return
        self._mine_mode = True
        self._load()

    def _load(self) -> None:
        query = self.ed_query.text().strip()
        kind = {"地图": "map", "模组": "mod"}.get(self.cb_kind.currentText(),
                                                  "")
        mine = self._mine_mode

        def work():
            if mine:
                return api.my_packages()
            _total, data = api.search_packages(pkg_type=kind, query=query)
            return data

        def done(data, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self._fill(data)

        async_task(work, done)

    def _fill(self, data: list[dict]) -> None:
        self._gen += 1
        gen = self._gen
        if not data:
            hint = "你还没有发布过作品" if self._mine_mode else "没有找到作品"
            self.grid.set_empty(hint)
            return
        frames = []
        jobs: list = []
        for p in data:
            card = self._card(p)
            frames.append(card.frame)
            pid = str(p.get("id") or "")
            if pid and p.get("thumbnail"):
                jobs.append((card.thumb, pid))
        self.grid.set_cards(frames)
        if jobs:
            self._fetch_thumbs(jobs, gen)
        self.app.set_status(("我的作品 " if self._mine_mode else "搜索结果 ")
                            + str(len(data)) + " 个")

    def _card(self, p: dict):
        box: dict = {}
        name = p.get("name", "")
        if self._mine_mode:
            buttons = [
                {"text": "删除", "variant": "danger",
                 "on_click": lambda _x=False, pp=p: self._delete(pp)},
                {"text": "详情",
                 "on_click": lambda _x=False, pp=p, b=box:
                 self._detail(pp, b.get("thumb"))},
            ]
        else:
            buttons = [
                {"text": "下载", "variant": "primary",
                 "on_click": lambda _x=False, pp=p: self._download(pp)},
                {"text": "详情",
                 "on_click": lambda _x=False, pp=p, b=box:
                 self._detail(pp, b.get("thumb"))},
            ]
        card = cards.build_card(
            title=name,
            subtitle=f"{_kind_text(p)} · 下载 {p.get('downloads', 0)}",
            desc=p.get("description") or "",
            seed=name,
            buttons=buttons)
        box["thumb"] = card.thumb
        return card

    def _detail(self, p: dict, thumb) -> None:
        self.dlg_detail.open_item(
            p.get("name", ""), cards.safe_image(thumb),
            [
                ("作者", p.get("author_name") or "-"),
                ("类型", _kind_text(p)),
                ("版本", p.get("version") or "-"),
                ("简介", p.get("description") or "-"),
                ("下载数", str(p.get("downloads", 0))),
            ],
            ([{"text": "删除", "variant": "danger",
               "on_click": lambda pp=p: self._delete(pp)}]
             if self._mine_mode else
             [{"text": "下载", "variant": "primary",
               "on_click": lambda pp=p: self._download(pp)}]))

    # ---------- 预览图 ----------

    def _fetch_thumbs(self, jobs: list, gen: int) -> None:
        """包缩略图：缓存优先，网络兜底；每张就绪立即上屏（增量）。"""

        def work():
            for lb, pid in jobs:
                url = f"{api.base_url}/api/packages/{pid}/thumbnail"
                data = thumbcache.get(url)   # 默认先查缓存，未命中才联网
                if not data:
                    continue
                img = QImage()
                if img.loadFromData(data):
                    ui_call(self._apply_thumb, gen, lb, img)

        def done(_v, _err):
            return   # 抓图失败 → 保持渐变占位

        async_task(work, done)

    def _apply_thumb(self, gen: int, lb, img) -> None:
        if gen != self._gen:
            return                      # 已进入新一轮刷新
        try:
            lb.set_image(img)
        except RuntimeError:            # noqa: PLE0605 — 卡片已被销毁
            pass

    # ---------- 操作 ----------

    def _download(self, p: dict) -> None:
        pid = p.get("id", "")
        self.app.set_status(f"正在下载 {p.get('name', '')}…")
        dest = Path(DATA_DIR) / "tmp" / f"pkg_{pid}.lnpkg"
        dest.parent.mkdir(parents=True, exist_ok=True)

        def work():
            path = api.download_package(str(pid), str(dest))
            manifest = read_manifest(path)
            ptype = manifest.get("type") or p.get("type", "")
            if ptype == "map":
                import_world_zip(path, worlds.WORLDS_ROOT)
                msg = f"地图已导入存档库：{manifest.get('name', '')}"
            else:
                modsvc.install_zip(path)
                msg = f"模组已安装：{manifest.get('name', '')}"
            Path(path).unlink(missing_ok=True)
            return msg

        def done(msg, err):
            if err is not None:
                self.app.set_status(f"下载失败: {err}")
                return
            self.app.set_status(msg)

        async_task(work, done)

    def _delete(self, p: dict) -> None:
        pid = p.get("id", "")
        name = p.get("name", "")

        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self.app.set_status(f"已删除 {name}")
            self._load()

        async_task(lambda: api.delete_package(str(pid)), done)
