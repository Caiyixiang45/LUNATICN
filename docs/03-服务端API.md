# 03 服务端 API

社区服务端默认监听 `:8080`，全部接口前缀 `/api`。请求与响应均为 JSON（上传/下载除外），字段统一 snake_case。

## 通用约定

- 认证：`Authorization: Bearer <token>`，令牌由登录/注册返回，有效期见 `token_ttl_minutes`。
- 错误响应：`{"error": "中文错误说明"}`，状态码 `400 / 401 / 404 / 409 / 500`。
- 未特别说明时，匿名可访问房间列表与分享包检索；其余接口需登录。

## 一、健康检查

### GET /api/health

匿名。`200` 返回 `{"status":"ok"}`。

## 二、账号认证

### POST /api/auth/register

```json
{ "username": "player01", "password": "secret6", "nickname": "小明" }
```

- 用户名 3-24 字符，仅小写字母、数字、下划线、连字符（服务端自动转小写）。
- 密码至少 6 位，argon2id 哈希存储。
- 昵称可空，空则取用户名。

`201`：

```json
{ "token": "<jwt>", "user": { "id": "...", "username": "player01", "nickname": "小明", "created_at": "..." } }
```

### POST /api/auth/login

```json
{ "username": "player01", "password": "secret6" }
```

`200` 同注册响应；`401` 用户名或密码错误。

### POST /api/auth/refresh

Header 带旧令牌。`200`：`{ "token": "<新令牌>", "user_id": "..." }`。

### GET /api/me

需登录。`200`：用户对象（id/username/nickname/created_at）。

### PATCH /api/me

```json
{ "nickname": "新昵称", "password": "新密码" }
```

两项均可选，非空才更新。`200` 返回用户对象。

## 三、好友

### GET /api/friends

`200`：`{ "friends": [用户对象...] }`

### POST /api/friends/request

```json
{ "username": "player02" }
```

或 `{ "user_id": "<id>" }`。`200`：`{"status":"ok"}`；`404` 用户不存在；`400` 不能添加自己/重复申请。

### GET /api/friends/requests

`200`：

```json
{
  "incoming": [ { "user": {...}, "direction": "in",  "created_at": "..." } ],
  "outgoing": [ { "user": {...}, "direction": "out", "created_at": "..." } ]
}
```

### POST /api/friends/respond

```json
{ "from": "<对方用户 id>", "accept": true }
```

`200`：`{"status":"ok"}`。

### DELETE /api/friends/{id}

删除好友关系。`200`：`{"status":"ok"}`。

## 四、房间（注册中心）

### GET /api/rooms

匿名可访问；带登录令牌时私密房间按好友关系过滤（私密房间仅房主与其好友可见）。

`200`：

```json
{
  "rooms": [
    {
      "id": "...", "name": "周末联机", "owner": "<uid>", "owner_name": "小明",
      "host": "203.0.113.5", "port": 30000, "gameid": "minetest",
      "world": "myworld", "max_players": 8, "players": 3,
      "has_password": false, "private": false, "engine": "5.16.1",
      "source": "launcher", "description": "生存档", "protocol": 1
    }
  ]
}
```

`source` 取值：`launcher`（玩家开房）、`fixed`（官方固定服）、`roomd`（外部房间服务器）。

### POST /api/room/register

需登录。注册或续期房间：

```json
{
  "token": "可选，已有房间则凭它续期",
  "name": "周末联机", "host": "203.0.113.5", "port": 30000,
  "gameid": "minetest", "world": "myworld",
  "max_players": 8, "players": 3,
  "has_password": false, "private": false,
  "engine": "5.16.1", "protocol": 1,
  "source": "launcher", "description": "生存档"
}
```

`200`：`{ "room": {...}, "room_token": "<用于心跳/注销的令牌>" }`

### POST /api/room/heartbeat

```json
{ "token": "<room_token>", "players": 3 }
```

默认超过若干个心跳周期未续期的房间会被清扫并广播下线。

### POST /api/room/unregister

```json
{ "token": "<room_token>" }
```

### GET /api/servers

固定服务器列表：

```json
{ "servers": [ { "name": "官方一服", "port": 30000, "running": true } ] }
```

## 五、WebSocket 推送

### GET /api/ws

升级 WebSocket。连接后先收到当前房间全量帧；之后出现下列事件时向所有连接推送：

```json
{ "type": "rooms" }    // 房间列表有变化（注册、人数变化、注销、超时清扫）
{ "type": "notice" }   // 公告或客户端更新推送有变化
```

客户端收到 `rooms` 后重新请求 `GET /api/rooms`；收到 `notice` 后重新请求公告与更新接口。

## 六、公告与客户端更新推送

### GET /api/announcements

匿名。公告列表（置顶优先、按时间倒序）：

```json
{ "announcements": [ { "id": "...", "title": "维护通知", "body": "周日凌晨 2 点维护", "level": "info", "pinned": true, "created_at": "..." } ] }
```

`level`：`info` | `warning` | `update`。

### POST /api/announcements

需管理头 `X-Admin-Token: <config.json 的 admin_token>`：

```json
{ "title": "维护通知", "body": "周日凌晨 2 点维护", "level": "warning", "pinned": true }
```

`201` 返回公告对象，并向全部 WebSocket 连接推送 `{"type":"notice"}`。

### DELETE /api/announcements/{id}

需管理头。`200`：`{"deleted": "<id>"}`；同时推送 `notice`。

### GET /api/client-update?version=1.0.0

匿名。服务端比对 `version` 与已配置的最新版本：

```json
{ "has_update": true, "current": "1.0.0", "latest": "1.1.0", "notes": "更新说明", "mirrors": ["https://…/client.zip"], "published_at": "..." }
```

### PUT /api/client-update

需管理头：

```json
{ "version": "1.1.0", "notes": "更新说明", "mirrors": ["https://gh-proxy.com/…", "https://ghproxy.net/…"] }
```

`mirrors` 按顺序作为客户端下载兜底链。修改后推送 `notice`。

## 七、分享包（工坊）

### GET /api/packages

参数：

| 参数 | 说明 |
|------|------|
| `type` | `map` 或 `mod`，空为全部 |
| `q` | 关键词，匹配名称与简介 |
| `limit` | 默认 20，最大 100 |
| `offset` | 分页偏移 |

`200`：

```json
{
  "total": 42,
  "packages": [ { "id": "...", "type": "map", "name": "雪山地图", "author_name": "小明", "version": "1.0.0", "description": "...", "size": 1048576, "downloads": 12, "created_at": "..." } ]
}
```

### GET /api/packages/mine

需登录。我上传的包，`200`：`{ "packages": [...] }`

### GET /api/packages/{id}

包详情（PackageMeta 完整字段，含 `depends`、`engine`、`file_name`、`thumbnail`）。

### POST /api/packages

需登录，`multipart/form-data`：

- `file`：必填，`.lnpkg` 或 zip，请求体上限 640MB。
- `thumbnail`：可选，PNG 缩略图。

`201` 返回 PackageMeta。

### GET /api/packages/{id}/download

返回二进制流，`Content-Disposition: attachment`，成功后 `downloads` 计数 +1。

### GET /api/packages/{id}/thumbnail

返回 PNG 缩略图。

### DELETE /api/packages/{id}

仅作者本人。`200`：`{"status":"ok"}`。

## 八、请求示例（PowerShell）

> 注意：PS 5.1 传中文 body 必须用 `\uXXXX` 转义，否则会变问号。

```powershell
# 注册（中文昵称转义为 小明）
$body = '{"username":"player01","password":"secret6","nickname":"\u5c0f\u660e"}'
Invoke-RestMethod -Uri http://localhost:8080/api/auth/register -Method Post `
  -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))

# 带令牌访问
Invoke-RestMethod -Uri http://localhost:8080/api/rooms -Headers @{ Authorization = "Bearer $token" }
```
