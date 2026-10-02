using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Lunaticn.Models;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class LobbyPage : Page
{
    private readonly ApiClient _api = AppServices.Instance.Api;
    private readonly RoomHostService _host = AppServices.Instance.RoomHost;
    private bool _hooked;

    public LobbyPage()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            if (!_hooked)
            {
                _hooked = true;
                _host.StateChanged += s => Dispatcher.BeginInvoke(() => UpdateHostCard(s));
                _host.LineLogged += line => Dispatcher.BeginInvoke(() => AppendLog(line));
                Unloaded += (_, _) => { /* 离开页面后由新实例重新订阅，见 RefreshAsync 的重复保护 */ };
            }
            ApplyTab();
            await RefreshAsync();
        };
    }

    private void ApplyTab()
    {
        RoomsPane.Visibility = Visibility.Visible;
        RoomList.Visibility = TabRooms.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        ServerList.Visibility = TabServers.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        EmptyHint.Visibility = TabRooms.IsChecked == true && RoomList.Items.Count == 0
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private async Task RefreshAsync()
    {
        LoadingRing.Visibility = Visibility.Visible;
        StatusText.Text = "正在刷新…";

        if (!_api.IsLoggedIn)
        {
            var dlg = new LoginDialog
            {
                Owner = Window.GetWindow(this),
                SubmitAsync = async (register, d) =>
                {
                    var r = register
                        ? await _api.RegisterAsync(d.InputUsername, d.InputPassword, d.InputNickname)
                        : await _api.LoginAsync(d.InputUsername, d.InputPassword);
                    if (r.Success) { _ = RefreshAfterLogin(); return null; }
                    return r.Error;
                },
            };
            dlg.ShowDialog();
            if (!_api.IsLoggedIn)
            {
                LoadingRing.Visibility = Visibility.Collapsed;
                StatusText.Text = "未登录，仅显示公开信息";
            }
        }

        var rooms = await _api.GetRoomsAsync();
        var servers = await _api.GetServersAsync();

        if (rooms.Success)
        {
            RoomList.ItemsSource = rooms.Data;
            EmptyHint.Visibility = rooms.Data is { Count: > 0 }
                ? Visibility.Collapsed : Visibility.Visible;
        }
        else
        {
            StatusText.Text = rooms.Error;
        }

        if (servers.Success)
            ServerList.ItemsSource = servers.Data;

        LoadingRing.Visibility = Visibility.Collapsed;
        if (rooms.Success) StatusText.Text = $"共 {rooms.Data!.Count} 个房间";
        ApplyTab();
    }

    private async Task RefreshAfterLogin()
    {
        await Dispatcher.BeginInvoke(new Action(async () => await RefreshAsync()));
    }

    private void Tab_Checked(object sender, RoutedEventArgs e) => ApplyTab();

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    // ---------- 创建房间 ----------

    private async void CreateRoom_Click(object sender, RoutedEventArgs e)
    {
        if (!_api.IsLoggedIn)
        {
            StatusText.Text = "请先登录再创建房间";
            return;
        }

        var worlds = AppServices.Instance.Worlds.List();
        if (worlds.Count == 0)
        {
            StatusText.Text = "还没有存档，请先到“世界”页创建一个";
            return;
        }

        var panel = new StackPanel();
        var nameBox = FormDialog.NewTextBox("给房间起个名字");
        var worldBox = FormDialog.NewComboBox();
        worldBox.ItemsSource = worlds;
        worldBox.DisplayMemberPath = nameof(WorldInfo.Name);
        worldBox.SelectedIndex = 0;
        var maxBox = FormDialog.NewTextBox("8");
        maxBox.Text = "8";
        var descBox = FormDialog.NewTextBox("房间简介（可选）");
        var privateCheck = new CheckBox
        {
            Content = "仅好友可见",
            Foreground = Brushes.White,
            Margin = new Thickness(0, 4, 0, 0),
        };

        panel.Children.Add(FormDialog.Field("房间名", nameBox));
        panel.Children.Add(FormDialog.Field("存档", worldBox));
        panel.Children.Add(FormDialog.Field("人数上限（1-64）", maxBox, "填写数字，默认 8"));
        panel.Children.Add(FormDialog.Field("房间简介（可选）", descBox));
        panel.Children.Add(privateCheck);

        var dlg = new FormDialog("创建房间", panel, "创建", "取消")
        {
            Owner = Window.GetWindow(this),
        };
        if (dlg.ShowDialog() != true || dlg.ClickedButton != "创建") return;

        if (!int.TryParse(maxBox.Text, out var max) || max < 1 || max > 64) max = 8;

        var world = (WorldInfo)worldBox.SelectedItem!;
        var ok = await _host.StartAsync(
            roomName: string.IsNullOrWhiteSpace(nameBox.Text) ? world.Name : nameBox.Text.Trim(),
            worldDirName: world.DirName,
            gameId: world.GameId,
            port: 30000,
            maxPlayers: max,
            hasPassword: false,
            isPrivate: privateCheck.IsChecked == true,
            description: descBox.Text.Trim());

        if (!ok)
        {
            StatusText.Text = $"开房失败: {_host.LastError}";
            return;
        }
        HostCard.Visibility = Visibility.Visible;
        UpdateHostCard(_host.State);
        await RefreshAsync();
    }

    private async void StopHost_Click(object sender, RoutedEventArgs e)
    {
        await _host.StopAsync();
        HostCard.Visibility = Visibility.Collapsed;
        await RefreshAsync();
    }

    private void UpdateHostCard(HostState state)
    {
        HostCard.Visibility = state == HostState.Idle && _host.LastError is null
            ? Visibility.Collapsed : Visibility.Visible;
        HostStateText.Text = state switch
        {
            HostState.Starting => "正在启动…",
            HostState.Running => "运行中",
            HostState.Stopping => "正在关闭…",
            HostState.Error => $"出错: {_host.LastError}",
            _ => "空闲",
        };
        HostPlayersText.Text = $"在线 {_host.Players} 人";
    }

    private void AppendLog(string line)
    {
        const int maxLines = 30;
        var lines = HostLogText.Text.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var list = new List<string>(lines) { line };
        if (list.Count > maxLines) list.RemoveRange(0, list.Count - maxLines);
        HostLogText.Text = string.Join('\n', list);
    }

    // ---------- 加入 ----------

    private async void JoinRoom_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: RoomInfo room }) return;
        await JoinAsync(room.Host, room.Port);
    }

    private async void JoinServer_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: ServerInfo server }) return;
        await JoinAsync("127.0.0.1", server.Port);
    }

    private async Task JoinAsync(string host, int port)
    {
        var user = AppServices.Instance.Api.CurrentUser;
        try
        {
            StatusText.Text = $"正在连接 {host}:{port} …";
            await AppServices.Instance.Joiner.JoinAsync(host, port, user?.Nickname ?? "");
            StatusText.Text = "游戏已启动";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"连接失败: {ex.Message}";
        }
    }
}
