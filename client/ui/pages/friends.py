"""好友 — 双栏卡片：好友列表 / 申请，支持私聊与邀请进房。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLineEdit, QTextEdit, QVBoxLayout, QWidget,
)

from lunaticn import settings as cfg
from lunaticn.api import api
from lunaticn.host import RUNNING, room_host
from ui import widgets
from ui.bridge import async_task

FRIEND_HEADERS = (("用户", 150), ("昵称", 140), ("", 380))
REQ_HEADERS = (("来自", 220), ("", 180))


class FriendsPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 10)
        lay.setSpacing(8)
        widgets.page_header(lay, "好友", "添加好友，开房时一键分享邀请地址")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_new = QLineEdit()
        self.ed_new.setPlaceholderText("对方用户名")
        self.ed_new.setMinimumWidth(170)
        self.ed_new.setMaximumWidth(300)
        self.ed_new.returnPressed.connect(self._add)
        row.addWidget(self.ed_new)
        row.addWidget(widgets.button("添加好友", self._add,
                                     variant="primary", width=100))
        row.addWidget(widgets.button("刷新", self.refresh, width=80))
        self.btn_invite = widgets.button("复制我的房间地址", self._copy_invite,
                                         width=160)
        self.btn_invite.hide()
        row.addWidget(self.btn_invite)
        row.addStretch(1)
        lay.addLayout(row)

        cols = QHBoxLayout()
        col1 = QVBoxLayout()
        widgets.section_title("我的好友", col1)
        self.table = widgets.table(FRIEND_HEADERS, min_height=320)
        col1.addWidget(self.table)
        cols.addLayout(col1, stretch=3)
        col2 = QVBoxLayout()
        widgets.section_title("收到的申请", col2)
        self.req_table = widgets.table(REQ_HEADERS, min_height=320)
        col2.addWidget(self.req_table)
        cols.addLayout(col2, stretch=2)
        lay.addLayout(cols, stretch=1)

        # 私聊窗口（非模态，收到实时消息时自动追加）
        self._chat_peer: tuple[str, str] = ("", "")  # (id, username)
        self._chat_sent_ids: set[int] = set()
        self.dlg_chat = QDialog(self)
        self.dlg_chat.setWindowTitle("私聊")
        self.dlg_chat.resize(460, 520)
        cl = QVBoxLayout(self.dlg_chat)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)
        self.chat_title = widgets.label("", tone="title")
        cl.addWidget(self.chat_title)
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        cl.addWidget(self.chat_log, stretch=1)
        widgets.hline(cl)
        irow = QHBoxLayout()
        irow.setSpacing(8)
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入消息，回车发送")
        self.chat_input.setMaxLength(500)
        self.chat_input.returnPressed.connect(self._chat_send)
        irow.addWidget(self.chat_input)
        irow.addWidget(widgets.button("发送", self._chat_send,
                                      variant="primary", width=80))
        cl.addLayout(irow)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        self.btn_invite.setVisible(room_host.state == RUNNING)
        if not api.is_logged_in:
            widgets.fill_table(self.table, [], "登录后查看好友列表")
            widgets.fill_table(self.req_table, [], "—")
            return

        def work():
            friends = api.friends()
            requests_in, _out = api.friend_requests()
            return friends, requests_in

        def done(v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            friends, requests_in = v
            self._fill_friends(friends)
            self._fill_requests(requests_in)
            self.app.set_status(f"好友 {len(friends)} 人 · "
                                f"申请 {len(requests_in)} 个")

        async_task(work, done)

    def _fill_friends(self, friends: list[dict]) -> None:
        if not friends:
            widgets.fill_table(self.table, [], "暂无好友，试试上方搜索添加")
            return
        watched = set(cfg.get("watched_friends") or [])
        rows = []
        for f in friends:
            fid = f.get("id", "")
            uname = f.get("username", "")
            is_w = fid in watched
            b_chat = widgets.button("聊天",
                                    lambda _x=False, fid=fid, u=uname:
                                    self._open_chat(fid, u))
            b_inv = widgets.button("邀请进房",
                                   lambda _x=False, fid=fid: self._invite(fid))
            b_watch = widgets.button(
                "★ 已关心" if is_w else "☆ 关心",
                lambda _x=False, fid=fid, w=is_w: self._watch(fid, not w),
                variant="primary" if is_w else "")
            btn = widgets.button("删除",
                                 lambda _x=False, fid=fid: self._remove(fid),
                                 variant="danger")
            for b in (b_chat, b_inv, b_watch, btn):
                b.setFixedHeight(26)
            rows.append(([uname, f.get("nickname", ""), ""],
                         {1: {"tone": "muted"},
                          2: {"widget": widgets.row_buttons(
                              b_chat, b_inv, b_watch, btn, spacing=4)}}))
        widgets.fill_table(self.table, rows)

    def _fill_requests(self, requests_in: list[dict]) -> None:
        if not requests_in:
            widgets.fill_table(self.req_table, [], "没有新的好友申请")
            return
        rows = []
        for r in requests_in:
            user = r.get("user") or {}
            uid = user.get("id", "")
            b_ok = widgets.button("同意",
                                  lambda _x=False, uid=uid:
                                  self._accept(uid))
            b_no = widgets.button("拒绝",
                                  lambda _x=False, uid=uid: self._reject(uid))
            b_ok.setFixedHeight(26)
            b_no.setFixedHeight(26)
            rows.append(([user.get("username", ""), ""],
                         {1: {"widget": widgets.row_buttons(b_ok, b_no)}}))
        widgets.fill_table(self.req_table, rows)

    # ---------- 操作 ----------

    def _add(self) -> None:
        name = self.ed_new.text().strip()
        if not name:
            return
        self.ed_new.setText("")

        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
            else:
                self.app.set_status(f"已向 {name} 发送好友申请")

        async_task(lambda: api.friend_request(name), done)

    def _remove(self, friend_id: str) -> None:
        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self.app.set_status("已删除该好友")
            self.refresh()

        async_task(lambda: api.friend_remove(friend_id), done)

    def _watch(self, friend_id: str, watch: bool) -> None:
        """特别关心：上线时弹托盘通知（本地偏好，不上传服务端）。"""
        watched = list(cfg.get("watched_friends") or [])
        if watch:
            if friend_id not in watched:
                watched.append(friend_id)
        else:
            watched = [x for x in watched if x != friend_id]
        cfg.set("watched_friends", watched)
        self.app.set_status("已取消特别关心" if not watch
                            else "已设为特别关心，上线会弹通知")
        self.refresh()

    def _accept(self, from_user_id: str) -> None:
        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self.app.set_status("已同意申请")
            self.refresh()

        async_task(lambda: api.friend_respond(from_user_id, True), done)

    def _reject(self, from_user_id: str) -> None:
        def done(_v, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            self.refresh()

        async_task(lambda: api.friend_respond(from_user_id, False), done)

    # ---------- 私聊 ----------

    @staticmethod
    def _fmt_ts(v) -> str:
        try:
            n = int(v or 0)
            if n > 10 ** 12:      # 毫秒
                n //= 1000
            return datetime.fromtimestamp(n).strftime("%m-%d %H:%M")
        except (ValueError, TypeError, OSError):
            return "--"

    def _open_chat(self, friend_id: str, username: str) -> None:
        self._chat_peer = (friend_id, username)
        self._chat_sent_ids = set()
        self.chat_title.setText(f"与 {username} 的私聊")
        self.chat_log.setPlainText("")
        if self.dlg_chat.isVisible():
            self.dlg_chat.raise_()
        else:
            self.dlg_chat.show()

        def done(msgs, err):
            if err is not None:
                self.app.set_status(str(err))
                return
            my_id = (api.user or {}).get("id") or ""
            lines = []
            for m in msgs:
                who = "我" if m.get("from") == my_id else username
                lines.append(f"[{self._fmt_ts(m.get('created_at'))}] "
                             f"{who}: {m.get('text', '')}")
            self.chat_log.setPlainText("\n".join(lines))
            sb = self.chat_log.verticalScrollBar()
            sb.setValue(sb.maximum())

        async_task(lambda: api.chat_history(friend_id), done)

    def on_chat_message(self, data: dict) -> bool:
        """WS 推送的私聊消息；已处理返回 True（不重复进状态栏）。"""
        my_id = (api.user or {}).get("id") or ""
        if data.get("from") == my_id:
            return True          # 自己在别处发送的回显，本地已显示过
        if not self.dlg_chat.isVisible():
            return False
        if self._chat_peer[0] != data.get("from"):
            return False
        who = data.get("from_name") or self._chat_peer[1]
        self._append_chat(who, str(data.get("text") or ""))
        return True

    def _chat_send(self) -> None:
        text = self.chat_input.text().strip()
        peer = self._chat_peer[0]
        if not text or not peer:
            return
        self.chat_input.clear()

        def done(mid, err):
            if err is not None:
                self.app.set_status(f"发送失败: {err}")
                return
            self._chat_sent_ids.add(int(mid))
            self._append_chat("我", text)

        async_task(lambda: api.chat_send(peer, text), done)

    def _append_chat(self, who: str, text: str) -> None:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%m-%d %H:%M")
        self.chat_log.append(f"[{ts}] {who}: {text}")
        sb = self.chat_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- 邀请进房 ----------

    def _invite(self, friend_id: str) -> None:
        if room_host.state != RUNNING or not room_host.room_name:
            self.app.set_status("请先到联机大厅开一个房间，再邀请好友")
            return
        room = room_host.room_name

        def done(_v, err):
            if err is not None:
                self.app.set_status(f"邀请失败: {err}")
            else:
                self.app.set_status(f"已邀请好友加入房间「{room}」")

        async_task(lambda: api.invite_to_room(friend_id, room), done)

    def _copy_invite(self) -> None:
        if room_host.state != RUNNING:
            self.app.set_status("当前没有运行中的房间")
            return
        from PySide6.QtWidgets import QApplication
        from lunaticn.host import detect_lan_ip
        addr = f"{detect_lan_ip()}:30000"
        QApplication.clipboard().setText(addr)
        self.app.set_status(f"房间地址已复制：{addr}（发给好友即可加入）")
