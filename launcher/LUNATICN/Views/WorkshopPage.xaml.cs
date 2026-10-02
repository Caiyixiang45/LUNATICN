using System.IO.Compression;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Lunaticn.Models;
using Lunaticn.Services;

namespace Lunaticn.Views;

public partial class WorkshopPage : Page
{
    private readonly ApiClient _api = AppServices.Instance.Api;

    public WorkshopPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await SearchAsync();
    }

    private string SelectedType =>
        (TypeBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "";

    private async Task SearchAsync(string? query = null)
    {
        StatusText.Text = "正在加载…";
        var r = await _api.SearchPackagesAsync(
            SelectedType, query ?? QueryBox.Text.Trim(), 50, 0);
        if (r.Success)
        {
            var (total, items) = r.Data;
            PackageList.ItemsSource = items;
            StatusText.Text = $"共 {total} 个作品";
            if (total == 0) StatusText.Text = "没有找到作品，换个关键词试试";
        }
        else
        {
            StatusText.Text = r.Error;
        }
    }

    private async void Search_Click(object sender, RoutedEventArgs e) => await SearchAsync();

    private async void Query_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) await SearchAsync();
    }

    private async void Mine_Click(object sender, RoutedEventArgs e)
    {
        if (!_api.IsLoggedIn)
        {
            StatusText.Text = "请先登录";
            return;
        }
        StatusText.Text = "正在加载…";
        var r = await _api.GetMyPackagesAsync();
        if (r.Success)
        {
            PackageList.ItemsSource = r.Data;
            StatusText.Text = $"我的作品 {r.Data!.Count} 个";
        }
        else StatusText.Text = r.Error;
    }

    // ---------- 下载 ----------

    private async void Download_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: PackageInfo pkg }) return;
        try
        {
            StatusText.Text = "正在下载…";
            var cacheDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "LUNATICN", "downloads");
            Directory.CreateDirectory(cacheDir);
            var dest = Path.Combine(cacheDir, $"{pkg.Id}.lnpkg");

            var dl = await _api.DownloadPackageAsync(pkg.Id, dest);
            if (!dl.Success)
            {
                StatusText.Text = dl.Error;
                return;
            }

            if (pkg.Type == "mod")
            {
                var mod = AppServices.Instance.Mods.InstallZip(dest);
                StatusText.Text = $"模组已安装: {mod.Title}";
            }
            else
            {
                ImportWorld(dest);
                StatusText.Text = $"地图已导入存档库: {pkg.Name}";
            }
            File.Delete(dest);
        }
        catch (Exception ex)
        {
            StatusText.Text = $"下载失败: {ex.Message}";
        }
    }

    /// <summary>把 .lnpkg 的 content/ 导入为存档。</summary>
    private void ImportWorld(string lnpkgPath)
    {
        var tmp = Path.Combine(Path.GetTempPath(), $"lnwk_{Guid.NewGuid():N}");
        ZipFile.ExtractToDirectory(lnpkgPath, tmp);
        try
        {
            var content = Path.Combine(tmp, "content");
            var src = Directory.Exists(content) ? content : tmp;
            var worlds = AppServices.Instance.Worlds;

            // content/ 直接是世界目录，或其下包一层
            string importDir;
            if (File.Exists(Path.Combine(src, "world.mt"))) importDir = src;
            else
            {
                var sub = Directory.GetDirectories(src)
                    .FirstOrDefault(d => File.Exists(Path.Combine(d, "world.mt")));
                if (sub is null) throw new InvalidDataException("包内没有 world.mt");
                importDir = sub;
            }

            var name = Path.GetFileName(importDir);
            var dest = Path.Combine(worlds.WorldsRoot, name);
            if (Directory.Exists(dest)) dest += "_" + Guid.NewGuid().ToString("N")[..4];
            CopyDir(importDir, dest);
        }
        finally
        {
            Directory.Delete(tmp, true);
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

    // ---------- 删除 ----------

    private async void DeletePackage_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { CommandParameter: PackageInfo pkg }) return;
        if (!_api.IsLoggedIn)
        {
            StatusText.Text = "请先登录";
            return;
        }
        if (!FormDialog.Confirm(Window.GetWindow(this), "删除作品",
            $"确定删除“{pkg.Name}”？（仅作者可删除）")) return;

        var r = await _api.DeletePackageAsync(pkg.Id);
        StatusText.Text = r.Success ? "已删除" : r.Error;
        if (r.Success) await SearchAsync();
    }
}
