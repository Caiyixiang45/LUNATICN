"""启动引导：恢复会话 / 自动登录（无 UI，后台线程执行）。

不登录不允许进入主界面：main.py 先在后台跑 try_login()，
成功则直接显示主窗口，失败则弹出登录对话框，取消即退出。
"""
from __future__ import annotations

from lunaticn import secure, settings as cfg
from lunaticn.api import api


def try_login() -> str:
    """尝试登录，返回 "restored" / "auto" / "none"。

    restored = 保存的令牌恢复会话；auto = 账密自动登录；none = 未登录。
    任何异常都归为 none（交给登录对话框处理）。
    """
    if cfg.token():
        try:
            if api.restore_session():
                return "restored"
        except Exception:  # noqa: BLE001
            pass
    if cfg.get("auto_login"):
        user = cfg.get("saved_username") or ""
        pwd = secure.load_password(cfg.get("saved_password_enc") or "")
        if user and pwd:
            try:
                api.login(user, pwd)
                return "auto"
            except Exception:  # noqa: BLE001
                pass
    return "none"
