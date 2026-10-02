"""设置 — 卡片分区：服务器 / 引擎 / 启动行为 / 更新 / 资料 / 存储 / 关于。"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLineEdit, QProgressBar, QScrollArea,
    QVBoxLayout, QWidget,
)

from lunaticn import download, engine, settings as cfg, storage
from lunaticn.api import api
from ui import widgets
from ui.bridge import async_task, ui_call

UPDATES_DIR = cfg.DATA_DIR / "updates"


def _card(lay: QVBoxLayout, title: str):
    fr = widgets.card(lay)
    inner = fr.layout()
    widgets.section_title(title, inner)
    return inner


class SettingsPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 10)
        root.setSpacing(10)
        widgets.page_header(root, "设置", "社区服务器、引擎与个人资料")

        scroll = QWidget()
        lay = QVBoxLayout(scroll)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)

        # ---- 社区服务器 ----
        inner = _card(lay, "社区服务器")
        row = widgets.hbox(inner)
        self.ed_server = QLineEdit()
        self.ed_server.setPlaceholderText("http://localhost:7698")
        row.addWidget(self.ed_server, stretch=1)
        row.addWidget(widgets.button("保存并测试", self._save_and_test,
                                     variant="primary", width=120))
        self.lb_server = widgets.label("", tone="faint", small=True)
        inner.addWidget(self.lb_server)
        tip = widgets.label("账号操作在“联机大厅”或左下角完成；"
                            "修改地址后请重新测试。", tone="faint", small=True)
        inner.addWidget(tip)

        # ---- 引擎 ----
        inner = _card(lay, "游戏引擎 Luanti")
        self.lb_engine = widgets.label("未安装", big=True)
        inner.addWidget(self.lb_engine)
        inner.addWidget(widgets.label(
            "多镜像下载官方便携版（约 17 MB，含全部运行文件）。",
            tone="faint", small=True))
        row = widgets.hbox(inner)
        row.addWidget(widgets.button("检查最新版本", self._check_engine,
                                     width=130))
        row.addWidget(widgets.button("下载 / 重装", self._install_engine,
                                     variant="primary", width=120))
        row.addStretch(1)
        self.pb_engine = QProgressBar()
        self.pb_engine.setRange(0, 100)
        self.pb_engine.hide()
        inner.addWidget(self.pb_engine)
        self.lb_engine_st = widgets.label("", tone="faint", small=True)
        inner.addWidget(self.lb_engine_st)

        # ---- 启动行为 ----
        inner = _card(lay, "启动行为")
        self.cb_auto_engine = QCheckBox("启动时自动下载 / 安装引擎与游戏")
        self.cb_auto_upd = QCheckBox("启动时检查引擎与客户端更新")
        self.cb_auto_login = QCheckBox("启动时自动登录（密码经 Windows DPAPI 加密）")
        self.cb_auto_engine.toggled.connect(
            lambda v: cfg.set("auto_engine", bool(v)))
        self.cb_auto_upd.toggled.connect(
            lambda v: cfg.set("auto_check_update", bool(v)))
        self.cb_auto_login.toggled.connect(
            lambda v: cfg.set("auto_login", bool(v)))
        inner.addWidget(self.cb_auto_engine)
        inner.addWidget(self.cb_auto_upd)
        inner.addWidget(self.cb_auto_login)
        row = widgets.hbox(inner)
        row.addWidget(widgets.button("打开数据目录", self._open_data,
                                     width=130))
        row.addWidget(widgets.button("打开存档目录",
                                     lambda: self._open_dir(
                                         cfg.DATA_DIR / "worlds"),
                                     width=130))
        row.addStretch(1)

        # ---- 托盘与提醒 ----
        inner = _card(lay, "托盘与提醒")
        self.cb_tray = QCheckBox("关闭窗口时最小化到托盘（程序继续后台运行）")
        self.cb_notify = QCheckBox("特别关心的好友上线时弹出通知")
        self.cb_tray.toggled.connect(self._toggle_tray)
        self.cb_notify.toggled.connect(
            lambda v: cfg.set("notify_friend_online", bool(v)))
        inner.addWidget(self.cb_tray)
        inner.addWidget(self.cb_notify)
        inner.addWidget(widgets.label(
            "在“好友”页可给好友标记特别关心；托盘图标在右下角通知区，"
            "右键可退出程序。", tone="faint", small=True))

        # ---- 客户端更新 ----
        inner = _card(lay, "客户端更新")
        row = widgets.hbox(inner)
        self.lb_version = widgets.label(f"当前版本 v{cfg.CLIENT_VERSION}",
                                        big=True)
        row.addWidget(self.lb_version)
        row.addStretch(1)
        row.addWidget(widgets.button("检查更新", self._check_update,
                                     width=100))
        row.addWidget(widgets.button("下载更新包", self._download_update,
                                     variant="primary", width=130))
        self.lb_update = widgets.label("", tone="faint", small=True)
        self.lb_update.setWordWrap(True)
        inner.addWidget(self.lb_update)
        self.pb_update = QProgressBar()
        self.pb_update.setRange(0, 100)
        self.pb_update.hide()
        inner.addWidget(self.pb_update)
        inner.addWidget(widgets.label("更新包按服务端配置的镜像地址逐个"
                                      "兜底下载。", tone="faint", small=True))

        # ---- 资料 ----
        inner = _card(lay, "个人资料")
        row = widgets.hbox(inner)
        row.addWidget(widgets.label("昵称", tone="muted", small=True))
        self.ed_nick = QLineEdit()
        self.ed_nick.setMinimumWidth(160)
        row.addWidget(self.ed_nick, stretch=1)
        row.addWidget(widgets.button("保存", self._save_profile, width=90))
        row.addStretch(1)
        self.lb_profile = widgets.label("", tone="faint", small=True)
        inner.addWidget(self.lb_profile)

        # ---- 存储管理 ----
        inner = _card(lay, "存储管理")
        self.lb_storage = widgets.label("计算中…", tone="muted", small=True)
        inner.addWidget(self.lb_storage)
        row = widgets.hbox(inner)
        row.addWidget(widgets.button("重新统计", self._refresh_storage,
                                     width=100))
        row.addWidget(widgets.button("清理日志与临时文件", self._cleanup,
                                     variant="primary", width=170))
        row.addStretch(1)
        self.lb_cleanup = widgets.label("", tone="faint", small=True)
        inner.addWidget(self.lb_cleanup)

        # ---- 关于 ----
        inner = _card(lay, "关于 LUNATICN")
        inner.addWidget(widgets.label(
            f"LUNATICN 沙盒平台 · 私有社区 · 客户端 v{cfg.CLIENT_VERSION}",
            tone="muted"))
        inner.addWidget(widgets.label(f"数据目录：{cfg.DATA_DIR}",
                                      tone="faint", small=True))

        lay.addStretch(1)
        from PySide6.QtWidgets import QScrollArea
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(scroll)
        area.verticalScrollBar().setSingleStep(6)
        root.addWidget(area, stretch=1)

    # ---------- 刷新 ----------

    def refresh(self) -> None:
        self.ed_server.setText(cfg.get("server_url"))
        u = api.user or {}
        self.ed_nick.setText(u.get("nickname", ""))
        self.lb_profile.setText(
            f"当前登录：@{u.get('username', '')}" if u else "未登录")
        ver = engine.installed_version()
        self.lb_engine.setText(
            f"已安装 · 版本 {ver}" if ver else "未安装")
        self.lb_server.setText("")
        self.lb_update.setText("")
        for cb, key in ((self.cb_auto_engine, "auto_engine"),
                        (self.cb_auto_upd, "auto_check_update"),
                        (self.cb_auto_login, "auto_login"),
                        (self.cb_tray, "tray_enable"),
                        (self.cb_notify, "notify_friend_online")):
            want = bool(cfg.get(key))
            if cb.isChecked() != want:
                cb.blockSignals(True)
                cb.setChecked(want)
                cb.blockSignals(False)
        self._refresh_storage()

    @staticmethod
    def _toggle_tray(v) -> None:
        cfg.set("tray_enable", bool(v))
        from ui.tray import tray
        tray.set_enabled(bool(v))

    @staticmethod
    def _open_dir(path) -> None:
        try:
            os.startfile(str(path))  # noqa: S606 — Windows 打开资源管理器
        except OSError:
            pass

    def _open_data(self) -> None:
        self._open_dir(cfg.DATA_DIR)

    def highlight_update(self) -> None:
        self.pb_update.show()
        self.pb_update.setValue(0)
        self.pb_update.setFormat("点击“下载更新包”开始下载")
        try:
            latest = (api.client_update_info() or {}).get("latest", "?")
        except Exception:  # noqa: BLE001
            latest = "?"
        self.lb_update.setText(f"服务端最新版本 v{latest}")

    # ---------- 存储 ----------

    def _refresh_storage(self) -> None:
        self.lb_storage.setText("计算中…")

        def done(rep, err):
            if err is not None:
                self.lb_storage.setText(f"统计失败: {err}")
                return
            self.lb_storage.setText(
                "  ·  ".join(f"{k} {v:.1f} MB"
                             for k, v in rep.items())
                + f"  ·  合计 {sum(rep.values()):.1f} MB")

        async_task(storage.storage_report, done)

    def _cleanup(self) -> None:
        def done(res, err):
            if err is not None:
                self.lb_cleanup.setText(f"清理失败: {err}")
                return
            self.lb_cleanup.setText(
                f"✓ 已清理 日志 {res['logs']} 个 · 临时 {res['tmp']} 项 · "
                f"残留 zip {res['engine_zip']} 个")
            self._refresh_storage()

        async_task(storage.cleanup, done)

    # ---------- 服务器 ----------

    def _save_and_test(self) -> None:
        url = self.ed_server.text().strip().rstrip("/")
        if not url.startswith("http"):
            self.lb_server.setText("地址需以 http:// 或 https:// 开头")
            return
        cfg.set("server_url", url)
        api.base_url = url
        self.lb_server.setText("已保存，正在连接…")

        def work():
            data = api.health()
            return (f"✓ 连接成功 · 服务版本 {data.get('version', '?')}"
                    f" · 房间 {data.get('rooms', 0)} 个")

        def done(msg, err):
            self.lb_server.setText(
                f"✗ 连接失败: {err}" if err is not None else msg)

        async_task(work, done)

    # ---------- 引擎 ----------

    @staticmethod
    def _bar_cb(bar: QProgressBar):
        def prog(p: int, text: str) -> None:
            ui_call(lambda: (bar.setValue(max(0, min(100, p))),
                             bar.setFormat(f"{text} {p}%")) if bar else None)
        return prog

    def _check_engine(self) -> None:
        def work():
            latest = engine.fetch_latest_version()
            cur = engine.installed_version()
            real = engine.probe_version()
            msg = f"最新版本 {latest}" + (f"（当前 {cur}）" if cur else "")
            if real:
                msg += f" · 引擎实际 {real}"
            return msg

        def done(msg, err):
            text = f"检查失败: {err}" if err is not None else msg
            self.app.set_status(text)
            self.lb_engine_st.setText(text)

        async_task(work, done)

    def _install_engine(self) -> None:
        self.pb_engine.show()
        self.pb_engine.setValue(0)
        self.pb_engine.setFormat("准备中… 0%")

        def work():
            cur = engine.installed_version()
            if cur:
                return engine.reinstall(progress=self._bar_cb(self.pb_engine))
            return engine.ensure_engine(progress=self._bar_cb(self.pb_engine))

        def done(ver, err):
            self.pb_engine.hide()
            if err is not None:
                self.app.set_status(f"安装失败: {err}")
                self.lb_engine_st.setText(f"✗ 安装失败: {err}")
                return
            self.app.set_status(f"引擎 {ver} 已就绪")
            self.lb_engine.setText(f"已安装 · 版本 {ver}")
            self.lb_engine_st.setText("安装完成，游戏与模组会按需自动准备")

        async_task(work, done)

    # ---------- 客户端更新 ----------

    def _check_update(self) -> None:
        def work():
            info = api.client_update_info()
            if info.get("has_update"):
                return (f'发现新版本 v{info.get("latest", "?")}：'
                        f'{(info.get("notes") or "").strip()[:60]}'
                        f'（{len(info.get("mirrors") or [])} 个下载源）')
            return f"已是最新版本 v{cfg.CLIENT_VERSION}"

        def done(msg, err):
            self.lb_update.setText(
                f"检查失败: {err}" if err is not None else msg)

        async_task(work, done)

    def _download_update(self) -> None:
        def work():
            info = api.client_update_info()
            if not info.get("has_update") or not info.get("mirrors"):
                return ("没有可用的更新包（已是最新或服务端未配置镜像）",
                        False)
            ver = info.get("latest", "new")
            dest = UPDATES_DIR / f"LUNATICN-client-{ver}.zip"
            ui_call(lambda: (self.pb_update.show(),
                             self.pb_update.setValue(0),
                             self.pb_update.setFormat("准备中… 0%")))
            download.fetch(list(info["mirrors"]), dest,
                           progress=self._bar_cb(self.pb_update))
            return (f"✓ 已下载：{dest}（解压覆盖客户端目录即可更新）",
                    True)

        def done(res, err):
            ui_call(self.pb_update.hide)
            if err is not None:
                self.lb_update.setText(f"✗ 下载失败: {err}")
                return
            msg, _ok = res
            self.lb_update.setText(msg)

        async_task(work, done)

    # ---------- 资料 ----------

    def _save_profile(self) -> None:
        nick = self.ed_nick.text().strip()
        if not nick:
            self.lb_profile.setText("昵称不能为空")
            return

        def done(_v, err):
            if err is not None:
                self.lb_profile.setText(f"✗ {err}")
                return
            self.lb_profile.setText("✓ 昵称已更新")
            self.app.update_account()

        async_task(lambda: api.update_profile(nickname=nick), done)
