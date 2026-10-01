# LUNATICN roomd

独立轻量房间服务器。玩家在自己电脑上运行它即可开设一个 Luanti 房间，并自动上架到 LUNATICN 社区服务器列表。

## 功能

- 一键拉起本机 `luanti --server` 进程
- 登录 LUNATICN 社区服务器，房间自动注册到服务器列表
- 每 15 秒心跳上报在线人数，房间下线自动从列表移除
- 从进程输出解析玩家加入/离开，实时统计人数
- 退出（Ctrl+C 或进程结束）自动注销房间

## 使用

1. 复制配置样例：

```powershell
copy config.example.json config.json
```

2. 编辑 `config.json`（UTF-8 编码）：

| 字段 | 说明 |
|------|------|
| `registry` | 社区服务器地址 |
| `username` / `password` | 社区账号 |
| `room_name` | 房间显示名 |
| `luanti_path` | 本机 luanti.exe 路径 |
| `worldname` / `world` | 世界名或世界路径（二选一） |
| `gameid` | 游戏 ID |
| `port` | 游戏端口（默认 30000） |
| `max_players` | 人数上限 |
| `host` | 对外地址，留空自动探测局域网 IP |
| `private` | true 时仅好友可见 |

3. 运行：

```powershell
go run . -config config.json
```

或编译后运行：

```powershell
go build -o roomd.exe .
.\roomd.exe -config config.json
```

## 网络说明

- 局域网内其他玩家直接可连
- 公网游玩需在路由器为 `port` 端口做端口映射（UDP），并把 `host` 填为公网 IP

## 编码

所有文本文件均为 UTF-8。如用记事本编辑 `config.json`，请另存为"UTF-8"而非"ANSI"。

## License

MIT
