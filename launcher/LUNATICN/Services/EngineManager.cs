using System.Diagnostics;
using System.IO.Compression;
using System.Text.Json;

namespace Lunaticn.Services;

/// <summary>
/// Luanti 引擎托管：检测、自动下载（aria2c）、解压、版本管理。
/// 引擎目录结构：
///   data/engine/&lt;version&gt;/bin/luanti.exe
///   data/engine/current.json   记录当前使用版本
/// </summary>
public sealed class EngineManager
{
    /// <summary>aria2c 路径（用于下载，禁证书校验参数在启动参数中指定）。</summary>
    public string Aria2Path { get; set; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Programs", "Motrix", "resources", "engine", "aria2c.exe");

    public string EngineRoot { get; }

    /// <summary>下载进度回调（0-100，-1 表示不确定）。</summary>
    public event Action<int>? ProgressChanged;

    /// <summary>状态文本回调（供 UI 显示）。</summary>
    public event Action<string>? StatusChanged;

    public EngineManager(string? dataDir = null)
    {
        EngineRoot = Path.Combine(dataDir ?? "data", "engine");
    }

    /// <summary>已安装引擎版本。</summary>
    public string? InstalledVersion
    {
        get
        {
            var marker = Path.Combine(EngineRoot, "current.json");
            if (!File.Exists(marker)) return null;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(marker));
                return doc.RootElement.GetProperty("version").GetString();
            }
            catch { return null; }
        }
    }

    /// <summary>当前引擎 luanti.exe 路径，未安装返回 null。</summary>
    public string? EngineExe
    {
        get
        {
            var v = InstalledVersion;
            if (v is null) return null;
            var exe = Path.Combine(EngineRoot, v, "bin", "luanti.exe");
            return File.Exists(exe) ? exe : null;
        }
    }

    public bool IsInstalled => EngineExe is not null;

    // 官方便携版 win64 下载源
    private const string DefaultVersion = "5.16.1";
    private static string ReleaseUrl(string v) =>
        $"https://github.com/luanti-org/luanti/releases/download/{v}/luanti-{v}-win64.zip";

    /// <summary>
    /// 确保引擎可用：已安装直接返回，否则自动下载解压。
    /// </summary>
    public async Task<string> EnsureEngineAsync(string? version = null, CancellationToken ct = default)
    {
        if (EngineExe is not null) return EngineExe;

        version ??= DefaultVersion;
        StatusChanged?.Invoke($"正在下载 Luanti {version}…");
        await DownloadAndExtractAsync(version, ct);
        StatusChanged?.Invoke("引擎安装完成");
        return EngineExe ?? throw new InvalidOperationException("引擎安装后仍不可用");
    }

    private async Task DownloadAndExtractAsync(string version, CancellationToken ct)
    {
        Directory.CreateDirectory(EngineRoot);
        var zipPath = Path.Combine(EngineRoot, $"luanti-{version}.zip");

        // 1. aria2c 下载（--check-certificate=false 兼容无证书验证场景）
        if (File.Exists(Aria2Path))
        {
            await RunAria2Async(ReleaseUrl(version), zipPath, ct);
        }
        else
        {
            await DownloadByHttpAsync(ReleaseUrl(version), zipPath, ct);
        }

        // 2. 解压到 version 目录
        var target = Path.Combine(EngineRoot, version);
        if (Directory.Exists(target)) Directory.Delete(target, true);
        StatusChanged?.Invoke("正在解压引擎…");
        await Task.Run(() => ZipFile.ExtractToDirectory(zipPath, target), ct);

        // 官方 zip 内含一层 luanti-<ver>/ 目录，规范化为直接内容
        NormalizeLayout(target);

        // 3. 记录版本
        await File.WriteAllTextAsync(Path.Combine(EngineRoot, "current.json"),
            JsonSerializer.Serialize(new { version, installed_at = DateTimeOffset.UtcNow }),
            ct);

        try { File.Delete(zipPath); } catch { }
    }

    /// <summary>把解压出的 luanti-x.y.z/ 子目录内容提升到目标目录。</summary>
    private static void NormalizeLayout(string target)
    {
        var exe = Path.Combine(target, "bin", "luanti.exe");
        if (File.Exists(exe)) return;

        var sub = Directory.GetDirectories(target)
            .FirstOrDefault(d => Directory.Exists(Path.Combine(d, "bin")));
        if (sub is null) return;

        foreach (var entry in Directory.GetFileSystemEntries(sub))
        {
            var name = Path.GetFileName(entry);
            var dest = Path.Combine(target, name);
            if (Directory.Exists(entry))
                Directory.Move(entry, dest);
            else
                File.Move(entry, dest, overwrite: true);
        }
        Directory.Delete(sub, true);
    }

    private async Task RunAria2Async(string url, string output, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = Aria2Path,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        // 禁证书校验 + 8 连接 + 断点续传
        psi.ArgumentList.Add("--check-certificate=false");
        psi.ArgumentList.Add("-x"); psi.ArgumentList.Add("8");
        psi.ArgumentList.Add("-s"); psi.ArgumentList.Add("8");
        psi.ArgumentList.Add("-k"); psi.ArgumentList.Add("4M");
        psi.ArgumentList.Add("--file-allocation=none");
        psi.ArgumentList.Add("--summary-interval=1");
        psi.ArgumentList.Add("--console-log-level=notice");
        psi.ArgumentList.Add("-d"); psi.ArgumentList.Add(Path.GetDirectoryName(output)!);
        psi.ArgumentList.Add("-o"); psi.ArgumentList.Add(Path.GetFileName(output));
        psi.ArgumentList.Add(url);

        using var proc = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 aria2c");
        // 解析 summary 行中的百分比
        while (!proc.StandardOutput.EndOfStream && !ct.IsCancellationRequested)
        {
            var line = await proc.StandardOutput.ReadLineAsync(ct);
            if (line is null) continue;
            var pct = ParsePercent(line);
            if (pct >= 0) ProgressChanged?.Invoke(pct);
        }
        await proc.WaitForExitAsync(ct);
        if (proc.ExitCode != 0 || !File.Exists(output))
            throw new InvalidOperationException($"aria2c 下载失败（退出码 {proc.ExitCode}）");
        ProgressChanged?.Invoke(100);
    }

    /// <summary>从 aria2 summary 行解析进度，如 [#1 20MiB/200MiB(10%)]。</summary>
    private static int ParsePercent(string line)
    {
        var idx = line.LastIndexOf('(');
        if (idx < 0) return -1;
        var end = line.IndexOf('%', idx);
        if (end < 0) return -1;
        if (!int.TryParse(line[(idx + 1)..end], out var p)) return -1;
        return Math.Clamp(p, 0, 100);
    }

    private async Task DownloadByHttpAsync(string url, string output, CancellationToken ct)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
        using var resp = await http.GetAsync(url,
            HttpCompletionOption.ResponseHeadersRead, ct);
        resp.EnsureSuccessStatusCode();
        var total = resp.Content.Headers.ContentLength ?? -1;
        await using var src = await resp.Content.ReadAsStreamAsync(ct);
        await using var dst = File.Create(output);
        var buf = new byte[81920];
        long readTotal = 0;
        int n;
        while ((n = await src.ReadAsync(buf, ct)) > 0)
        {
            await dst.WriteAsync(buf.AsMemory(0, n), ct);
            readTotal += n;
            if (total > 0) ProgressChanged?.Invoke((int)(readTotal * 100 / total));
        }
        ProgressChanged?.Invoke(100);
    }

    private static async Task RunHiddenAsync(string fileName, string[] args, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        using var p = Process.Start(psi)!;
        await p.WaitForExitAsync(ct);
    }

    /// <summary>卸载当前引擎。</summary>
    public void Uninstall()
    {
        var v = InstalledVersion;
        if (v is null) return;
        var dir = Path.Combine(EngineRoot, v);
        if (Directory.Exists(dir)) Directory.Delete(dir, true);
        var marker = Path.Combine(EngineRoot, "current.json");
        if (File.Exists(marker)) File.Delete(marker);
    }

    /// <summary>查询 Luanti 最新发布版本号（GitHub API，失败返回默认版本）。</summary>
    public async Task<string> FetchLatestVersionAsync(CancellationToken ct = default)
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd("LUNATICN/1.0");
            var json = await http.GetStringAsync(
                "https://api.github.com/repos/luanti-org/luanti/releases/latest", ct);
            using var doc = JsonDocument.Parse(json);
            var tag = doc.RootElement.GetProperty("tag_name").GetString() ?? "";
            return tag.TrimStart('v');
        }
        catch { return DefaultVersion; }
    }

    /// <summary>卸载后重新下载安装引擎。progress: 0-100 或 -1 不确定。</summary>
    public async Task ReinstallAsync(Action<int>? progress = null, CancellationToken ct = default)
    {
        Uninstall();
        void Handler(int p) => progress?.Invoke(p);
        ProgressChanged += Handler;
        try
        {
            var ver = await FetchLatestVersionAsync(ct);
            await EnsureEngineAsync(ver, ct);
        }
        finally { ProgressChanged -= Handler; }
    }
}
