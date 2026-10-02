namespace Lunaticn.Services;

/// <summary>
/// 应用服务集合（单例）。所有页面通过 AppServices.Instance 取用。
/// </summary>
public sealed class AppServices
{
    public static AppServices Instance { get; } = new();

    public ApiClient Api { get; } = new();
    public EngineManager Engine { get; } = new();
    public WorldService Worlds { get; } = new();
    public ModService Mods { get; } = new();
    public RoomHostService RoomHost { get; }
    public JoinService Joiner { get; }

    /// <summary>服务器地址（设置页可改，持久化到本地）。</summary>
    public string ServerUrl
    {
        get => _serverUrl;
        set
        {
            _serverUrl = value;
            Api.BaseUrl = value;
            SaveServerUrl(value);
        }
    }

    private string _serverUrl;

    private AppServices()
    {
        _serverUrl = LoadServerUrl();
        Api.BaseUrl = _serverUrl;
        RoomHost = new RoomHostService(Engine, Api);
        Joiner = new JoinService(Engine);
    }

    private static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "LUNATICN", "settings.json");

    private static string LoadServerUrl()
    {
        try
        {
            if (File.Exists(SettingsPath))
            {
                using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(SettingsPath));
                if (doc.RootElement.TryGetProperty("server_url", out var v))
                    return v.GetString() ?? DefaultUrl;
            }
        }
        catch { }
        return DefaultUrl;
    }

    private const string DefaultUrl = "http://localhost:8080";

    private static void SaveServerUrl(string url)
    {
        var data = LoadAll();
        data["server_url"] = url;
        SaveAll(data);
    }

    // ---------- 通用设置项 ----------

    /// <summary>读取一项设置（不存在返回默认值）。</summary>
    public static string GetSetting(string key, string defaultValue = "")
    {
        try
        {
            var data = LoadAll();
            return data.TryGetValue(key, out var v) && v is not null ? v : defaultValue;
        }
        catch { return defaultValue; }
    }

    /// <summary>写入一项设置。</summary>
    public static void SetSetting(string key, string value)
    {
        var data = LoadAll();
        data[key] = value;
        SaveAll(data);
    }

    private static Dictionary<string, string?> LoadAll()
    {
        try
        {
            if (File.Exists(SettingsPath))
                return System.Text.Json.JsonSerializer
                    .Deserialize<Dictionary<string, string?>>(File.ReadAllText(SettingsPath))
                    ?? new();
        }
        catch { }
        return new();
    }

    private static void SaveAll(Dictionary<string, string?> data)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!);
            File.WriteAllText(SettingsPath, System.Text.Json.JsonSerializer.Serialize(data));
        }
        catch { }
    }
}
