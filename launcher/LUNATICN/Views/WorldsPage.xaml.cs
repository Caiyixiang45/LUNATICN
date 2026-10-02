using System.Windows;
using System.Windows.Controls;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class WorldsPage : Page
{
    private readonly WorldService _worlds = AppServices.Instance.Worlds;

    public WorldsPage()
    {
        InitializeComponent();
        Loaded += (_, _) => Refresh();
    }

    private void Refresh()
    {
        var list = _worlds.List();
        WorldList.ItemsSource = list;
        EmptyHint.Visibility = list.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private Window Owner => Window.GetWindow(this);

    // ---------- 新建 ----------

    private void Create_Click(object sender, RoutedEventArgs e)
    {
        var nameBox = FormDialog.NewTextBox("例如：宁静谷地");
        var gameBox = FormDialog.NewComboBox();
        gameBox.ItemsSource = new[] { "minetest" };
        gameBox.SelectedIndex = 0;
        var modeBox = FormDialog.NewComboBox();
        modeBox.ItemsSource = new[] { "生存", "创造" };
        modeBox.SelectedIndex = 0;
        var seedBox = FormDialog.NewTextBox("留空随机");

        var panel = new StackPanel();
        panel.Children.Add(FormDialog.Field("存档名", nameBox));
        panel.Children.Add(FormDialog.Field("游戏", gameBox));
        panel.Children.Add(FormDialog.Field("模式", modeBox));
        panel.Children.Add(FormDialog.Field("种子（可选）", seedBox));

        var dlg = new FormDialog("新建存档", panel, "创建", "取消") { Owner = Owner };
        if (dlg.ShowDialog() != true || dlg.ClickedButton != "创建") return;

        var name = nameBox.Text.Trim();
        if (name.Length == 0)
        {
            StatusText.Text = "存档名不能为空";
            return;
        }
        try
        {
            _worlds.CreateWorld(name, gameBox.SelectedItem as string ?? "minetest",
                creative: modeBox.SelectedIndex == 1, seed: seedBox.Text.Trim());
            StatusText.Text = $"存档 {name} 创建成功";
            Refresh();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    // ---------- 进入 ----------

    private async void Play_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: WorldInfo world }) return;
        try
        {
            var exe = await AppServices.Instance.Engine.EnsureEngineAsync();
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = exe,
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(exe),
            };
            psi.ArgumentList.Add("--go");
            psi.ArgumentList.Add("--worldname");
            psi.ArgumentList.Add(world.DirName);
            if (!string.IsNullOrEmpty(world.GameId))
            {
                psi.ArgumentList.Add("--gameid");
                psi.ArgumentList.Add(world.GameId);
            }
            System.Diagnostics.Process.Start(psi);
            StatusText.Text = $"正在启动 {world.Name}…";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"启动失败: {ex.Message}";
        }
    }

    // ---------- 复制 ----------

    private void Copy_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: WorldInfo world }) return;
        var box = FormDialog.NewTextBox();
        box.Text = world.Name + "_副本";
        var panel = new StackPanel();
        panel.Children.Add(FormDialog.Field("新存档名", box));

        var dlg = new FormDialog("复制存档", panel, "复制", "取消") { Owner = Owner };
        if (dlg.ShowDialog() != true || dlg.ClickedButton != "复制") return;
        try
        {
            _worlds.CopyWorld(world.DirName, box.Text.Trim());
            StatusText.Text = "复制完成";
            Refresh();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    // ---------- 分享 ----------

    private async void Share_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: WorldInfo world }) return;
        if (!AppServices.Instance.Api.IsLoggedIn)
        {
            StatusText.Text = "请先登录再分享";
            return;
        }

        var nameBox = FormDialog.NewTextBox();
        nameBox.Text = world.Name;
        var verBox = FormDialog.NewTextBox();
        verBox.Text = "1.0.0";
        var descBox = FormDialog.NewTextBox("作品简介");
        descBox.AcceptsReturn = true;
        descBox.Height = 80;
        descBox.TextWrapping = TextWrapping.Wrap;
        descBox.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;

        var panel = new StackPanel();
        panel.Children.Add(FormDialog.Field("作品名", nameBox));
        panel.Children.Add(FormDialog.Field("版本", verBox));
        panel.Children.Add(FormDialog.Field("简介", descBox));

        var dlg = new FormDialog("分享地图", panel, "打包上传", "取消") { Owner = Owner };
        if (dlg.ShowDialog() != true || dlg.ClickedButton != "打包上传") return;

        try
        {
            StatusText.Text = "正在打包…";
            var tmpZip = Path.Combine(Path.GetTempPath(),
                $"lunaticn_{Guid.NewGuid():N}.lnpkg");
            var manifest = new Manifest
            {
                Type = "map",
                Name = string.IsNullOrWhiteSpace(nameBox.Text) ? world.Name : nameBox.Text.Trim(),
                Version = verBox.Text.Trim(),
                Description = descBox.Text.Trim(),
                GameId = world.GameId,
                Engine = AppServices.Instance.Engine.InstalledVersion ?? "",
                Author = AppServices.Instance.Api.CurrentUser?.Nickname ?? "",
            };
            PackageBuilder.BuildFromWorld(
                Path.Combine(_worlds.WorldsRoot, world.DirName), manifest, tmpZip);

            StatusText.Text = "正在上传…";
            var r = await AppServices.Instance.Api.UploadPackageAsync(tmpZip, null);
            File.Delete(tmpZip);
            StatusText.Text = r.Success ? $"已发布：{r.Data!.Name}" : $"上传失败: {r.Error}";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"分享失败: {ex.Message}";
        }
    }

    // ---------- 删除 ----------

    private void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: WorldInfo world }) return;
        if (!FormDialog.Confirm(Owner, "删除存档",
            $"确定删除“{world.Name}”？该操作不可恢复。")) return;
        try
        {
            _worlds.DeleteWorld(world.DirName);
            StatusText.Text = "已删除";
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
            Filter = "存档包 (*.zip;*.lnpkg)|*.zip;*.lnpkg",
            Multiselect = false,
        };
        if (picker.ShowDialog(Window.GetWindow(this)) != true) return;
        try
        {
            // 若为 .lnpkg（含 manifest），先解出 content/；否则整个 zip 当存档
            var tmp = Path.Combine(Path.GetTempPath(), $"lnimp_{Guid.NewGuid():N}");
            System.IO.Compression.ZipFile.ExtractToDirectory(picker.FileName, tmp);
            var content = Path.Combine(tmp, "content");
            var src = Directory.Exists(content) ? content : tmp;

            var worldDirs = Directory.GetDirectories(src);
            string importDir;
            if (worldDirs.Length == 1 && File.Exists(Path.Combine(worldDirs[0], "world.mt")))
                importDir = worldDirs[0];           // zip 根下包了一层世界目录
            else if (File.Exists(Path.Combine(src, "world.mt")))
                importDir = src;                     // zip 直接就是世界目录
            else
            {
                StatusText.Text = "无效的存档文件（未找到 world.mt）";
                Directory.Delete(tmp, true);
                return;
            }

            var name = Path.GetFileName(importDir);
            var dest = Path.Combine(_worlds.WorldsRoot, name);
            if (Directory.Exists(dest)) dest += "_" + Guid.NewGuid().ToString("N")[..4];
            CopyDir(importDir, dest);
            Directory.Delete(tmp, true);
            StatusText.Text = "导入完成";
            Refresh();
        }
        catch (Exception ex)
        {
            StatusText.Text = $"导入失败: {ex.Message}";
        }
    }

    private static void CopyDir(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var f in Directory.GetFiles(src))
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(src))
            CopyDir(d, Path.Combine(dst, Path.GetFileName(d)));
    }
}
