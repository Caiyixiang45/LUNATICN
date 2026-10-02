using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Lunaticn.Models;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class FriendsPage : Page
{
    private readonly ApiClient _api = AppServices.Instance.Api;
    private List<FriendRequestInfo> _incoming = new();

    public FriendsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        if (!_api.IsLoggedIn)
        {
            StatusText.Text = "请先登录后查看好友";
            return;
        }
        var r = await _api.GetFriendsAsync();
        if (r.Success)
        {
            FriendList.ItemsSource = r.Data;
            EmptyHint.Visibility = r.Data is { Count: > 0 }
                ? Visibility.Collapsed : Visibility.Visible;
        }
        else StatusText.Text = r.Error;
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async void AddFriend_Click(object sender, RoutedEventArgs e)
    {
        if (!_api.IsLoggedIn) { StatusText.Text = "请先登录"; return; }
        var name = AddBox.Text.Trim();
        if (name.Length == 0) { StatusText.Text = "请输入用户名"; return; }
        var r = await _api.AddFriendAsync(name);
        StatusText.Text = r.Success ? $"已向 {name} 发送好友申请" : r.Error;
        if (r.Success) AddBox.Text = "";
    }

    private async void Requests_Click(object sender, RoutedEventArgs e)
    {
        if (!_api.IsLoggedIn) { StatusText.Text = "请先登录"; return; }
        var r = await _api.GetFriendRequestsAsync();
        if (!r.Success) { StatusText.Text = r.Error; return; }

        var data = r.Data!;
        _incoming = data.Where(x => x.Direction == "in").ToList();
        var outgoing = data.Where(x => x.Direction == "out").ToList();

        if (_incoming.Count == 0 && outgoing.Count == 0)
        {
            StatusText.Text = "暂无好友申请";
            return;
        }

        var panel = new StackPanel();
        if (_incoming.Count > 0)
        {
            panel.Children.Add(new TextBlock
            {
                Text = "收到的申请",
                FontWeight = FontWeights.SemiBold,
                Foreground = Brushes.White,
                Margin = new Thickness(0, 0, 0, 4),
            });
            foreach (var req in _incoming)
            {
                panel.Children.Add(new TextBlock
                {
                    Text = $"{req.User?.Nickname}（{req.User?.Username}）",
                    Foreground = Brushes.LightGray,
                    Margin = new Thickness(0, 0, 0, 4),
                });
            }
        }
        if (outgoing.Count > 0)
        {
            panel.Children.Add(new TextBlock
            {
                Text = "我发出的",
                FontWeight = FontWeights.SemiBold,
                Foreground = Brushes.White,
                Margin = new Thickness(0, 8, 0, 4),
            });
            foreach (var req in outgoing)
            {
                panel.Children.Add(new TextBlock
                {
                    Text = $"{req.User?.Nickname}（{req.User?.Username}）",
                    Foreground = Brushes.Gray,
                    Margin = new Thickness(0, 0, 0, 4),
                });
            }
        }

        string[] buttons = _incoming.Count > 0
            ? new[] { "全部接受", "全部拒绝", "取消" }
            : new[] { "关闭" };
        var dlg = new FormDialog("好友申请", panel, buttons)
        {
            Owner = Window.GetWindow(this),
        };
        var clicked = dlg.ShowDialog() == true ? dlg.ClickedButton : null;

        if (_incoming.Count > 0 &&
            (clicked == "全部接受" || clicked == "全部拒绝"))
        {
            var accept = clicked == "全部接受";
            foreach (var req in _incoming)
            {
                if (req.User is not null)
                    await _api.RespondFriendAsync(req.User.Id, accept);
            }
            StatusText.Text = accept ? "已接受全部申请" : "已拒绝全部申请";
            await RefreshAsync();
        }
    }

    private async void Invite_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: FriendInfo friend }) return;
        var host = AppServices.Instance.RoomHost;
        if (host.State != HostState.Running)
        {
            StatusText.Text = "先去大厅开一个房间，才能邀请好友";
            return;
        }
        StatusText.Text = $"已向 {friend.Nickname} 发送房间邀请（好友会在客户端收到推送）";
        await Task.CompletedTask;
    }

    private void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: FriendInfo friend }) return;
        if (!FormDialog.Confirm(Window.GetWindow(this), "删除好友",
            $"确定删除好友 {friend.Nickname}？")) return;
        _ = RemoveCoreAsync(friend);
    }

    private async Task RemoveCoreAsync(FriendInfo friend)
    {
        var r = await _api.RemoveFriendAsync(friend.Id);
        StatusText.Text = r.Success ? "已删除" : r.Error;
        if (r.Success) await RefreshAsync();
    }
}
