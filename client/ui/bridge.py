"""线程安全 UI 调度：队列 + 主循环定时器排水（替代 DPG 的 mutex 方案）。

任何后台线程想更新界面，只需 ui_call(fn, *args)；fn 会在 UI 线程执行。
async_task(fn, on_done)：后台执行 fn，完成后 on_done(value, error) 回 UI 线程。
"""
from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable

_q: "queue.Queue[tuple[Callable, tuple]]" = queue.Queue()


def ui_call(fn: Callable, *args: Any) -> None:
    _q.put((fn, args))


def drain(max_items: int = 400) -> None:
    """在 UI 线程定时调用：执行积压的回调（异常只打印，不中断循环）。"""
    for _ in range(max_items):
        try:
            fn, args = _q.get_nowait()
        except queue.Empty:
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def async_task(fn: Callable[[], Any],
               on_done: Callable[[Any, BaseException | None], None]) -> None:
    """后台线程执行 fn；on_done(value, error) 于 UI 线程回调。"""
    def run() -> None:
        try:
            ui_call(on_done, fn(), None)
        except BaseException as ex:  # noqa: BLE001 — 网络/IO 异常统一上报
            ui_call(on_done, None, ex)

    threading.Thread(target=run, daemon=True).start()
