using System.IO.Compression;
using System.Text;
using System.Text.Json;

namespace Lunaticn.Services;

/// <summary>manifest.json 内容（与服务端约定）。</summary>
public sealed class Manifest
{
    public string Type { get; set; } = ""; // map | mod
    public string Name { get; set; } = "";
    public string Author { get; set; } = "";
    public string Version { get; set; } = "1.0.0";
    public string Description { get; set; } = "";
    public string GameId { get; set; } = "";
    public string Engine { get; set; } = "";
    public List<string> Depends { get; set; } = new();
}

/// <summary>
/// 分享包（.lnpkg）构建：把存档或模组打包为
/// manifest.json + content/ + thumbnail.png 的 zip。
/// </summary>
public static class PackageBuilder
{
    public static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    /// <summary>打包存档目录。</summary>
    public static string BuildFromWorld(string worldDir, Manifest manifest, string destFile)
    {
        manifest.Type = "map";
        return Build(worldDir, manifest, destFile);
    }

    /// <summary>打包模组目录。</summary>
    public static string BuildFromMod(string modDir, Manifest manifest, string destFile)
    {
        manifest.Type = "mod";
        return Build(modDir, manifest, destFile);
    }

    private static string Build(string sourceDir, Manifest manifest, string destFile)
    {
        if (File.Exists(destFile)) File.Delete(destFile);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(destFile))!);

        using var zip = ZipFile.Open(destFile, ZipArchiveMode.Create);

        // manifest.json
        var mfEntry = zip.CreateEntry("manifest.json");
        using (var s = mfEntry.Open())
        {
            var json = JsonSerializer.Serialize(manifest, JsonOpts);
            var bytes = Encoding.UTF8.GetBytes(json);
            s.Write(bytes, 0, bytes.Length);
        }

        // content/ 下全部文件
        foreach (var file in Directory.GetFiles(sourceDir, "*", SearchOption.AllDirectories))
        {
            var rel = Path.GetRelativePath(sourceDir, file).Replace('\\', '/');
            // 分享时不带截图（由上传方单独提供缩略图）
            if (rel.StartsWith("screenshot.")) continue;
            zip.CreateEntryFromFile(file, "content/" + rel, CompressionLevel.Optimal);
        }
        return destFile;
    }

    /// <summary>校验包结构（上传前自检）。</summary>
    public static string? Validate(string lnpkgPath)
    {
        try
        {
            using var zip = ZipFile.OpenRead(lnpkgPath);
            var names = zip.Entries.Select(e => e.FullName.Replace('\\', '/')).ToList();
            if (!names.Any(n => n == "manifest.json")) return "缺少 manifest.json";
            if (!names.Any(n => n.StartsWith("content/"))) return "缺少 content/ 目录";
            if (names.Any(n => n.Contains("..") || n.StartsWith('/')))
                return "包内含非法路径";

            var mfEntry = zip.GetEntry("manifest.json");
            using var s = mfEntry!.Open();
            var mf = JsonSerializer.Deserialize<Manifest>(s, JsonOpts);
            if (mf is null || mf.Name.Length == 0 || mf.Version.Length == 0)
                return "manifest 缺少 name 或 version";
            if (mf.Type is not ("map" or "mod")) return "manifest.type 必须是 map 或 mod";
            return null;
        }
        catch (Exception ex)
        {
            return $"无法读取包: {ex.Message}";
        }
    }
}
