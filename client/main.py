"""LUNATICN 客户端入口（Python + PySide6）。

启动流程（门禁）：
  清理 → 主题 → 构建主窗口（隐藏）→ 后台恢复会话/自动登录
  → 成功：显示主窗口；失败：登录对话框（取消即退出）。
未登录永远进不了主界面。
"""
import sys
from pathlib import Path

# 保证以项目根为工作目录（data/ 相对定位等）
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_splash(app):
    """启动加载画面：浅色毛玻璃风格占位（纯代码绘制，无资源文件）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    pm = QPixmap(460, 260)
    pm.fill(QColor("#EDF1F7"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 180)))
    p.setBrush(QColor(255, 255, 255, 140))
    p.drawRoundedRect(6, 6, pm.width() - 12, pm.height() - 12, 18, 18)
    p.setPen(QColor("#1E88FF"))
    f = QFont()
    f.setPixelSize(40)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect().adjusted(0, -24, 0, -24),
               int(Qt.AlignmentFlag.AlignCenter), "LUNATICN")
    p.setPen(QColor("#6B7684"))
    f2 = QFont()
    f2.setPixelSize(13)
    p.setFont(f2)
    p.drawText(pm.rect().adjusted(0, 52, 0, 52),
               int(Qt.AlignmentFlag.AlignCenter), "社区沙盒平台 · 正在启动…")
    p.end()

    splash = QSplashScreen(pm)
    splash.setWindowFlags(Qt.WindowType.SplashScreen |
                          Qt.WindowType.FramelessWindowHint)
    return splash


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QDialog

    from lunaticn import storage
    from ui import bootstrap, theme
    from ui.app import MainWindow
    from ui.bridge import async_task
    from ui.pages.login import LoginDialog

    app = QApplication(sys.argv)
    app.setApplicationName("LUNATICN")
    app.setOrganizationName("LUNATICN")

    # 启动即做安全清理（日志轮转 / 临时文件 / 残留 zip）
    try:
        storage.prune_logs(keep=5)
        storage.prune_tmp()
        storage.prune_engine_archives()
    except Exception:  # noqa: BLE001
        pass

    theme.apply(app)

    splash = _make_splash(app)
    splash.showMessage("正在恢复会话…",
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                       QColor("#6B7684"))
    splash.show()
    app.processEvents()

    win = MainWindow()  # 已构建但不显示（内含队列排水定时器）

    def on_boot(state: str, err) -> None:
        if err is not None:
            state = "none"
        if state != "none":
            splash.finish(win)
            win.show()
            win.start(state)
            return
        # 未登录 → 登录门禁：不登录进不了主界面
        splash.close()
        dlg = LoginDialog()
        if dlg.exec() == QDialog.Accepted:
            win.show()
            win.start("manual")
        else:
            app.quit()

    async_task(bootstrap.try_login, on_boot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
