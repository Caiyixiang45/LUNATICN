using System.Windows;

namespace Lunaticn;

/// <summary>
/// LUNATICN 启动器应用程序入口。
/// </summary>
public partial class App : Application
{
    public new static Window? MainWindow { get; private set; }

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        MainWindow = new MainWindow();
        MainWindow.Show();
    }
}
