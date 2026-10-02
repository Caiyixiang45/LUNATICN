"""联机大厅 — 页头 / 公告与更新推送 / 房主控制台 / 房间卡片 / 官方服务器。"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from lunaticn import engine, worlds
from lunaticn.api import ApiError, api
from lunaticn.host import RUNNING, join_room, room_host
from ui import cards, theme, widgets
from ui.bridge import async_task, ui_call
from ui.pages.login import LoginDialog

_SERVER_HEADERS = (("名称", 300), ("端口", 100), ("状态", 110), ("", 90))

_SOURCE_TEXT = {"launcher": "启动器开房", "roomd": "独立房间服务"}


class CreateRoomDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("创建房间")
        self.setMinimumWidth(440)
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)

        widgets.section_title("房间信息", lay)
        lay.addWidget(widgets.label("房间名", tone="muted", small=True))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("给好友看的名称")
        lay.addWidget(self.ed_name)
        lay.addWidget(widgets.label("存档", tone="muted", small=True))
        self.cb_world = QComboBox()
        lay.addWidget(self.cb_world)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(widgets.label("人数上限", tone="muted", small=True))
        self.sp_max = QSpinBox()
        self.sp_max.setRange(2, 64)
        self.sp_max.setValue(8)
        col1.addWidget(self.sp_max)
        row.addLayout(col1)
        col2 = QVBoxLayout()
        col2.addWidget(widgets.label("仅好友可见", tone="muted", small=True))
        self.cb_private = QCheckBox()
        col2.addWidget(self.cb_private)
        col2.addStretch(1)
        row.addLayout(col2)
        lay.addLayout(row)

        lay.addWidget(widgets.label("房间简介（可选）", tone="muted", small=True))
        self.ed_desc = QLineEdit()
        lay.addWidget(self.ed_desc)
        widgets.hline(lay)

        row2 = QHBoxLayout()
        self.btn_ok = widgets.button("创建并开房", variant="primary",
                                     width=130, on_click=self.accept)
        self.btn_cancel = widgets.button("取消", width=90, on_click=self.reject)
        self.lb_error = QLabel("")
        theme.set_tone(self.lb_error, "danger")
        row2.addWidget(self.btn_ok)
        row2.addWidget(self.btn_cancel)
        row2.addWidget(self.lb_error)
        row2.addStretch(1)
        lay.addLayout(row2)


class LobbyPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.login = LoginDialog(on_done=self._after_login, parent=app)
        self._log_lines: deque[str] = deque(maxlen=200)
        self._build()
        room_host.on_state = lambda s: ui_call(self._update_host_card, s)
        room_host.on_log = lambda line: ui_call(self._append_log, line)

    # ---------- UI ----------

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 10)
        lay.setSpacing(8)

        widgets.page_header(lay, "联机大厅",
                            "创建房间邀请好友，或加入其他玩家的世界")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(widgets.button("刷新", self.refresh))
        row.addWidget(widgets.button("创建房间", self._create_room_dialog,
                                     variant="primary"))
        row.addStretch(1)
        lay.addLayout(row)

        # ---- 更新横幅 ----
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner.hide()
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(6)
        brow = QHBoxLayout()
        icon = widgets.label("⬆", big=True, tone="brand")
        self.banner_title = widgets.label("", big=True)
        self.banner_body = widgets.label("", tone="muted", small=True)
        self.banner_body.setWordWrap(True)
        brow.addWidget(icon)
        brow.addWidget(self.banner_title)
        brow.addStretch(1)
        brow.addWidget(widgets.button("去下载", self._goto_update,
                                      variant="primary", width=84))
        brow.addWidget(widgets.button(
            "忽略", lambda: self.banner.hide(), width=64))
        bl.addLayout(brow)
        bl.addWidget(self.banner_body)
        lay.addWidget(self.banner)

        # ---- 公告列表 ----
        self.ann_box = QVBoxLayout()
        self.ann_box.setSpacing(6)
        lay.addLayout(self.ann_box)

        # ---- 房主控制台 ----
        self.host_card = QFrame()
        self.host_card.setObjectName("card")
        self.host_card.hide()
        hl = QVBoxLayout(self.host_card)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(8)
        hrow = QHBoxLayout()
        self.host_dot = widgets.label("●", tone="warning")
        self.host_title = widgets.label("正在启动…", big=True)
        self.host_meta = widgets.label("", tone="muted")
        hrow.addWidget(self.host_dot)
        hrow.addWidget(self.host_title)
        hrow.addWidget(self.host_meta)
        hrow.addStretch(1)
        hrow.addWidget(widgets.button("结束房间", self._stop_host,
                                      variant="danger", width=96))
        hl.addLayout(hrow)
        hl.addWidget(widgets.label("服务端日志", tone="faint", small=True))
        self.host_log = QPlainTextEdit()
        self.host_log.setReadOnly(True)
        self.host_log.setMaximumBlockCount(200)   # 内存环形缓冲
        self.host_log.setFixedHeight(170)
        hl.addWidget(self.host_log)
        lay.addWidget(self.host_card)

        # ---- 玩家房间 ----
        srow = QHBoxLayout()
        widgets.section_title("玩家房间", srow)
        self.room_count = widgets.label("", tone="faint")
        srow.addWidget(self.room_count)
        srow.addStretch(1)
        lay.addLayout(srow)
        self.room_grid = cards.CardGrid()
        lay.addWidget(self.room_grid, stretch=1)
        self.dlg_room_detail = cards.ItemDetailDialog(self)

        lay.addWidget(widgets.label("官方固定服（本机守护进程）",
                                    tone="faint", small=True))
        self.server_table = widgets.table(_SERVER_HEADERS, min_height=140)
        lay.addWidget(self.server_table)

        self.dlg_create = CreateRoomDialog(self)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        self._update_host_card(room_host.state)

        def work():
            return api.rooms(), api.servers()

        def done(v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            rooms, servers = v
            self._fill_rooms(rooms)
            self._fill_servers(servers)
            self.app.set_status(f"共 {len(rooms)} 个房间在线")

        async_task(work, done)

    def _fill_rooms(self, rooms: list[dict]) -> None:
        self.room_count.setText(f"· {len(rooms)}")
        if not rooms:
            self.room_grid.set_empty(
                "暂无房间 — 点击上方“创建房间”开一局")
            return
        self.room_grid.set_cards([self._room_card(r) for r in rooms])

    def _room_card(self, r: dict):
        me = (api.user or {}).get("id", "")
        is_mine = r.get("owner") == me and r.get("source") == "launcher"
        name = r.get("name", "") + ("  ◀ 我的" if is_mine else "")
        players = f'{r.get("players", 0)}/{r.get("max_players", 0)}'
        desc = (r.get("description")
                or f'世界 {r.get("world") or "-"} · 房主 '
                   f'{r.get("owner_name") or "-"}')
        box: dict = {}
        card = cards.build_card(
            title=name,
            subtitle=f"{players} 人 · 运行中",
            desc=desc,
            seed=r.get("world") or r.get("name") or "",
            overlay=r.get("gameid") or "",
            buttons=[
                {"text": "加入", "variant": "primary",
                 "on_click": lambda _x=False, rr=r:
                 self._join(rr.get("host", ""), rr.get("port", 0))},
                {"text": "详情",
                 "on_click": lambda _x=False, rr=r, b=box:
                 self._room_detail(rr, b.get("thumb"))},
            ])
        box["thumb"] = card.thumb
        if is_mine:
            c = theme.current()["brand"]
            card.title.setStyleSheet(
                f"color: rgba({c[0]}, {c[1]}, {c[2]}, {c[3]});")
        return card.frame

    def _room_detail(self, r: dict, thumb) -> None:
        players = f'{r.get("players", 0)}/{r.get("max_players", 0)}'
        addr = f'{r.get("host", "")}:{r.get("port", 0)}'
        source = str(r.get("source") or "")
        self.dlg_room_detail.open_item(
            r.get("name", ""), cards.safe_image(thumb),
            [
                ("房主", r.get("owner_name") or "-"),
                ("地址", addr),
                ("人数", players),
                ("简介", r.get("description") or "-"),
                ("来源", _SOURCE_TEXT.get(source, source or "-")),
            ],
            [
                {"text": "加入", "variant": "primary",
                 "on_click": lambda rr=r:
                 self._join(rr.get("host", ""), rr.get("port", 0))},
            ])

    def _fill_servers(self, servers: list[dict]) -> None:
        from PySide6.QtGui import QBrush, QColor
        pal = theme.current()
        if not servers:
            widgets.fill_table(self.server_table, [], "暂无固定服在线")
            return
        rows = []
        for s in servers:
            ss = s
            btn = widgets.button(
                "进入", lambda _x=False, ss=ss: self._join(
                    "127.0.0.1", ss.get("port", 0)), variant="brand")
            btn.setFixedHeight(26)
            running = bool(s.get("running"))
            rows.append((
                [s.get("name", ""), str(s.get("port", "")),
                 "运行中" if running else "已停止", ""],
                {2: {"tone": "success" if running else "faint"},
                 3: {"widget": widgets.row_buttons(btn)}}))
        widgets.fill_table(self.server_table, rows)

    def _after_login(self) -> None:
        self.app.update_account()
        self.refresh()

    # ---------- 公告与更新推送 ----------

    def set_notices(self, anns: list[dict], upd: dict) -> None:
        show_upd = bool(upd.get("has_update"))
        self.banner.setVisible(show_upd)
        if show_upd:
            self.banner_title.setText(
                f'客户端新版本 v{upd.get("latest", "?")} 已发布')
            notes = (upd.get("notes") or "").strip().splitlines()
            self.banner_body.setText(
                notes[0] if notes else "前往设置页下载更新包。")

        while self.ann_box.count():
            item = self.ann_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    it2 = sub.takeAt(0)
                    if it2.widget():
                        it2.widget().deleteLater()
        for a in anns[:3]:
            fr = QFrame()
            fr.setObjectName("card")
            v = QVBoxLayout(fr)
            v.setContentsMargins(14, 10, 14, 10)
            v.setSpacing(4)
            hrow = QHBoxLayout()
            level = a.get("level", "info")
            tone = {"warning": "warning", "update": "success"}.get(level,
                                                                   "brand")
            hrow.addWidget(widgets.label("●", tone=tone))
            hrow.addWidget(widgets.label(a.get("title", ""), big=True))
            if a.get("pinned"):
                hrow.addWidget(widgets.label("置顶", tone="brand", small=True))
            hrow.addStretch(1)
            created = str(a.get("created_at", ""))[:10]
            if created:
                hrow.addWidget(widgets.label(created, tone="faint", small=True))
            v.addLayout(hrow)
            body = widgets.label(a.get("body", ""), tone="muted", small=True)
            body.setWordWrap(True)
            v.addWidget(body)
            self.ann_box.addWidget(fr)

    def _goto_update(self) -> None:
        self.app.show_page("settings")
        page = self.app.pages.get("settings")
        if page is not None and hasattr(page, "highlight_update"):
            page.highlight_update()

    # ---------- 创建房间 ----------

    def _create_room_dialog(self) -> None:
        if not api.is_logged_in:
            self.app.set_status("请先登录再创建房间")
            self.login.open()
            return
        world_list = worlds.list_worlds()
        if not world_list:
            self.app.set_status("还没有存档，请先到“存档库”创建一个")
            return
        self.dlg_create.cb_world.clear()
        for w in world_list:
            self.dlg_create.cb_world.addItem(w["name"], w["dir_name"])
        self.dlg_create.lb_error.setText("")
        self.dlg_create.ed_name.setText("")
        if self.dlg_create.exec() != QDialog.Accepted:
            return
        self._create_submit()

    def _create_submit(self) -> None:
        name = self.dlg_create.ed_name.text().strip()
        dir_name = self.dlg_create.cb_world.currentData()
        world = next((w for w in worlds.list_worlds()
                      if w["dir_name"] == dir_name), None)
        if world is None:
            return
        self.app.set_status("正在启动服务端…")
        max_players = self.dlg_create.sp_max.value()
        is_private = self.dlg_create.cb_private.isChecked()
        desc = self.dlg_create.ed_desc.text().strip()

        def work():
            return room_host.start(
                room_name=name or world["name"],
                world_dir_name=world["dir_name"],
                gameid=world["gameid"],
                port=30000,
                max_players=max_players,
                is_private=is_private,
                description=desc,
            )

        def done(ok, err):
            if err is not None:
                self.app.set_status(f"开房失败: {err}")
                return
            self.app.set_status("开房成功，房间已上架" if ok
                                else f"开房失败: {room_host.last_error}")
            self.refresh()

        async_task(work, done)

    def _stop_host(self) -> None:
        def done(_v, _e):
            self.app.set_status("房间已结束")
            self.refresh()

        async_task(room_host.stop, done)

    # ---------- 加入 ----------

    def _join(self, host: str, port: int) -> None:
        if not host or not port:
            self.app.set_status("房间地址无效")
            return

        def work():
            engine.ensure_engine(status=self.app.set_status)
            name = (api.user or {}).get("username", "") or ""
            join_room(host, port, name)

        def done(_v, err):
            if err is not None:
                self.app.set_status(f"连接失败: {err}")
            else:
                self.app.set_status(f"正在连接 {host}:{port} …")

        async_task(work, done)

    # ---------- 房主状态 ----------

    def _update_host_card(self, state: str) -> None:
        show = state != "idle"
        self.host_card.setVisible(show)
        if not show:
            return
        color, title, extra = {
            "starting": ("warning", "正在启动…", ""),
            "running": ("success", "房间运行中",
                        f" · 端口 30000 · 在线 {room_host.player_count} 人"),
            "stopping": ("warning", "正在关闭…", ""),
            "error": ("danger", "出错", f" · {room_host.last_error}"),
        }.get(state, ("faint", state, ""))
        theme.set_tone(self.host_dot, color)
        self.host_title.setText(title)
        self.host_meta.setText(extra)

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        self.host_log.setPlainText("\n".join(self._log_lines))
        sb = self.host_log.verticalScrollBar()
        sb.setValue(sb.maximum())
