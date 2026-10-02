"""模组中心 — 动态多源浏览（本地/社区自托管/ContentDB 排序源）与安装。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from lunaticn import engine, modsources, thumbcache, translate, worlds
from lunaticn import mods as modsvc
from lunaticn import packages as pkgsvc
from lunaticn.api import api
from ui import cards, theme, widgets
from ui.bridge import async_task, ui_call


class ModsPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._assign_mod: dict | None = None
        self._share_src: dict | None = None
        self._gen = 0          # 渲染代次：过期的缩略图/翻译回调直接丢弃
        self._zh: dict[str, str] = {}   # 原文 -> 译文（本轮累计）
        self._show_original = False     # True = 显示原文
        self._last_items: list[dict] = []
        self._last_origin = ""
        self._src_keys: list[str] = []
        self._sources: list[dict] = []
        self._per = 20            # 每页模组数
        self._page = 1            # 当前页（1 起）
        self._pages = 1           # 总页数（CDB 无总数时为下界）
        self._total = 0           # 模组总数（CDB 不可知，保持 0）
        self._has_more = False    # CDB：本页之后是否还有
        self._pages_exact = True  # _pages 是否为确切值
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 10)
        lay.setSpacing(8)
        widgets.page_header(lay, "模组中心", "切换数据源浏览模组，安装后启用到存档")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(widgets.button("导入模组包", self._import,
                                     variant="primary"))
        row.addWidget(widgets.button("刷新", self.refresh))
        self.btn_lang = widgets.button("显示原文", self._toggle_lang)
        row.addWidget(self.btn_lang)
        row.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索模组…（回车）")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search)
        self.search.setMaximumWidth(240)
        row.addWidget(self.search)
        self.cb_source = QComboBox()
        self.cb_source.setMinimumWidth(190)
        self._sync_sources(fill=True)
        self.cb_source.currentIndexChanged.connect(
            lambda _i: self._source_changed())
        row.addWidget(self.cb_source)
        lay.addLayout(row)

        self.grid = cards.CardGrid()
        lay.addWidget(self.grid, stretch=1)

        # 翻页条：上一页 / 页码 / 下一页（换页仅拉取该页数据）
        pager = QHBoxLayout()
        pager.setSpacing(8)
        pager.addStretch(1)
        self.lb_page = widgets.label("第 1 页", tone="muted", small=True)
        pager.addWidget(self.lb_page)
        self.btn_prev = widgets.button("上一页", self._prev_page)
        self.btn_next = widgets.button("下一页", self._next_page)
        pager.addWidget(self.btn_prev)
        pager.addWidget(self.btn_next)
        lay.addLayout(pager)

        self.dlg_detail = cards.ItemDetailDialog(self)

        # 启用到存档
        d = QDialog(self)
        d.setWindowTitle("启用到存档")
        d.setMinimumWidth(440)
        d.setModal(True)
        dl = QVBoxLayout(d)
        dl.setContentsMargins(20, 18, 20, 16)
        dl.setSpacing(8)
        widgets.section_title("选择目标存档", dl)
        self.assign_world = QComboBox()
        dl.addWidget(self.assign_world)
        self.assign_hint = widgets.label("", tone="faint", small=True)
        self.assign_hint.setWordWrap(True)
        dl.addWidget(self.assign_hint)
        widgets.hline(dl)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("启用", variant="primary", width=96,
                                      on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        dl.addLayout(brow)
        self.dlg_assign = d

        self._build_share_dlg()

    def _build_share_dlg(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("分享到工坊")
        d.setMinimumWidth(460)
        d.setModal(True)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        widgets.section_title("发布模组包 .lnpkg", lay)
        lay.addWidget(widgets.label("模组名", tone="muted", small=True))
        self.share_name = QLineEdit()
        lay.addWidget(self.share_name)
        hrow = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(widgets.label("版本", tone="muted", small=True))
        self.share_ver = QLineEdit("1.0.0")
        col.addWidget(self.share_ver)
        hrow.addLayout(col)
        hrow.addStretch(1)
        lay.addLayout(hrow)
        lay.addWidget(widgets.label("简介", tone="muted", small=True))
        self.share_desc = QPlainTextEdit()
        self.share_desc.setFixedHeight(80)
        lay.addWidget(self.share_desc)
        self.err_share = QLabel("")
        theme.set_tone(self.err_share, "danger")
        lay.addWidget(self.err_share)
        widgets.hline(lay)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("打包并上传", variant="primary",
                                      width=130, on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        lay.addLayout(brow)
        self.dlg_share = d

    # ---------- 数据源（动态解析） ----------

    def _sync_sources(self, fill: bool = False) -> None:
        """按 modsources 重建下拉；keys 未变则不动（防递归刷新）。"""
        srcs = modsources.list_sources()
        keys = [s["key"] for s in srcs]
        cur = self.cb_source.currentData()
        if fill or keys != self._src_keys:
            self._src_keys = keys
            self.cb_source.blockSignals(True)
            self.cb_source.clear()
            for s in srcs:
                self.cb_source.addItem(s["label"], s["key"])
            idx = keys.index(cur) if cur in keys else 0
            self.cb_source.setCurrentIndex(idx)
            self.cb_source.blockSignals(False)
        self._sources = srcs

    def _source(self) -> dict:
        key = self.cb_source.currentData()
        for s in self._sources:
            if s["key"] == key:
                return s
        return self._sources[0] if self._sources else {"kind": "community"}

    # ---------- 翻页 ----------

    def _search(self) -> None:
        self._page = 1
        self.refresh()

    def _source_changed(self) -> None:
        self._page = 1
        self._has_more = False
        self.refresh()

    def _prev_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self._page += 1
        self.refresh()

    def _update_pager(self) -> None:
        if self._pages_exact:
            self.lb_page.setText(
                f"第 {self._page} / {self._pages} 页 · 共 {self._total} 个")
        else:
            more = "，还有更多" if self._has_more else ""
            self.lb_page.setText(f"第 {self._page} 页{more}")
        self.btn_prev.setEnabled(self._page > 1)
        self.btn_next.setEnabled(
            self._has_more or self._page < self._pages)

    def refresh(self) -> None:
        self._sync_sources()
        src = self._source()
        kind = src.get("kind")
        if kind == "local":
            self._render_local()
            return
        page = self._page
        q = self.search.text().strip()
        if kind == "community":
            base = src.get("base", "")
            self.app.set_status("正在获取社区模组源…")
            async_task(
                lambda: api.list_remote_mods(base, page=page,
                                             per=self._per, q=q),
                lambda v, e, pg=page: self._got_community(v, e, pg))
        else:
            sort = src.get("sort", "")
            base = src.get("base", "")
            self.app.set_status("正在搜索 ContentDB…")
            async_task(
                lambda: api.cdb_search_mods(q, sort=sort, base=base,
                                            page=page, per=self._per),
                lambda v, e, pg=page: self._got_cdb(v, e, pg))

    def _bump(self) -> int:
        """新一轮渲染；旧的缩略图/翻译回调据此作废。"""
        self._gen += 1
        return self._gen

    # ---------- 翻译 ----------

    def _t(self, text: str) -> str:
        """显示用文本：默认译文，切换后原文。"""
        s = str(text or "")
        if self._show_original:
            return s
        return self._zh.get(s, s)

    def _toggle_lang(self) -> None:
        self._show_original = not self._show_original
        self.btn_lang.setText("显示译文" if self._show_original
                              else "显示原文")
        self.refresh()

    def _kick_translate(self, gen: int, items: list[dict]) -> None:
        """后台翻译标题与简介，完成后按代次重新渲染。"""
        texts: list[str] = []
        for m in items:
            for k in ("title", "description"):
                v = m.get(k)
                if v and translate.is_translatable(v) and v not in texts:
                    texts.append(v)
        if not texts:
            return
        self.app.set_status("正在翻译模组信息…")

        def work() -> dict:
            return translate.translate_many(texts)

        def done(zh, err):
            if err is not None or not zh:
                return
            self._zh.update(zh)
            if gen != self._gen:
                return  # 已进入新一轮刷新
            self._render_remote(self._last_items, self._last_origin,
                                kick=False)

        async_task(work, done)

    # ---------- 渲染 ----------

    def _render_local(self) -> None:
        q = self.search.text().strip().lower()
        items = modsvc.list_mods()
        if q:
            items = [m for m in items
                     if q in (m["name"] or "").lower()
                     or q in (m["description"] or "").lower()]
        self._total = len(items)
        pages = max(1, (self._total + self._per - 1) // self._per)
        self._pages = pages
        self._pages_exact = True
        if self._page > pages:
            self._page = pages
        if self._page < 1:
            self._page = 1
        self._has_more = self._page < pages
        page_items = items[(self._page - 1) * self._per:
                           self._page * self._per]
        self._bump()
        self._update_pager()
        if not page_items:
            self.grid.set_empty(
                "还没有本地模组 — 切到线上源安装，或点“导入模组包”")
            self.app.set_status(f"共 {self._total} 个本地模组")
            return
        self.grid.set_cards([self._local_card(m).frame
                             for m in page_items])
        self.app.set_status(
            f"共 {self._total} 个本地模组 · 第 {self._page} / {pages} 页")

    def _local_card(self, m: dict):
        box: dict = {}
        card = cards.build_card(
            title=m["name"],
            subtitle=f"{m['author'] or '-'} · v{m['version'] or '-'}",
            desc=m["description"] or modsvc.depends_summary(m) or "",
            seed=m["name"], overlay=m["name"],
            buttons=[
                {"text": "启用到存档", "variant": "primary",
                 "on_click": lambda _x=False, mm=m: self._assign(mm)},
                {"text": "分享",
                 "on_click": lambda _x=False, mm=m: self._share(mm)},
                {"text": "详情",
                 "on_click": lambda _x=False, mm=m, b=box:
                 self._detail_local(mm, b.get("thumb"))},
                {"text": "卸载", "variant": "danger",
                 "on_click": lambda _x=False, mm=m: self._uninstall(mm)},
            ])
        box["thumb"] = card.thumb
        return card

    def _detail_local(self, m: dict, thumb) -> None:
        self.dlg_detail.open_item(
            m["name"], cards.safe_image(thumb),
            [
                ("名称", m["name"]),
                ("版本", m["version"] or "-"),
                ("作者", m["author"] or "-"),
                ("依赖", modsvc.depends_summary(m) or "无"),
                ("简介", m["description"] or "-"),
                ("来源", "本地已安装"),
            ],
            [
                {"text": "启用到存档", "variant": "primary",
                 "on_click": lambda mm=m: self._assign(mm)},
                {"text": "分享", "on_click": lambda mm=m: self._share(mm)},
                {"text": "卸载", "variant": "danger",
                 "on_click": lambda mm=m: self._uninstall(mm)},
            ])

    def _got_community(self, data, err, page) -> None:
        if err is not None:
            self._bump()
            self.grid.set_empty(f"社区源获取失败：{err}")
            self.app.set_status(f"社区源获取失败: {err}")
            return
        if page != self._page:
            return                      # 用户已翻走，丢弃过期响应
        items = data.get("mods") or []
        self._page = int(data.get("page") or page)
        self._total = int(data.get("total") or len(items))
        self._pages = int(data.get("pages") or 1)
        self._pages_exact = True
        self._has_more = self._page < self._pages
        self._render_remote(items, "community")
        self._update_pager()
        self.app.set_status(
            f"社区源共 {self._total} 个模组 · "
            f"第 {self._page} / {self._pages} 页")

    def _got_cdb(self, data, err, page) -> None:
        if err is not None:
            self._bump()
            self.grid.set_empty(f"ContentDB 查询失败：{err}")
            self.app.set_status(f"ContentDB 查询失败: {err}")
            return
        if page != self._page:
            return                      # 用户已翻走，丢弃过期响应
        items = data.get("mods") or []
        self._page = int(data.get("page") or page)
        self._total = int(data.get("total") or len(items))
        self._pages = int(data.get("pages") or 1)
        self._pages_exact = True
        self._has_more = self._page < self._pages
        self._render_remote(items, "cdb")
        self._update_pager()
        self.app.set_status(
            f"ContentDB 共 {self._total} 个适配模组 · "
            f"第 {self._page} / {self._pages} 页")

    def _render_remote(self, items: list[dict], origin: str,
                       kick: bool = True) -> None:
        q = self.search.text().strip().lower()
        if q and origin == "community":
            items = [m for m in items
                     if q in (m.get("name") or "").lower()
                     or q in (m.get("title") or "").lower()]
        gen = self._bump()
        self._last_items, self._last_origin = items, origin
        if not items:
            self.grid.set_empty("没有找到匹配的模组")
            return
        source_label = "自托管" if origin == "community" else "ContentDB"
        frames = []
        jobs: list = []
        for m in items:
            box: dict = {}
            title = self._t(m.get("title") or m.get("name") or "-")
            card = cards.build_card(
                title=title,
                subtitle=f"{m.get('author') or '-'} · "
                         f"v{m.get('version') or '-'}",
                desc=self._t(m.get("description") or ""),
                seed=str(m.get("title") or m.get("name") or "-"),
                overlay=title,
                buttons=[
                    {"text": "安装", "variant": "primary",
                     "on_click": lambda _x=False, mm=m, oo=origin:
                     self._install_remote(oo, mm)},
                    {"text": "详情",
                     "on_click": lambda _x=False, mm=m, b=box, oo=origin:
                     self._detail_remote(mm, oo, source_label,
                                         b.get("thumb"))},
                ])
            box["thumb"] = card.thumb
            frames.append(card.frame)
            if origin == "cdb" and m.get("thumbnail"):
                jobs.append((card.thumb, str(m.get("thumbnail"))))
        self.grid.set_cards(frames)
        if jobs:
            self._fetch_thumbs(jobs, gen)
        if kick:
            self._kick_translate(gen, items)

    def _detail_remote(self, m: dict, origin: str, source_label: str,
                       thumb) -> None:
        title = self._t(m.get("title") or m.get("name") or "-")
        self.dlg_detail.open_item(
            title, cards.safe_image(thumb),
            [
                ("名称", m.get("name") or "-"),
                ("版本", m.get("version") or "-"),
                ("作者", m.get("author") or "-"),
                ("依赖", "—"),
                ("简介", self._t(m.get("description") or "-")),
                ("来源", source_label),
            ],
            [
                {"text": "安装", "variant": "primary",
                 "on_click": lambda mm=m, oo=origin:
                 self._install_remote(oo, mm)},
            ])

    def _fetch_thumbs(self, jobs: list, gen: int) -> None:
        """缩略图：缓存(内存→磁盘)优先，网络兜底；每张就绪立即上屏。"""

        def work():
            for lb, url in jobs:
                u = (engine.CONTENTDB_MIRRORS[0] + url
                     if url.startswith("/") else url)
                data = thumbcache.get(u)   # 默认先查缓存，未命中才联网
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

    def _install_remote(self, origin: str, m: dict) -> None:
        if origin == "community":
            filename = m.get("filename") or ""
            if not filename:
                self.app.set_status("该模组缺少文件名")
                return

            def dl(tmp: Path) -> Path:
                return Path(api.download_remote_mod(filename, tmp / filename))
            title = m.get("title") or m.get("name") or filename
        else:
            author = m.get("author") or ""
            name = m.get("name") or ""

            def dl(tmp: Path) -> Path:
                return Path(api.cdb_download_mod(author, name,
                                                 tmp / f"{name}.zip"))
            title = m.get("title") or name

        self.app.set_status(f"正在下载 {title}…")

        def work() -> dict:
            tmp = Path(tempfile.gettempdir()) / "lunaticn_mods"
            tmp.mkdir(parents=True, exist_ok=True)
            path = dl(tmp)
            return modsvc.install_zip(str(path))

        def done(v, err):
            if err is not None:
                self.app.set_status(f"安装失败: {err}")
                return
            self.app.set_status(f"已安装 {v.get('name', title)}")
            self._switch_local()
            self.refresh()

        async_task(work, done)

    def _switch_local(self) -> None:
        """安装完成后切到本地源（不触发额外刷新）。"""
        idx = self.cb_source.findData("local")
        if idx >= 0 and self.cb_source.currentIndex() != idx:
            self.cb_source.blockSignals(True)
            self.cb_source.setCurrentIndex(idx)
            self.cb_source.blockSignals(False)
            self._sync_sources()  # keys 未变，仅同步数据

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模组包", "",
            "模组包 (*.lnpkg *.zip);;所有文件 (*)")
        if not path:
            return
        self.app.set_status("正在导入模组…")

        def done(_v, err):
            if err is not None:
                self.app.set_status(f"导入失败: {err}")
                return
            self.app.set_status(f"已导入 {_v.get('name', '')}")
            self._switch_local()
            self.refresh()

        async_task(lambda: modsvc.install_zip(path), done)

    def _assign(self, m: dict) -> None:
        world_list = worlds.list_worlds()
        if not world_list:
            self.app.set_status("还没有存档")
            return
        self._assign_mod = m
        self.assign_world.clear()
        for w in world_list:
            self.assign_world.addItem(w["name"], w["dir_name"])
        self.assign_hint.setText(
            f"将 {m['name']} 写入选中存档的 load_mod_ 配置")
        if self.dlg_assign.exec() == QDialog.Accepted:
            self._assign_submit()

    def _assign_submit(self) -> None:
        m = self._assign_mod
        dir_name = self.assign_world.currentData()
        w = next((x for x in worlds.list_worlds()
                  if x["dir_name"] == dir_name), None)
        if m is None or w is None:
            return
        try:
            worlds.set_mod_enabled(w["dir_name"], m["name"], True)
            self.app.set_status(f"已启用 {m['name']} → {w['name']}")
        except Exception as ex:  # noqa: BLE001
            self.app.set_status(str(ex))

    def _uninstall(self, m: dict) -> None:
        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self.app.set_status(f"已卸载 {m['name']}")
            self.refresh()

        async_task(lambda: modsvc.uninstall(m["name"]), done)

    # ---------- 分享到工坊 ----------

    def _share(self, m: dict) -> None:
        if not api.is_logged_in:
            self.app.set_status("请先登录再分享")
            return
        self._share_src = m
        self.share_name.setText(m.get("title") or m.get("name") or "")
        self.share_ver.setText(m.get("version") or "1.0.0")
        self.share_desc.setPlainText(m.get("description") or "")
        self.err_share.setText("")
        if self.dlg_share.exec() == QDialog.Accepted:
            self._share_submit()

    def _share_submit(self) -> None:
        m = self._share_src
        if m is None:
            return
        name = self.share_name.text().strip() or m.get("name") or "模组"
        version = self.share_ver.text().strip() or "1.0.0"
        desc = self.share_desc.toPlainText().strip()
        mod_path = Path(m.get("path") or "")
        if not mod_path.is_dir():
            self.app.set_status("模组目录不存在")
            return
        self.app.set_status("正在打包模组…")

        def work():
            tmp = (Path(tempfile.gettempdir())
                   / f"lunaticn_mod_share_{id(m)}.lnpkg")
            try:
                manifest = {
                    "type": "mod", "name": name, "version": version,
                    "description": desc,
                    "author": (api.user or {}).get("nickname", ""),
                    "depends": list(m.get("depends") or []),
                }
                pkgsvc.build_from_mod(mod_path, manifest, str(tmp))
                ui_call(self.app.set_status, "正在上传…")
                return api.upload_package(str(tmp))
            finally:
                tmp.unlink(missing_ok=True)

        def done(pkg, err):
            if err is not None:
                self.app.set_status(f"分享失败: {err}")
                return
            self.app.set_status(f"已发布到工坊：{pkg.get('name', name)}")

        async_task(work, done)
