using System.Diagnostics;
using System.Net;
using System.Net.Sockets;

namespace Lunaticn.Services;

/// <summary>房主开服状态。</summary>
public enum HostState
{
    Idle,
    Starting,
    Running,
    Stopping,
    Error,
}

/// <summary>
/// 房主开服：在本机拉起 luanti --server，注册到社区服务器并维持心跳。
/// 退出房间时自动注销。
/// </summary>
public sealed class RoomHostService : IDisposable
{
    private readonly EngineManager _engine;
    private readonly ApiClient _api;
    private Process? _proc;
    private Timer? _heartbeat;
    private string? _roomToken;
    private readonly HashSet<string> _players = new();
    private readonly object _lock = new();

    public HostState State { get; private set; } = HostState.Idle;
    public string? LastError { get; private set; }
    public int Players { get { lock (_lock) return _players.Count; } }

    public event Action<HostState>? StateChanged;
    public event Action<string>? LineLogged;

    public RoomHostService(EngineManager engine, ApiClient api)
    {
        _engine = engine;
        _api = api;
    }

    private void SetState(HostState s)
    {
        State = s;
        StateChanged?.Invoke(s);
    }

    /// <summary>探测本机局域网 IP（UDP 假连接不发包）。</summary>
    public static string DetectLanIp()
    {
        try
        {
            using var s = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            s.Connect("8.8.8.8", 53);
            return (s.LocalEndPoint as IPEndPoint)?.Address.ToString() ?? "127.0.0.1";
        }
        catch { return "127.0.0.1"; }
    }

    /// <summary>
    /// 开房：启动引擎服务端进程 → 注册房间 → 开始心跳。
    /// </summary>
    public async Task<bool> StartAsync(
        string roomName, string worldDirName, string gameId,
        int port, int maxPlayers, bool hasPassword, bool isPrivate,
        string description, string? host = null, CancellationToken ct = default)
    {
        if (State is HostState.Starting or HostState.Running)
        {
            LastError = "已在开房中";
            return false;
        }
        SetState(HostState.Starting);
        LastError = null;

        try
        {
            var exe = await _engine.EnsureEngineAsync(null, ct);

            // 1. 启动服务端进程
            var worldPath = Path.Combine(new WorldService().WorldsRoot, worldDirName);
            if (!Directory.Exists(worldPath))
                throw new DirectoryNotFoundException($"存档不存在: {worldDirName}");

            var psi = new ProcessStartInfo
            {
                FileName = exe,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                WorkingDirectory = Path.GetDirectoryName(exe)!,
            };
            psi.ArgumentList.Add("--server");
            psi.ArgumentList.Add("--world"); psi.ArgumentList.Add(worldPath);
            psi.ArgumentList.Add("--gameid"); psi.ArgumentList.Add(gameId);
            psi.ArgumentList.Add("--port"); psi.ArgumentList.Add(port.ToString());

            _proc = Process.Start(psi) ?? throw new InvalidOperationException("进程启动失败");
            _proc.OutputDataReceived += (_, e) => OnOutput(e.Data, join: true);
            _proc.ErrorDataReceived += (_, e) => OnOutput(e.Data, join: false);
            _proc.BeginOutputReadLine();
            _proc.BeginErrorReadLine();
            _proc.EnableRaisingEvents = true;
            _proc.Exited += (_, _) =>
            {
                _ = StopAsync(unregister: true);
                LineLogged?.Invoke("[room] 服务端进程已退出");
            };

            SetState(HostState.Running);

            // 2. 注册到社区服务器
            if (_api.IsLoggedIn)
            {
                var info = new
                {
                    name = roomName,
                    host = host ?? DetectLanIp(),
                    port,
                    gameid = gameId,
                    world = worldDirName,
                    max_players = maxPlayers,
                    has_password = hasPassword,
                    @private = isPrivate,
                    source = "launcher",
                    description,
                };
                var reg = await _api.RegisterRoomAsync(info);
                if (reg.Success)
                {
                    _roomToken = reg.Data;
                    LineLogged?.Invoke("[room] 房间已上架社区服务器列表");
                    StartHeartbeat();
                }
                else
                {
                    LineLogged?.Invoke($"[room] 房间注册失败: {reg.Error}（仍可局域网游玩）");
                }
            }
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            SetState(HostState.Error);
            LineLogged?.Invoke($"[room] 开房失败: {ex.Message}");
            return false;
        }
    }

    private void OnOutput(string? line, bool join)
    {
        if (line is null) return;
        LineLogged?.Invoke(line);

        // 解析玩家进出
        var lower = line.ToLowerInvariant();
        string? name = null;
        if (lower.Contains("join:")) name = AfterMarker(line, "join:");
        else if (lower.Contains("joins game")) name = BeforeMarker(line, " joins game");
        else if (lower.Contains("leave:")) name = AfterMarker(line, "leave:");
        else if (lower.Contains("leaves game")) name = BeforeMarker(line, " leaves game");
        if (name is null) return;

        lock (_lock)
        {
            if (lower.Contains("leave") || lower.Contains("left the game"))
                _players.Remove(name);
            else
                _players.Add(name);
        }
    }

    private static string? AfterMarker(string line, string marker)
    {
        var i = line.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        return i < 0 ? null : line[(i + marker.Length)..].Trim();
    }

    private static string? BeforeMarker(string line, string marker)
    {
        var i = line.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        return i < 0 ? null : line[..i].Replace("*", "").Trim();
    }

    private void StartHeartbeat()
    {
        _heartbeat = new Timer(async _ =>
        {
            if (_roomToken is null || State != HostState.Running) return;
            await _api.HeartbeatAsync(_roomToken, Players);
        }, null, TimeSpan.FromSeconds(15), TimeSpan.FromSeconds(15));
    }

    /// <summary>停止开房（注销房间 + 结束进程）。</summary>
    public async Task StopAsync(bool unregister = true)
    {
        if (State == HostState.Idle) return;
        SetState(HostState.Stopping);

        if (_heartbeat is not null)
        {
            await _heartbeat.DisposeAsync();
            _heartbeat = null;
        }

        if (unregister && _roomToken is not null)
        {
            await _api.UnregisterRoomAsync(_roomToken);
            _roomToken = null;
        }

        try
        {
            if (_proc is { HasExited: false })
            {
                _proc.Kill(entireProcessTree: true);
                await _proc.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
            }
        }
        catch { }
        finally
        {
            _proc?.Dispose();
            _proc = null;
            lock (_lock) _players.Clear();
            SetState(HostState.Idle);
        }
    }

    public void Dispose()
    {
        _heartbeat?.Dispose();
        try { _proc?.Kill(entireProcessTree: true); } catch { }
        _proc?.Dispose();
    }
}

/// <summary>加入房间：启动客户端连接到远端地址。</summary>
public sealed class JoinService
{
    private readonly EngineManager _engine;
    private Process? _proc;

    public event Action<string>? LineLogged;

    public JoinService(EngineManager engine) => _engine = engine;

    /// <summary>连接房间：luanti.exe --go --address host:port</summary>
    public async Task<bool> JoinAsync(string host, int port, string playerName,
        CancellationToken ct = default)
    {
        var exe = await _engine.EnsureEngineAsync(null, ct);

        var psi = new ProcessStartInfo
        {
            FileName = exe,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = Path.GetDirectoryName(exe)!,
        };
        psi.ArgumentList.Add("--go");
        psi.ArgumentList.Add("--address"); psi.ArgumentList.Add($"{host}:{port}");
        if (!string.IsNullOrWhiteSpace(playerName))
        {
            psi.ArgumentList.Add("--name"); psi.ArgumentList.Add(playerName);
        }

        _proc = Process.Start(psi) ?? throw new InvalidOperationException("客户端启动失败");
        _proc.OutputDataReceived += (_, e) => { if (e.Data is not null) LineLogged?.Invoke(e.Data); };
        _proc.BeginOutputReadLine();
        _proc.EnableRaisingEvents = true;
        _proc.Exited += (_, _) => LineLogged?.Invoke("[client] 游戏已退出");
        return true;
    }

    public void StopGame()
    {
        try { _proc?.Kill(entireProcessTree: true); } catch { }
        _proc?.Dispose();
        _proc = null;
    }
}
