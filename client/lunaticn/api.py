"""与 LUNATICN 社区服务端通信的 HTTP 客户端（同步，本地服务足够快）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import requests

from . import settings


class ApiError(Exception):
    """服务端返回的业务错误（message 已提取中文 error 字段）。"""


class Api:
    def __init__(self) -> None:
        cfg = settings.load()
        self.base_url: str = cfg["server_url"].rstrip("/")
        self.on_expired = None  # 401 时通知 UI
        self.session = requests.Session()
        self._token: str = cfg.get("token") or ""
        self.user: Optional[dict] = None
        self.on_auth_changed = None  # callable

    # ---------- 账号 ----------

    @property
    def is_logged_in(self) -> bool:
        return bool(self._token) and self.user is not None

    def register(self, username: str, password: str, nickname: str) -> dict:
        data = self._post("/api/auth/register", {
            "username": username, "password": password, "nickname": nickname,
        })
        return self._adopt_login(data)

    def login(self, username: str, password: str) -> dict:
        data = self._post("/api/auth/login", {"username": username, "password": password})
        return self._adopt_login(data)

    def _adopt_login(self, data: dict) -> dict:
        self._token = data["token"]
        settings.set_token(self._token)
        self.user = self._get("/api/me")
        if self.on_auth_changed:
            self.on_auth_changed()
        return self.user

    def health(self) -> dict:
        return self._get("/api/health") or {}

    def ws_url(self) -> str:
        base = self.base_url.replace("https://", "wss://").replace(
            "http://", "ws://")
        if self._token:
            return base + "/api/ws?token=" + self._token
        return base + "/api/ws"

    def update_profile(self, nickname: str = "", password: str = "") -> dict:
        body: dict = {}
        if nickname:
            body["nickname"] = nickname
        if password:
            body["password"] = password
        return self._request("PATCH", "/api/me", json=body) or {}

    def logout(self) -> None:
        self._token = ""
        self.user = None
        settings.set_token("")
        if self.on_auth_changed:
            self.on_auth_changed()

    def restore_session(self) -> bool:
        if not self._token:
            return False
        try:
            self.user = self._get("/api/me")
        except ApiError:
            self._token = ""
            settings.set_token("")
            return False
        if self.on_auth_changed:
            self.on_auth_changed()
        return True

    # ---------- 房间 ----------

    def rooms(self) -> list[dict]:
        return (self._get("/api/rooms") or {}).get("rooms") or []

    def servers(self) -> list[dict]:
        return (self._get("/api/servers") or {}).get("servers") or []

    def room_register(self, info: dict) -> str:
        data = self._post("/api/room/register", info)
        return data.get("room_token") or data.get("roomToken") or ""

    def room_heartbeat(self, room_token: str, players: int) -> None:
        self._post("/api/room/heartbeat", {"token": room_token, "players": players})

    def room_unregister(self, room_token: str) -> None:
        self._post("/api/room/unregister", {"token": room_token})

    # ---------- 好友 ----------

    def friends(self) -> list[dict]:
        return (self._get("/api/friends") or {}).get("friends") or []

    def friend_request(self, username: str) -> None:
        self._post("/api/friends/request", {"username": username})

    def friend_requests(self) -> tuple[list[dict], list[dict]]:
        data = self._get("/api/friends/requests") or {}
        return data.get("incoming") or [], data.get("outgoing") or []

    def friend_respond(self, from_user_id: str, accept: bool) -> None:
        self._post("/api/friends/respond", {"from": from_user_id, "accept": accept})

    def friend_remove(self, friend_id: str) -> None:
        self._delete(f"/api/friends/{friend_id}")

    # ---------- 聊天与邀请 ----------

    def chat_history(self, peer_id: str, before_id: int = 0,
                     limit: int = 50) -> list[dict]:
        """与 peer 的私聊历史（按时间升序）。"""
        params: dict = {"limit": limit}
        if before_id:
            params["before"] = before_id
        data = self._get(f"/api/chat/{peer_id}", params=params) or {}
        return data.get("messages") or []

    def chat_send(self, peer_id: str, text: str) -> int:
        """发送私聊消息，返回消息 id。"""
        data = self._post(f"/api/chat/{peer_id}", {"text": text}) or {}
        return int(data.get("id") or 0)

    def invite_to_room(self, user_id: str, room_name: str) -> None:
        """邀请好友加入自己运行中的房间（对方会收到 WS 邀请）。"""
        self._post("/api/invite", {"user_id": user_id, "room": room_name})

    # ---------- 工坊 ----------

    def search_packages(self, pkg_type: str = "", query: str = "",
                        limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
        data = self._get("/api/packages", params={
            "type": pkg_type, "q": query, "limit": limit, "offset": offset,
        }) or {}
        return data.get("total") or 0, data.get("packages") or []

    def my_packages(self) -> list[dict]:
        return (self._get("/api/packages/mine") or {}).get("packages") or []

    def upload_package(self, file_path: str,
                       thumbnail_path: Optional[str] = None) -> dict:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
            if thumbnail_path and os.path.exists(thumbnail_path):
                with open(thumbnail_path, "rb") as t:
                    files["thumbnail"] = (os.path.basename(thumbnail_path), t, "image/png")
                    return self._request("POST", "/api/packages", files=files)
            return self._request("POST", "/api/packages", files=files)

    def download_package(self, package_id: str, dest_path: str) -> str:
        resp = self.session.get(
            f"{self.base_url}/api/packages/{package_id}/download",
            headers=self._auth_headers(), stream=True, timeout=(15, 300),
        )
        if resp.status_code != 200:
            raise ApiError(f"下载失败: {resp.status_code}")
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(1 << 18):
                f.write(chunk)
        return dest_path

    def delete_package(self, package_id: str) -> None:
        self._delete(f"/api/packages/{package_id}")

    # ---------- 模组源 ----------

    def list_remote_mods(self, base: str = "", *, page: int = 0,
                         per: int = 0, q: str = "") -> dict:
        """社区自托管模组仓库列表（默认本服务端，可指定镜像地址）。

        page/per>0 时按页获取；返回 {mods, total, page, per_page, pages}。
        旧服务端不带分页参数返回全量，此时按 pages=1 补全字段。
        """
        params: dict = {}
        if page > 0 and per > 0:
            params.update({"page": page, "per_page": per})
        if q:
            params["q"] = q
        if base:
            resp = self.session.get(base.rstrip("/") + "/api/mods",
                                    params=params, timeout=(10, 30))
            if resp.status_code != 200:
                raise ApiError(f"模组源获取失败: {resp.status_code}")
            data = resp.json() or {}
        else:
            data = self._get("/api/mods", params) or {}
        mods = data.get("mods") or []
        if "total" not in data:
            data = {"mods": mods, "total": len(mods), "page": 1,
                    "per_page": len(mods), "pages": 1}
        return data

    def download_remote_mod(self, filename: str, dest_path: str) -> str:
        """下载自托管仓库中的模组 zip。"""
        resp = self.session.get(
            f"{self.base_url}/api/mods/{filename}",
            headers=self._auth_headers(), stream=True, timeout=(15, 300),
        )
        if resp.status_code != 200:
            raise ApiError(f"下载失败: {resp.status_code}")
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(1 << 18):
                f.write(chunk)
        return dest_path

    def cdb_search_mods(self, query: str = "", sort: str = "",
                        base: str = "", page: int = 1,
                        per: int = 20) -> dict:
        """ContentDB 模组查询（经自家服务端代理分页，默认只列适配当前
        游戏的模组）。

        sort: 排序（downloads / score / name，空为默认序）。
        base: 代理地址（空则默认自家服务端）。
        返回 {mods, total, page, per_page, pages}，mods 为规范化行数据。
        """
        from . import engine
        params: dict = {"page": max(1, page), "per_page": max(1, per)}
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        gk = engine.CDB_GAME_KEYS.get(engine.DEFAULT_GAME)
        if gk:
            params["game"] = gk
        root = base.rstrip("/") if base else self.base_url
        resp = self.session.get(root + "/api/cdb/mods", params=params,
                                timeout=(10, 90))
        if resp.status_code != 200:
            raise ApiError(f"ContentDB 查询失败: {resp.status_code}")
        data = resp.json() or {}
        rows: list[dict] = []
        for it in data.get("mods") or []:
            if not isinstance(it, dict):
                continue
            author = it.get("author")
            author_name = (author.get("name") if isinstance(author, dict)
                           else str(author or ""))
            rows.append({
                "author": author_name,
                "name": str(it.get("name") or ""),
                "title": str(it.get("title") or it.get("name") or ""),
                "description": str(it.get("short_description")
                                   or it.get("summary") or ""),
                "thumbnail": str(it.get("thumbnail") or ""),
            })
        data["mods"] = rows
        return data

    def cdb_download_mod(self, author: str, name: str, dest_path: str) -> str:
        """下载 ContentDB 最新 release 的模组 zip。"""
        from . import download, engine
        release, _title = engine._cdb_latest_release(author, name)
        if release <= 0:
            raise ApiError(f"ContentDB 上找不到模组 {name}")
        urls = [engine._cdb_release_url(base, author, name, release)
                for base in engine.CONTENTDB_MIRRORS]
        download.fetch(urls, Path(dest_path))
        return dest_path

    # ---------- 公告与客户端更新推送 ----------

    def announcements(self) -> list[dict]:
        """公告列表（公开接口，无需登录）。"""
        return (self._get("/api/announcements") or {}).get("announcements") or []

    def client_update_info(self) -> dict:
        """检查客户端更新（公开接口，服务端比对版本后返回 has_update）。"""
        return self._get("/api/client-update", params={
            "version": settings.CLIENT_VERSION}) or {}

    def _admin_headers(self) -> dict:
        tok = settings.get("admin_token") or ""
        return {"X-Admin-Token": tok} if tok else {}

    def create_announcement(self, title: str, body: str,
                            level: str = "info", pinned: bool = False) -> dict:
        """发布公告（需服务端 config.json 的 admin_token）。"""
        return self._request("POST", "/api/announcements", json={
            "title": title, "body": body, "level": level, "pinned": pinned,
        }, headers=self._admin_headers())

    def delete_announcement(self, ann_id: str) -> None:
        self._request("DELETE", f"/api/announcements/{ann_id}",
                      headers=self._admin_headers())

    def set_client_update(self, version: str, notes: str,
                          mirrors: list[str]) -> dict:
        """推送客户端更新（需 admin_token）。"""
        return self._request("PUT", "/api/client-update", json={
            "version": version, "notes": notes, "mirrors": mirrors,
        }, headers=self._admin_headers())

    # ---------- HTTP 底层 ----------

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    @staticmethod
    def _extract_error(text: str) -> str:
        try:
            import json
            return json.loads(text).get("error", text)
        except Exception:
            return text

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self.base_url + path
        headers = dict(self._auth_headers())
        headers.update(kwargs.pop("headers", None) or {})
        kwargs.setdefault("timeout", (10, 60))
        try:
            resp = self.session.request(method, url,
                                        headers=headers, **kwargs)
        except requests.RequestException as ex:
            raise ApiError(f"无法连接服务器: {ex}") from ex
        if resp.status_code == 401 and self._token:
            self.logout()
            if self.on_expired:
                self.on_expired()
            raise ApiError("登录已过期，请重新登录")
        if resp.status_code >= 400:
            raise ApiError(f"{resp.status_code}: {self._extract_error(resp.text)}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as ex:
            raise ApiError(f"响应解析失败: {ex}") from ex

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict | None = None) -> Any:
        return self._request("POST", path, json=body)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)


api = Api()
