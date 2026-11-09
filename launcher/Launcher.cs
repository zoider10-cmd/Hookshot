// Mako Launcher (Ocarina of Time PC recompile, by sharkiix; based on Hookshot, GPL-3). The window players open first: update
// check (the same GitHub release and graphics patch rules as host/hos_update.c), the game's settings (hookshot_options.ini, the
// Insert menu's file), the AMD fix switches (hookshot_env.txt, read by the game at start), language, saves folders, and PLAY.
// It sits beside the game's exe. One window drawn by hand (no stock controls): a dark navy theme taken from the shark logo,
// animated light streaks and bubbles, hover fades. Built with the .NET Framework's own csc (C# 5, nothing to install): build.ps1.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Mako Launcher")]
[assembly: System.Reflection.AssemblyProduct("Mako")]
[assembly: System.Reflection.AssemblyCompany("sharkiix")]
[assembly: System.Reflection.AssemblyVersion("3.0.0.0")]

static class Fork {
    public const string Name = "Mako";
    // (the update check compares the first number of the tags: the first Mako release must be numbered above amd-fix-2.1, or the
    // 2.x launchers players have would think it older and never offer it)
    public const string Base = "mako-3.0";      // (host/hos_update.c HOOKSHOT_FORK_BASE: the exe this launcher ships with)
    public const string Version = "mako-3.0.1"; // (HOOKSHOT_FORK_VERSION)
    public const int Api = 7;                   // (gpu/vk/vk_api.h MKWVK_API_VERSION)
    public const string Api_Url = "https://api.github.com/repos/Shakoquo/Hookshot/releases/latest";
    public const string Page = "https://github.com/Shakoquo/Hookshot/releases/latest";
    public const string Home = "https://github.com/Shakoquo/Hookshot";
    public const string GameExe = "hookshot.exe";
    public static string Shown(string v) { var m = Regex.Match(v ?? "", @"\d+(\.\d+)*"); return m.Success ? "v" + m.Value : v; }
}

static class Theme {
    public static readonly Color Bg0 = Color.FromArgb(5, 8, 15);
    public static readonly Color Bg1 = Color.FromArgb(10, 18, 34);
    public static readonly Color Card = Color.FromArgb(14, 22, 38);
    public static readonly Color CardHi = Color.FromArgb(20, 32, 54);
    public static readonly Color Line = Color.FromArgb(32, 48, 78);
    public static readonly Color Text = Color.FromArgb(234, 241, 255);
    public static readonly Color Dim = Color.FromArgb(132, 148, 178);
    public static readonly Color Faint = Color.FromArgb(78, 92, 120);
    public static readonly Color Blue = Color.FromArgb(46, 123, 255);
    public static readonly Color Cyan = Color.FromArgb(56, 200, 255);
    public static readonly Color Green = Color.FromArgb(61, 220, 151);
    public static readonly Color Amber = Color.FromArgb(255, 181, 71);
    public static readonly Color Red = Color.FromArgb(255, 90, 106);

    public static Color Mix(Color a, Color b, float t) {
        t = Math.Max(0, Math.Min(1, t));
        return Color.FromArgb((int)(a.A + (b.A - a.A) * t), (int)(a.R + (b.R - a.R) * t), (int)(a.G + (b.G - a.G) * t), (int)(a.B + (b.B - a.B) * t));
    }
    public static Color A(Color c, int a) { return Color.FromArgb(Math.Max(0, Math.Min(255, a)), c); }
    public static GraphicsPath Round(RectangleF r, float rad) {
        var p = new GraphicsPath();
        float d = Math.Min(rad * 2, Math.Min(r.Width, r.Height));
        if (d <= 0.5f) { p.AddRectangle(r); return p; }
        p.AddArc(r.X, r.Y, d, d, 180, 90);
        p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }
    static HashSet<string> installed;
    public static Font Pick(float size, FontStyle style, params string[] names) {
        if (installed == null) {
            installed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using (var fonts = new InstalledFontCollection()) foreach (var f in fonts.Families) installed.Add(f.Name);
        }
        foreach (var n in names) if (installed.Contains(n)) return new Font(n, size, style, GraphicsUnit.Pixel);
        return new Font("Segoe UI", size, style, GraphicsUnit.Pixel);
    }
    public static readonly Font Small = Pick(12f, FontStyle.Regular, "Segoe UI");
    public static readonly Font Body = Pick(13.5f, FontStyle.Regular, "Segoe UI");
    public static readonly Font Label = Pick(11.5f, FontStyle.Bold, "Segoe UI Semibold", "Segoe UI");
    public static readonly Font Value = Pick(15f, FontStyle.Regular, "Segoe UI Semibold", "Segoe UI");
    public static readonly Font Strong = Pick(15f, FontStyle.Regular, "Segoe UI Semibold", "Segoe UI");
    public static readonly Font Tab = Pick(15f, FontStyle.Regular, "Segoe UI Semibold", "Segoe UI");
    public static readonly Font Mark = Pick(52f, FontStyle.Bold, "Bahnschrift", "Segoe UI Black", "Segoe UI");
    public static readonly Font Play = Pick(24f, FontStyle.Bold, "Bahnschrift", "Segoe UI Black", "Segoe UI");
    public static readonly Font Caps = Pick(11f, FontStyle.Regular, "Bahnschrift", "Segoe UI");

    public static void Text_(Graphics g, string s, Font f, Color c, RectangleF r, StringAlignment h, StringAlignment v) {
        using (var b = new SolidBrush(c))
        using (var fmt = new StringFormat { Alignment = h, LineAlignment = v, Trimming = StringTrimming.EllipsisCharacter })
            g.DrawString(s, f, b, r, fmt);
    }
    // (letter-spaced capitals, centred on cx)
    public static void Spaced(Graphics g, string s, Font f, Brush b, float cx, float y, float spacing) {
        var fmt = StringFormat.GenericTypographic;
        float total = 0;
        var w = new float[s.Length];
        for (int i = 0; i < s.Length; i++) { w[i] = g.MeasureString(s[i].ToString(), f, 1000, fmt).Width; total += w[i]; }
        total += spacing * (s.Length - 1);
        float x = cx - total / 2;
        for (int i = 0; i < s.Length; i++) { g.DrawString(s[i].ToString(), f, b, x, y, fmt); x += w[i] + spacing; }
    }
}

// ---- the widgets: rectangles the window paints and hit-tests itself ----
abstract class Widget {
    public RectangleF R;
    public int Page = -1;        // (-1: always shown; else the tab it belongs to)
    public float Hover;          // (0..1, eased toward the mouse)
    public bool Enabled = true;
    public virtual string Help { get { return null; } }
    public virtual bool Hit(PointF p) { return Enabled && R.Contains(p); }
    public abstract void Paint(Graphics g, LauncherForm ui);
    public virtual void Down(PointF p, LauncherForm ui) { }
    public virtual bool Animating { get { return false; } }
    public virtual void Tick() { }
}

class Btn : Widget {
    public enum Kind { Ghost, Primary, Play, Link }
    public string Text; public Kind Style; public Action Click; public Font Font = Theme.Strong;
    public override void Down(PointF p, LauncherForm ui) { if (Click != null) Click(); }
    public override void Paint(Graphics g, LauncherForm ui) {
        float h = Hover;
        if (Style == Kind.Link) {
            Theme.Text_(g, Text, Theme.Small, Theme.Mix(Theme.Dim, Theme.Cyan, h), R, StringAlignment.Near, StringAlignment.Center);
            return;
        }
        if (Style == Kind.Play) { PaintPlay(g, ui); return; }
        using (var path = Theme.Round(R, 10)) {
            if (Style == Kind.Primary && Enabled) {
                using (var br = new LinearGradientBrush(R, Theme.Mix(Theme.Blue, Theme.Cyan, h * 0.5f), Theme.Mix(Color.FromArgb(28, 92, 220), Theme.Blue, h),
                                                        LinearGradientMode.ForwardDiagonal)) g.FillPath(br, path);
                using (var pen = new Pen(Theme.A(Color.White, 40 + (int)(50 * h)), 1f)) g.DrawPath(pen, path);
            } else {
                using (var br = new SolidBrush(Theme.Mix(Theme.Card, Theme.CardHi, h))) g.FillPath(br, path);
                using (var pen = new Pen(Theme.Mix(Theme.Line, Theme.Blue, h), 1f)) g.DrawPath(pen, path);
            }
        }
        Color fg = !Enabled ? Theme.Faint : Style == Kind.Primary ? Color.White : Theme.Mix(Theme.Text, Color.White, h);
        Theme.Text_(g, Text, Font, fg, R, StringAlignment.Center, StringAlignment.Center);
    }
    void PaintPlay(Graphics g, LauncherForm ui) {
        float t = ui.Time, h = Hover;
        float pulse = 0.5f + 0.5f * (float)Math.Sin(t * 2.2);
        // (the glow under it, breathing)
        for (int i = 8; i >= 1; i--) {
            var gr = RectangleF.Inflate(R, i * 2.2f, i * 2.2f);
            using (var p = Theme.Round(gr, 16 + i * 2))
            using (var b = new SolidBrush(Theme.A(Theme.Blue, (int)((5 + 6 * pulse + 8 * h) * (Enabled ? 1 : 0.2f))))) g.FillPath(b, p);
        }
        using (var path = Theme.Round(R, 16)) {
            using (var br = new LinearGradientBrush(R, Theme.Mix(Color.FromArgb(30, 110, 255), Theme.Cyan, h * 0.4f), Theme.Mix(Color.FromArgb(22, 70, 200), Theme.Blue, h),
                                                    LinearGradientMode.Vertical)) g.FillPath(br, path);
            // (a shine sweeping across now and then)
            float sweep = (t % 4.5f) / 1.3f;
            if (sweep < 1) {
                float x = R.X - 120 + (R.Width + 240) * sweep;
                var band = new RectangleF(x, R.Y, 120, R.Height);
                var state = g.Save();
                g.SetClip(path);
                using (var br = new LinearGradientBrush(new RectangleF(x - 1, R.Y, 122, R.Height), Color.FromArgb(0, 255, 255, 255), Color.FromArgb(0, 255, 255, 255), 0f)) {
                    var blend = new ColorBlend(3);
                    blend.Colors = new[] { Color.FromArgb(0, 255, 255, 255), Color.FromArgb(70, 255, 255, 255), Color.FromArgb(0, 255, 255, 255) };
                    blend.Positions = new[] { 0f, 0.5f, 1f };
                    br.InterpolationColors = blend;
                    g.FillRectangle(br, band);
                }
                g.Restore(state);
            }
            using (var top = new LinearGradientBrush(new RectangleF(R.X, R.Y, R.Width, R.Height / 2 + 1), Color.FromArgb(50, 255, 255, 255), Color.FromArgb(0, 255, 255, 255), LinearGradientMode.Vertical)) {
                var state = g.Save(); g.SetClip(path); g.FillRectangle(top, R.X, R.Y, R.Width, R.Height / 2); g.Restore(state);
            }
            using (var pen = new Pen(Color.FromArgb(90, 255, 255, 255), 1.2f)) g.DrawPath(pen, path);
        }
        using (var b = new SolidBrush(Enabled ? Color.White : Theme.A(Color.White, 120)))
            Theme.Spaced(g, Text, Theme.Play, b, R.X + R.Width / 2, R.Y + R.Height / 2 - Theme.Play.Size * 0.62f, 6);
    }
    public override bool Animating { get { return Style == Kind.Play; } }
}

// (a setting: its name above, the choice below, arrows on the right; a click on the choice opens the list)
class Selector : Widget {
    public string Key, Label, HelpText; public string[] Items; public int[] Values; public int Index;
    public Action<Selector> Changed;
    float flash;
    public override string Help { get { return HelpText; } }
    RectangleF Left { get { return new RectangleF(R.Right - 72, R.Y + 14, 30, R.Height - 28); } }
    RectangleF Right { get { return new RectangleF(R.Right - 38, R.Y + 14, 30, R.Height - 28); } }
    public void Set(int i, bool notify) {
        i = Math.Max(0, Math.Min(Items.Length - 1, i));
        if (i == Index) return;
        Index = i; flash = 1;
        if (notify && Changed != null) Changed(this);
    }
    public int Value { get { return Values[Math.Max(0, Index)]; } }
    public override void Down(PointF p, LauncherForm ui) {
        if (Left.Contains(p)) { Set(Index - 1, true); return; }
        if (Right.Contains(p)) { Set(Index + 1, true); return; }
        ui.ShowList(this);
    }
    public override bool Animating { get { return flash > 0; } }
    public override void Tick() { flash = Math.Max(0, flash - 0.08f); }
    public override void Paint(Graphics g, LauncherForm ui) {
        float h = Hover;
        using (var path = Theme.Round(R, 12)) {
            using (var br = new SolidBrush(Theme.Mix(Theme.Card, Theme.CardHi, h))) g.FillPath(br, path);
            using (var pen = new Pen(Theme.Mix(Theme.Line, Theme.A(Theme.Blue, 200), Math.Max(h, flash)), 1f)) g.DrawPath(pen, path);
        }
        // (a thin accent on the left edge, lit on hover)
        using (var b = new SolidBrush(Theme.A(Theme.Cyan, (int)(40 + 180 * Math.Max(h, flash)))))
            using (var p = Theme.Round(new RectangleF(R.X + 1, R.Y + 14, 3, R.Height - 28), 1.5f)) g.FillPath(b, p);
        Theme.Text_(g, Label.ToUpperInvariant(), Theme.Label, Theme.Dim, new RectangleF(R.X + 16, R.Y + 9, R.Width - 90, 18), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, Index >= 0 ? Items[Index] : "", Theme.Value, Theme.Mix(Theme.Text, Color.White, flash),
                    new RectangleF(R.X + 16, R.Y + 27, R.Width - 92, 24), StringAlignment.Near, StringAlignment.Near);
        Arrow(g, Left, true, Index > 0, ui.MouseIn(Left));
        Arrow(g, Right, false, Index < Items.Length - 1, ui.MouseIn(Right));
    }
    static void Arrow(Graphics g, RectangleF r, bool left, bool on, bool over) {
        if (over && on) using (var p = Theme.Round(r, 8)) using (var b = new SolidBrush(Theme.A(Theme.Blue, 60))) g.FillPath(b, p);
        float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2, s = 4.5f;
        using (var pen = new Pen(on ? (over ? Color.White : Theme.Dim) : Theme.A(Theme.Faint, 120), 2f) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round })
            if (left) g.DrawLines(pen, new[] { new PointF(cx + s * 0.5f, cy - s), new PointF(cx - s * 0.5f, cy), new PointF(cx + s * 0.5f, cy + s) });
            else g.DrawLines(pen, new[] { new PointF(cx - s * 0.5f, cy - s), new PointF(cx + s * 0.5f, cy), new PointF(cx - s * 0.5f, cy + s) });
    }
}

// (an on/off switch with its explanation)
class Toggle : Widget {
    public string Key, Label, HelpText; public bool On; public Action<Toggle> Changed;
    float knob;   // (0..1, follows On)
    public override string Help { get { return HelpText; } }
    public override void Down(PointF p, LauncherForm ui) { On = !On; if (Changed != null) Changed(this); }
    public void Snap() { knob = On ? 1 : 0; }
    public override bool Animating { get { return Math.Abs(knob - (On ? 1 : 0)) > 0.01f; } }
    public override void Tick() { knob += ((On ? 1 : 0) - knob) * 0.25f; }
    public override void Paint(Graphics g, LauncherForm ui) {
        float h = Hover;
        using (var path = Theme.Round(R, 12)) {
            using (var br = new SolidBrush(Theme.Mix(Theme.Card, Theme.CardHi, h))) g.FillPath(br, path);
            using (var pen = new Pen(Theme.Mix(Theme.Line, Theme.A(Theme.Blue, 200), h), 1f)) g.DrawPath(pen, path);
        }
        Theme.Text_(g, Label, Theme.Strong, Theme.Text, new RectangleF(R.X + 20, R.Y + 14, R.Width - 110, 22), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, HelpText, Theme.Small, Theme.Dim, new RectangleF(R.X + 20, R.Y + 40, R.Width - 110, R.Height - 46), StringAlignment.Near, StringAlignment.Near);
        var sw = new RectangleF(R.Right - 74, R.Y + R.Height / 2 - 13, 52, 26);
        using (var p = Theme.Round(sw, 13)) {
            using (var b = new SolidBrush(Theme.Mix(Color.FromArgb(34, 44, 66), Theme.Blue, knob))) g.FillPath(b, p);
            using (var pen = new Pen(Theme.Mix(Theme.Line, Theme.Cyan, knob * 0.6f), 1f)) g.DrawPath(pen, p);
        }
        float kx = sw.X + 3 + (sw.Width - 26) * knob;
        using (var b = new SolidBrush(Theme.A(Color.Black, 70))) g.FillEllipse(b, kx, sw.Y + 4, 20, 20);
        using (var b = new SolidBrush(Color.White)) g.FillEllipse(b, kx, sw.Y + 3, 20, 20);
    }
}

class TabW : Widget {
    public string Text; public int Index;
    public override void Down(PointF p, LauncherForm ui) { ui.ShowPage(Index); }
    public override void Paint(Graphics g, LauncherForm ui) {
        bool on = ui.PageNow == Index;
        Theme.Text_(g, Text, Theme.Tab, on ? Color.White : Theme.Mix(Theme.Dim, Theme.Text, Hover), R, StringAlignment.Center, StringAlignment.Center);
    }
}

class TitleBtn : Widget {
    public bool Close; public Action Click;
    public override void Down(PointF p, LauncherForm ui) { if (Click != null) Click(); }
    public override void Paint(Graphics g, LauncherForm ui) {
        if (Hover > 0.01f)
            using (var b = new SolidBrush(Theme.A(Close ? Color.FromArgb(232, 17, 35) : Color.White, (int)((Close ? 230 : 22) * Hover)))) g.FillRectangle(b, R);
        float cx = R.X + R.Width / 2, cy = R.Y + R.Height / 2;
        using (var pen = new Pen(Theme.Mix(Theme.Dim, Color.White, Hover), 1.3f)) {
            if (Close) { g.DrawLine(pen, cx - 5, cy - 5, cx + 5, cy + 5); g.DrawLine(pen, cx - 5, cy + 5, cx + 5, cy - 5); }
            else g.DrawLine(pen, cx - 5, cy, cx + 5, cy);
        }
    }
}

// (the drop-down list in the theme)
class DarkMenu : ToolStripProfessionalRenderer {
    protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e) {
        using (var b = new SolidBrush(Color.FromArgb(16, 25, 43))) e.Graphics.FillRectangle(b, e.AffectedBounds);
    }
    protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) {
        using (var p = new Pen(Theme.Line)) e.Graphics.DrawRectangle(p, 0, 0, e.AffectedBounds.Width - 1, e.AffectedBounds.Height - 1);
    }
    protected override void OnRenderImageMargin(ToolStripRenderEventArgs e) { }
    protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) {
        var r = new Rectangle(3, 1, e.Item.Width - 6, e.Item.Height - 2);
        if (e.Item.Selected)
            using (var p = Theme.Round(r, 6)) using (var b = new SolidBrush(Theme.A(Theme.Blue, 150))) { e.Graphics.SmoothingMode = SmoothingMode.AntiAlias; e.Graphics.FillPath(b, p); }
    }
    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e) {
        e.TextColor = e.Item.Selected ? Color.White : (((ToolStripMenuItem)e.Item).Checked ? Theme.Cyan : Theme.Text);
        base.OnRenderItemText(e);
    }
    protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e) {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        float cx = e.ImageRectangle.X + e.ImageRectangle.Width / 2f, cy = e.ImageRectangle.Y + e.ImageRectangle.Height / 2f;
        using (var b = new SolidBrush(Theme.Cyan)) g.FillEllipse(b, cx - 3.5f, cy - 3.5f, 7, 7);
    }
}

class LauncherForm : Form {
    readonly string dir;
    readonly string optionsPath, envPath, langPath;
    readonly List<Widget> widgets = new List<Widget>();
    readonly Dictionary<string, Selector> settings = new Dictionary<string, Selector>();
    readonly Dictionary<string, Toggle> fixes = new Dictionary<string, Toggle>();
    readonly List<TabW> tabs = new List<TabW>();
    Selector langSel;
    Btn updateButton, playButton;
    Image logo;
    Bitmap backdrop;
    readonly System.Windows.Forms.Timer timer;
    readonly Stopwatch clock = Stopwatch.StartNew();
    public float Time;
    public int PageNow;
    float tabX, tabW;        // (the underline under the current tab, eased)
    float pageFade = 1;      // (0..1 as a page appears)
    float helpFade; string helpShown = "";
    PointF mouse = new PointF(-1, -1);
    Widget pressed;
    bool loading;
    int randoSeed;          // (rando_seed: the randomizer seed's random part, 0 none yet)
    bool randoDropImport;   // (a randomizer setting was changed here: a rando_import line still in the file would undo it at the game's start)
    // (update card)
    Color updDot = Theme.Faint; string updTitle = "Checking for updates…", updLine = "";
    float updProgress = -1;  // (-1: none; else 0..1)
    string patchDll, patchTag; long patchSize;
    string rebuildTag, builderZip; long builderZipSize;   // (a release that needs the game built again)
    // (bubbles rising in the left panel)
    struct Bubble { public float X, Y, R, V, P; }
    readonly Bubble[] bubbles = new Bubble[26];
    readonly Random rnd = new Random(7);

    const int W = 1120, H = 680, LeftW = 400;

    // (key in hookshot_options.ini, label, choices shown, the value each choice writes, help)
    static readonly object[][] GraphicsRows = {
        new object[] { "quality_preset", "Quality preset", new[] { "Custom", "Minimum (4 GB)", "Low (6 GB)", "Balanced (8 GB)", "High (12 GB)", "Ultra (16 GB+)" }, new[] { 0, 1, 2, 3, 4, 5 },
            "Sets the settings below for your graphics card's memory. Changing one of them by hand makes it Custom." },
        new object[] { "output_res", "Output resolution", new[] { "2048 x 1152 (the game's)", "2560 x 1440", "3840 x 2160 (4K)" }, new[] { 0, 1, 2 },
            "The size the game draws its whole picture at, menus included, before it is fitted to your screen. Higher is sharper and heavier." },
        new object[] { "resolution", "3D resolution", new[] { "Auto", "100%", "75%", "67%", "50%" }, new[] { 0, 1, 2, 3, 4 },
            "How sharp the 3D is drawn, as a share of the output resolution. Auto lowers it when the graphics card is busy." },
        new object[] { "upscaling", "Upscaling", new[] { "Off", "Catmull-Rom", "Lanczos" }, new[] { 0, 1, 2 },
            "The filter that fits the picture to your screen. Catmull-Rom is sharper, Lanczos sharper still." },
        new object[] { "sharpness", "Sharpness", new[] { "0%", "10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%" }, new[] { 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 },
            "Sharpens the picture on its way to the screen. Too much shows halos around edges." },
        new object[] { "frame_generation", "Frame generation", new[] { "Off", "2x", "3x", "4x", "5x", "6x", "7x", "8x" }, new[] { 0, 2, 3, 4, 5, 6, 7, 8 },
            "Shows extra in-between frames for smoother motion." },
        new object[] { "frame_pacing", "Frame pacing", new[] { "Off", "On" }, new[] { 0, 1 },
            "Spaces the frames evenly: steadier motion." },
        new object[] { "fullscreen", "Display", new[] { "Window", "Fullscreen" }, new[] { 0, 1 },
            "Play in a window or full screen. Alt+Enter switches in game." },
        new object[] { "ultrawide", "Screen shape", new[] { "16:9", "Monitor's shape" }, new[] { 0, 1 },
            "Monitor's shape widens the camera to fill a screen wider than 16:9." },
        new object[] { "handheld_profile", "Handheld profile", new[] { "Off", "On" }, new[] { 0, 1 },
            "Runs the game as if the console were undocked: lower resolutions, lighter on the graphics card." },
        new object[] { "fps_counter", "FPS counter", new[] { "Off", "On" }, new[] { 0, 1 },
            "Shows the frames per second in a corner of the screen." },
    };
    static readonly object[][] GameRows = {
        new object[] { "game_speed", "Game speed", new[] { "Per frame", "Real time" }, new[] { 0, 1 },
            "Real time keeps the game at its normal speed even when the frame rate drops." },
        new object[] { "text_speed", "Text speed", new[] { "Normal", "2x", "4x", "Instant" }, new[] { 0, 1, 2, 3 },
            "How fast the dialogue text appears." },
        new object[] { "controller_in_background", "Controller in background", new[] { "Off", "On" }, new[] { 0, 1 },
            "Keeps the controller working when the game window is not in front." },
    };
    // (the randomizer: the rows of the Insert menu's Randomizer tab, gpu/vk/oot_rando.h. The same keys, choices and order:
    // tests/test_rando_settings.py checks them against that file. The seed's random part, rando_seed, is the New seed button's)
    static readonly object[][] RandoRows = {
        new object[] { "rando_on", "Randomizer", new[] { "Off", "On" }, new[] { 0, 1 },
            "Plays the seed in place of the game as shipped. Settings only for now: item placement is not in this build yet." },
        new object[] { "rando_chests", "Chests", new[] { "Off", "Overworld", "Dungeons", "All" }, new[] { 0, 1, 2, 3 },
            "Which treasure chests hold a shuffled item. All is every chest in the game." },
        new object[] { "rando_skulltulas", "Gold Skulltulas", new[] { "Off", "Dungeons", "Overworld", "All" }, new[] { 0, 1, 2, 3 },
            "Which Gold Skulltulas drop a shuffled item instead of a token. The tokens join the item pool." },
        new object[] { "rando_quests", "Quest rewards", new[] { "Off", "On" }, new[] { 0, 1 },
            "What characters give you is shuffled: gifts, side quests, mini-games and the Gold Skulltula family's rewards." },
        new object[] { "rando_songs", "Songs", new[] { "Off", "Song spots", "Anywhere" }, new[] { 0, 1, 2 },
            "Song spots: the songs are shuffled among the places that teach one. Anywhere: a song can be any item's place." },
        new object[] { "rando_heart_pieces", "Heart Pieces", new[] { "Off", "On" }, new[] { 0, 1 },
            "Heart Pieces and the other items lying in the world are shuffled." },
        new object[] { "rando_shops", "Shops", new[] { "Off", "On", "Random prices" }, new[] { 0, 1, 2 },
            "Shop shelves sell shuffled items. Random prices also rolls what each one costs." },
        new object[] { "rando_scrubs", "Deku Scrubs", new[] { "Off", "On" }, new[] { 0, 1 },
            "What the Business Scrubs sell is shuffled." },
        new object[] { "rando_dungeon_rewards", "Dungeon rewards", new[] { "Off", "Dungeons", "Anywhere" }, new[] { 0, 1, 2 },
            "The Spiritual Stones and Medallions. Dungeons: shuffled among the dungeons' ends. Anywhere: any item's place." },
        new object[] { "rando_keys", "Dungeon keys", new[] { "Off", "Own dungeon", "Anywhere" }, new[] { 0, 1, 2 },
            "Small keys and Boss Keys. Own dungeon: shuffled inside their dungeon. Anywhere: they can be in any place of the game." },
    };
    static readonly string[] PresetKeys = { "resolution", "upscaling", "sharpness", "frame_generation", "frame_pacing", "game_speed", "handheld_profile" };
    static readonly string[][] Languages = {
        new[] { "en-US", "English (US)" }, new[] { "en-GB", "English (UK)" }, new[] { "fr", "Français (France)" }, new[] { "fr-CA", "Français (Canada)" },
        new[] { "de", "Deutsch" }, new[] { "it", "Italiano" }, new[] { "es", "Español (España)" }, new[] { "es-419", "Español (Latinoamérica)" },
        new[] { "pt-BR", "Português (Brasil)" }, new[] { "nl", "Nederlands" }, new[] { "pl", "Polski" }, new[] { "ru", "Русский" },
        new[] { "ja", "日本語" }, new[] { "ko", "한국어" }, new[] { "zh-Hans", "简体中文" }, new[] { "zh-Hant", "繁體中文" },
    };
    // (env name, value when on, label, help, value when off; "" = no line, the game's default)
    static readonly string[][] Fixes = {
        new[] { "RX_VK_WAIT_GPU", "", "No blue light flashes", "Each frame waits for the graphics card to finish the previous one. Stops the one-frame blue light flashes in Hyrule Field. Costs a few fps. Recommended.", "-1" },
        new[] { "HOOKSHOT_OCCLUSION_OFF", "1", "Occlusion tests off", "The game no longer guesses what is hidden: everything is drawn. Steadier sun glare on AMD cards, a little slower.", "" },
    };

    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, int w, int l);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);

    protected override CreateParams CreateParams {
        get { var cp = base.CreateParams; cp.ClassStyle |= 0x20000; cp.Style |= 0x20000; return cp; }   // (drop shadow; minimize from the taskbar)
    }

    public LauncherForm(string dir) {
        this.dir = dir;
        optionsPath = Path.Combine(dir, "hookshot_options.ini");
        envPath = Path.Combine(dir, "hookshot_env.txt");
        langPath = Path.Combine(dir, "language.txt");

        Text = "Mako";
        FormBorderStyle = FormBorderStyle.None;
        ClientSize = new Size(W, H);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Theme.Bg0;
        DoubleBuffered = true;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        try {
            using (var s = typeof(LauncherForm).Assembly.GetManifestResourceStream("mako_logo.png"))
                if (s != null) logo = Image.FromStream(s);
        } catch { }

        for (int i = 0; i < bubbles.Length; i++) { bubbles[i] = NewBubble(); bubbles[i].Y = (float)(rnd.NextDouble() * H); }

        // (title bar)
        widgets.Add(new TitleBtn { R = new RectangleF(W - 92, 0, 46, 36), Click = () => WindowState = FormWindowState.Minimized });
        widgets.Add(new TitleBtn { R = new RectangleF(W - 46, 0, 46, 36), Close = true, Click = Close });

        // (left panel: update card button and PLAY)
        updateButton = new Btn { Text = "Check again", R = new RectangleF(236, 448, 116, 30), Font = Theme.Label, Enabled = false };
        updateButton.Click = OnUpdateButton;
        widgets.Add(updateButton);
        playButton = new Btn { Text = "PLAY", Style = Btn.Kind.Play, R = new RectangleF(32, 512, 336, 76), Click = OnPlay };
        widgets.Add(playButton);
        widgets.Add(new Btn { Text = "Made by sharkiix  ·  based on Hookshot", Style = Btn.Kind.Link, R = new RectangleF(32, 626, 300, 24),
                              Click = () => OpenUrl(Fork.Home) });

        // (tabs)
        string[] names = { "Graphics", "Game", "Randomizer", "AMD fixes", "About" };
        float tx = LeftW + 36;
        using (var g = CreateGraphics())
            for (int i = 0; i < names.Length; i++) {
                float w = g.MeasureString(names[i], Theme.Tab).Width + 26;
                var t = new TabW { Text = names[i], Index = i, R = new RectangleF(tx, 50, w, 40) };
                tabs.Add(t); widgets.Add(t);
                tx += w + 6;
            }

        float cx = LeftW + 36, cw = W - LeftW - 72, colW = (cw - 14) / 2;
        AddSelectors(GraphicsRows, 0, cx, colW);
        AddSelectors(GameRows, 1, cx, colW);
        AddSelectors(RandoRows, 2, cx, colW);
        widgets.Add(new Btn { Text = "New seed", R = new RectangleF(cx, 468, 130, 40), Page = 2, Click = OnNewSeed });
        var langItems = new string[Languages.Length]; var langValues = new int[Languages.Length];
        for (int i = 0; i < Languages.Length; i++) { langItems[i] = Languages[i][1]; langValues[i] = i; }
        langSel = new Selector { Key = "language", Label = "Language", Items = langItems, Values = langValues, Page = 1, Index = 0,
                                 HelpText = "The game's language: text and voices.",
                                 R = new RectangleF(cx + colW + 14, 112 + 70, colW, 62) };
        langSel.Changed = s => { if (!loading) SaveLanguage(); };
        widgets.Add(langSel);
        for (int i = 0; i < Fixes.Length; i++) {
            var tg = new Toggle { Key = Fixes[i][0], Label = Fixes[i][2], HelpText = Fixes[i][3], Page = 3, R = new RectangleF(cx, 112 + i * 112, cw, 100) };
            tg.Changed = t => { if (!loading) SaveEnv(); };
            fixes[tg.Key] = tg; widgets.Add(tg);
        }
        widgets.Add(new Btn { Text = "Project page on GitHub", R = new RectangleF(cx, 470, 220, 40), Page = 4, Click = () => OpenUrl(Fork.Home) });
        widgets.Add(new Btn { Text = "Licence (GPL-3)", R = new RectangleF(cx + 232, 470, 170, 40), Page = 4, Click = () => OpenUrl(Fork.Home + "/blob/HEAD/LICENSE") });

        // (bottom row: folders)
        widgets.Add(new Btn { Text = "Saves", R = new RectangleF(cx, 612, 130, 42), Click = () => OpenFolder(Path.Combine(dir, "user", "save")) });
        widgets.Add(new Btn { Text = "Import saves", R = new RectangleF(cx + 140, 612, 150, 42), Click = OnImport });
        widgets.Add(new Btn { Text = "Game folder", R = new RectangleF(cx + 300, 612, 150, 42), Click = () => OpenFolder(dir) });

        LoadAll();
        int first;
        string[] cmd = Environment.GetCommandLineArgs();
        ShowPage(cmd.Length > 2 && int.TryParse(cmd[2], out first) && first >= 0 && first < tabs.Count ? first : 0);
        tabX = tabs[PageNow].R.X; tabW = tabs[PageNow].R.Width;

        timer = new System.Windows.Forms.Timer { Interval = 16 };
        timer.Tick += (s, e) => Step();
        timer.Start();
        CheckUpdate();
    }

    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e);
        try { int round = 2; DwmSetWindowAttribute(Handle, 33, ref round, 4); } catch { }   // (Windows 11: rounded corners)
    }

    void AddSelectors(object[][] rows, int page, float x0, float colW) {
        for (int i = 0; i < rows.Length; i++) {
            var row = rows[i];
            int col = i % 2, line = i / 2;
            var s = new Selector { Key = (string)row[0], Label = (string)row[1], Items = (string[])row[2], Values = (int[])row[3], HelpText = (string)row[4],
                                   Page = page, R = new RectangleF(x0 + col * (colW + 14), 112 + line * 70, colW, 62) };
            s.Changed = OnSetting;
            settings[s.Key] = s; widgets.Add(s);
        }
    }

    Bubble NewBubble() {
        return new Bubble { X = (float)(rnd.NextDouble() * LeftW), Y = H + 10 + (float)(rnd.NextDouble() * 60), R = 1f + (float)(rnd.NextDouble() * 2.6),
                            V = 0.25f + (float)(rnd.NextDouble() * 0.55), P = (float)(rnd.NextDouble() * 6.28) };
    }

    public bool MouseIn(RectangleF r) { return r.Contains(mouse); }

    public void ShowPage(int k) {
        if (k == PageNow && pageFade >= 1 && tabW > 0) return;
        PageNow = k; pageFade = 0;
    }

    // ---- animation ----
    void Step() {
        float dt = 1 / 60f;
        Time = (float)clock.Elapsed.TotalSeconds;
        foreach (var w in widgets) {
            bool visible = w.Page < 0 || w.Page == PageNow;
            float target = visible && w.Enabled && w.R.Contains(mouse) ? 1 : 0;
            w.Hover += (target - w.Hover) * 0.22f;
            w.Tick();
        }
        var t = tabs[PageNow].R;
        tabX += (t.X - tabX) * 0.2f; tabW += (t.Width - tabW) * 0.2f;
        pageFade = Math.Min(1, pageFade + dt * 5);
        for (int i = 0; i < bubbles.Length; i++) {
            bubbles[i].Y -= bubbles[i].V;
            if (bubbles[i].Y < -10) bubbles[i] = NewBubble();
        }
        // (the help line: the hovered setting's explanation)
        string want = null;
        foreach (var w in widgets) if ((w.Page == PageNow) && w.Help != null && w.R.Contains(mouse)) want = w.Help;
        if (want != null && want != helpShown) { helpShown = want; helpFade = 0; }
        helpFade = want != null ? Math.Min(1, helpFade + dt * 6) : Math.Max(0, helpFade - dt * 3);
        if (WindowState != FormWindowState.Minimized) Invalidate();
    }

    // ---- painting ----
    void MakeBackdrop() {
        backdrop = new Bitmap(W, H);
        using (var g = Graphics.FromImage(backdrop)) {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var b = new LinearGradientBrush(new Rectangle(0, 0, W, H), Theme.Bg1, Theme.Bg0, 60f)) g.FillRectangle(b, 0, 0, W, H);
            // (the left panel: deeper, with a blue light from below)
            var left = new RectangleF(0, 0, LeftW, H);
            using (var b = new LinearGradientBrush(left, Color.FromArgb(7, 12, 24), Color.FromArgb(4, 7, 14), LinearGradientMode.Vertical)) g.FillRectangle(b, left);
            using (var p = new GraphicsPath()) {
                p.AddEllipse(-160, H - 300, LeftW + 320, 520);
                using (var pb = new PathGradientBrush(p) { CenterColor = Color.FromArgb(70, 30, 100, 255), SurroundColors = new[] { Color.FromArgb(0, 30, 100, 255) } })
                    g.FillPath(pb, p);
            }
            using (var p = new GraphicsPath()) {
                p.AddEllipse(LeftW + 200, -260, 700, 520);
                using (var pb = new PathGradientBrush(p) { CenterColor = Color.FromArgb(26, 56, 200, 255), SurroundColors = new[] { Color.FromArgb(0, 56, 200, 255) } })
                    g.FillPath(pb, p);
            }
            using (var pen = new Pen(Color.FromArgb(28, 120, 170, 255), 1f)) g.DrawLine(pen, LeftW, 0, LeftW, H);
            using (var pen = new Pen(Color.FromArgb(40, 120, 170, 255), 1f)) g.DrawRectangle(pen, 0, 0, W - 1, H - 1);
        }
    }

    protected override void OnPaint(PaintEventArgs e) {
        var g = e.Graphics;
        if (backdrop == null) MakeBackdrop();
        g.DrawImageUnscaled(backdrop, 0, 0);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.PixelOffsetMode = PixelOffsetMode.HighQuality;

        PaintLeft(g);
        // (title)
        using (var b = new SolidBrush(Theme.A(Theme.Dim, 160))) Theme.Spaced(g, "MAKO LAUNCHER", Theme.Caps, b, LeftW + (W - LeftW) / 2f, 13, 4);

        // (tabs underline and the page)
        using (var b = new LinearGradientBrush(new RectangleF(tabX, 88, Math.Max(1, tabW), 3), Theme.Blue, Theme.Cyan, 0f))
            using (var p = Theme.Round(new RectangleF(tabX + 10, 88, Math.Max(1, tabW - 20), 3), 1.5f)) g.FillPath(b, p);
        using (var pen = new Pen(Color.FromArgb(24, 120, 170, 255))) g.DrawLine(pen, LeftW + 36, 92, W - 36, 92);

        var state = g.Save();
        float slide = (1 - Ease(pageFade)) * 14;
        g.TranslateTransform(0, slide);
        foreach (var w in widgets) if (w.Page >= 0 && w.Page == PageNow) w.Paint(g, this);
        g.Restore(state);
        if (pageFade < 1)   // (the page fading in: a veil of the background over it)
            using (var b = new SolidBrush(Theme.A(Theme.Bg1, (int)(255 * (1 - Ease(pageFade)))))) g.FillRectangle(b, LeftW + 1, 100, W - LeftW - 2, 496);
        PaintPageExtras(g);

        // (help line)
        if (helpFade > 0.01f) {
            var r = new RectangleF(LeftW + 36, 548, W - LeftW - 72, 46);
            using (var p = Theme.Round(r, 10)) using (var b = new SolidBrush(Theme.A(Theme.Blue, (int)(22 * helpFade)))) g.FillPath(b, p);
            using (var b = new SolidBrush(Theme.A(Theme.Cyan, (int)(255 * helpFade)))) g.FillEllipse(b, r.X + 14, r.Y + r.Height / 2 - 3, 6, 6);
            Theme.Text_(g, helpShown, Theme.Small, Theme.A(Theme.Text, (int)(230 * helpFade)), new RectangleF(r.X + 30, r.Y, r.Width - 40, r.Height),
                        StringAlignment.Near, StringAlignment.Center);
        }
        foreach (var w in widgets) if (w.Page < 0) w.Paint(g, this);
    }

    static float Ease(float t) { t = Math.Max(0, Math.Min(1, t)); return 1 - (1 - t) * (1 - t) * (1 - t); }

    void PaintLeft(Graphics g) {
        float t = Time;
        // (bubbles)
        foreach (var b in bubbles) {
            float x = b.X + (float)Math.Sin(t * 0.8 + b.P) * 6;
            int a = (int)(40 + 50 * Math.Sin(t + b.P) * Math.Sin(t + b.P));
            using (var pen = new Pen(Color.FromArgb(Math.Min(255, a), 120, 200, 255), 1f)) g.DrawEllipse(pen, x, b.Y, b.R * 2, b.R * 2);
        }
        // (light streaks sweeping like the logo's, slowly drifting)
        var clip0 = g.Save(); g.SetClip(new RectangleF(0, 0, LeftW, H));
        for (int i = 0; i < 3; i++) {
            float ph = t * 0.35f + i * 2.1f;
            float y0 = 330 + i * 70 + (float)Math.Sin(ph) * 16;
            var p0 = new PointF(-40, y0 + 120); var p1 = new PointF(120, y0 - 10); var p2 = new PointF(280, y0 - 60); var p3 = new PointF(LeftW + 40, y0 - 70 - i * 10);
            float shine = (float)((t * 0.22 + i * 0.37) % 1.0);
            using (var br = new LinearGradientBrush(new RectangleF(-40, 0, LeftW + 80, 10), Color.Transparent, Color.Transparent, 0f)) {
                var blend = new ColorBlend(4);
                int a = 34 - i * 8;
                blend.Colors = new[] { Color.FromArgb(0, Theme.Cyan), Color.FromArgb(a, Theme.Blue), Color.FromArgb(a * 3, Theme.Cyan), Color.FromArgb(0, Theme.Cyan) };
                blend.Positions = new[] { 0f, Math.Max(0.01f, shine * 0.9f), Math.Min(0.98f, shine * 0.9f + 0.08f), 1f };
                br.InterpolationColors = blend;
                using (var pen = new Pen(br, 2.2f - i * 0.5f)) g.DrawBezier(pen, p0, p1, p2, p3);
            }
        }
        g.Restore(clip0);
        // (the logo with a soft glow behind it, breathing)
        var lr = new RectangleF(30, 64, 340, 340f * 660 / 1375);
        if (logo != null) lr.Height = lr.Width * logo.Height / logo.Width;
        float pulse = 0.5f + 0.5f * (float)Math.Sin(t * 1.4);
        using (var p = new GraphicsPath()) {
            var gr = RectangleF.Inflate(lr, 10, 26);
            p.AddEllipse(gr);
            using (var pb = new PathGradientBrush(p) { CenterColor = Color.FromArgb((int)(40 + 30 * pulse), 40, 130, 255), SurroundColors = new[] { Color.FromArgb(0, 40, 130, 255) } })
                g.FillPath(pb, p);
        }
        if (logo != null) {
            float bob = (float)Math.Sin(t * 1.1) * 3;
            g.DrawImage(logo, lr.X, lr.Y + bob, lr.Width, lr.Height);
        }
        // (wordmark)
        float my = lr.Bottom + 16;
        using (var b = new LinearGradientBrush(new RectangleF(0, my, LeftW, 60), Color.White, Color.FromArgb(170, 200, 240), LinearGradientMode.Vertical))
            Theme.Spaced(g, "MAKO", Theme.Mark, b, LeftW / 2f, my, 16);
        using (var b = new SolidBrush(Theme.Dim)) Theme.Spaced(g, "OCARINA OF TIME  ·  PC", Theme.Caps, b, LeftW / 2f, my + 66, 3.5f);
        // (version pill)
        string v = Fork.Shown(Installed());
        var vs = g.MeasureString(v, Theme.Small);
        var pill = new RectangleF(LeftW / 2f - vs.Width / 2 - 12, my + 90, vs.Width + 24, 22);
        using (var p = Theme.Round(pill, 11)) {
            using (var b = new SolidBrush(Theme.A(Theme.Blue, 34))) g.FillPath(b, p);
            using (var pen = new Pen(Theme.A(Theme.Blue, 120))) g.DrawPath(pen, p);
        }
        Theme.Text_(g, v, Theme.Small, Theme.Cyan, pill, StringAlignment.Center, StringAlignment.Center);

        // (update card)
        var card = new RectangleF(32, 398, 336, 94);
        using (var p = Theme.Round(card, 14)) {
            using (var b = new SolidBrush(Color.FromArgb(200, 12, 20, 36))) g.FillPath(b, p);
            using (var pen = new Pen(Theme.Line)) g.DrawPath(pen, p);
        }
        float dp = 0.5f + 0.5f * (float)Math.Sin(t * 3);
        using (var b = new SolidBrush(Theme.A(updDot, (int)(60 * dp)))) g.FillEllipse(b, card.X + 14, card.Y + 16, 16, 16);
        using (var b = new SolidBrush(updDot)) g.FillEllipse(b, card.X + 18, card.Y + 20, 8, 8);
        Theme.Text_(g, updTitle, Theme.Strong, Theme.Text, new RectangleF(card.X + 38, card.Y + 12, card.Width - 50, 22), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, updLine, Theme.Small, Theme.Dim, new RectangleF(card.X + 38, card.Y + 34, card.Width - 50, 18), StringAlignment.Near, StringAlignment.Near);
        if (updProgress >= 0) {
            var bar = new RectangleF(card.X + 16, card.Bottom - 26, card.Width - 32, 8);
            using (var p = Theme.Round(bar, 4)) using (var b = new SolidBrush(Color.FromArgb(30, 42, 66))) g.FillPath(b, p);
            var fill = new RectangleF(bar.X, bar.Y, Math.Max(8, bar.Width * updProgress), bar.Height);
            using (var p = Theme.Round(fill, 4)) using (var b = new LinearGradientBrush(bar, Theme.Blue, Theme.Cyan, 0f)) g.FillPath(b, p);
            updateButton.Enabled = false;
        }
    }

    void PaintPageExtras(Graphics g) {
        float x = LeftW + 36;
        if (PageNow == 1)
            Theme.Text_(g, "Controls are set in game: press Insert for the menu.", Theme.Small, Theme.Faint, new RectangleF(x, 112 + 2 * 70 + 6, 500, 20),
                        StringAlignment.Near, StringAlignment.Near);
        if (PageNow == 2) {   // (the randomizer: the seed beside its button, and what the page does not do yet)
            string seed = randoSeed != 0 ? "Seed " + randoSeed + "  ·  its ID, to share it, is on the game's Randomizer tab (Insert)"
                                         : "No seed yet: turn the randomizer on, or press New seed.";
            Theme.Text_(g, seed, Theme.Small, Theme.Dim, new RectangleF(x + 144, 468, W - LeftW - 72 - 144, 40), StringAlignment.Near, StringAlignment.Center);
            Theme.Text_(g, "Settings only for now: item placement is not in this build yet, so the game still plays as shipped. Read by the game when it starts.",
                        Theme.Small, Theme.Faint, new RectangleF(x, 516, W - LeftW - 72, 20), StringAlignment.Near, StringAlignment.Near);
        }
        if (PageNow == 3)
            Theme.Text_(g, "Read by the game when it starts.", Theme.Small, Theme.Faint, new RectangleF(x, 112 + Fixes.Length * 112, 500, 20),
                        StringAlignment.Near, StringAlignment.Near);
        if (PageNow == 4) {
            var r = new RectangleF(x, 112, W - LeftW - 72, 340);
            using (var p = Theme.Round(r, 14)) {
                using (var b = new SolidBrush(Theme.Card)) g.FillPath(b, p);
                using (var pen = new Pen(Theme.Line)) g.DrawPath(pen, p);
            }
            Theme.Text_(g, "Mako", Theme.Pick(26f, FontStyle.Bold, "Bahnschrift", "Segoe UI"), Color.White, new RectangleF(r.X + 24, r.Y + 20, 400, 34), StringAlignment.Near, StringAlignment.Near);
            Theme.Text_(g, Fork.Shown(Installed()) + "  ·  made by sharkiix", Theme.Body, Theme.Cyan, new RectangleF(r.X + 24, r.Y + 58, 500, 22), StringAlignment.Near, StringAlignment.Near);
            Theme.Text_(g,
                "A native PC version of The Legend of Zelda: Ocarina of Time, tuned for AMD graphics cards: steadier frame times, " +
                "fixed lighting and textures, and its own launcher.\n\n" +
                "Mako is based on Hookshot, the open-source recompilation project, and is free software under the GNU GPL version 3. " +
                "It contains no game data: you need your own copy of the game.\n\n" +
                "Thanks to the Hookshot authors and everyone who tests and reports.",
                Theme.Body, Theme.Text, new RectangleF(r.X + 24, r.Y + 96, r.Width - 48, r.Height - 110), StringAlignment.Near, StringAlignment.Near);
        }
    }

    // ---- mouse ----
    protected override void OnMouseMove(MouseEventArgs e) {
        mouse = e.Location;
        Widget w = At(mouse);
        Cursor = w != null ? Cursors.Hand : Cursors.Default;
        base.OnMouseMove(e);
    }
    protected override void OnMouseLeave(EventArgs e) { mouse = new PointF(-1, -1); Cursor = Cursors.Default; base.OnMouseLeave(e); }
    Widget At(PointF p) {
        for (int i = widgets.Count - 1; i >= 0; i--) {
            var w = widgets[i];
            if ((w.Page < 0 || w.Page == PageNow) && w.Hit(p)) return w;
        }
        return null;
    }
    protected override void OnMouseDown(MouseEventArgs e) {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        pressed = At(e.Location);
        if (pressed == null && e.Y < 40) { ReleaseCapture(); SendMessage(Handle, 0xA1, 2, 0); }   // (drag the window by its top)
    }
    protected override void OnMouseUp(MouseEventArgs e) {
        base.OnMouseUp(e);
        var w = At(e.Location);
        if (w != null && w == pressed && e.Button == MouseButtons.Left) w.Down(e.Location, this);
        pressed = null;
    }

    public void ShowList(Selector s) {
        var m = new ContextMenuStrip { Renderer = new DarkMenu(), ShowImageMargin = true, Font = new Font("Segoe UI", 10f), BackColor = Color.FromArgb(16, 25, 43) };
        for (int i = 0; i < s.Items.Length; i++) {
            int k = i;
            var it = new ToolStripMenuItem(s.Items[i]) { Checked = i == s.Index, ForeColor = Theme.Text, Padding = new Padding(4, 3, 4, 3) };
            it.Click += (o, e) => s.Set(k, true);
            m.Items.Add(it);
        }
        m.MinimumSize = new Size((int)s.R.Width, 0);
        m.Show(this, new Point((int)s.R.X, (int)s.R.Bottom + 4));
    }

    // ---- settings ----
    Dictionary<string, int> ReadOptions() {
        var d = new Dictionary<string, int>();
        if (!File.Exists(optionsPath)) return d;
        foreach (var raw in File.ReadAllLines(optionsPath)) {
            int eq = raw.IndexOf('=');
            int v;
            if (eq > 0 && int.TryParse(raw.Substring(eq + 1).Trim(), out v)) d[raw.Substring(0, eq).Trim()] = v;
        }
        return d;
    }

    void SetSetting(string key, int value) {
        Selector s;
        if (!settings.TryGetValue(key, out s)) return;
        if (key == "frame_generation" && value == 1) value = 2;
        int best = 0;
        for (int i = 0; i < s.Values.Length; i++) if (Math.Abs(s.Values[i] - value) < Math.Abs(s.Values[best] - value)) best = i;
        if (s.Index < 0) s.Index = best; else s.Set(best, false);
    }

    void LoadAll() {
        loading = true;
        var o = ReadOptions();
        // (the game's own defaults where the file has nothing yet: options.ini is written by the game's Insert menu)
        var defaults = new Dictionary<string, int> { { "quality_preset", 0 }, { "output_res", 0 }, { "resolution", 0 }, { "upscaling", 2 }, { "sharpness", 30 },
            { "frame_generation", 2 }, { "frame_pacing", 1 }, { "fullscreen", 1 }, { "ultrawide", 0 }, { "handheld_profile", 0 },
            { "fps_counter", 0 }, { "game_speed", 1 }, { "text_speed", 0 }, { "controller_in_background", 0 } };
        foreach (var row in RandoRows) defaults[(string)row[0]] = 0;   // (the randomizer: off, every setting the game's own)
        foreach (var kv in defaults) SetSetting(kv.Key, o.ContainsKey(kv.Key) ? o[kv.Key] : kv.Value);
        randoSeed = o.ContainsKey("rando_seed") ? Math.Max(0, o["rando_seed"]) : 0;
        var env = ReadEnv();
        foreach (var f in Fixes) {
            string v;
            fixes[f[0]].On = env.TryGetValue(f[0], out v) ? v == f[1] : f[1].Length == 0;
            fixes[f[0]].Snap();
        }
        string lang = ReadLanguage();
        for (int i = 0; i < Languages.Length; i++) if (string.Equals(Languages[i][0], lang, StringComparison.OrdinalIgnoreCase)) langSel.Index = i;
        loading = false;
    }

    void OnSetting(Selector s) {
        if (loading) return;
        loading = true;
        if (s.Key == "quality_preset") ApplyPreset(s.Value);
        else if (Array.IndexOf(PresetKeys, s.Key) >= 0) SetSetting("quality_preset", 0);   // (changed by hand: Custom)
        if (s.Key.StartsWith("rando_")) {
            randoDropImport = true;
            if (s.Key == "rando_on" && s.Value != 0 && randoSeed == 0) randoSeed = NewSeed();   // (turned on before any seed was made)
        }
        loading = false;
        SaveOptions();
    }

    // (a seed's random part, 1 to 2^31 - 2: 0 is "none yet", as in the Insert menu)
    static int NewSeed() { return new Random(Environment.TickCount ^ Guid.NewGuid().GetHashCode()).Next(1, int.MaxValue); }

    void OnNewSeed() {
        randoSeed = NewSeed();
        randoDropImport = true;
        SaveOptions();
    }

    // (the Insert menu's presets, gpu/vk/vk_menu.cpp apply_preset)
    void ApplyPreset(int p) {
        int[][] t = {
            null,
            new[] { 4, 2, 50, 2, 1, 1, 1 },
            new[] { 2, 2, 35, 2, 1, 1, 1 },
            new[] { 1, 1, 25, 2, 1, 1, 0 },
            new[] { 1, 2, 30, 2, 1, 1, 0 },
            new[] { 1, 2, 40, 3, 1, 1, 0 },
        };
        if (p <= 0 || p >= t.Length) return;
        for (int i = 0; i < PresetKeys.Length; i++) SetSetting(PresetKeys[i], t[p][i]);
    }

    void SaveOptions() {
        try {
            var lines = File.Exists(optionsPath) ? new List<string>(File.ReadAllLines(optionsPath)) : new List<string>();
            var done = new HashSet<string>();
            if (randoDropImport) lines.RemoveAll(l => l.StartsWith("rando_import="));
            randoDropImport = false;
            for (int i = 0; i < lines.Count; i++) {
                int eq = lines[i].IndexOf('=');
                if (eq <= 0) continue;
                string k = lines[i].Substring(0, eq).Trim();
                if (settings.ContainsKey(k)) { lines[i] = k + "=" + settings[k].Value; done.Add(k); }
                else if (k == "rando_seed") { lines[i] = k + "=" + randoSeed; done.Add(k); }
            }
            // (new keys go before the controls, as the game writes them)
            int at = lines.FindIndex(l => l.StartsWith("options_version=") || l.StartsWith("pad_"));
            if (at < 0) at = lines.Count;
            foreach (var k in settings.Keys)
                if (!done.Contains(k)) lines.Insert(at++, k + "=" + settings[k].Value);
            if (!done.Contains("rando_seed") && randoSeed != 0) lines.Insert(at++, "rando_seed=" + randoSeed);
            if (!lines.Exists(l => l.StartsWith("options_version="))) lines.Insert(at, "options_version=2");
            File.WriteAllLines(optionsPath, lines.ToArray(), new UTF8Encoding(false));
        } catch (Exception ex) {
            MessageBox.Show(this, "The settings could not be saved:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    Dictionary<string, string> ReadEnv() {
        var d = new Dictionary<string, string>();
        if (!File.Exists(envPath)) return d;
        foreach (var raw in File.ReadAllLines(envPath)) {
            string l = raw.Trim();
            if (l.StartsWith("#")) continue;
            int eq = l.IndexOf('=');
            if (eq > 0) d[l.Substring(0, eq).Trim()] = l.Substring(eq + 1).Trim();
        }
        return d;
    }

    void SaveEnv() {
        try {
            var lines = File.Exists(envPath) ? new List<string>(File.ReadAllLines(envPath)) : new List<string>();
            foreach (var f in Fixes) {
                lines.RemoveAll(l => { var t = l.Trim(); return !t.StartsWith("#") && t.StartsWith(f[0] + "="); });
                string v = fixes[f[0]].On ? f[1] : f[4];
                if (v.Length > 0) lines.Add(f[0] + "=" + v);
            }
            if (lines.Count == 0 && File.Exists(envPath)) File.Delete(envPath);
            else if (lines.Count > 0) File.WriteAllLines(envPath, lines.ToArray(), new UTF8Encoding(false));
        } catch (Exception ex) {
            MessageBox.Show(this, "The AMD fix switches could not be saved:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    string ReadLanguage() {
        if (!File.Exists(langPath)) return "en-US";
        foreach (var raw in File.ReadAllLines(langPath)) {
            string l = raw.Trim();
            if (l.Length > 0 && !l.StartsWith("#")) return l;
        }
        return "en-US";
    }

    void SaveLanguage() {
        string code = Languages[Math.Max(0, langSel.Index)][0];
        try {
            if (!File.Exists(langPath)) { File.WriteAllText(langPath, code + "\n", new UTF8Encoding(false)); return; }
            var lines = new List<string>(File.ReadAllLines(langPath));
            int i = lines.FindIndex(l => l.Trim().Length > 0 && !l.Trim().StartsWith("#"));
            if (i >= 0) lines[i] = code; else lines.Insert(Math.Min(2, lines.Count), code);
            File.WriteAllLines(langPath, lines.ToArray(), new UTF8Encoding(false));
        } catch (Exception ex) {
            MessageBox.Show(this, "The language could not be saved:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    // ---- update ----
    static string ValueIn(string text, string name) {
        if (text == null) return "";
        foreach (var raw in text.Split('\n')) {
            string l = raw.Trim().TrimStart('﻿');
            if (l.StartsWith(name + "=")) return l.Substring(name.Length + 1).Trim();
        }
        return "";
    }

    // (a release not newer than this folder's: the first number found in each tag)
    static bool Older(string tag, string have) {
        var a = Regex.Match(tag, @"\d+(\.\d+)*"); var b = Regex.Match(have, @"\d+(\.\d+)*");
        if (!a.Success || !b.Success) return false;
        string[] x = a.Value.Split('.'), y = b.Value.Split('.');
        for (int i = 0; i < Math.Max(x.Length, y.Length); i++) {
            int u = i < x.Length ? int.Parse(x[i]) : 0, v = i < y.Length ? int.Parse(y[i]) : 0;
            if (u != v) return u < v;
        }
        return true;   // (the same number)
    }

    string Installed() {
        string p = Path.Combine(dir, "user", "hookshot_vk_version.txt");
        string v = File.Exists(p) ? ValueIn(File.ReadAllText(p), "version") : "";
        return v.Length > 0 && !Older(v, Fork.Version) ? v : Fork.Version;
    }

    static WebClient Client() {
        var c = new WebClient();
        c.Headers[HttpRequestHeader.UserAgent] = "Mako-launcher";
        c.Headers[HttpRequestHeader.Accept] = "application/vnd.github+json";
        return c;
    }

    void SetUpdate(Color dot, string title, string line, string button, bool primary, bool enabled) {
        updDot = dot; updTitle = title; updLine = line;
        updateButton.Text = button;
        updateButton.Style = primary ? Btn.Kind.Primary : Btn.Kind.Ghost;
        updateButton.Enabled = enabled;
    }

    void CheckUpdate() {
        patchDll = null; rebuildTag = null; updProgress = -1;
        SetUpdate(Theme.Faint, "Checking for updates…", "Asking GitHub for the latest release", "Check again", false, false);
        string have = Installed();
        var t = new Thread(() => {
            string tag = "", status = "offline", dll = null, zip = null; long size = 0, zipSize = 0;
            try {
                string json;
                using (var c = Client()) json = c.DownloadString(Fork.Api_Url);
                var m = Regex.Match(json, "\"tag_name\"\\s*:\\s*\"([^\"]+)\"");
                tag = m.Success ? m.Groups[1].Value : "";
                if (tag.Length == 0 || tag == have || Older(tag, have)) status = "current";
                else {
                    string manifest = null;
                    foreach (Match a in Regex.Matches(json, "\"browser_download_url\"\\s*:\\s*\"([^\"]+)\"")) {
                        string u = a.Groups[1].Value;
                        if (u.EndsWith("/hookshot_vk_update.txt")) manifest = u;
                        if (u.EndsWith("/hookshot_vk.dll")) dll = u;
                        if (u.EndsWith("/HookshotBuilder.zip")) zip = u;
                    }
                    if (zip != null) {
                        var zm = Regex.Match(json, "\"size\"\\s*:\\s*(\\d+)[^{}]*?\"browser_download_url\"\\s*:\\s*\"" + Regex.Escape(zip) + "\"");
                        if (zm.Success) long.TryParse(zm.Groups[1].Value, out zipSize);
                    }
                    status = "rebuild";
                    if (manifest != null && dll != null) {
                        string mt;
                        using (var c = Client()) mt = c.DownloadString(manifest);
                        int api;
                        long.TryParse(ValueIn(mt, "size"), out size);
                        if (ValueIn(mt, "base") == Fork.Base && int.TryParse(ValueIn(mt, "api"), out api) && api == Fork.Api) status = "patch";
                        // (a graphics patch for the old amd-fix 2.x game - the bridge to Mako - is nothing for a Mako folder)
                        else if (ValueIn(mt, "base").StartsWith("amd-fix-") && zip == null) status = "current";
                    }
                }
            } catch { status = "offline"; }
            try {
                BeginInvoke((Action)(() => {
                    if (status == "current") SetUpdate(Theme.Green, "Up to date", Fork.Shown(have) + " is the latest version", "Check again", false, true);
                    else if (status == "patch") {
                        patchDll = dll; patchTag = tag; patchSize = size;
                        SetUpdate(Theme.Amber, "Update available: " + Fork.Shown(tag), "Small download, a click to install", "Update", true, true);
                    } else if (status == "rebuild") {
                        rebuildTag = tag; builderZip = zip; builderZipSize = zipSize;
                        SetUpdate(Theme.Amber, "New version: " + Fork.Shown(tag), "Your saves and settings are kept", "Update", true, true);
                    }
                    else SetUpdate(Theme.Faint, "Could not check for updates", "Offline? " + Fork.Shown(have) + " installed", "Check again", false, true);
                }));
            } catch { }
        });
        t.IsBackground = true;
        t.Start();
    }

    void OnUpdateButton() {
        if (updateButton.Text != "Update" || (patchDll == null && rebuildTag == null)) { CheckUpdate(); return; }
        if (GameRunning()) { MessageBox.Show(this, "Close the game first.", Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
        if (patchDll == null) { StartRebuild(); return; }
        SetUpdate(Theme.Blue, "Downloading " + Fork.Shown(patchTag) + "…", "", "Update", true, false);
        updProgress = 0;
        string url = patchDll, tag = patchTag; long size = patchSize;
        var t = new Thread(() => {
            string error = InstallPatch(url, tag, size);
            try {
                BeginInvoke((Action)(() => {
                    updProgress = -1;
                    if (error == null) SetUpdate(Theme.Green, "Updated to " + Fork.Shown(tag), "The first start prepares the shaders again", "Check again", false, true);
                    else SetUpdate(Theme.Red, "The update failed", error, "Check again", false, true);
                }));
            } catch { }
        });
        t.IsBackground = true;
        t.Start();
    }

    // (a release that changes the game's own exe: the game folder is built again by the builder, from the game files it keeps
    // (.hookshot_exefs, romfs), with nx2/make_game.py --update. Saves (user\), settings and this folder's files stay. The builder
    // that made the folder is named in hookshot_version.txt; when it is gone, the release's HookshotBuilder.zip is fetched here.
    // The builder downloads its own newer version itself when it is not the release's (builder Updater.cs))
    void StartRebuild() {
        string tag = rebuildTag;
        string builder = "";
        try {
            string vf = Path.Combine(dir, "hookshot_version.txt");
            if (File.Exists(vf)) builder = ValueIn(File.ReadAllText(vf), "builder");
        } catch { }
        if (!Directory.Exists(Path.Combine(dir, ".hookshot_exefs"))) {
            MessageBox.Show(this, "This game folder has no copy of the game files to update from (it was built before updates came in).\n\n" +
                            "Open the Mako builder, choose your game files and build into this same folder once: your saves are kept.",
                            Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Information);
            OpenUrl(Fork.Page);
            return;
        }
        if (builder.Length > 0 && File.Exists(builder)) { RunBuilder(builder, tag); return; }
        if (builderZip == null) { OpenUrl(Fork.Page); return; }
        SetUpdate(Theme.Blue, "Getting the Mako builder…", "", "Update", true, false);
        updProgress = 0;
        string url = builderZip; long size = builderZipSize;
        var t = new Thread(() => {
            string exe = null, error = null;
            try { exe = FetchBuilder(url, tag, size); } catch (Exception ex) { error = ex.Message; }
            try {
                BeginInvoke((Action)(() => {
                    updProgress = -1;
                    if (exe != null) RunBuilder(exe, tag);
                    else SetUpdate(Theme.Red, "The update could not start", error ?? "the builder was not in the download", "Check again", false, true);
                }));
            } catch { }
        });
        t.IsBackground = true;
        t.Start();
    }

    string FetchBuilder(string url, string tag, long size) {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Mako", "builders");
        string safe = Regex.Replace(tag, "[^A-Za-z0-9._-]", "_");
        string target = Path.Combine(root, safe);
        string exe = Path.Combine(target, "HookshotBuilder", "HookshotBuilder.exe");
        if (File.Exists(exe)) return exe;
        Directory.CreateDirectory(root);
        string zip = Path.Combine(root, safe + ".zip");
        using (var c = Client()) {
            c.Headers[HttpRequestHeader.Accept] = "application/octet-stream";
            var done = new ManualResetEvent(false); Exception err = null;
            c.DownloadProgressChanged += (s, e) => {
                long total = e.TotalBytesToReceive > 0 ? e.TotalBytesToReceive : size;
                if (total > 0) {
                    float p = 0.9f * e.BytesReceived / total;
                    try { BeginInvoke((Action)(() => { updProgress = p; updLine = "Downloading  " + (e.BytesReceived >> 20) + " / " + (total >> 20) + " MB"; })); } catch { }
                }
            };
            c.DownloadFileCompleted += (s, e) => { err = e.Error; done.Set(); };
            c.DownloadFileAsync(new Uri(url), zip);
            done.WaitOne();
            if (err != null) throw err;
        }
        try { BeginInvoke((Action)(() => { updProgress = 0.92f; updLine = "Unpacking"; })); } catch { }
        string part = target + ".part";
        if (Directory.Exists(part)) Directory.Delete(part, true);
        System.IO.Compression.ZipFile.ExtractToDirectory(zip, part);
        if (Directory.Exists(target)) Directory.Delete(target, true);
        Directory.Move(part, target);
        try { File.Delete(zip); } catch { }
        return File.Exists(exe) ? exe : null;
    }

    void RunBuilder(string exe, string tag) {
        try {
            var psi = new ProcessStartInfo(exe, "--update \"" + dir + "\" --tag \"" + tag + "\"") { WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false };
            Process.Start(psi);
            Close();   // (the builder rebuilds this folder, this launcher with it)
        } catch (Exception ex) {
            SetUpdate(Theme.Red, "The builder could not start", ex.Message, "Check again", false, true);
        }
    }

    // (host/hos_update.c install_patch: downloaded, checked, the old dll kept as hookshot_vk.prev.dll)
    string InstallPatch(string url, string tag, long size) {
        try {
            byte[] data = null;
            using (var c = Client()) {
                c.Headers[HttpRequestHeader.Accept] = "application/octet-stream";
                var done = new ManualResetEvent(false); Exception err = null;
                c.DownloadProgressChanged += (s, e) => {
                    long total = e.TotalBytesToReceive > 0 ? e.TotalBytesToReceive : size;
                    if (total > 0) { float p = (float)e.BytesReceived / total; try { BeginInvoke((Action)(() => { updProgress = p; updLine = (e.BytesReceived >> 20) + " / " + (total >> 20) + " MB"; })); } catch { } }
                };
                c.DownloadDataCompleted += (s, e) => { if (e.Error != null) err = e.Error; else data = e.Result; done.Set(); };
                c.DownloadDataAsync(new Uri(url));
                done.WaitOne();
                if (err != null) throw err;
            }
            if (data == null || data.Length < 4096 || data[0] != 'M' || data[1] != 'Z' || (size > 0 && data.Length != size)) return "the download is not right";
            string part = Path.Combine(dir, "hookshot_vk.dll.part"), cur = Path.Combine(dir, "hookshot_vk.dll"), prev = Path.Combine(dir, "hookshot_vk.prev.dll");
            File.WriteAllBytes(part, data);
            if (File.Exists(cur)) {
                if (File.Exists(prev)) File.Delete(prev);
                File.Move(cur, prev);
            }
            try { File.Move(part, cur); } catch { if (File.Exists(prev)) File.Move(prev, cur); throw; }
            Directory.CreateDirectory(Path.Combine(dir, "user"));
            File.WriteAllText(Path.Combine(dir, "user", "hookshot_vk_version.txt"), "version=" + tag + "\n");
            return null;
        } catch (Exception ex) { return ex.Message; }
    }

    // ---- play and folders ----
    static bool GameRunning() { return Process.GetProcessesByName(Path.GetFileNameWithoutExtension(Fork.GameExe)).Length > 0; }

    void OpenFolder(string path) {
        try {
            Directory.CreateDirectory(path);
            Process.Start("explorer.exe", "\"" + path + "\"");
        } catch (Exception ex) { MessageBox.Show(this, ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    void OpenUrl(string url) { try { Process.Start(url); } catch { } }

    void OnImport() {
        OpenFolder(Path.Combine(dir, "SAVE FOLDER"));
        MessageBox.Show(this, "Put saves from another emulator here (the folder holding slot_00, slot_01… or a folder above it).\n" +
                        "They are copied into the game at the next start, and the saves you had are kept in a backup folder.",
                        "Import saves", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    void OnPlay() {
        string exe = Path.Combine(dir, Fork.GameExe);
        if (!File.Exists(exe)) {
            MessageBox.Show(this, "The game is not in this folder:\n" + dir + "\n\nThe launcher must sit beside it.", Fork.Name,
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (GameRunning()) { MessageBox.Show(this, "The game is already running.", Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
        try {
            var psi = new ProcessStartInfo(exe) { WorkingDirectory = dir, UseShellExecute = false };
            psi.EnvironmentVariables["HOOKSHOT_NO_UPDATE_CHECK"] = "1";   // (the launcher did it)
            Process.Start(psi);
            Close();
        } catch (Exception ex) { MessageBox.Show(this, "The game could not start:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    [STAThread]
    static void Main(string[] args) {
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;   // (TLS 1.2: GitHub)
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string dir = args.Length > 0 && Directory.Exists(args[0]) ? Path.GetFullPath(args[0]) : AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        Application.Run(new LauncherForm(dir));
    }
}
