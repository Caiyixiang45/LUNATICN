"""房主开服与加入房间：拉起 luanti 进程 + 社区服务器注册/心跳。

实测依据（Luanti 5.17.0）：
  - 加入服务器：--go --address <host> --port <n>（--address 不接受 host:port 合写）
  - 开服：--server --world <abs> --gameid <id> --port <n> --logfile <file>
  - 服务端日志（logfile 中）玩家进出权威格式：
      ACTION[Server]: <名字> [<ip>] joins game. List of players: A, B
      ACTION[Server]: <名字> [<ip>] leaves game. List of players: A
    → 直接以 "List of players:" 后的全量名单为准，比逐条 join/leave 追踪可靠。
"""
from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import engine
from .api import ApiError, api
from .settings import DATA_DIR
from .worlds import WORLDS_ROOT, ensure_ascii_dir

IDLE, STARTING, RUNNING, STOPPING, ERROR = "idle", "starting", "running", "stopping", "error"

LOGS_DIR = DATA_DIR / "logs"
PLAYERS_MARK = "List of players:"


def detect_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def sanitize_player_name(name: str) -> str:
    """玩家名必须是 ASCII（Luanti Windows argv 窄字符限制）。

    保留字母数字下划线连字符；中文昵称等剔除，空则生成随机名。
    """
    import re
    out = re.sub(r"[^A-Za-z0-9_\-]", "", name or "").strip()[:20]
    if not out:
        out = f"player_{int(time.time()) % 10000:04d}"
    return out


def join_room(host: str, port: int, player_name: str = "") -> subprocess.Popen:
    """luanti.exe --go --address host --port port --name nick"""
    exe = engine.ensure_engine()
    args = [exe, "--go", "--address", str(host), "--port", str(int(port))]
    nick = sanitize_player_name(player_name)
    args += ["--name", nick]
    return subprocess.Popen(
        args, cwd=str(Path(exe).parent.parent),
        creationflags=0x00000008)  # DETACHED_PROCESS


class RoomHost:
    """本机开房：luanti --server + 注册/心跳。线程安全的单实例。"""

    def __init__(self) -> None:
        self.state = IDLE
        self.last_error: Optional[str] = None
        self.players: set[str] = set()
        self.log_lines: list[str] = []
        self.log_file: Optional[Path] = None
        self.room_name: str = ""      # 运行中的房间名（邀请好友用）
        self.port: int = 0
        self.on_state = None       # callable(state)
        self.on_log = None         # callable(line)
        self._proc: Optional[subprocess.Popen] = None
        self._room_token = ""
        self._hb_stop = threading.Event()
        self._tail_stop = threading.Event()
        self._lock = threading.Lock()

    def _set_state(self, s: str) -> None:
        self.state = s
        if self.on_state:
            self.on_state(s)

    def _log(self, line: str) -> None:
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > 60:
                del self.log_lines[: len(self.log_lines) - 60]
        if self.on_log:
            self.on_log(line)

    def start(self, room_name: str, world_dir_name: str, gameid: str,
              port: int = 30000, max_players: int = 8,
              is_private: bool = False, description: str = "") -> bool:
        if self.state in (STARTING, RUNNING):
            self.last_error = "已在开房中"
            return False
        self._set_state(STARTING)
        self.last_error = None
        self.room_name = room_name
        self.port = port
        try:
            exe = engine.ensure_engine()
            if gameid and not engine.has_game(gameid):
                # 游戏不显示在 UI：开房缺失时静默自动安装
                engine.install_game(gameid)
            engine.sync_mods()
            world_path = ensure_ascii_dir(WORLDS_ROOT / world_dir_name)
            if not world_path.exists():
                raise FileNotFoundError(f"存档不存在: {world_dir_name}")

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            logfile = LOGS_DIR / f"host_{time.strftime('%Y%m%d_%H%M%S')}.log"
            self.log_file = logfile

            self._proc = subprocess.Popen(
                [exe, "--server",
                 "--world", engine.engine_arg(world_path),
                 "--gameid", gameid, "--port", str(int(port)),
                 "--logfile", engine.engine_arg(logfile)],
                cwd=str(Path(exe).parent.parent),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            self._tail_stop.clear()
            threading.Thread(target=self._drain_stdout, daemon=True).start()
            threading.Thread(target=self._tail_log, args=(logfile,),
                             daemon=True).start()
            threading.Thread(target=self._wait_exit, daemon=True).start()
            self._set_state(RUNNING)
            self._log(f"[room] 服务端进程已启动 · 日志 {logfile.name}")

            if api.is_logged_in:
                try:
                    self._room_token = api.room_register({
                        "name": room_name,
                        "host": detect_lan_ip(),
                        "port": port,
                        "gameid": gameid,
                        "world": world_path.name,
                        "max_players": max_players,
                        "players": 0,
                        "has_password": False,
                        "private": is_private,
                        "engine": engine.installed_version() or "",
                        "protocol": 0,
                        "source": "launcher",
                        "description": description,
                    })
                    self._log("[room] 房间已上架社区服务器列表")
                    self._start_heartbeat()
                except ApiError as ex:
                    self._log(f"[room] 房间注册失败: {ex}（仍可局域网游玩）")
            return True
        except Exception as ex:  # noqa: BLE001 — 状态回传给 UI
            self.last_error = str(ex)
            self._set_state(ERROR)
            self._log(f"[room] 开房失败: {ex}")
            return False

    # ---------- 日志 ----------

    def _drain_stdout(self) -> None:
        """排空 stdout 管道（防止写满阻塞服务端）；日志以 logfile 为准。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for _ in proc.stdout:
                pass
        except (ValueError, OSError):
            pass

    def _tail_log(self, logfile: Path, poll: float = 0.4) -> None:
        """增量读取服务端日志文件，逐行交给 _on_line。"""
        offset = 0
        pending = ""
        while not self._tail_stop.is_set():
            try:
                if not logfile.exists():
                    time.sleep(poll)
                    continue
                with open(logfile, "rb") as f:
                    f.seek(offset)
                    data = f.read()
                    offset = f.tell()
            except OSError:
                time.sleep(poll)
                continue
            if not data:
                time.sleep(poll)
                continue
            text = pending + data.decode("utf-8", errors="replace")
            lines = text.split("\n")
            pending = lines.pop()  # 末尾可能是半行
            for line in lines:
                line = line.rstrip("\r")
                if line:
                    self._on_line(line)

    def _on_line(self, line: str) -> None:
        self._log(line)
        self._track_player(line)

    def _track_player(self, line: str) -> None:
        """以日志中 'List of players:' 的全量名单为准刷新在线玩家。"""
        idx = line.find(PLAYERS_MARK)
        if idx >= 0:
            rest = line[idx + len(PLAYERS_MARK):].strip()
            names = {n.strip() for n in rest.split(",") if n.strip()}
            with self._lock:
                self.players = names
            return
        # 兜底：个别版本/场景的逐条进出（英文日志恒定不本地化）
        low = line.lower()
        name = None
        if "join:" in low:
            name = line.split("join:", 1)[1].strip()
        elif "joins game" in low:
            name = line.split(" joins game", 1)[0].split(":")[-1].strip()
        elif "leave:" in low:
            name = line.split("leave:", 1)[1].strip()
        elif "leaves game" in low:
            name = line.split(" leaves game", 1)[0].split(":")[-1].strip()
        if not name:
            return
        with self._lock:
            if "leave" in low:
                self.players.discard(name)
            else:
                self.players.add(name)

    # ---------- 生命周期 ----------

    def _wait_exit(self) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.wait()
        if self.state == RUNNING:
            self._log("[room] 服务端进程已退出")
            self.stop(unregister=True)

    def _start_heartbeat(self) -> None:
        self._hb_stop.clear()

        def loop() -> None:
            while not self._hb_stop.wait(15):
                if self.state != RUNNING or not self._room_token:
                    continue
                try:
                    api.room_heartbeat(self._room_token, self.player_count)
                except ApiError:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    @property
    def player_count(self) -> int:
        with self._lock:
            return len(self.players)

    def stop(self, unregister: bool = True) -> None:
        if self.state == IDLE:
            return
        self._set_state(STOPPING)
        self._hb_stop.set()
        self._tail_stop.set()
        if unregister and self._room_token:
            try:
                api.room_unregister(self._room_token)
            except ApiError:
                pass
            self._room_token = ""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        with self._lock:
            self.players.clear()
        self._set_state(IDLE)


room_host = RoomHost()
