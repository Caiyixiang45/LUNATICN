"""LUNATICN 客户端主框架（PySide6）— PCL 风格侧边导航 + 状态栏 + WS 推送。"""
from __future__ import annotations

import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from lunaticn import settings as cfg
from lunaticn.api import api
from lunaticn.ws import room_watch
from ui import theme, widgets
from ui.bridge import drain, ui_call
from ui.tray import tray

NAV_ITEMS = [
    ("lobby", "联机大厅"),
    ("worlds", "存档库"),
    ("mods", "模组中心"),
    ("workshop", "分享工坊"),
    ("friends", "好友"),
    ("settings", "设置"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LUNATICN")
        self.resize(1240, 800)
        self.setMinimumSize(1000, 660)

        self.pages: dict[str, QWidget] = {}
        self._nav_btns: dict[str, QPushButton] = {}
        self.current = "lobby"
        self.announcements: list[dict] = []
        self.update_info: dict = {}
        self._status_text = "就绪"
        self._ws_ok = False
        self._tray_hint_done = False

        # 回调统一回到 UI 线程
        api.on_auth_changed = lambda: ui_call(self.update_account)
        api.on_expired = lambda: ui_call(self._on_expired)

        self._build_ui()

        # 托盘（关闭窗口最小化到托盘，按设置开关）
        tray.setup(self, on_show=self._show_from_tray,
                   on_quit=self._quit_app)
        tray.set_enabled(bool(cfg.get("tray_enable")))

        # 队列排水定时器（bridge → UI 线程）
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(50)
        self._drain_timer.timeout.connect(drain)
        self._drain_timer.start()

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        root.addWidget(self._build_sidebar())

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, stretch=1)
        body.addWidget(self._build_statusbar())
        root.addLayout(body, stretch=1)

        self._build_pages()

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(216)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(4)

        logo_row = QHBoxLayout()
        ic = QLabel("◣")
        theme.set_tone(ic, "brand")
        ic.setStyleSheet("font-size: 22px; font-weight: 700;")
        logo_row.addWidget(ic)
        t = QLabel("LUNATICN")
        theme.set_tone(t, "title")
        t.setStyleSheet("font-size: 19px;")
        logo_row.addWidget(t)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)
        sub = QLabel("SANDBOX PLATFORM")
        theme.set_tone(sub, "faint")
        sub.setStyleSheet("font-size: 10px;")
        lay.addWidget(sub)
        lay.addSpacing(18)

        # 导航（互斥）
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for i, (key, text) in enumerate(NAV_ITEMS):
            btn = QPushButton(f"  {text}")
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setFixedHeight(40)
            btn.setCursor(Qt.PointingHandCursor)
            self._nav_group.addButton(btn, i)
            btn.clicked.connect(lambda _x=False, k=key: self.show_page(k))
            lay.addWidget(btn)
            self._nav_btns[key] = btn
            lay.addSpacing(2)
        lay.addStretch(1)

        # 账号卡片
        acc = QFrame()
        acc.setObjectName("card")
        al = QVBoxLayout(acc)
        al.setContentsMargins(12, 10, 12, 10)
        al.setSpacing(4)
        al.addWidget(widgets.label("账号", tone="faint", small=True))
        self.lb_acct_name = widgets.label("未登录", big=True)
        al.addWidget(self.lb_acct_name)
        self.lb_acct_sub = widgets.label("登录后可开房与分享", tone="muted",
                                         small=True)
        al.addWidget(self.lb_acct_sub)
        self.btn_account = widgets.button("登录 / 注册", self._login_clicked,
                                          variant="primary")
        al.addWidget(self.btn_account)
        lay.addWidget(acc)
        return side

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("card")
        bar.setFixedHeight(34)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)
        self.lb_status = widgets.label("  就绪", tone="muted", small=True)
        row.addWidget(self.lb_status)
        row.addStretch(1)
        self.lb_ws = widgets.label("○ 实时同步", tone="faint", small=True)
        row.addWidget(self.lb_ws)
        row.addWidget(widgets.label("  ·  ", tone="faint", small=True))
        self.lb_srv = widgets.label(cfg.get("server_url"), tone="faint",
                                    small=True)
        row.addWidget(self.lb_srv)
        return bar

    def _build_pages(self) -> None:
        from .pages import friends, lobby, mods, settings_page, workshop, worlds
        for key, page_cls in (
            ("lobby", lobby.LobbyPage),
            ("worlds", worlds.WorldsPage),
            ("mods", mods.ModsPage),
            ("workshop", workshop.WorkshopPage),
            ("friends", friends.FriendsPage),
            ("settings", settings_page.SettingsPage),
        ):
            page = page_cls(self)
            self.pages[key] = page
            self.stack.addWidget(page)
        self._nav_btns["lobby"].setChecked(True)

    # ---------- 状态栏 ----------

    def set_status(self, text: str) -> None:
        self._status_text = text
        self.lb_status.setText(f"  {text}")

    # ---------- 托盘 ----------

    def closeEvent(self, ev) -> None:  # noqa: N802
        if tray.enabled and tray.available():
            ev.ignore()
            self.hide()
            if not self._tray_hint_done:
                self._tray_hint_done = True
                tray.notify("LUNATICN",
                            "已最小化到托盘，点击图标恢复，右键可退出")
            return
        ev.accept()
        self._quit_app()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _quit_app() -> None:
        from PySide6.QtWidgets import QApplication
        tray.set_enabled(False)   # 允许真正退出
        QApplication.instance().quit()

    def set_ws_state(self, ok: bool) -> None:
        self._ws_ok = ok
        if ok:
            self.lb_ws.setText("● 实时同步")
            theme.set_tone(self.lb_ws, "success")
        else:
            self.lb_ws.setText("○ 实时同步断开")
            theme.set_tone(self.lb_ws, "faint")

    def update_account(self) -> None:
        u = api.user
        if u:
            self.lb_acct_name.setText(
                u.get("nickname") or u.get("username", ""))
            self.lb_acct_sub.setText(f'@{u.get("username", "")}')
            self.btn_account.setText("退出登录")
        else:
            self.lb_acct_name.setText("未登录")
            self.lb_acct_sub.setText("登录后可开房与分享")
            self.btn_account.setText("登录 / 注册")

    def _on_expired(self) -> None:
        self.set_status("登录已过期，请重新登录")
        self.update_account()

    # ---------- 导航 ----------

    def show_page(self, name: str) -> None:
        if name not in self.pages:
            return
        self.current = name
        self.stack.setCurrentWidget(self.pages[name])
        self._nav_btns[name].setChecked(True)
        page = self.pages[name]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as ex:  # noqa: BLE001
                self.set_status(f"页面加载失败: {ex}")

    # ---------- 登录 ----------

    def _login_clicked(self) -> None:
        if api.is_logged_in:
            api.logout()
            # 清除保存的凭据（防下次自动登录立刻重登）；
            # 保留 auto_login 勾选偏好，下次登录框默认勾上
            cfg.set("saved_username", "")
            cfg.set("saved_password_enc", "")
            self.set_status("已退出登录（已清除保存的凭据）")
            self.update_account()
            return
        self.show_page("lobby")
        lobby = self.pages.get("lobby")
        if lobby is not None and hasattr(lobby, "login"):
            lobby.login.open()

    # ---------- WebSocket ----------

    def _start_ws(self) -> None:
        room_watch.on_event = lambda: ui_call(self._rooms_changed)
        room_watch.on_notice = lambda: threading.Thread(
            target=self._fetch_notices, daemon=True).start()
        room_watch.on_state = lambda ok: ui_call(self.set_ws_state, ok)
        room_watch.on_chat = lambda data: ui_call(self._on_chat_msg, data)
        room_watch.on_invite = lambda data: ui_call(self._on_invite_msg, data)
        room_watch.on_presence = lambda data: ui_call(self._on_presence, data)
        try:
            room_watch.start(api.ws_url())
        except Exception:  # noqa: BLE001
            pass

    def _rooms_changed(self) -> None:
        if self.current == "lobby":
            page = self.pages.get("lobby")
            if page is not None and hasattr(page, "refresh"):
                try:
                    page.refresh_rooms()
                except Exception:  # noqa: BLE001
                    pass

    # ---------- 好友上/下线 ----------

    def _on_presence(self, data: dict) -> None:
        """特别关心的好友上线 → 托盘气泡 + 状态栏（可设置关闭）。"""
        if not cfg.get("notify_friend_online") or not data.get("online"):
            return
        uid = str(data.get("user_id") or "")
        if uid not in (cfg.get("watched_friends") or []):
            return
        name = str(data.get("name") or "好友")
        tray.notify("好友上线", f"{name} 上线了")
        self.set_status(f"{name} 上线了")

    # ---------- 聊天与邀请推送 ----------

    def _on_chat_msg(self, data: dict) -> None:
        page = self.pages.get("friends")
        delivered = False
        if page is not None and hasattr(page, "on_chat_message"):
            try:
                delivered = bool(page.on_chat_message(data))
            except Exception:  # noqa: BLE001
                delivered = False
        if not delivered:
            who = data.get("from_name") or "好友"
            text = str(data.get("text") or "")[:40]
            self.set_status(f"来自 {who} 的消息：{text}")

    def _on_invite_msg(self, data: dict) -> None:
        from PySide6.QtWidgets import QMessageBox
        who = data.get("from_name") or "好友"
        room = data.get("room_name") or "房间"
        box = QMessageBox(self)
        box.setWindowTitle("进房邀请")
        box.setText(f"{who} 邀请你加入房间「{room}」\n"
                    f"地址 {data.get('host')}:{data.get('port')}")
        btn_join = box.addButton("加入", QMessageBox.AcceptRole)
        box.addButton("忽略", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not btn_join:
            return
        host = str(data.get("host") or "")
        port = int(data.get("port") or 0)
        if not host or not port:
            self.set_status("邀请中的房间地址无效")
            return

        def work():
            from lunaticn import engine
            from lunaticn.host import join_room
            engine.ensure_engine(status=self.set_status)
            name = (api.user or {}).get("username", "") or ""
            join_room(host, port, name)

        def done(_v, err):
            if err is not None:
                self.set_status(f"连接失败: {err}")
            else:
                self.set_status(f"正在连接 {host}:{port} …")

        from ui.bridge import async_task
        async_task(work, done)

    # ---------- 公告与更新推送 ----------

    def _fetch_notices(self) -> None:
        anns: list[dict] = []
        upd: dict = {}
        try:
            anns = api.announcements()
        except Exception:  # noqa: BLE001
            pass
        try:
            upd = api.client_update_info()
        except Exception:  # noqa: BLE001
            pass
        ui_call(self._apply_notices, anns, upd)

    def _apply_notices(self, anns: list[dict], upd: dict) -> None:
        self.announcements = anns
        self.update_info = upd or {}
        page = self.pages.get("lobby")
        if page is not None and hasattr(page, "set_notices"):
            try:
                page.set_notices(self.announcements, self.update_info)
            except Exception:  # noqa: BLE001
                pass
        if self.update_info.get("has_update"):
            self.set_status(
                f'发现客户端新版本 v{self.update_info.get("latest", "?")}，'
                "请到设置页下载")

    # ---------- 启动 ----------

    def start(self, login_state: str = "none") -> None:
        """登录完成后的引导：状态栏 → 大厅 → WS → 公告。

        登录/自动登录在 ui/bootstrap.py（main.py 门禁）先行完成，
        进不了主界面就没到这里——未登录不会执行到 start()。
        """
        labels = {"restored": "会话已恢复", "auto": "已自动登录",
                  "manual": "已登录", "none": "就绪"}
        self.set_status(labels.get(login_state, "就绪"))
        self.update_account()
        self.show_page("lobby")
        self._start_ws()
        threading.Thread(target=self._fetch_notices, daemon=True).start()
        if cfg.get("auto_engine"):
            threading.Thread(target=self._prepare_engine, daemon=True,
                             name="lunaticn-engine").start()

    def _prepare_engine(self) -> None:
        """后台确保引擎与默认游戏就绪（设置 auto_engine 开关）。"""
        from lunaticn import engine
        try:
            did = False
            if engine.installed_version() is None:
                engine.ensure_engine(
                    status=lambda s: ui_call(self.set_status, s))
                did = True
            if not engine.has_game(engine.DEFAULT_GAME):
                engine.install_game(
                    engine.DEFAULT_GAME,
                    status=lambda s: ui_call(self.set_status, s))
                did = True
            if did:
                ui_call(self.set_status, "引擎与游戏已自动就绪")
        except Exception as ex:  # noqa: BLE001
            ui_call(self.set_status, f"引擎准备失败: {ex}")


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()
