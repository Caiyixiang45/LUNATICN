"""WebSocket 房间推送：连接 /api/ws，房间列表变化时回调。自动重连。"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional


class RoomWatch:
    """线程安全的 WS 客户端。收到 {"type":"rooms"} 事件触发 on_event。"""

    def __init__(self) -> None:
        self.connected = False
        self.on_event: Optional[Callable[[], None]] = None      # 房间变化
        self.on_notice: Optional[Callable[[], None]] = None     # 公告/更新推送
        self.on_chat: Optional[Callable[[dict], None]] = None   # 私聊消息推送
        self.on_invite: Optional[Callable[[dict], None]] = None  # 进房邀请
        self.on_presence: Optional[Callable[[dict], None]] = None  # 好友上/下线
        self.on_state: Optional[Callable[[bool], None]] = None
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._url = ""

    def start(self, url: str) -> None:
        if self._thread is not None and self._thread.is_alive():
            if url == self._url:
                return
            self.stop()
        self._url = url
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="lunaticn-ws")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    # ---------- 内部 ----------

    def _set_connected(self, value: bool) -> None:
        if self.connected == value:
            return
        self.connected = value
        if self.on_state:
            self.on_state(value)

    def _run(self) -> None:
        import websocket  # 延迟导入，未安装时不影响主程序

        while not self._stop.is_set():
            try:
                ws = websocket.WebSocketApp(
                    self._url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                pass
            finally:
                self._set_connected(False)
                self._ws = None
            if self._stop.is_set():
                break
            time.sleep(3)  # 断线重连等待

    def _on_open(self, _ws) -> None:  # noqa: ANN001
        self._set_connected(True)

    def _on_error(self, _ws, _err) -> None:  # noqa: ANN001
        pass

    def _on_close(self, _ws, *_a) -> None:  # noqa: ANN001
        self._set_connected(False)

    def _on_message(self, _ws, message) -> None:  # noqa: ANN001
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        typ = data.get("type")
        if typ == "rooms" and self.on_event:
            self.on_event()
        elif typ == "notice" and self.on_notice:
            self.on_notice()
        elif typ == "chat" and self.on_chat:
            self.on_chat(data)
        elif typ == "invite" and self.on_invite:
            self.on_invite(data)
        elif typ == "presence" and self.on_presence:
            self.on_presence(data)


room_watch = RoomWatch()
