using System.Diagnostics;
using System.Text;

namespace Lunaticn.Services;

/// <summary>世界（存档）信息。</summary>
public sealed class WorldInfo
{
    public string DirName { get; set; } = "";
    public string Name { get; set; } = "";
    public string GameId { get; set; } = "";
    public bool Creative { get; set; }
    public bool Damage { get; set; } = true;
    public DateTime LastPlayed { get; set; }
    public long SizeBytes { get; set; }
    public string? Screenshot { get; set; }
    /// <summary>已启用模组（world.mt 中 load_mod_*=true 的项）。</summary>
    public List<string> EnabledMods { get; set; } = new();
}

/// <summary>
/// 存档管理：world 目录 CRUD 与 world.mt 配置读写。
/// </summary>
public sealed class WorldService
{
    public string WorldsRoot { get; }

    public WorldService(string? dataDir = null)
    {
        WorldsRoot = Path.Combine(dataDir ?? "data", "worlds");
        Directory.CreateDirectory(WorldsRoot);
    }

    /// <summary>列出全部存档。</summary>
    public List<WorldInfo> List()
    {
        var result = new List<WorldInfo>();
        foreach (var dir in Directory.GetDirectories(WorldsRoot))
        {
            var info = ReadWorld(dir);
            if (info is not null) result.Add(info);
        }
        result.Sort((a, b) => b.LastPlayed.CompareTo(a.LastPlayed));
        return result;
    }

    /// <summary>读取单个世界目录。</summary>
    public WorldInfo? ReadWorld(string dir)
    {
        var mtPath = Path.Combine(dir, "world.mt");
        if (!File.Exists(mtPath)) return null;

        var settings = ReadSettings(mtPath);
        var info = new WorldInfo
        {
            DirName = Path.GetFileName(dir),
            Name = settings.GetValueOrDefault("world_name", Path.GetFileName(dir)),
            GameId = settings.GetValueOrDefault("gameid", ""),
            Creative = settings.GetValueOrDefault("creative_mode", "false") == "true",
            Damage = settings.GetValueOrDefault("enable_damage", "true") == "true",
        };
        foreach (var (k, v) in settings)
        {
            if (k.StartsWith("load_mod_") && v == "true")
                info.EnabledMods.Add(k["load_mod_".Length..]);
        }

        // 最后游玩时间与体积
        var map = Path.Combine(dir, "map.sqlite");
        if (File.Exists(map))
        {
            info.LastPlayed = File.GetLastWriteTime(map);
            info.SizeBytes += new FileInfo(map).Length;
        }
        foreach (var f in Directory.GetFiles(dir))
            info.SizeBytes += new FileInfo(f).Length;

        // 缩略图
        foreach (var name in new[] { "screenshot.png", "screenshot.jpg", "screenshot.jpeg" })
        {
            var p = Path.Combine(dir, name);
            if (File.Exists(p)) { info.Screenshot = p; break; }
        }
        return info;
    }

    /// <summary>
    /// 新建世界：创建目录并写 world.mt（引擎首启时还会补全其余文件）。
    /// </summary>
    public WorldInfo CreateWorld(string name, string gameId, bool creative,
        bool damage = true, string? seed = null)
    {
        var dirName = SanitizeDirName(name);
        var dir = Path.Combine(WorldsRoot, dirName);
        if (Directory.Exists(dir))
            throw new InvalidOperationException("同名存档已存在");

        Directory.CreateDirectory(dir);
        var sb = new StringBuilder();
        sb.AppendLine($"gameid = {gameId}");
        sb.AppendLine($"world_name = {name}");
        sb.AppendLine($"enable_damage = {(damage ? "true" : "false")}");
        sb.AppendLine($"creative_mode = {(creative ? "true" : "false")}");
        sb.AppendLine("backend = sqlite3");
        sb.AppendLine("player_backend = sqlite3");
        sb.AppendLine("auth_backend = sqlite3");
        sb.AppendLine("mod_storage_backend = sqlite3");
        sb.AppendLine("server_announce = false");
        if (!string.IsNullOrWhiteSpace(seed))
            sb.AppendLine($"seed = {seed.Trim()}");
        File.WriteAllText(Path.Combine(dir, "world.mt"), sb.ToString(), new UTF8Encoding(false));

        return ReadWorld(dir)!;
    }

    /// <summary>复制存档。</summary>
    public WorldInfo CopyWorld(string srcDirName, string newName)
    {
        var src = Path.Combine(WorldsRoot, srcDirName);
        if (!Directory.Exists(src)) throw new DirectoryNotFoundException("源存档不存在");
        var dst = Path.Combine(WorldsRoot, SanitizeDirName(newName));
        if (Directory.Exists(dst)) throw new InvalidOperationException("同名存档已存在");

        CopyDirectory(src, dst);
        // 更新 world_name
        var mtPath = Path.Combine(dst, "world.mt");
        var settings = ReadSettings(mtPath);
        settings["world_name"] = newName;
        WriteSettings(mtPath, settings);
        return ReadWorld(dst)!;
    }

    /// <summary>删除存档。</summary>
    public void DeleteWorld(string dirName)
    {
        var dir = Path.Combine(WorldsRoot, dirName);
        if (!Directory.Exists(dir)) throw new DirectoryNotFoundException("存档不存在");
        Directory.Delete(dir, true);
    }

    /// <summary>导出存档为 zip（分享用）。</summary>
    public string ExportWorld(string dirName, string destZip)
    {
        var dir = Path.Combine(WorldsRoot, dirName);
        if (!Directory.Exists(dir)) throw new DirectoryNotFoundException("存档不存在");
        if (File.Exists(destZip)) File.Delete(destZip);
        System.IO.Compression.ZipFile.CreateFromDirectory(dir, destZip);
        return destZip;
    }

    // ---------- world.mt 读写 ----------

    /// <summary>解析 key = value 格式文件。</summary>
    public static Dictionary<string, string> ReadSettings(string path)
    {
        var dict = new Dictionary<string, string>(StringComparer.Ordinal);
        if (!File.Exists(path)) return dict;
        foreach (var raw in File.ReadAllLines(path))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith('#') || line.StartsWith(';')) continue;
            var eq = line.IndexOf('=');
            if (eq <= 0) continue;
            dict[line[..eq].Trim()] = line[(eq + 1)..].Trim();
        }
        return dict;
    }

    /// <summary>写回 key = value 文件（UTF-8 无 BOM）。</summary>
    public static void WriteSettings(string path, Dictionary<string, string> dict)
    {
        var sb = new StringBuilder();
        foreach (var (k, v) in dict)
            sb.AppendLine($"{k} = {v}");
        File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
    }

    /// <summary>为存档启用/禁用模组（写 load_mod_*）。</summary>
    public void SetModEnabled(string dirName, string modName, bool enabled)
    {
        var mtPath = Path.Combine(WorldsRoot, dirName, "world.mt");
        var settings = ReadSettings(mtPath);
        settings[$"load_mod_{modName}"] = enabled ? "true" : "false";
        WriteSettings(mtPath, settings);
    }

    /// <summary>批量设置模组启用状态。</summary>
    public void ApplyMods(string dirName, IEnumerable<string> enabledMods)
    {
        var mtPath = Path.Combine(WorldsRoot, dirName, "world.mt");
        var settings = ReadSettings(mtPath);
        // 先清空已知的 load_mod_ 项（仅 true 的保留判断由调用方决定）
        var keys = settings.Keys.Where(k => k.StartsWith("load_mod_")).ToList();
        var enabled = new HashSet<string>(enabledMods);
        foreach (var k in keys)
        {
            var mod = k["load_mod_".Length..];
            settings[k] = enabled.Contains(mod) ? "true" : "false";
        }
        foreach (var mod in enabled)
        {
            var k = $"load_mod_{mod}";
            if (!settings.ContainsKey(k)) settings[k] = "true";
        }
        WriteSettings(mtPath, settings);
    }

    // ---------- 工具 ----------

    private static string SanitizeDirName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sb = new StringBuilder();
        foreach (var c in name)
            sb.Append(Array.IndexOf(invalid, c) >= 0 ? '_' : c);
        var dir = sb.ToString().Trim();
        return dir.Length == 0 ? "world" : dir;
    }

    private static void CopyDirectory(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var f in Directory.GetFiles(src))
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(src))
            CopyDirectory(d, Path.Combine(dst, Path.GetFileName(d)));
    }
}
