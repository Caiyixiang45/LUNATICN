# 06 GitHub 接入与部署

## 一、仓库布局

| 仓库 | 可见性 | 内容 | 远端 |
|------|--------|------|------|
| `Caiyixiang45/LUNATICN` | 公开 | 仅 roomd 独立房间服务器 + README | https://github.com/Caiyixiang45/LUNATICN |
| `Caiyixiang45/LUNATICN-server` | 私有 | 完整项目（启动器 + 社区服务端 + 文档） | https://github.com/Caiyixiang45/LUNATICN-server |
| `Caiyixiang45/LUNATICN-archive-old` | 私有 | 旧仓库改名归档，保留历史 | 原仓库地址 |

边界规则：

- 公开仓只有 roomd；任何账号逻辑、部署脚本、密钥、启动器源码都不得进入公开仓。
- 两仓共用同一套编码与禁词规则，提交前必须过禁词扫描。
- 仓库描述与 README 一律不含违禁词。

## 二、凭据

- PAT 保存在 **Windows 凭据管理器**（`git credential-manager`），不写入任何文件：
  - 主机：`github.com`，凭据含 PAT。
  - PAT 权限：`repo`（读写）。无 `delete_repo` 权限，删除/改名仓库需网页操作。
- 克隆私有仓首次推送会弹凭据窗口；本机已保存则静默通过。

## 三、日常推送

```powershell
# 完整项目（私有）
cd E:\LUNATICN
git add -A
git commit -m "feat: xxx"
git push origin main

# roomd（公开）
cd E:\LUNATICN-roomd
git add -A
git commit -m "docs: xxx"
git push origin main
```

提交前检查清单：

1. `git status` 无意外文件（config.json、data/、bin/、obj/ 不入库）；
2. 禁词扫描通过；
3. 新增文件为 UTF-8 无 BOM。

## 四、禁词扫描（码点构造，不打印原词）

```powershell
# 用码点构造检测词，避免脚本源码中出现原词
$w = [string]::new([char]0x8FF7, [char]0x4F60, [char]0x4E16, [char]0x754C)
$roots = 'E:\LUNATICN', 'E:\LUNATICN-roomd'
$hits = @()
foreach ($r in $roots) {
  Get-ChildItem -Recurse -File $r |
    Where-Object { $_.FullName -notmatch '\\(\.git|bin|obj)\\' -and $_.Length -lt 2MB } |
    ForEach-Object {
      $t = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)
      if ($t.Contains($w)) { $hits += $_.FullName }
    }
}
if ($hits.Count) { $hits; exit 1 } else { 'ALL_REPOS_CLEAN' }
```

> 扫描输出只打印命中文件路径，不打印词本身。

## 五、社区服务端部署（Windows）

### 1. 构建

```powershell
cd E:\LUNATICN\server
& "C:\Program Files\dotnet\dotnet.exe" --version   # 确认 SDK
go build -o dist\lunaticn-server.exe .\cmd\server
```

### 2. 配置

```powershell
Copy-Item config.example.json config.json
# 编辑 config.json：
#   listen        ":8080"
#   jwt_secret    换成 >=32 字节随机串
#   public_base   实际对外地址
#   fixed_servers 固定服列表
```

`config.json` 已被 `.gitignore` 排除，绝不入库。

### 3. 作为计划任务自启动

```powershell
$exe = 'E:\LUNATICN\server\dist\lunaticn-server.exe'
$action  = New-ScheduledTaskAction -Execute $exe -Argument '-config config.json' `
           -WorkingDirectory 'E:\LUNATICN\server'
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
Register-ScheduledTask -TaskName 'LUNATICN-Server' -Action $action `
  -Trigger $trigger -Principal $principal -Description 'LUNATICN 社区服务端'
```

启动/停止：

```powershell
Start-ScheduledTask -TaskName 'LUNATICN-Server'
Stop-ScheduledTask  -TaskName 'LUNATICN-Server'
```

### 4. 防火墙

```powershell
New-NetFirewallRule -DisplayName 'LUNATICN-Server' -Direction Inbound `
  -Protocol TCP -LocalPort 8080 -Action Allow
```

## 六、roomd 部署（独立）

roomd 可脱离社区服务端单机运行，也可注册到注册中心：

```powershell
cd E:\LUNATICN-roomd
go build -o roomd.exe .
Copy-Item config.example.json config.json
# registry 填社区服务端地址，留空则纯单机
.\roomd.exe -config config.json
```

配置项：`registry / username / password / room_name / luanti_path / world / worldname / gameid / port / max_players / host / has_password / private / description`。

作为计划任务自启的方式与服务端相同（任务名 `LUNATICN-Roomd`）。

## 七、启动器分发

```powershell
cd E:\LUNATICN\launcher
& "C:\Program Files\dotnet\dotnet.exe" build LUNATICN.sln -c Release
# 产物：LUNATICN\bin\x64\Release\net9.0-windows10.0.19041.0\publish\
```

- 未打包运行（`WindowsPackageType=None`）：拷贝目录即用。
- 首次运行自动下载引擎到 `data/engine/`，需网络可达 GitHub Releases。

## 八、首次接入某台新机器

1. 安装 Go 1.23+、.NET SDK 9、Git；
2. `git clone https://github.com/Caiyixiang45/LUNATICN-server.git`（输入 PAT 完成凭据保存）；
3. 按第五节部署服务端；
4. 按第七节构建启动器；
5. 跑一次禁词扫描确认 `ALL_REPOS_CLEAN`。
