using System.IO.Compression;
using System.Text;

namespace Lunaticn.Services;

/// <summary>模组信息。</summary>
public sealed class ModInfo
{
    /// <summary>技术名（mod.conf 的 name，缺省为目录名）。</summary>
    public string Name { get; set; } = "";
    public string Title { get; set; } = "";
    public string Description { get; set; } = "";
    public string Author { get; set; } = "";
    public string Version { get; set; } = "";
    public string Path { get; set; } = "";
    public bool IsModPack { get; set; }
    /// <summary>硬依赖。</summary>
    public List<string> Depends { get; set; } = new();
    /// <summary>可选依赖。</summary>
    public List<string> OptionalDepends { get; set; } = new();

    /// <summary>展示用：依赖摘要。</summary>
    public string DependsSummary
    {
        get
        {
            if (Depends.Count == 0 && OptionalDepends.Count == 0) return "";
            var parts = new List<string>();
            if (Depends.Count > 0) parts.Add("依赖: " + string.Join(", ", Depends));
            if (OptionalDepends.Count > 0) parts.Add("可选: " + string.Join(", ", OptionalDepends));
            return string.Join("    ", parts);
        }
    }
}

/// <summary>
/// 模组管理：扫描模组库、解析 mod.conf 与依赖、拓扑排序。
/// </summary>
public sealed class ModService
{
    public string ModsRoot { get; }

    public ModService(string? dataDir = null)
    {
        ModsRoot = Path.Combine(dataDir ?? "data", "mods");
        Directory.CreateDirectory(ModsRoot);
    }

    /// <summary>扫描模组库全部模组。</summary>
    public List<ModInfo> List()
    {
        var mods = new List<ModInfo>();
        foreach (var dir in Directory.GetDirectories(ModsRoot))
        {
            var mod = ReadMod(dir);
            if (mod is not null) { mods.Add(mod); continue; }
            // 模组包：目录下每个子目录是独立模组
            foreach (var sub in Directory.GetDirectories(dir))
            {
                var inner = ReadMod(sub);
                if (inner is not null)
                {
                    inner.IsModPack = false;
                    mods.Add(inner);
                }
            }
        }
        return mods.OrderBy(m => m.Name, StringComparer.Ordinal).ToList();
    }

    /// <summary>读取单个模组目录（需含 init.lua 或 mod.conf）。</summary>
    public ModInfo? ReadMod(string dir)
    {
        if (!Directory.Exists(dir)) return null;
        var confPath = Path.Combine(dir, "mod.conf");
        var hasConf = File.Exists(confPath);
        var hasInit = File.Exists(Path.Combine(dir, "init.lua"));
        var packConf = Path.Combine(dir, "modpack.conf");
        if (!hasConf && !hasInit && !File.Exists(packConf)) return null;

        var conf = hasConf ? WorldService.ReadSettings(confPath) : new();
        var info = new ModInfo
        {
            Name = conf.GetValueOrDefault("name", Path.GetFileName(dir)),
            Title = conf.GetValueOrDefault("title", Path.GetFileName(dir)),
            Description = conf.GetValueOrDefault("description", ""),
            Author = conf.GetValueOrDefault("author", ""),
            Version = conf.GetValueOrDefault("version", ""),
            Path = dir,
            IsModPack = File.Exists(packConf),
        };
        info.Depends = SplitList(conf.GetValueOrDefault("depends", ""));
        info.OptionalDepends = SplitList(conf.GetValueOrDefault("optional_depends", ""));
        return info;
    }

    private static List<string> SplitList(string raw) =>
        raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
           .ToList();

    /// <summary>按名字查找模组。</summary>
    public ModInfo? Find(string name) =>
        List().FirstOrDefault(m => m.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

    // ---------- 依赖 ----------

    /// <summary>
    /// 解析启用某组模组所需包含的全部模组（自动带上硬依赖），
    /// 并返回缺失依赖列表。order 为满足依赖关系的加载顺序。
    /// </summary>
    public (List<string> Selected, List<string> Order, List<string> Missing)
        ResolveDependencies(IEnumerable<string> requested)
    {
        var all = List().ToDictionary(m => m.Name, StringComparer.OrdinalIgnoreCase);
        var selected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var missing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var queue = new Queue<string>(requested);

        // 闭包：把所有硬依赖纳入
        while (queue.Count > 0)
        {
            var name = queue.Dequeue();
            if (!all.TryGetValue(name, out var mod))
            {
                missing.Add(name);
                continue;
            }
            if (!selected.Add(mod.Name)) continue;
            foreach (var dep in mod.Depends)
                if (!selected.Contains(dep)) queue.Enqueue(dep);
        }

        var order = TopoSort(selected.Where(n => all.ContainsKey(n))
            .Select(n => all[n]).ToList(), missing);
        return (selected.Where(all.ContainsKey).ToList(), order, missing.ToList());
    }

    /// <summary>拓扑排序（依赖在前），检测到环时追加到 missing。</summary>
    private static List<string> TopoSort(List<ModInfo> mods, HashSet<string> missing)
    {
        var byName = mods.ToDictionary(m => m.Name, StringComparer.OrdinalIgnoreCase);
        var state = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase); // 0未访 1访中 2完成
        var order = new List<string>();

        bool Visit(ModInfo m)
        {
            if (state.TryGetValue(m.Name, out var s))
            {
                if (s == 1) { missing.Add($"循环依赖: {m.Name}"); return false; }
                if (s == 2) return true;
            }
            state[m.Name] = 1;
            foreach (var dep in m.Depends)
            {
                if (byName.TryGetValue(dep, out var dm))
                {
                    if (!Visit(dm)) return false;
                }
                // 缺失的依赖不阻塞排序（missing 已记录）
            }
            state[m.Name] = 2;
            order.Add(m.Name);
            return true;
        }

        foreach (var m in mods) Visit(m);
        return order;
    }

    /// <summary>校验某组模组能否装进某存档，返回问题列表（空=通过）。</summary>
    public List<string> ValidateForWorld(string worldDirName, IEnumerable<string> modNames)
    {
        var problems = new List<string>();
        var (selected, order, missing) = ResolveDependencies(modNames);
        foreach (var m in missing) problems.Add($"缺失依赖: {m}");

        // 与存档 world.mt 中已启用模组名冲突检测（同名不同路径）
        var world = new WorldService();
        var existing = world.ReadWorld(Path.Combine(world.WorldsRoot, worldDirName));
        if (existing is not null)
        {
            var installed = List().ToDictionary(m => m.Name, StringComparer.OrdinalIgnoreCase);
            foreach (var name in existing.EnabledMods)
            {
                if (!installed.ContainsKey(name) && !selected.Contains(name, StringComparer.OrdinalIgnoreCase))
                    problems.Add($"存档启用的模组未安装: {name}");
            }
        }
        _ = order;
        return problems;
    }

    // ---------- 安装 ----------

    /// <summary>
    /// 安装模组 zip（解压到模组库）。zip 根目录需直接包含 mod.conf/init.lua，
    /// 或包一层同名目录。
    /// </summary>
    public ModInfo InstallZip(string zipPath)
    {
        using var archive = System.IO.Compression.ZipFile.OpenRead(zipPath);
        // 判断结构：找第一个含 mod.conf / init.lua / modpack.conf 的层级
        var entries = archive.Entries
            .Where(e => !e.FullName.EndsWith('/'))
            .ToList();

        string? rootPrefix = null;
        foreach (var e in entries)
        {
            var name = e.FullName.Replace('\\', '/');
            if (name.EndsWith("mod.conf") || name.EndsWith("init.lua") || name.EndsWith("modpack.conf"))
            {
                var idx = name.LastIndexOf('/');
                rootPrefix = idx >= 0 ? name[..(idx + 1)] : "";
                break;
            }
        }
        if (rootPrefix is null)
            throw new InvalidDataException("压缩包中未找到 mod.conf 或 init.lua");

        // 目标目录 = 前缀首段或 zip 文件名
        string targetName;
        if (rootPrefix.Contains('/'))
            targetName = rootPrefix.Split('/')[0];
        else
            targetName = Path.GetFileNameWithoutExtension(zipPath);
        var target = Path.Combine(ModsRoot, targetName);
        if (Directory.Exists(target)) Directory.Delete(target, true);
        Directory.CreateDirectory(target);

        foreach (var e in entries)
        {
            var rel = e.FullName.Replace('\\', '/');
            if (!rel.StartsWith(rootPrefix)) continue;
            var sub = rel[rootPrefix.Length..];
            if (sub.Length == 0) continue;
            var dest = Path.Combine(target, sub);
            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
            e.ExtractToFile(dest, overwrite: true);
        }

        var mod = ReadMod(target) ?? ReadMod(Path.Combine(target))
            ?? throw new InvalidDataException("解压后未找到有效模组");
        return mod;
    }

    /// <summary>卸载模组。</summary>
    public void Uninstall(string modName)
    {
        var mod = Find(modName) ?? throw new DirectoryNotFoundException("模组不存在");
        Directory.Delete(mod.Path, true);
    }
}
