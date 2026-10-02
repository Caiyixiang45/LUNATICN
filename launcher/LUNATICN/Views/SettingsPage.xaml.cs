using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class SettingsPage : Page
{
    private readonly AppServices _svc = AppServices.Instance;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += (_, _) => Load();
    }

    private void Load()
    {
        ServerUrlBox.Text = _svc.ServerUrl;
        PlayerNameBox.Text = AppServices.GetSetting("player_name",
            Environment.UserName);
        ClientPortBox.Text = AppServices.GetSetting("client_port", "0");
        DirsText.Text =
            $"存档: {AppServices.Instance.Worlds.WorldsRoot}\n" +
            $"模组: {AppServices.Instance.Mods.ModsRoot}";
        UpdateAccount();
        UpdateEngineInfo();
        AboutText.Text = $"版本 {GetVersion()} · Luanti {(_svc.Engine.InstalledVersion ?? "未安装")}";
    }

    private static string GetVersion()
    {
        try
        {
            return Assembly.GetExecutingAssembly()
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
                .InformationalVersion.Split('+')[0] ?? "1.0.0";
        }
        catch { return "1.0.0"; }
    }

    private void UpdateAccount()
    {
        var u = _svc.Api.CurrentUser;
        AccountText.Text = u is null ? "未登录" : $"已登录：{u.Nickname}（{u.Username}）";
    }

    private void UpdateEngineInfo()
    {
        var exe = _svc.Engine.EngineExe;
        EngineInfoText.Text = exe is not null
            ? $"已安装：{exe}\n版本：{_svc.Engine.InstalledVersion ?? "未知"}"
            : "引擎未安装，首次启动游戏时会自动下载。";
    }

    // ---------- 社区服务器 ----------

    private async void SaveServer_Click(object sender, RoutedEventArgs e)
    {
        var url = ServerUrlBox.Text.Trim().TrimEnd('/');
        if (url.Length == 0)
        {
            StatusText.Text = "服务器地址不能为空";
            return;
        }
        if (!Uri.TryCreate(url, UriKind.Absolute, out _))
        {
            StatusText.Text = "地址格式不正确，示例：http://127.0.0.1:8080";
            return;
        }
        _svc.ServerUrl = url;

        StatusText.Text = "正在测试连接…";
        var r = await _svc.Api.GetRoomsAsync();
        StatusText.Text = r.Success ? "连接成功，服务器可用" : $"连接失败: {r.Error}";
    }

    private async void Logout_Click(object sender, RoutedEventArgs e)
    {
        if (!FormDialog.Confirm(Window.GetWindow(this), "退出登录", "确定退出当前账号？"))
            return;
        await _svc.Api.LogoutAsync();
        UpdateAccount();
        StatusText.Text = "已退出登录";
    }

    // ---------- 引擎 ----------

    private async void CheckEngine_Click(object sender, RoutedEventArgs e)
    {
        EngineStatusText.Text = "正在检查…";
        try
        {
            var ver = await _svc.Engine.FetchLatestVersionAsync();
            var cur = _svc.Engine.InstalledVersion;
            EngineStatusText.Text = ver == cur
                ? $"已是最新版本 {ver}"
                : $"发现新版本 {ver}（当前 {cur ?? "未安装"}）";
        }
        catch (Exception ex)
        {
            EngineStatusText.Text = $"检查失败: {ex.Message}";
        }
    }

    private async void ReinstallEngine_Click(object sender, RoutedEventArgs e)
    {
        if (!FormDialog.Confirm(Window.GetWindow(this), "重新下载引擎",
            "将删除并重新下载 Luanti 官方便携版（约 100MB）。")) return;

        EngineProgress.Visibility = Visibility.Visible;
        EngineProgress.IsIndeterminate = true;
        try
        {
            await _svc.Engine.ReinstallAsync(progress =>
                Dispatcher.BeginInvoke(() =>
                {
                    if (progress < 0) EngineProgress.IsIndeterminate = true;
                    else
                    {
                        EngineProgress.IsIndeterminate = false;
                        EngineProgress.Value = progress;
                    }
                }));
            EngineStatusText.Text = "引擎已就绪";
            UpdateEngineInfo();
        }
        catch (Exception ex)
        {
            EngineStatusText.Text = $"下载失败: {ex.Message}";
        }
        finally
        {
            EngineProgress.Visibility = Visibility.Collapsed;
        }
    }

    // ---------- 联机 ----------

    private void SaveNet_Click(object sender, RoutedEventArgs e)
    {
        if (!int.TryParse(ClientPortBox.Text, out var port) || port < 0 || port > 65535)
            port = 0;
        AppServices.SetSetting("player_name", PlayerNameBox.Text.Trim());
        AppServices.SetSetting("client_port", port.ToString());
        StatusText.Text = "联机设置已保存";
    }

    // ---------- 目录 ----------

    private void OpenWorlds_Click(object sender, RoutedEventArgs e)
        => OpenDir(AppServices.Instance.Worlds.WorldsRoot);

    private void OpenMods_Click(object sender, RoutedEventArgs e)
        => OpenDir(AppServices.Instance.Mods.ModsRoot);

    private static void OpenDir(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = path,
                UseShellExecute = true,
            });
        }
        catch { }
    }
}
