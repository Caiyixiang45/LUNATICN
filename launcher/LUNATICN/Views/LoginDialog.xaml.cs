using System.Windows;

namespace Lunaticn.Views;

/// <summary>登录/注册对话框（WPF）。</summary>
public partial class LoginDialog : Window
{
    private bool _registerMode;

    public LoginDialog()
    {
        InitializeComponent();
    }

    public string InputUsername => UsernameBox.Text.Trim();
    public string InputPassword => PasswordBox1.Password;
    public string InputNickname => NicknameBox.Text.Trim();

    /// <summary>提交回调：返回 null 表示成功（关闭窗口），否则返回错误信息显示在窗口内。</summary>
    public Func<bool, LoginDialog, Task<string?>>? SubmitAsync { get; set; }

    private async void Primary_Click(object sender, RoutedEventArgs e)
    {
        if (!Validate()) return;
        if (SubmitAsync is null)
        {
            DialogResult = true;
            return;
        }
        PrimaryBtn.IsEnabled = false;
        SecondaryBtn.IsEnabled = false;
        try
        {
            var error = await SubmitAsync(_registerMode, this);
            if (error is null) DialogResult = true;
            else ErrorText.Text = error;
        }
        finally
        {
            PrimaryBtn.IsEnabled = true;
            SecondaryBtn.IsEnabled = true;
        }
    }

    private void Secondary_Click(object sender, RoutedEventArgs e)
    {
        _registerMode = !_registerMode;
        TitleText.Text = _registerMode ? "注册 LUNATICN 账号" : "登录 LUNATICN";
        PrimaryBtn.Content = _registerMode ? "创建账号" : "登录";
        SecondaryBtn.Content = _registerMode ? "去登录" : "注册";
        NickPanel.Visibility = _registerMode ? Visibility.Visible : Visibility.Collapsed;
        ErrorText.Text = "";
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
    }

    private bool Validate()
    {
        if (InputUsername.Length < 3)
        {
            ErrorText.Text = "用户名至少 3 个字符";
            return false;
        }
        if (InputPassword.Length < 6)
        {
            ErrorText.Text = "密码至少 6 位";
            return false;
        }
        ErrorText.Text = "";
        return true;
    }

    public void ShowError(string msg) => ErrorText.Text = msg;
}
