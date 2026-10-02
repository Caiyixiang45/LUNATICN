using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Lunaticn.Views;

/// <summary>替代 WinUI ContentDialog 的通用表单对话框。</summary>
public class FormDialog : Window
{
    public string? ClickedButton { get; private set; }

    public FormDialog(string title, UIElement content, params string[] buttons)
    {
        Title = title;
        Width = 440;
        SizeToContent = SizeToContent.Height;
        MaxHeight = 680;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        Background = (Brush)Application.Current.Resources["PageBrush"];
        BorderBrush = new SolidColorBrush(Color.FromRgb(0x2A, 0x33, 0x42));
        BorderThickness = new Thickness(1);
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;

        var root = new StackPanel { Margin = new Thickness(20) };

        root.Children.Add(new TextBlock
        {
            Text = title,
            FontSize = 18,
            FontWeight = FontWeights.Bold,
            Foreground = Brushes.White,
            Margin = new Thickness(0, 0, 0, 12),
        });

        var scroll = new ScrollViewer
        {
            Content = content,
            MaxHeight = 480,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Margin = new Thickness(0, 0, 0, 16),
        };
        root.Children.Add(scroll);

        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        foreach (var text in buttons)
        {
            var b = new Button
            {
                Content = text,
                MinWidth = 84,
                Margin = new Thickness(8, 0, 0, 0),
                Padding = new Thickness(12, 6, 12, 6),
                Cursor = System.Windows.Input.Cursors.Hand,
            };
            if (text == buttons[0])
            {
                b.Style = (Style)Application.Current.Resources["BrandButtonStyle"];
            }
            var captured = text;
            b.Click += (_, _) =>
            {
                ClickedButton = captured;
                DialogResult = true;
            };
            bar.Children.Add(b);
        }
        root.Children.Add(bar);

        Content = root;
    }

    /// <summary>一行“标签 + 控件”的纵向字段。</summary>
    public static StackPanel Field(string label, FrameworkElement control, string? hint = null)
    {
        var p = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
        p.Children.Add(new TextBlock
        {
            Text = label,
            Foreground = new SolidColorBrush(Color.FromRgb(0x7A, 0x86, 0x99)),
            FontSize = 12,
            Margin = new Thickness(0, 0, 0, 4),
        });
        p.Children.Add(control);
        if (!string.IsNullOrEmpty(hint))
        {
            p.Children.Add(new TextBlock
            {
                Text = hint,
                Foreground = new SolidColorBrush(Color.FromRgb(0x5C, 0x6B, 0x7F)),
                FontSize = 11,
                Margin = new Thickness(0, 4, 0, 0),
            });
        }
        return p;
    }

    public static TextBox NewTextBox(string? placeholder = null) => new()
    {
        Tag = placeholder,
        Padding = new Thickness(8, 6, 8, 6),
        Background = new SolidColorBrush(Color.FromRgb(0x14, 0x18, 0x1F)),
        Foreground = Brushes.White,
        BorderBrush = new SolidColorBrush(Color.FromRgb(0x2A, 0x33, 0x42)),
        CaretBrush = Brushes.White,
        ToolTip = placeholder,
    };

    public static PasswordBox NewPasswordBox(string? placeholder = null) => new()
    {
        Padding = new Thickness(8, 6, 8, 6),
        Background = new SolidColorBrush(Color.FromRgb(0x14, 0x18, 0x1F)),
        Foreground = Brushes.White,
        BorderBrush = new SolidColorBrush(Color.FromRgb(0x2A, 0x33, 0x42)),
        CaretBrush = Brushes.White,
        ToolTip = placeholder,
    };

    public static ComboBox NewComboBox() => new()
    {
        Padding = new Thickness(8, 6, 8, 6),
        Background = new SolidColorBrush(Color.FromRgb(0x14, 0x18, 0x1F)),
        Foreground = Brushes.White,
        BorderBrush = new SolidColorBrush(Color.FromRgb(0x2A, 0x33, 0x42)),
    };

    /// <summary>简单确认框。</summary>
    public static bool Confirm(Window owner, string title, string message)
    {
        var text = new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Foreground = Brushes.White,
        };
        var dlg = new FormDialog(title, text, "确定", "取消") { Owner = owner };
        return dlg.ShowDialog() == true && dlg.ClickedButton == "确定";
    }

    /// <summary>提示框。</summary>
    public static void Alert(Window owner, string title, string message)
    {
        var text = new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Foreground = Brushes.White,
        };
        var dlg = new FormDialog(title, text, "知道了") { Owner = owner };
        dlg.ShowDialog();
    }
}
