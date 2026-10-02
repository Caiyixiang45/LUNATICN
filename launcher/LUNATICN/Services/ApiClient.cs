using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Lunaticn.Models;

namespace Lunaticn.Services;

/// <summary>
/// 与 LUNATICN 社区服务器通信的 HTTP 客户端。
/// 令牌保存在本地，启动时自动恢复登录态。
/// </summary>
public sealed class ApiClient
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private static readonly HttpClient Http = new()
    {
        Timeout = TimeSpan.FromSeconds(30),
    };

    /// <summary>服务器地址，默认本地开发地址。</summary>
    public string BaseUrl { get; set; } = "http://localhost:8080";

    public string? Token { get; set; }

    public UserInfo? CurrentUser { get; private set; }

    public bool IsLoggedIn => !string.IsNullOrEmpty(Token) && CurrentUser is not null;

    /// <summary>登录态变化（供 UI 刷新）。</summary>
    public event Action? AuthChanged;

    // ---------- 账号 ----------

    public async Task<Result<UserInfo>> RegisterAsync(string username, string password, string nickname)
    {
        var (ok, data, err) = await PostAsync<LoginResponse>("/api/auth/register",
            new { username, password, nickname });
        if (!ok) return Result<UserInfo>.Fail(err);
        return await AdoptLoginAsync(data!);
    }

    public async Task<Result<UserInfo>> LoginAsync(string username, string password)
    {
        var (ok, data, err) = await PostAsync<LoginResponse>("/api/auth/login",
            new { username, password });
        if (!ok) return Result<UserInfo>.Fail(err);
        return await AdoptLoginAsync(data!);
    }

    private async Task<Result<UserInfo>> AdoptLoginAsync(LoginResponse data)
    {
        Token = data.Token;
        SaveToken();
        var (ok, me, err) = await GetAsync<UserInfo>("/api/me");
        if (!ok) return Result<UserInfo>.Fail(err);
        CurrentUser = me;
        AuthChanged?.Invoke();
        return Result<UserInfo>.Ok(me!);
    }

    public async Task LogoutAsync()
    {
        Token = null;
        CurrentUser = null;
        ClearToken();
        AuthChanged?.Invoke();
        await Task.CompletedTask;
    }

    /// <summary>启动时尝试静默恢复登录。</summary>
    public async Task<bool> RestoreSessionAsync()
    {
        Token = LoadToken();
        if (string.IsNullOrEmpty(Token)) return false;
        var (ok, me, _) = await GetAsync<UserInfo>("/api/me");
        if (!ok || me is null)
        {
            Token = null;
            ClearToken();
            return false;
        }
        CurrentUser = me;
        AuthChanged?.Invoke();
        return true;
    }

    // ---------- 房间 ----------

    public async Task<Result<List<RoomInfo>>> GetRoomsAsync()
    {
        var (ok, obj, err) = await GetAsync<RoomsResponse>("/api/rooms");
        if (!ok) return Result<List<RoomInfo>>.Fail(err);
        return Result<List<RoomInfo>>.Ok(obj?.Rooms ?? new());
    }

    public async Task<Result<List<ServerInfo>>> GetServersAsync()
    {
        var (ok, obj, err) = await GetAsync<ServersResponse>("/api/servers");
        if (!ok) return Result<List<ServerInfo>>.Fail(err);
        return Result<List<ServerInfo>>.Ok(obj?.Servers ?? new());
    }

    /// <summary>注册/续期房间，返回房间令牌。</summary>
    public async Task<Result<string>> RegisterRoomAsync(object roomInfo)
    {
        var (ok, obj, err) = await PostAsync<RoomRegisterResponse>("/api/room/register", roomInfo);
        if (!ok) return Result<string>.Fail(err);
        return Result<string>.Ok(obj!.RoomToken);
    }

    public async Task HeartbeatAsync(string roomToken, int players)
    {
        await PostAsync<object>("/api/room/heartbeat", new { token = roomToken, players });
    }

    public async Task UnregisterRoomAsync(string roomToken)
    {
        await PostAsync<object>("/api/room/unregister", new { token = roomToken });
    }

    // ---------- 好友 ----------

    public async Task<Result<List<FriendInfo>>> GetFriendsAsync()
    {
        var (ok, obj, err) = await GetAsync<FriendsResponse>("/api/friends");
        if (!ok) return Result<List<FriendInfo>>.Fail(err);
        return Result<List<FriendInfo>>.Ok(obj?.Friends ?? new());
    }

    public async Task<Result<string>> AddFriendAsync(string username)
    {
        var (ok, _, err) = await PostAsync<object>("/api/friends/request", new { username });
        return ok ? Result<string>.Ok("ok") : Result<string>.Fail(err);
    }

    public async Task<Result<List<FriendRequestInfo>>> GetFriendRequestsAsync()
    {
        var (ok, obj, err) = await GetAsync<RequestsResponse>("/api/friends/requests");
        if (!ok) return Result<List<FriendRequestInfo>>.Fail(err);
        var list = new List<FriendRequestInfo>();
        list.AddRange(obj?.Incoming ?? new());
        list.AddRange(obj?.Outgoing ?? new());
        return Result<List<FriendRequestInfo>>.Ok(list);
    }

    public async Task<Result<string>> RespondFriendAsync(string fromUserId, bool accept)
    {
        var (ok, _, err) = await PostAsync<object>("/api/friends/respond",
            new { from = fromUserId, accept });
        return ok ? Result<string>.Ok("ok") : Result<string>.Fail(err);
    }

    public async Task<Result<string>> RemoveFriendAsync(string friendId)
    {
        var (ok, _, err) = await DeleteAsync<object>($"/api/friends/{friendId}");
        return ok ? Result<string>.Ok("ok") : Result<string>.Fail(err);
    }

    // ---------- 工坊 ----------

    public async Task<Result<(int Total, List<PackageInfo> Items)>> SearchPackagesAsync(
        string type = "", string query = "", int limit = 20, int offset = 0)
    {
        var url = $"/api/packages?type={Uri.EscapeDataString(type)}" +
                  $"&q={Uri.EscapeDataString(query)}&limit={limit}&offset={offset}";
        var (ok, obj, err) = await GetAsync<PackagesResponse>(url);
        if (!ok) return Result<(int, List<PackageInfo>)>.Fail(err);
        return Result<(int, List<PackageInfo>)>.Ok((obj?.Total ?? 0, obj?.Packages ?? new()));
    }

    public async Task<Result<List<PackageInfo>>> GetMyPackagesAsync()
    {
        var (ok, obj, err) = await GetAsync<PackagesResponse>("/api/packages/mine");
        if (!ok) return Result<List<PackageInfo>>.Fail(err);
        return Result<List<PackageInfo>>.Ok(obj?.Packages ?? new());
    }

    public async Task<Result<PackageInfo>> UploadPackageAsync(string filePath, string? thumbnailPath)
    {
        using var form = new MultipartFormDataContent();
        var fileBytes = await File.ReadAllBytesAsync(filePath);
        var fileContent = new ByteArrayContent(fileBytes);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(fileContent, "file", Path.GetFileName(filePath));
        if (thumbnailPath is not null && File.Exists(thumbnailPath))
        {
            var thumbBytes = await File.ReadAllBytesAsync(thumbnailPath);
            var thumbContent = new ByteArrayContent(thumbBytes);
            thumbContent.Headers.ContentType = new MediaTypeHeaderValue("image/png");
            form.Add(thumbContent, "thumbnail", Path.GetFileName(thumbnailPath));
        }
        var (ok, obj, err) = await SendAsync<PackageInfo>(HttpMethod.Post, "/api/packages", form);
        return ok ? Result<PackageInfo>.Ok(obj!) : Result<PackageInfo>.Fail(err);
    }

    public async Task<Result<string>> DownloadPackageAsync(string packageId, string destPath)
    {
        try
        {
            using var req = BuildRequest(HttpMethod.Get, $"/api/packages/{packageId}/download");
            using var resp = await Http.SendAsync(req);
            if (!resp.IsSuccessStatusCode)
                return Result<string>.Fail($"下载失败: {(int)resp.StatusCode}");
            await using var fs = File.Create(destPath);
            await (await resp.Content.ReadAsStreamAsync()).CopyToAsync(fs);
            return Result<string>.Ok(destPath);
        }
        catch (Exception ex)
        {
            return Result<string>.Fail(ex.Message);
        }
    }

    public async Task<Result<string>> DeletePackageAsync(string packageId)
    {
        var (ok, _, err) = await DeleteAsync<object>($"/api/packages/{packageId}");
        return ok ? Result<string>.Ok("ok") : Result<string>.Fail(err);
    }

    // ---------- HTTP 底层 ----------

    private HttpRequestMessage BuildRequest(HttpMethod method, string url)
    {
        var req = new HttpRequestMessage(method, BaseUrl + url);
        if (!string.IsNullOrEmpty(Token))
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Token);
        return req;
    }

    private async Task<(bool Ok, T? Data, string Err)> GetAsync<T>(string url)
        => await SendAsync<T>(HttpMethod.Get, url, null);

    private async Task<(bool Ok, T? Data, string Err)> PostAsync<T>(string url, object body)
    {
        var json = new StringContent(JsonSerializer.Serialize(body, body.GetType(), JsonOpts),
            Encoding.UTF8, "application/json");
        return await SendAsync<T>(HttpMethod.Post, url, json);
    }

    private async Task<(bool Ok, T? Data, string Err)> DeleteAsync<T>(string url)
        => await SendAsync<T>(HttpMethod.Delete, url, null);

    private async Task<(bool Ok, T? Data, string Err)> SendAsync<T>(
        HttpMethod method, string url, HttpContent? content)
    {
        try
        {
            using var req = BuildRequest(method, url);
            if (content is not null) req.Content = content;
            using var resp = await Http.SendAsync(req);
            var text = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
            {
                var err = TryExtractError(text);
                return (false, default, $"{(int)resp.StatusCode}: {err}");
            }
            if (typeof(T) == typeof(object)) return (true, default, "");
            var data = JsonSerializer.Deserialize<T>(text, JsonOpts);
            return (true, data, "");
        }
        catch (HttpRequestException ex)
        {
            return (false, default, $"无法连接服务器: {ex.Message}");
        }
        catch (TaskCanceledException)
        {
            return (false, default, "请求超时");
        }
        catch (JsonException ex)
        {
            return (false, default, $"响应解析失败: {ex.Message}");
        }
    }

    private static string TryExtractError(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("error", out var e))
                return e.GetString() ?? json;
        }
        catch { }
        return json;
    }

    // ---------- 令牌本地保存 ----------

    private static string TokenPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "LUNATICN", "token.txt");

    private void SaveToken()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(TokenPath)!);
            File.WriteAllText(TokenPath, Token ?? "");
        }
        catch { }
    }

    private void ClearToken()
    {
        try { if (File.Exists(TokenPath)) File.Delete(TokenPath); } catch { }
    }

    private string? LoadToken()
    {
        try { return File.Exists(TokenPath) ? File.ReadAllText(TokenPath).Trim() : null; }
        catch { return null; }
    }

    // ---------- 响应模型（snake_case） ----------

    private sealed class LoginResponse
    {
        public string Token { get; set; } = "";
        public UserInfo? User { get; set; }
    }

    private sealed class RoomsResponse
    {
        public List<RoomInfo>? Rooms { get; set; }
    }

    private sealed class ServersResponse
    {
        public List<ServerInfo>? Servers { get; set; }
    }

    private sealed class RoomRegisterResponse
    {
        public string RoomToken { get; set; } = "";
        public RoomInfo? Room { get; set; }
    }

    private sealed class FriendsResponse
    {
        public List<FriendInfo>? Friends { get; set; }
    }

    private sealed class RequestsResponse
    {
        public List<FriendRequestInfo>? Incoming { get; set; }
        public List<FriendRequestInfo>? Outgoing { get; set; }
    }

    private sealed class PackagesResponse
    {
        public int Total { get; set; }
        public List<PackageInfo>? Packages { get; set; }
    }
}

/// <summary>统一操作结果。</summary>
public sealed class Result<T>
{
    public bool Success { get; init; }
    public T? Data { get; init; }
    public string Error { get; init; } = "";

    public static Result<T> Ok(T data) => new() { Success = true, Data = data };
    public static Result<T> Fail(string err) => new() { Success = false, Error = err };
}
