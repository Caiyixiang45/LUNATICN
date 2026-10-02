using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Lunaticn;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();

        NavList.SelectedIndex = 0;
        Navigate("lobby");

        // 标题栏显示账号
        Services.AppServices.Instance.Api.AuthChanged += () =>
            Dispatcher.BeginInvoke(UpdateAccountText);
        _ = Services.AppServices.Instance.Api.RestoreSessionAsync();
        UpdateAccountText();
    }

    private void UpdateAccountText()
    {
        var api = Services.AppServices.Instance.Api;
        AccountText.Text = api.CurrentUser is { } u
            ? $"{u.Nickname} ({u.Username})"
            : "未登录";
    }

    private void NavList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (NavList.SelectedItem is ListViewItem item && item.Tag is string tag)
            Navigate(tag);
    }

    private void Navigate(string tag)
    {
        Type page = tag switch
        {
            "lobby" => typeof(Views.LobbyPage),
            "worlds" => typeof(Views.WorldsPage),
            "mods" => typeof(Views.ModsPage),
            "workshop" => typeof(Views.WorkshopPage),
            "friends" => typeof(Views.FriendsPage),
            "settings" => typeof(Views.SettingsPage),
            _ => typeof(Views.LobbyPage),
        };
        ContentFrame.Navigate(page);
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal
                : WindowState.Maximized;
        else
            DragMove();
    }

    private void MinButton_Click(object sender, RoutedEventArgs e)
        => WindowState = WindowState.Minimized;

    private void CloseButton_Click(object sender, RoutedEventArgs e)
        => Close();
}
