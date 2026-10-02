# LUNATICN

基于 [Luanti](https://luanti.org) 引擎二次封装的沙盒游戏平台，提供联机大厅、存档管理、模组管理、地图与模组分享等完整功能。

## 项目组成

| 目录 | 技术栈 | 说明 |
|------|--------|------|
| `client/` | Python 3.13 + DearPyGui | 客户端：登录、联机大厅、存档库、模组中心、工坊、好友、设置（毛玻璃 UI） |
| `server/` | Go | 独立服务端：账号认证、房间大厅、地图/模组分享、固定服务器守护、好友、公告与客户端更新推送 |
| `launcher/` | C# WPF (.NET SDK 9) | 旧版客户端（保留备选） |
| `docs/` | Markdown（中文） | 总体规划、架构设计、API 文档、联机流程、分享包格式 |

## 核心功能

- **模组管理**：本地模组库安装/卸载/启用，依赖自动解析，按存档读写 `world.mt`
- **联机**：房主开服制 + 官方固定服务器制，房间列表实时刷新（WebSocket），好友邀请
- **存档**：世界的新建/进入/复制/导出/删除；主游戏为 Mineclonia（ContentDB 安装）
- **分享**：地图与模组打包上传（`.lnpkg`）、浏览搜索、一键下载
- **引擎托管**：多镜像兜底下载官方 Luanti 便携版（GitHub 直连失败自动切 gh-proxy / ghproxy.net），零修改引擎源码；游戏经 ContentDB 安装
- **公告与更新推送**：服务端发布公告/新版本，WebSocket 实时推送给在线客户端，更新包多下载源逐个兜底

## 快速开始

### 服务端（Go）

```powershell
cd server
go run ./cmd/server -config config.json
```

### 客户端（Python 3.13）

```powershell
cd client
py -3.13 -m pip install -r requirements.txt
py -3.13 main.py
```

> 必须使用 Python 3.13（dearpygui 在 3.14 上崩溃）。

## 文档

- [01 总体规划](docs/01-总体规划.md)
- [02 架构设计](docs/02-架构设计.md)
- [03 服务端 API](docs/03-服务端API.md)
- [04 联机流程](docs/04-联机流程.md)
- [05 分享包格式](docs/05-分享包格式.md)
- [06 GitHub 接入与部署](docs/06-GitHub接入与部署.md)

## 许可证

MIT（Luanti 引擎本身为 LGPL-2.1，本项目不修改引擎源码，引擎由用户首次运行时自动下载）
