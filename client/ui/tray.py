"""系统托盘 — 关闭窗口最小化到托盘 + 好友上线气泡通知。"""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme


def _make_icon(size: int = 64) -> QIcon:
    """程序化绘制托盘图标：品牌色圆角底 + 白色三角。"""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pal = theme.current()
    c = QColor(*(pal.get("brand") or (30, 136, 255)))
    p.setBrush(c)
    p.setPen(c)
    p.drawRoundedRect(0, 0, size, size, size // 4, size // 4)
    p.setBrush(QColor(255, 255, 255))
    p.setPen(QColor(255, 255, 255))
    pts = QPolygon([
        QPoint(int(size * 0.34), int(size * 0.28)),
        QPoint(int(size * 0.74), int(size * 0.5)),
        QPoint(int(size * 0.34), int(size * 0.72)),
    ])
    p.drawPolygon(pts)
    p.end()
    return QIcon(pm)


class Tray:
    """托盘图标封装：显示/隐藏主窗口、退出、气泡通知。"""

    def __init__(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        self.window = None          # 主窗口
        self.on_show = None         # 恢复窗口回调
        self.on_quit = None         # 退出回调
        self._tray_enabled = True

    def setup(self, window, on_show, on_quit) -> None:
        if self.tray is not None:
            return
        self.window = window
        self.on_show = on_show
        self.on_quit = on_quit

        tray = QSystemTrayIcon(_make_icon(), window)
        tray.setToolTip("LUNATICN")
        menu = QMenu()
        act_show = QAction("显示主窗口", menu)
        act_show.triggered.connect(self._show)
        act_quit = QAction("退出 LUNATICN", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._activated)
        tray.show()
        self.tray = tray

    def set_enabled(self, enabled: bool) -> None:
        """关闭窗口时是否最小化到托盘（False 则真正退出）。"""
        self._tray_enabled = bool(enabled)

    @property
    def enabled(self) -> bool:
        return self._tray_enabled

    def available(self) -> bool:
        return (self.tray is not None
                and QSystemTrayIcon.isSystemTrayAvailable())

    def notify(self, title: str, message: str) -> None:
        if self.tray is None:
            return
        self.tray.showMessage(title, message,
                              QSystemTrayIcon.Information, 6000)

    def _activated(self, reason) -> None:  # noqa: ANN001
        if reason == QSystemTrayIcon.Trigger:
            self._show()

    def _show(self) -> None:
        if self.on_show:
            self.on_show()

    def _quit(self) -> None:
        if self.on_quit:
            self.on_quit()


tray = Tray()
