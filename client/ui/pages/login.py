"""登录/注册模态对话框（含自动登录）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from lunaticn import secure, settings as cfg
from lunaticn.api import ApiError, api
from ui import theme, widgets
from ui.bridge import async_task


class LoginDialog(QDialog):
    def __init__(self, on_done=None, parent=None) -> None:
        super().__init__(parent)
        self.on_done = on_done
        self.register_mode = False
        self.setWindowTitle("登录 LUNATICN")
        self.setMinimumWidth(400)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(9)

        tip = QLabel("使用社区账号登录，即可开房、加好友、上传分享作品。")
        theme.set_tone(tip, "brand")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        lay.addWidget(widgets.label("用户名", tone="muted", small=True))
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("3-24 位小写字母/数字")
        lay.addWidget(self.ed_user)

        lay.addWidget(widgets.label("密码", tone="muted", small=True))
        self.ed_pass = QLineEdit()
        self.ed_pass.setPlaceholderText("至少 6 位")
        self.ed_pass.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.ed_pass)

        self.lb_nick = widgets.label("昵称", tone="muted", small=True)
        self.lb_nick.hide()
        lay.addWidget(self.lb_nick)
        self.ed_nick = QLineEdit()
        self.ed_nick.setPlaceholderText("展示用，可留空")
        self.ed_nick.hide()
        lay.addWidget(self.ed_nick)

        self.cb_auto = QCheckBox("自动登录（密码经 Windows DPAPI 加密保存）")
        self.cb_auto.setChecked(bool(cfg.get("auto_login")))
        lay.addWidget(self.cb_auto)

        self.lb_error = QLabel("")
        self.lb_error.setWordWrap(True)
        theme.set_tone(self.lb_error, "danger")
        lay.addWidget(self.lb_error)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_switch = widgets.button("注册", self._toggle_mode, width=90)
        self.btn_cancel = widgets.button("取消", self.reject, width=90)
        self.btn_primary = widgets.button("登录", self._submit, width=90,
                                          variant="primary")
        row.addWidget(self.btn_switch)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_primary)
        lay.addLayout(row)

    # ---------- 逻辑 ----------

    def open(self) -> None:
        self.lb_error.setText("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.ed_user.setFocus()

    def _toggle_mode(self) -> None:
        self.register_mode = not self.register_mode
        self.setWindowTitle("注册 LUNATICN 账号" if self.register_mode
                            else "登录 LUNATICN")
        self.btn_primary.setText("创建账号" if self.register_mode else "登录")
        self.btn_switch.setText("去登录" if self.register_mode else "注册")
        self.ed_nick.setVisible(self.register_mode)
        self.lb_nick.setVisible(self.register_mode)
        self.lb_error.setText("")

    def _submit(self) -> None:
        user = self.ed_user.text().strip()
        pwd = self.ed_pass.text()
        nick = self.ed_nick.text().strip()
        if len(user) < 3:
            self.lb_error.setText("用户名至少 3 个字符")
            return
        if len(pwd) < 6:
            self.lb_error.setText("密码至少 6 位")
            return
        self.btn_primary.setEnabled(False)
        self.lb_error.setText("正在连接…")

        def work():
            if self.register_mode:
                api.register(user, pwd, nick)
            else:
                api.login(user, pwd)
            return user

        def done(_v, err):
            self.btn_primary.setEnabled(True)
            if err is not None:
                self.lb_error.setText(str(err) if isinstance(err, ApiError)
                                      else f"连接失败: {err}")
                return
            if self.cb_auto.isChecked():
                cfg.set("auto_login", True)
                cfg.set("saved_username", user)
                cfg.set("saved_password_enc", secure.save_password(pwd))
            else:
                cfg.set("auto_login", False)
                cfg.set("saved_username", "")
                cfg.set("saved_password_enc", "")
            self.accept()
            if self.on_done:
                self.on_done()

        async_task(work, done)
