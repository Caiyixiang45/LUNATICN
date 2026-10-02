"""本地设置与令牌持久化。"""
import json
import os
from pathlib import Path

# 客户端数据根目录（存档/模组/引擎/设置都在这里）
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LUNATICN" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 客户端版本号（服务端 /api/client-update 用它判断是否推送新版本）
CLIENT_VERSION = "1.0.0"

_SETTINGS_PATH = DATA_DIR / "settings.json"

_DEFAULTS = {
    "server_url": "http://localhost:7698",
    "player_name": os.environ.get("USERNAME", "player"),
    "client_port": "0",
    "engine_version": "5.17.0",
    "admin_token": "",
    "token": "",
    # 自动登录
    "auto_login": True,
    # 启动行为：自动准备引擎/游戏、检查更新
    "auto_engine": True,
    "auto_check_update": True,
    # 托盘与提醒
    "tray_enable": True,            # 关闭窗口时最小化到托盘
    "notify_friend_online": True,   # 特别关心的好友上线时弹通知
    "watched_friends": [],          # 特别关心的好友 ID 列表
    # 自定义模组源（动态解析，追加在内置源之后）
    # 形如 [{"label": "镜像站", "kind": "community", "base": "http://..."}]
    "mod_sources": [],
    "saved_username": "",
    "saved_password_enc": "",
}


def load() -> dict:
    cfg = dict(_DEFAULTS)
    if _SETTINGS_PATH.exists():
        try:
            cfg.update(json.loads(_SETTINGS_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    _SETTINGS_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get(key: str):
    return load().get(key, _DEFAULTS.get(key))


def set(key: str, value) -> None:
    cfg = load()
    cfg[key] = value
    save(cfg)


def token() -> str:
    return load().get("token") or ""


def set_token(token: str) -> None:
    set("token", token)
