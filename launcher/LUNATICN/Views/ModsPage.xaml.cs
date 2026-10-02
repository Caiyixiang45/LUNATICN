using System.Windows;
using System.Windows.Controls;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class ModsPage : Page
{
    private readonly ModService _mods = AppServices.Instance.Mods;
    private readonly WorldService _worlds = AppServices.Instance.Worlds;

    public ModsPage()
    {
        InitializeComponent();
        Loaded += (_, _) => Refresh();
    }

    private void Refresh()
    {
        var list = _mods.List();
        ModList.ItemsSource = list;
        EmptyHint.Visibility = list.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private void Refresh_Click(object sender, RoutedEventArgs e) => Refresh();

    private Window Owner => Window.GetWindow(this);

    // ---------- 配置到存档 ----------

    private void Assign_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: ModInfo mod }) return;
        var worlds = _worlds.List();
        if (worlds.Count == 0)
        {
            StatusText.Text = "还没有存档，请先到“存档库”创建";
            return;
        }

        var worldBox = FormDialog.NewComboBox();
        worldBox.ItemsSource = worlds;
        worldBox.DisplayMemberPath = nameof(WorldInfo.Name);
        worldBox.SelectedIndex = 0;
        var panel = new StackPanel();
        panel.Children.Add(FormDialog.Field("目标存档", worldBox));

        var dlg = new FormDialog($"把“{mod.Title}”配置到存档", panel,
            "启用", "禁用", "取消") { Owner = Owner };
        if (dlg.ShowDialog() != true) return;
        if (dlg.ClickedButton == "取消" || dlg.ClickedButton is null) return;

        var world = (WorldInfo)worldBox.SelectedItem!;
        try
        {
            if (dlg.ClickedButton == "启用")
            {
                // 带依赖解析
                var (selected, order, missing) = _mods.ResolveDependencies(
                    world.EnabledMods.Append(mod.Name));
                if (missing.Count > 0)
                {
                    StatusText.Text = "缺失依赖: " + string.Join(", ", missing);
                    return;
                }
                _worlds.ApplyMods(world.DirName, selected);
                StatusText.Text = $"已启用 {selected.Count} 个模组（含依赖），加载顺序: "
                    + string.Join(" → ", order);
            }
            else
            {
                _worlds.SetModEnabled(world.DirName, mod.Name, false);
                StatusText.Text = $"已在存档“{world.Name}”中禁用 {mod.Name}";
            }
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    // ---------- 卸载 ----------

    private void Uninstall_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: ModInfo mod }) return;
        if (!FormDialog.Confirm(Owner, "卸载模组",
            $"确定卸载“{mod.Title}”？已启用它的存档将在下次启动时报错。")) return;
        try
        {
            _mods.Uninstall(mod.Name);
            StatusText.Text = "已卸载";
            Refresh();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    // ---------- 导入 ----------

    private void Import_Click(object sender, RoutedEventArgs e)
    {
        var picker = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "模组压缩包 (*.zip)|*.zip",
            Multiselect = false,
        };
        if (picker.ShowDialog(Owner) != true) return;
        try
        {
            var mod = _mods.InstallZip(picker.FileName);
            StatusText.Text = $"已安装: {mod.Title} ({mod.Name})";
            Refresh();
        }
        catch (Exception ex)
        {
            StatusText.Text = $"导入失败: {ex.Message}";
        }
    }
}
