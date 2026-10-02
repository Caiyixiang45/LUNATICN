namespace Lunaticn.Models;

/// <summary>当前登录用户。</summary>
public sealed class UserInfo
{
    public string Id { get; set; } = "";
    public string Username { get; set; } = "";
    public string Nickname { get; set; } = "";
}

/// <summary>联机大厅房间。</summary>
public sealed class RoomInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Owner { get; set; } = "";
    public string OwnerName { get; set; } = "";
    public string Host { get; set; } = "";
    public int Port { get; set; }
    public string GameId { get; set; } = "";
    public string World { get; set; } = "";
    public int MaxPlayers { get; set; }
    public int Players { get; set; }
    public bool HasPassword { get; set; }
    public bool Private { get; set; }
    public string Engine { get; set; } = "";
    public string Source { get; set; } = "";
    public string Description { get; set; } = "";
}

/// <summary>官方固定服务器。</summary>
public sealed class ServerInfo
{
    public string Name { get; set; } = "";
    public int Port { get; set; }
    public bool Running { get; set; }
}

/// <summary>分享包（地图/模组）。</summary>
public sealed class PackageInfo
{
    public string Id { get; set; } = "";
    public string Type { get; set; } = ""; // map | mod
    public string Name { get; set; } = "";
    public string Author { get; set; } = "";
    public string AuthorName { get; set; } = "";
    public string Version { get; set; } = "";
    public string Description { get; set; } = "";
    public string GameId { get; set; } = "";
    public List<string> Depends { get; set; } = new();
    public long Size { get; set; }
    public int Downloads { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>好友。</summary>
public sealed class FriendInfo
{
    public string Id { get; set; } = "";
    public string Username { get; set; } = "";
    public string Nickname { get; set; } = "";

    /// <summary>头像首字。</summary>
    public string Initial =>
        string.IsNullOrEmpty(Nickname) ? (Username.Length > 0 ? Username[..1].ToUpper() : "?")
        : Nickname[..1].ToUpper();
}

/// <summary>好友请求。</summary>
public sealed class FriendRequestInfo
{
    public FriendInfo? User { get; set; }
    public string Direction { get; set; } = "in"; // in | out
    public DateTimeOffset CreatedAt { get; set; }
}
