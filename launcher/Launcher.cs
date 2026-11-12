// Mako Launcher (Ocarina of Time PC recompile, by sharkiix; based on Hookshot, GPL-3). The window players open first: update
// check (the same GitHub release and graphics patch rules as host/hos_update.c), the game's settings (hookshot_options.ini, the
// Insert menu's file), the fix switches (AMD fixes, basic controller mode) (hookshot_env.txt, read by the game at start), language, saves folders, and PLAY.
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
[assembly: System.Reflection.AssemblyVersion("3.3.0.0")]

// A seed's ID, as gpu/vk/oot_rando.h makes and reads it (oot_rando_id, oot_rando_from_id): 15 characters, XXXXX-XXXXX-XXXXX,
// of the seed's random part and every setting, with a checksum. Bits, low first: the format's version 4, the random part 31,
// 16 settings of 2 bits in the table's order, the checksum 8. And the longer one, 20 characters, made only when a setting
// past the sixteenth is set: the version 2, the random part 31, 28 settings of 2 bits, a bit that is 0, the checksum 8.
static class RandoId {
    const string Alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    const int Bits = 75, Check = 8, Slots = 16, FormatVersion = 1;
    const int LongBits = 100, LongSlots = 28, LongVersion = 2;

    static void Put(byte[] bits, ref int n, uint value, int width) { for (int i = 0; i < width; i++) bits[n++] = (byte)(value >> i & 1); }
    static uint Get(byte[] bits, ref int n, int width) { uint v = 0; for (int i = 0; i < width; i++) v |= (uint)bits[n++] << i; return v; }
    static uint Sum(byte[] bits, int total) {   // (FNV-1a over the bits before the checksum, folded to its width)
        uint h = 0x811c9dc5u;
        unchecked { for (int i = 0; i < total - Check; i++) h = (h ^ bits[i]) * 0x01000193u; }
        return (h ^ h >> 8 ^ h >> 16 ^ h >> 24) & ((1u << Check) - 1);
    }
    static uint Choice(int[] choices, int i) { return i < choices.Length && choices[i] > 0 && choices[i] < 4 ? (uint)choices[i] : 0; }

    public static string Make(int seed, int[] choices) {
        bool longer = false;
        for (int i = Slots; i < LongSlots; i++) longer |= Choice(choices, i) != 0;
        return Make(seed, choices, longer);
    }

    // (longer: the 20 characters, which hold the settings past the sixteenth; else the 15)
    public static string Make(int seed, int[] choices, bool longer) {
        int total = longer ? LongBits : Bits;
        var bits = new byte[total];
        int n = 0;
        Put(bits, ref n, (uint)(longer ? LongVersion : FormatVersion), 4);
        Put(bits, ref n, (uint)seed & 0x7fffffffu, 31);
        for (int i = 0; i < (longer ? LongSlots : Slots); i++) Put(bits, ref n, Choice(choices, i), 2);
        n = total - Check;   // (the longer one's bit before the checksum stays 0)
        Put(bits, ref n, Sum(bits, total), Check);
        var sb = new StringBuilder();
        for (int c = 0; c < total / 5; c++) {
            int at = c * 5;
            if (c > 0 && c % 5 == 0) sb.Append('-');
            sb.Append(Alphabet[(int)Get(bits, ref at, 5)]);
        }
        return sb.ToString();
    }

    // (null and the seed and its choices, or what is wrong with the text. counts: how many choices each setting has)
    public static string Read(string text, int[] counts, out int seed, out int[] choices) {
        seed = 0; choices = new int[counts.Length];
        var bits = new byte[LongBits];
        int n = 0;
        foreach (char raw in text) {
            char ch = char.ToUpperInvariant(raw);
            if (ch == '-' || ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n') continue;
            if (ch == 'O') ch = '0';
            if (ch == 'I' || ch == 'L') ch = '1';
            int at = Alphabet.IndexOf(ch);
            if (at < 0) return "it has a character no seed ID has";
            if (n == LongBits) return "it is too long (a seed ID has 15 or 20 characters)";
            Put(bits, ref n, (uint)at, 5);
        }
        if (n < Bits) return "it is too short (a seed ID has 15 or 20 characters)";
        if (n != Bits && n != LongBits) return "it is not as long as a seed ID is (15 or 20 characters)";
        int total = n;
        bool longer = n == LongBits;
        n = total - Check;
        if (Get(bits, ref n, Check) != Sum(bits, total)) return "a typo? Its checksum does not match";
        n = 0;
        if (Get(bits, ref n, 4) != (uint)(longer ? LongVersion : FormatVersion)) return "it is from another version of the randomizer";
        seed = (int)Get(bits, ref n, 31);
        for (int i = 0; i < (longer ? LongSlots : Slots); i++) {
            int v = (int)Get(bits, ref n, 2);
            if (v >= (i < counts.Length ? counts[i] : 1)) return "it has a setting this version does not have";
            if (i < counts.Length) choices[i] = v;
        }
        if (longer && Get(bits, ref n, 1) != 0) return "it has a setting this version does not have";
        return null;
    }
}

// ---- kept copies of the saves ----
// The game has one save of the player's own and five it makes itself (slot_00, and slot_01 to slot_05), and its load menu
// lists no more. A kept copy is the whole save folder under a name, in <game folder>\user\save_copies\<save folder>\<name>:
// the randomizer's saves (save_rando) and the normal game's (save) have their own. Restoring one puts it in the save
// folder's place, after keeping what was there as a copy of its own, so that nothing is lost. tests/test_save_copies.py
public static class SaveCopies {
    public const string Folder = "save_copies";
    public const string BeforeRestore = "Before restore ";

    public static string Root(string dir, string saveFolder) { return Path.Combine(dir, "user", Folder, saveFolder); }

    // Whether a restore keeps the saves that were there as a "Before restore" copy first: the window's tick box, kept in
    // <game folder>\user\save_copies\keep_before_restore.txt ("0" off; no file, or anything else: on, so that nothing is
    // lost by one who never looked at the box).
    static string KeepFile(string dir) { return Path.Combine(dir, "user", Folder, "keep_before_restore.txt"); }
    public static bool KeepBefore(string dir) {
        try { return File.ReadAllText(KeepFile(dir)).Trim() != "0"; } catch { return true; }
    }
    public static void SetKeepBefore(string dir, bool on) {
        try {
            Directory.CreateDirectory(Path.Combine(dir, "user", Folder));
            File.WriteAllText(KeepFile(dir), on ? "1" : "0");
        } catch { }
    }

    // (a name that can be a folder's: no path, no character Windows refuses, no dot or space at its end)
    public static string Clean(string name) {
        var sb = new StringBuilder();
        foreach (char c in name ?? "")
            if (Array.IndexOf(Path.GetInvalidFileNameChars(), c) < 0 && c >= ' ') sb.Append(c);
        string n = sb.ToString().Trim().TrimEnd('.', ' ');
        return n.Length > 80 ? n.Substring(0, 80).TrimEnd('.', ' ') : n;
    }

    // (the copies, the newest first)
    public static List<string> List(string dir, string saveFolder) {
        var found = new List<string>();
        string root = Root(dir, saveFolder);
        if (!Directory.Exists(root)) return found;
        var dirs = new List<DirectoryInfo>(new DirectoryInfo(root).GetDirectories());
        dirs.Sort((a, b) => b.CreationTimeUtc.CompareTo(a.CreationTimeUtc));
        foreach (var d in dirs) found.Add(d.Name);
        return found;
    }

    static void CopyTree(string from, string to) {
        Directory.CreateDirectory(to);
        foreach (string f in Directory.GetFiles(from)) File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
        foreach (string d in Directory.GetDirectories(from)) CopyTree(d, Path.Combine(to, Path.GetFileName(d)));
    }

    static bool HasFiles(string path) {
        return Directory.Exists(path) && Directory.GetFiles(path, "*", SearchOption.AllDirectories).Length > 0;
    }

    // Keeps the save folder as a copy named `name`. Returns null, or what went wrong. A copy of that name is not replaced.
    public static string Keep(string dir, string saveFolder, string name) {
        string clean = Clean(name);
        if (clean.Length == 0) return "Give the copy a name.";
        string from = Path.Combine(dir, "user", saveFolder), to = Path.Combine(Root(dir, saveFolder), clean);
        if (!HasFiles(from)) return "There are no saves to copy yet.";
        if (Directory.Exists(to)) return "There is already a copy named \"" + clean + "\".";
        string part = to + ".part";
        try {
            if (Directory.Exists(part)) Directory.Delete(part, true);
            CopyTree(from, part);
            Directory.Move(part, to);   // (whole, or not there)
            return null;
        } catch (Exception ex) {
            try { if (Directory.Exists(part)) Directory.Delete(part, true); } catch { }
            return ex.Message;
        }
    }

    // Makes the copy named `name` the saves as they are now, in place of what it held. Returns null, or what went wrong
    // (then the copy is as it was): the new one is made whole beside it before the old one goes.
    public static string Update(string dir, string saveFolder, string name) {
        string from = Path.Combine(dir, "user", saveFolder), to = Path.Combine(Root(dir, saveFolder), name);
        if (name != Clean(name) || name.Length == 0 || !Directory.Exists(to)) return "That copy is not there any more.";
        if (!HasFiles(from)) return "There are no saves to copy yet.";
        string part = to + ".part", old = to + ".old";
        try {
            if (Directory.Exists(part)) Directory.Delete(part, true);
            if (Directory.Exists(old)) Directory.Delete(old, true);
            CopyTree(from, part);
            Directory.Move(to, old);
            try { Directory.Move(part, to); }
            catch { Directory.Move(old, to); throw; }   // (as it was)
            Directory.Delete(old, true);
            return null;
        } catch (Exception ex) {
            try { if (Directory.Exists(part)) Directory.Delete(part, true); } catch { }
            return ex.Message;
        }
    }

    // Puts the copy named `name` in the save folder's place. With keepFirst, what was there is kept first, as "Before
    // restore <date and time>", unless it is empty; without, it is replaced. Returns null, or what went wrong (then the
    // saves are as they were).
    public static string Restore(string dir, string saveFolder, string name, DateTime now, bool keepFirst = true) {
        string from = Path.Combine(Root(dir, saveFolder), name), to = Path.Combine(dir, "user", saveFolder);
        if (name != Clean(name) || !HasFiles(from)) return "That copy is not there any more.";
        if (keepFirst && HasFiles(to)) {
            string stem = BeforeRestore + now.ToString("yyyy-MM-dd HH.mm.ss"), kept = stem;
            for (int i = 2; Directory.Exists(Path.Combine(Root(dir, saveFolder), kept)); i++) kept = stem + " (" + i + ")";
            string error = Keep(dir, saveFolder, kept);
            if (error != null) return "The saves you have now could not be kept first, so nothing was changed:\n" + error;
        }
        string old = to + ".old";
        try {
            if (Directory.Exists(old)) Directory.Delete(old, true);
            if (Directory.Exists(to)) Directory.Move(to, old);
            try { CopyTree(from, to); }
            catch {
                try { if (Directory.Exists(to)) Directory.Delete(to, true); } catch { }
                if (Directory.Exists(old)) Directory.Move(old, to);   // (as they were)
                throw;
            }
            if (Directory.Exists(old)) Directory.Delete(old, true);
            return null;
        } catch (Exception ex) { return ex.Message; }
    }

    public static string Delete(string dir, string saveFolder, string name) {
        string path = Path.Combine(Root(dir, saveFolder), name);
        if (name != Clean(name) || name.Length == 0 || !Directory.Exists(path)) return "That copy is not there any more.";
        try { Directory.Delete(path, true); return null; } catch (Exception ex) { return ex.Message; }
    }
}

// (the window of the Save copies button: a name to keep the saves under, and the copies kept, to restore or delete)
class SaveCopiesForm : Form {
    readonly string dir, saveFolder;
    readonly TextBox name = new TextBox();
    readonly ListBox list = new ListBox();
    readonly Button keep = new Button(), restore = new Button(), update = new Button(), delete = new Button(), close = new Button();
    readonly CheckBox keepFirst = new CheckBox();

    public SaveCopiesForm(string dir, string saveFolder) {
        this.dir = dir; this.saveFolder = saveFolder;
        bool rando = saveFolder == "save_rando";
        Text = "Save copies: " + (rando ? "the randomizer's saves" : "the normal game's saves");
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false; ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;
        ClientSize = new Size(520, 458);
        BackColor = Color.FromArgb(16, 25, 43); ForeColor = Theme.Text; Font = new Font("Segoe UI", 10f);
        var top = new Label { Text = "Keep the saves you have now under a name:", AutoSize = true, Location = new Point(16, 14) };
        name.SetBounds(16, 40, 368, 26); name.MaxLength = 80;
        name.BackColor = Color.FromArgb(24, 36, 60); name.ForeColor = Theme.Text; name.BorderStyle = BorderStyle.FixedSingle;
        Style(keep, "Keep a copy", 394, 38, 110);
        var mid = new Label { Text = "Kept copies, the newest first:", AutoSize = true, Location = new Point(16, 84) };
        list.SetBounds(16, 110, 488, 232); list.IntegralHeight = false;
        keepFirst.Text = "Before a restore, keep the saves I have now as a \"Before restore\" copy";
        keepFirst.SetBounds(16, 394, 488, 24); keepFirst.ForeColor = Theme.Text; keepFirst.FlatStyle = FlatStyle.Flat;
        keepFirst.Checked = SaveCopies.KeepBefore(dir);
        keepFirst.CheckedChanged += (o, e) => SaveCopies.SetKeepBefore(dir, keepFirst.Checked);
        list.BackColor = Color.FromArgb(24, 36, 60); list.ForeColor = Theme.Text; list.BorderStyle = BorderStyle.FixedSingle;
        Style(restore, "Restore", 16, 354, 110); Style(update, "Update", 136, 354, 110); Style(delete, "Delete", 256, 354, 110);
        Style(close, "Close", 394, 354, 110);
        var foot = new Label { Text = "Update: the copy becomes the saves you have now. Close the game before a restore.",
                               AutoSize = false, ForeColor = Theme.Dim, Location = new Point(16, 426), Size = new Size(488, 24), Font = new Font("Segoe UI", 8.5f) };
        Controls.AddRange(new Control[] { top, name, keep, mid, list, restore, update, delete, close, keepFirst, foot });
        AcceptButton = keep; CancelButton = close;
        keep.Click += (o, e) => OnKeep();
        restore.Click += (o, e) => OnRestore();
        update.Click += (o, e) => OnUpdate();
        delete.Click += (o, e) => OnDelete();
        close.Click += (o, e) => Close();
        list.SelectedIndexChanged += (o, e) => Buttons();
        list.DoubleClick += (o, e) => OnRestore();
        Fill(null);
    }

    static void Style(Button b, string text, int x, int y, int w) {
        b.Text = text; b.SetBounds(x, y, w, 30); b.FlatStyle = FlatStyle.Flat;
        b.BackColor = Color.FromArgb(30, 46, 78); b.ForeColor = Color.White; b.FlatAppearance.BorderColor = Color.FromArgb(60, 90, 150);
    }

    void Buttons() { restore.Enabled = update.Enabled = delete.Enabled = list.SelectedIndex >= 0; }

    void Fill(string select) {
        list.Items.Clear();
        foreach (string n in SaveCopies.List(dir, saveFolder)) list.Items.Add(n);
        if (select != null) list.SelectedItem = select;
        Buttons();
    }

    void Say(string text, MessageBoxIcon icon) { MessageBox.Show(this, text, "Save copies", MessageBoxButtons.OK, icon); }

    void OnKeep() {
        string n = SaveCopies.Clean(name.Text);
        string error = SaveCopies.Keep(dir, saveFolder, n);
        if (error != null) { Say(error, MessageBoxIcon.Warning); return; }
        name.Text = "";
        Fill(n);
    }

    void OnRestore() {
        if (list.SelectedIndex < 0) return;
        string n = (string)list.SelectedItem;
        if (LauncherForm.GameRunning()) { Say("Close the game first: it would write its own saves over the restored ones.", MessageBoxIcon.Information); return; }
        bool first = keepFirst.Checked;
        if (MessageBox.Show(this, "Restore \"" + n + "\"?\n\n" + (first ? "The saves you have now are kept as a copy first."
                                : "The saves you have now are replaced and NOT kept: the box below is off."), "Save copies",
                            MessageBoxButtons.OKCancel, first ? MessageBoxIcon.Question : MessageBoxIcon.Warning,
                            first ? MessageBoxDefaultButton.Button1 : MessageBoxDefaultButton.Button2) != DialogResult.OK) return;
        string error = SaveCopies.Restore(dir, saveFolder, n, DateTime.Now, first);
        if (error != null) { Say(error, MessageBoxIcon.Warning); Fill(n); return; }
        Fill(n);
        Say("\"" + n + "\" is restored. It is in the game's load menu at the next start.", MessageBoxIcon.Information);
    }

    void OnUpdate() {
        if (list.SelectedIndex < 0) return;
        string n = (string)list.SelectedItem;
        if (MessageBox.Show(this, "Update \"" + n + "\" to the saves you have now?\n\nWhat the copy held is replaced.", "Save copies",
                            MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
        string error = SaveCopies.Update(dir, saveFolder, n);
        if (error != null) Say(error, MessageBoxIcon.Warning);
        Fill(n);
    }

    void OnDelete() {
        if (list.SelectedIndex < 0) return;
        string n = (string)list.SelectedItem;
        if (MessageBox.Show(this, "Delete the copy \"" + n + "\"? It cannot be brought back.\n\nThe saves in the game are not touched.", "Save copies",
                            MessageBoxButtons.OKCancel, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.OK) return;
        string error = SaveCopies.Delete(dir, saveFolder, n);
        if (error != null) Say(error, MessageBoxIcon.Warning);
        Fill(null);
    }
}

// (Mako) AMD's FSR files, from AMD's own repository (FidelityFX SDK v2.4.0, Kits/FidelityFX/signedbin): name, what it is, size
static class Fsr {
    public const string Base = "https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/v2.4.0/Kits/FidelityFX/signedbin/";
    public const string Page = "https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK";
    public static readonly string[][] Files = {
        new[] { "amd_fidelityfx_loader_vk.dll", "AMD FSR loader", "39184" },
        new[] { "amd_fidelityfx_upscaler_vk.dll", "AMD FSR 4 upscaling", "36135696" },
        new[] { "amd_fidelityfx_framegeneration_vk.dll", "AMD FSR frame generation (RX 9000)", "36806928" },
    };
    static string gpu;
    /// the display adapter's name, a Radeon first (the registry's display class: no WMI)
    public static string Gpu() {
        if (gpu != null) return gpu;
        gpu = "";
        try {
            using (var cls = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}")) {
                if (cls != null)
                    foreach (string k in cls.GetSubKeyNames()) {
                        if (k.Length != 4) continue;
                        try {
                            using (var a = cls.OpenSubKey(k)) {
                                string d = a == null ? null : a.GetValue("DriverDesc") as string;
                                if (string.IsNullOrEmpty(d)) continue;
                                if (gpu.Length == 0 || (d.Contains("Radeon") && !gpu.Contains("Radeon"))) gpu = d;
                            }
                        } catch { }
                    }
            }
        } catch { }
        return gpu;
    }
    /// 2: Radeon RX 9000 (FSR 4 + frame generation), 1: Radeon RX 6000 / 7000 (FSR 4), 0: other
    public static int Tier(string name) {
        if (name.IndexOf("Radeon", StringComparison.OrdinalIgnoreCase) < 0) return 0;
        var m = Regex.Match(name, @"RX\s*(\d)\d{3}", RegexOptions.IgnoreCase);
        if (!m.Success) return 0;
        int series = m.Groups[1].Value[0] - '0';
        return series >= 9 ? 2 : series >= 6 ? 1 : 0;
    }

    [DllImport("wintrust.dll", CharSet = CharSet.Unicode)]
    static extern int WinVerifyTrust(IntPtr hwnd, [MarshalAs(UnmanagedType.LPStruct)] Guid action, ref WinTrustData data);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WinTrustFileInfo { public uint Size; public string Path; public IntPtr File; public IntPtr Subject; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WinTrustData {
        public uint Size; public IntPtr Policy; public IntPtr SipData; public uint UiChoice; public uint RevocationChecks; public uint UnionChoice;
        public IntPtr FileInfo; public uint StateAction; public IntPtr StateData; public string UrlReference; public uint ProvFlags; public uint UiContext;
        public IntPtr SignatureSettings;
    }
    /// a valid Authenticode signature whose signer is AMD
    public static bool SignedByAmd(string path) {
        try {
            var cert = System.Security.Cryptography.X509Certificates.X509Certificate.CreateFromSignedFile(path);
            if (cert.Subject.IndexOf("Advanced Micro Devices", StringComparison.OrdinalIgnoreCase) < 0) return false;
        } catch { return false; }
        var fi = new WinTrustFileInfo { Size = (uint)Marshal.SizeOf(typeof(WinTrustFileInfo)), Path = path };
        IntPtr pfi = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WinTrustFileInfo)));
        try {
            Marshal.StructureToPtr(fi, pfi, false);
            var d = new WinTrustData { Size = (uint)Marshal.SizeOf(typeof(WinTrustData)), UiChoice = 2, RevocationChecks = 0, UnionChoice = 1,
                                       FileInfo = pfi, StateAction = 0, ProvFlags = 0x80 };
            var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");   // (WINTRUST_ACTION_GENERIC_VERIFY_V2)
            return WinVerifyTrust(new IntPtr(-1), action, ref d) == 0;
        } finally { Marshal.DestroyStructure(pfi, typeof(WinTrustFileInfo)); Marshal.FreeHGlobal(pfi); }
    }
}

// (Mako) The Recommended tab: what this PC has (graphics card and its memory, processor, memory, screen), read once, and the
// settings that suit it, with the reason for each
class PcInfo {
    public string Gpu = "", Cpu = "";
    public int Tier, Threads, ScreenW, ScreenH, Hz;
    public long VramMB, RamMB;
    public bool Amd, Nvidia, Intel, Integrated;

    [StructLayout(LayoutKind.Sequential)]
    struct MemStatus { public uint Length, Load; public ulong Total, Avail, TotalPage, AvailPage, TotalVirt, AvailVirt, AvailExt; }
    [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref MemStatus m);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct DevMode {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        public short SpecVersion, DriverVersion, Size, DriverExtra; public int Fields;
        public int PositionX, PositionY, DisplayOrientation, DisplayFixedOutput;
        public short Color, Duplex, YResolution, TTOption, Collate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string FormName;
        public short LogPixels; public int BitsPerPel, PelsWidth, PelsHeight, DisplayFlags, DisplayFrequency;
        public int ICMMethod, ICMIntent, MediaType, DitherType, Reserved1, Reserved2, PanningWidth, PanningHeight;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumDisplaySettings(string dev, int mode, ref DevMode dm);

    public static PcInfo Read() {
        var p = new PcInfo();
        p.Gpu = Fsr.Gpu();
        p.Tier = Fsr.Tier(p.Gpu);
        string n = p.Gpu.ToLowerInvariant();
        p.Amd = n.Contains("radeon") || n.Contains("amd");
        p.Nvidia = n.Contains("nvidia") || n.Contains("geforce") || n.Contains("rtx") || n.Contains("gtx");
        p.Intel = n.Contains("intel");
        try {   // (the adapter's memory: the display class key the name came from)
            using (var cls = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"))
                if (cls != null)
                    foreach (string k in cls.GetSubKeyNames()) {
                        if (k.Length != 4) continue;
                        try {
                            using (var a = cls.OpenSubKey(k)) {
                                if (a == null || (a.GetValue("DriverDesc") as string) != p.Gpu) continue;
                                object q = a.GetValue("HardwareInformation.qwMemorySize"), m = a.GetValue("HardwareInformation.MemorySize");
                                long bytes = 0;
                                if (q is long) bytes = (long)q;
                                else if (m is int) bytes = (uint)(int)m;
                                else if (m is byte[] && ((byte[])m).Length >= 4) bytes = BitConverter.ToUInt32((byte[])m, 0);
                                if (bytes > 0) p.VramMB = Math.Max(p.VramMB, bytes >> 20);
                            }
                        } catch { }
                    }
        } catch { }
        // (built into the processor: Intel's (not Arc), or a Radeon without an RX name and little memory of its own)
        p.Integrated = (p.Intel && !n.Contains("arc")) || (p.Amd && !Regex.IsMatch(p.Gpu, @"RX\s*\d", RegexOptions.IgnoreCase) && p.VramMB > 0 && p.VramMB <= 2048);
        try {
            var ms = new MemStatus { Length = (uint)Marshal.SizeOf(typeof(MemStatus)) };
            if (GlobalMemoryStatusEx(ref ms)) p.RamMB = (long)(ms.Total >> 20);
        } catch { }
        p.Threads = Environment.ProcessorCount;
        try {
            using (var c = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"HARDWARE\DESCRIPTION\System\CentralProcessor\0"))
                if (c != null) p.Cpu = ((c.GetValue("ProcessorNameString") as string) ?? "").Trim();
        } catch { }
        try {
            var dm = new DevMode { DeviceName = "", FormName = "" };
            dm.Size = (short)Marshal.SizeOf(typeof(DevMode));
            if (EnumDisplaySettings(null, -1, ref dm)) { p.ScreenW = dm.PelsWidth; p.ScreenH = dm.PelsHeight; p.Hz = dm.DisplayFrequency; }
        } catch { }
        if (p.ScreenW <= 0) { var b = Screen.PrimaryScreen.Bounds; p.ScreenW = b.Width; p.ScreenH = b.Height; }
        if (p.Hz <= 1) p.Hz = 60;
        return p;
    }

    public int VramGB { get { return (int)Math.Round(VramMB / 1024.0); } }
    public int RamGB { get { return (int)Math.Round(RamMB / 1024.0); } }
}

// (one line of the Recommended tab: a setting, the value for this PC, why; apply: the options.ini key and value the Apply button
// writes, null for advice only)
class RecRow {
    public string What, Value, Why, Key; public int Set; public bool Good = true;
    public RecRow(string what, string value, string why) { What = what; Value = value; Why = why; }
}

static class Fork {
    public const string Name = "Mako";
    // (the update check compares the first number of the tags: the first Mako release must be numbered above amd-fix-2.1, or the
    // 2.x launchers players have would think it older and never offer it)
    public const string Base = "mako-3.5";      // (host/hos_update.c HOOKSHOT_FORK_BASE: the exe this launcher ships with)
    public const string Version = "mako-3.5"; // (HOOKSHOT_FORK_VERSION)
    public const int Api = 15;                  // (gpu/vk/vk_api.h MKWVK_API_VERSION)
    public const string Api_Url = "https://api.github.com/repos/Shakoquo/Mako/releases/latest";
    public const string Page = "https://github.com/Shakoquo/Mako/releases/latest";
    public const string Home = "https://github.com/Shakoquo/Mako";
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
    public int HideOn = -1;      // (an always-shown widget left out on this page)
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
    public bool Gold;   // (Mako: the Master Quest Play button)
    public Image Logo;  // (Mako: the left panel's Master Quest button: its logo on a dark button)
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
        if (Gold) { PaintGold(g); return; }
        float pulse = 0.5f + 0.5f * (float)Math.Sin(t * 2.2);
        // (the glow under it, breathing)
        for (int i = 8; i >= 1; i--) {
            var gr = RectangleF.Inflate(R, i * 2.2f, i * 2.2f);
            using (var p = Theme.Round(gr, 16 + i * 2))
            using (var b = new SolidBrush(Theme.A(Gold ? Theme.Amber : Theme.Blue, (int)((5 + 6 * pulse + 8 * h) * (Enabled ? 1 : 0.2f))))) g.FillPath(b, p);
        }
        using (var path = Theme.Round(R, 16)) {
            Color top0 = Gold ? Color.FromArgb(232, 168, 52) : Color.FromArgb(30, 110, 255), top1 = Gold ? Color.FromArgb(255, 214, 120) : Theme.Cyan;
            Color bot0 = Gold ? Color.FromArgb(150, 92, 18) : Color.FromArgb(22, 70, 200), bot1 = Gold ? Theme.Amber : Theme.Blue;
            using (var br = new LinearGradientBrush(R, Theme.Mix(top0, top1, h * 0.4f), Theme.Mix(bot0, bot1, h),
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
    public override bool Animating { get { return Style == Kind.Play && !Gold; } }
    // (Mako: the Master Quest Play button, plain: a deep gold, lighter under the mouse)
    void PaintGold(Graphics g) {
        float h = Hover;
        if (Logo != null) {
            using (var path = Theme.Round(R, 14)) {
                using (var br = new LinearGradientBrush(R, Theme.Mix(Color.FromArgb(26, 22, 18), Color.FromArgb(40, 33, 24), h), Color.FromArgb(14, 12, 10),
                                                        LinearGradientMode.Vertical)) g.FillPath(br, path);
                using (var pen = new Pen(Theme.Mix(Color.FromArgb(150, 118, 62), Color.FromArgb(226, 184, 106), h), 1.2f)) g.DrawPath(pen, path);
            }
            float lh = R.Height - 8, lw = lh * Logo.Width / Logo.Height;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.DrawImage(Logo, R.X + 14, R.Y + 4, lw, lh);
            using (var b = new SolidBrush(Theme.Mix(Color.FromArgb(226, 184, 106), Color.FromArgb(255, 222, 160), h)))
                Theme.Spaced(g, Text, Theme.Pick(15f, FontStyle.Bold, "Bahnschrift", "Segoe UI Semibold", "Segoe UI"), b,
                             R.X + 14 + lw + (R.Width - 14 - lw) / 2, R.Y + R.Height / 2 - 9.5f, 4);
            return;
        }
        using (var path = Theme.Round(R, 14)) {
            using (var br = new LinearGradientBrush(R, Theme.Mix(Color.FromArgb(196, 146, 62), Color.FromArgb(214, 166, 80), h),
                                                    Theme.Mix(Color.FromArgb(150, 104, 36), Color.FromArgb(170, 122, 48), h), LinearGradientMode.Vertical)) g.FillPath(br, path);
            using (var pen = new Pen(Color.FromArgb(70 + (int)(60 * h), 255, 236, 190), 1f)) g.DrawPath(pen, path);
        }
        using (var b = new SolidBrush(Color.White))
            Theme.Spaced(g, Text, Theme.Pick(20f, FontStyle.Bold, "Bahnschrift", "Segoe UI Black", "Segoe UI"), b, R.X + R.Width / 2, R.Y + R.Height / 2 - 12.5f, 5);
    }
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
    public override string Help { get { return null; } }   // (its text is on it already)
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

// (Mako) one of the Master Quest page's trials: a card, gold when chosen
class GoldChoice : Widget {
    public string Title, Sub; public Func<bool> IsOn; public Action Click;
    public override void Down(PointF p, LauncherForm ui) { if (Click != null) Click(); }
    public override void Paint(Graphics g, LauncherForm ui) {
        bool on = IsOn != null && IsOn();
        var gold = Color.FromArgb(226, 184, 106);
        using (var path = Theme.Round(R, 10)) {
            using (var b = new SolidBrush(on ? Theme.A(gold, 22) : Theme.Mix(Theme.Card, Theme.CardHi, Hover))) g.FillPath(b, path);
            using (var pen = new Pen(on ? gold : Theme.Mix(Theme.Line, Theme.A(gold, 160), Hover), on ? 1.4f : 1f)) g.DrawPath(pen, path);
        }
        Theme.Text_(g, Title, Theme.Value, on ? gold : Theme.Text, new RectangleF(R.X + 18, R.Y, 60, R.Height), StringAlignment.Near, StringAlignment.Center);
        Theme.Text_(g, Sub, Theme.Small, on ? Theme.Text : Theme.Dim, new RectangleF(R.X + 62, R.Y, R.Width - 70, R.Height), StringAlignment.Near, StringAlignment.Center);
    }
}

class TabW : Widget {
    public string Text; public int Index;
    public override void Down(PointF p, LauncherForm ui) { ui.ShowPage(Index); }
    public override void Paint(Graphics g, LauncherForm ui) {
        bool on = ui.PageNow == Index;
        Color c = on ? Color.White : Theme.Mix(Theme.Dim, Theme.Text, Hover);
        Theme.Text_(g, Text, Theme.Tab, c, R, StringAlignment.Center, StringAlignment.Center);
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
    Btn updateButton, playButton, fsrButton;
    string fsrLine = ""; Color fsrLineColor = Theme.Dim; bool fsrBusy;
    Image logo, mqLogo;
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
    readonly Dictionary<string, Selector> cosmetics = new Dictionary<string, Selector>();   // (the Cosmetics page's selectors, by their line)
    readonly string cosmeticsPath;
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
        new object[] { "output_res", "Output resolution", new[] { "1280 x 720", "1600 x 900", "1920 x 1080", "2048 x 1152 (the game's)", "2560 x 1440", "3840 x 2160 (4K)" }, new[] { 6, 5, 3, 0, 1, 2 },
            "The size the game draws its whole picture at, menus included, before it is fitted to your screen. Higher is sharper and heavier." },
        new object[] { "resolution", "3D resolution", new[] { "Auto", "100%", "75%", "67%", "50%" }, new[] { 0, 1, 2, 3, 4 },
            "How sharp the 3D is drawn, as a share of the output resolution. Auto lowers it when the graphics card is busy." },
        new object[] { "dlss", "Upscaler", new[] { "The game's own", "AMD FSR 3.1", "AMD FSR 4", "AMD FSR 4 Native AA" }, new[] { 0, 3, 4, 5 },
            "What brings the 3D up to the output resolution. FSR 3.1 works on any graphics card. FSR 4 is sharper: RX 9000 cards, and AMD's FSR 4 files in the game folder. Native AA keeps the full resolution and only smooths the edges." },
        new object[] { "upscaling", "Screen filter", new[] { "Off", "Catmull-Rom", "Lanczos" }, new[] { 0, 1, 2 },
            "The filter that fits the picture to your screen. Catmull-Rom is sharper, Lanczos sharper still." },
        new object[] { "sharpness", "Sharpness", new[] { "0%", "10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%" }, new[] { 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 },
            "Sharpens the picture on its way to the screen. Too much shows halos around edges." },
        new object[] { "frame_generation", "Frame generation", new[] { "Off", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "AMD Redstone 2x" }, new[] { 0, 2, 3, 4, 5, 6, 7, 8, 2 },
            "Shows extra in-between frames for smoother motion. AMD Redstone 2x: AMD's AI frame generation instead of Mako's, for RX 9000 cards with AMD's files (FSR tab) and FSR 4. Best with 12 GB+." },
        new object[] { "frame_rate_cap", "Frame rate cap", new[] { "60 (the console's)", "90", "120", "144", "165", "240" }, new[] { 0, 1, 2, 3, 4, 5 },
            "The most frames per second the game runs at. Above 60 needs a screen that shows them." },
        new object[] { "amd_anti-lag_2", "AMD Anti-Lag 2", new[] { "Off", "On" }, new[] { 0, 1 },
            "AMD graphics cards: less delay between your button and the screen. Has no effect while frame generation is on." },
        new object[] { "frame_pacing", "Frame pacing", new[] { "Off", "On" }, new[] { 0, 1 },
            "Spaces the frames evenly: steadier motion." },
        new object[] { "vsync", "VSync", new[] { "Off", "On" }, new[] { 0, 1 },
            "Waits for your screen before showing each frame: no tearing, at a little more delay." },
        new object[] { "fullscreen", "Display", new[] { "Window", "Fullscreen" }, new[] { 0, 1 },
            "Play in a window or full screen. Alt+Enter switches in game." },
        new object[] { "ultrawide", "Screen shape", new[] { "16:9", "Monitor's shape" }, new[] { 0, 1 },
            "Monitor's shape widens the camera to fill a screen wider than 16:9." },
        new object[] { "handheld_profile", "Handheld profile", new[] { "Off", "On" }, new[] { 0, 1 },
            "Runs the game as if the console were undocked: lower resolutions, lighter on the graphics card." },
    };
    static readonly object[][] GameRows = {
        new object[] { "fps_counter", "FPS counter", new[] { "Off", "On" }, new[] { 0, 1 },
            "Shows the frames per second in a corner of the screen." },
        new object[] { "game_speed", "Game speed", new[] { "Per frame", "Real time" }, new[] { 0, 1 },
            "Real time keeps the game at its normal speed even when the frame rate drops." },
        new object[] { "text_speed", "Text speed", new[] { "Normal", "2x", "4x", "Instant" }, new[] { 0, 1, 2, 3 },
            "How fast the dialogue text appears." },
        new object[] { "fast_forward", "Fast forward", new[] { "Off", "Hold", "Toggle" }, new[] { 0, 1, 2 },
            "The ` key (under Esc) or both sticks clicked in: the game runs 4x, to get through cutscenes. Toggle: press once for on, again for off." },
        new object[] { "controller_in_background", "Controller in background", new[] { "Off", "On" }, new[] { 0, 1 },
            "Keeps the controller working when the game window is not in front." },
    };
    // (the randomizer: the settings of gpu/vk/oot_rando.h. The same keys, choices and order: tests/test_rando_settings.py
    // checks them against that file. The seed's random part, rando_seed, is the New seed button's. The game's Insert menu
    // has no Randomizer tab since Mako 3.3 (its menu was written anew): this page is where they are set, and where a
    // seed's ID is copied and pasted)
    static readonly object[][] RandoRows = {
        new object[] { "rando_on", "Randomizer", new[] { "Off", "On" }, new[] { 0, 1 },
            "Turns the seed on. Chests, Gold Skulltulas, Quest rewards (with Frogs and Light Arrows), Deku Scrubs, Starting rupees, Dungeon keys, Major items, the forest's two ways and the opening are made when Play is pressed; the other settings are not placed yet. Saves made with it on are kept apart from the normal game's." },
        new object[] { "rando_chests", "Chests", new[] { "Off", "Overworld", "Dungeons", "All" }, new[] { 0, 1, 2, 3 },
            "Which treasure chests hold a shuffled item. All is every chest in the game." },
        new object[] { "rando_skulltulas", "Gold Skulltulas", new[] { "Off", "Dungeons", "Overworld", "All" }, new[] { 0, 1, 2, 3 },
            "Which Gold Skulltulas take part: their tokens change places with the chests' supplies (all but rupees). Needs Chests." },
        new object[] { "rando_quests", "Quest rewards", new[] { "Off", "On" }, new[] { 0, 1 },
            "What some characters give takes part with the chests: Darunia, mini-games, side quests and the Gold Skulltula family. Needs Chests." },
        new object[] { "rando_songs", "Songs", new[] { "Off", "Song spots", "Anywhere" }, new[] { 0, 1, 2 },
            "Song spots: the songs are shuffled among the places that teach one. Anywhere: a song can be any item's place." },
        new object[] { "rando_heart_pieces", "Heart Pieces", new[] { "Off", "On" }, new[] { 0, 1 },
            "Heart Pieces and the other items lying in the world are shuffled." },
        new object[] { "rando_shops", "Shops", new[] { "Off", "Low prices", "Any price" }, new[] { 0, 1, 2 },
            "Four shelves of each shop sell a shuffled item, once each, at a rolled price of 1 to 1000 rupees. The wallets are shuffled too: a price asks for one that holds it. Needs Chests." },
        new object[] { "rando_scrubs", "Deku Scrubs", new[] { "Off", "On" }, new[] { 0, 1 },
            "The Business Scrubs' one-time sales (two Pieces of Heart, the Deku Stick and Deku Nut upgrades) take part with the chests. Needs Chests." },
        new object[] { "rando_dungeon_rewards", "Dungeon rewards", new[] { "Off", "Dungeons", "Anywhere" }, new[] { 0, 1, 2 },
            "The Spiritual Stones and Medallions. Dungeons: shuffled among the dungeons' ends. Anywhere: any item's place." },
        new object[] { "rando_keys", "Dungeon keys", new[] { "Off", "Own dungeon", "Anywhere" }, new[] { 0, 1, 2 },
            "Small keys and Boss Keys. Own dungeon: shuffled inside their dungeon. Anywhere: they can be in any place of the game." },
        new object[] { "rando_major", "Major items", new[] { "Off", "On" }, new[] { 0, 1 },
            "The big items in chests (Kokiri Sword, Bow, Megaton Hammer and the like) are shuffled too, placed so the game can be finished. Needs Chests." },
        new object[] { "rando_open_deku", "Open Deku Tree", new[] { "Off", "On" }, new[] { 0, 1 },
            "A new game's way to the Great Deku Tree is open from the start: Mido lets Link by without a sword and a shield." },
        new object[] { "rando_open_forest", "Open forest exit", new[] { "Off", "On" }, new[] { 0, 1 },
            "A new game's way out of Kokiri Forest is open from the start: Link can leave before the Deku Tree is done." },
        new object[] { "rando_skip_intro", "Skip opening", new[] { "Off", "On" }, new[] { 0, 1 },
            "A new game starts in Link's house, without the narration and Navi's flight." },
        new object[] { "rando_frogs", "Frogs", new[] { "Off", "On" }, new[] { 0, 1 },
            "With Quest rewards: the frogs of Zora's River take part too." },
        new object[] { "rando_light_arrows", "Light Arrows", new[] { "Off", "On" }, new[] { 0, 1 },
            "With Quest rewards: the Light Arrows Zelda gives take part too, and can be anywhere." },
        new object[] { "rando_start_rupees", "Starting rupees", new[] { "Off", "200" }, new[] { 0, 1 },
            "A new game starts with 200 rupees in Link's wallet." },
        new object[] { "rando_progressive", "Progressive items", new[] { "Off", "On" }, new[] { 0, 1 },
            "An upgrade found gives the next one Link has not: bomb bags, the bow and quivers, the slingshot and bullet bags, Hookshot and Longshot, strength, scales, wallets, stick and nut bags, magic. A chest still shows the item it was shuffled as." },
    };
    // (cosmetics: the colours of the tunics, the hearts and the magic meter, kept in hookshot_cosmetics.ini beside the options (the game's menu writes the options file
    // whole and would drop lines it does not know). tools/rando/rando_cosmetics.py reads them at Play: the same keys, and
    // the colours of its COLOURS in the same order (tests/test_rando_cosmetics.py))
    static readonly string[] TunicColours = { "The game's", "Green", "Red", "Blue", "Purple", "Pink", "Orange", "Yellow", "Teal", "White", "Black" };
    static readonly int[] TunicValues = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 };
    static readonly object[][] CosmeticRows = {
        new object[] { "cosmetic_tunic_kokiri", "Kokiri Tunic", TunicColours, TunicValues,
            "The colour of the green tunic's cloth, vest and hat, as an adult and as a child. Mido's clothes are the same cloth and change with it." },
        new object[] { "cosmetic_tunic_goron", "Goron Tunic", TunicColours, TunicValues,
            "The colour of the red tunic's cloth and hat. Its gold trim and leather keep their own." },
        new object[] { "cosmetic_tunic_zora", "Zora Tunic", TunicColours, TunicValues,
            "The colour of the blue tunic's cloth and hat. Its trim and leather keep their own." },
        new object[] { "cosmetic_hearts", "Hearts", TunicColours, TunicValues,
            "The colour of the hearts in the corner of the screen." },
        new object[] { "cosmetic_magic", "Magic meter", TunicColours, TunicValues,
            "The colour of the magic meter under the hearts." },
    };
    // (Mako) the Master Quest page (host/master_quest.c): started by its own Play button (HOS_MASTER_QUEST=1), its saves apart
    // (user\save_mq), its title logo made at build time from the player's files (prompts/mq, nx2/mq_logo.py)
    static readonly object[][] MqRows = {
        new object[] { "master_quest_damage", "Damage Link takes", new[] { "x2 (3DS)", "x3", "x4" }, new[] { 2, 3, 4 },
            "How much harder enemies, falls and hazards hit in Master Quest. The 3DS Master Quest uses x2." },
    };
    static readonly string[] PresetKeys = { "resolution", "upscaling", "sharpness", "frame_pacing", "game_speed", "handheld_profile" };   // (as the game's presets: frame generation is the player's)
    static readonly string[][] Languages = {
        new[] { "en-US", "English (US)" }, new[] { "en-GB", "English (UK)" }, new[] { "fr", "Français (France)" }, new[] { "fr-CA", "Français (Canada)" },
        new[] { "de", "Deutsch" }, new[] { "it", "Italiano" }, new[] { "es", "Español (España)" }, new[] { "es-419", "Español (Latinoamérica)" },
        new[] { "pt-BR", "Português (Brasil)" }, new[] { "nl", "Nederlands" }, new[] { "pl", "Polski" }, new[] { "ru", "Русский" },
        new[] { "ja", "日本語" }, new[] { "ko", "한국어" }, new[] { "zh-Hans", "简体中文" }, new[] { "zh-Hant", "繁體中文" },
    };
    // (env name, value when on, label, help, value when off; "" = no line, the game's default)
    const int FixPitch = 92;   // (five switches; 80 holds six over the bottom row of buttons)
    static readonly string[][] Fixes = {
        // (the switch wrote no line when on and -1 when off, and the renderer takes both as 0, no wait (vk_replay.cpp: RX_VK_WAIT_GPU=<frames>):
        // it did nothing either way. It writes 1 now. Seen without a player, the Market walked into from Hyrule Field: 15 to 20 frames
        // washed with glare in 20 s without the wait, none with it, for about 5 fps)
        new[] { "RX_VK_WAIT_GPU", "1", "No light flashes", "Each frame waits for the graphics card to finish the previous one. Stops the one-frame flashes of glare (the Market, Hyrule Field). Costs a few fps. Recommended.", "0" },
        new[] { "HOOKSHOT_OCCLUSION_OFF", "1", "Occlusion tests off", "The game no longer guesses what is hidden: everything is drawn. Steadier sun glare on AMD cards, a little slower.", "" },
        // (Mako) Ducky's controller workaround: HOS_NO_SDL=1 leaves SDL out (host/pad_sdl.c), pads only through XInput
        new[] { "HOS_NO_SDL", "1", "Basic controller mode (tip by Ducky)", "Controller not detected, double inputs or wrong buttons? Reads only Xbox-style (XInput) pads: a PlayStation pad then needs Steam or DS4Windows. No motion aiming.", "" },
        // (Mako) the predicted pipelines behind the game (gpu/vk/vk_draw.cpp predict_background); off: all before the title
        new[] { "RX_VK_PREDICT_BG", "1", "Quick first start", "Off (recommended): effects are prepared the first time they appear, as in Mako 3.3 (short hitches the first time only). On: they are also prepared behind the game while you play, which costs some fps for a while.", "" },
        // (Mako) AMD FSR Redstone frame generation (gpu/vk/vk_redstone.h), off unless switched on: it takes video memory
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
        cosmeticsPath = Path.Combine(dir, "hookshot_cosmetics.ini");
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
        playButton = new Btn { Text = "PLAY", Style = Btn.Kind.Play, R = new RectangleF(32, 504, 336, 62), Click = OnPlay };
        widgets.Add(playButton);
        // (Mako) Master Quest's own Play, under it: its logo on the button (prompts/mq/logo.png, made by the build from the player's files)
        try {
            string mqPath = Path.Combine(dir, "prompts", "mq", "logo.png");
            if (File.Exists(mqPath)) mqLogo = Image.FromStream(new MemoryStream(File.ReadAllBytes(mqPath)));
        } catch { }
        widgets.Add(new Btn { Text = "MASTER QUEST", Style = Btn.Kind.Play, Gold = true, Logo = mqLogo, R = new RectangleF(32, 576, 336, 64), Click = () => OnPlay(true) });
        widgets.Add(new Btn { Text = "Made by sharkiix  ·  based on Hookshot", Style = Btn.Kind.Link, R = new RectangleF(32, 648, 300, 24),
                              Click = () => OpenUrl(Fork.Home) });

        // (tabs)
        string[] names = { "Recommended", "Graphics", "Game", "Randomizer", "Cosmetics", "Fixes", "FSR", "About", "Master Quest" };
        float tx = LeftW + 36;
        using (var g = CreateGraphics()) {
            // (nine tabs with the randomizer's two and Master Quest: the room around each name is made smaller until they fit the page's width)
            float room = W - LeftW - 72, text = 0, pad = 26, gap = 6;
            foreach (string name in names) text += g.MeasureString(name, Theme.Tab).Width;
            if (text + names.Length * pad + (names.Length - 1) * gap > room) {
                gap = 2;
                pad = Math.Max(2, (room - text - (names.Length - 1) * gap) / names.Length);
            }
            for (int i = 0; i < names.Length; i++) {
                float w = g.MeasureString(names[i], Theme.Tab).Width + pad;
                var t = new TabW { Text = names[i], Index = i, R = new RectangleF(tx, 50, w, 40) };
                tabs.Add(t); widgets.Add(t);
                tx += w + gap;
            }
        }

        float cx = LeftW + 36, cw = W - LeftW - 72, colW = (cw - 14) / 2;
        AddSelectors(GraphicsRows, 1, cx, colW);
        AddSelectors(GameRows, 2, cx, colW);
        AddSelectors(RandoRows, 3, cx, colW, null, 47, 45);   // (seventeen of them: closer lines, nine in all, over the seed's buttons)
        AddSelectors(CosmeticRows, 4, cx, colW, cosmetics);
        // (beside the fifth selector, in the third line's right half)
        widgets.Add(new Btn { Text = "Randomize all", R = new RectangleF(cx + colW + 14, 112 + 2 * 70 + 11, 160, 40), Page = 4, Click = OnRandomCosmetics });
        // (under the selectors: the seed's three buttons, and its ID beside them)
        widgets.Add(new Btn { Text = "New seed", R = new RectangleF(cx, 542, 116, 36), Page = 3, Click = OnNewSeed });
        widgets.Add(new Btn { Text = "Copy seed ID", R = new RectangleF(cx + 126, 542, 136, 36), Page = 3, Click = OnCopySeedId });
        widgets.Add(new Btn { Text = "Paste seed ID", R = new RectangleF(cx + 272, 542, 136, 36), Page = 3, Click = OnPasteSeedId });
        var langItems = new string[Languages.Length]; var langValues = new int[Languages.Length];
        for (int i = 0; i < Languages.Length; i++) { langItems[i] = Languages[i][1]; langValues[i] = i; }
        langSel = new Selector { Key = "language", Label = "Language", Items = langItems, Values = langValues, Page = 2, Index = 0,
                                 HelpText = "The game's language: text and voices.",
                                 R = new RectangleF(cx + GameRows.Length % 2 * (colW + 14), 112 + GameRows.Length / 2 * 70, colW, 62) };   // (after the Game rows)
        langSel.Changed = s => { if (!loading) SaveLanguage(); };
        widgets.Add(langSel);
        for (int i = 0; i < Fixes.Length; i++) {
            var tg = new Toggle { Key = Fixes[i][0], Label = Fixes[i][2], HelpText = Fixes[i][3], Page = 5, R = new RectangleF(cx, 112 + i * FixPitch, cw, FixPitch - 4) };
            tg.Changed = t => { if (!loading) SaveEnv(); };
            fixes[tg.Key] = tg; widgets.Add(tg);
        }
        // (Mako) the FSR tab: AMD's files, fetched from AMD's own GitHub with one button (Fsr below)
        fsrButton = new Btn { Text = "Download AMD FSR", Style = Btn.Kind.Primary, R = new RectangleF(cx, 470, 260, 44), Page = 6, Click = OnFsrDownload };
        widgets.Add(fsrButton);
        widgets.Add(new Btn { Text = "AMD FSR SDK on GitHub", R = new RectangleF(cx + 272, 470, 220, 44), Page = 6, Click = () => OpenUrl(Fsr.Page) });
        widgets.Add(new Btn { Text = "Project page on GitHub", R = new RectangleF(cx, 470, 220, 40), Page = 7, Click = () => OpenUrl(Fork.Home) });
        widgets.Add(new Btn { Text = "Licence (GPL-3)", R = new RectangleF(cx + 232, 470, 170, 40), Page = 7, Click = () => OpenUrl(Fork.Home + "/blob/HEAD/LICENSE") });

        // (Mako) the Master Quest page: its logo (PaintMasterQuest), its Play button, the damage, its saves
        widgets.Add(new Btn { Text = "PLAY MASTER QUEST", Style = Btn.Kind.Play, Gold = true, R = new RectangleF(cx + (cw - 420) / 2, 452, 420, 70),
                              Page = 8, Click = () => OnPlay(true) });
        AddSelectors(MqRows, 99, cx, colW);   // (the damage kept and saved as a setting; shown as the three cards below)
        string[][] trials = { new[] { "x2", "As on 3DS" }, new[] { "x3", "Hard" }, new[] { "x4", "Very hard" } };
        float cardW = (cw - 24) / 3;
        for (int i = 0; i < trials.Length; i++) {
            int at = i;
            widgets.Add(new GoldChoice { Title = trials[i][0], Sub = trials[i][1], Page = 8, R = new RectangleF(cx + i * (cardW + 12), 544, cardW, 58),
                                         IsOn = () => settings["master_quest_damage"].Index == at,
                                         Click = () => settings["master_quest_damage"].Set(at, true) });
        }
        widgets.Add(new Btn { Text = "Open the Master Quest saves", Style = Btn.Kind.Link, R = new RectangleF(cx + cw - 230, 622, 230, 26), Page = 8,
                              Click = () => { Directory.CreateDirectory(Path.Combine(dir, "user", "save_mq")); OpenFolder(Path.Combine(dir, "user", "save_mq")); } });

        // (bottom row: folders)
        widgets.Add(new Btn { Text = "Saves", R = new RectangleF(cx, 612, 104, 42), HideOn = 8, Click = () => OpenFolder(Path.Combine(dir, "user", SaveFolder())) });
        widgets.Add(new Btn { Text = "Import saves", R = new RectangleF(cx + 112, 612, 128, 42), HideOn = 8, Click = OnImport });
        widgets.Add(new Btn { Text = "Game folder", R = new RectangleF(cx + 248, 612, 124, 42), HideOn = 8, Click = () => OpenFolder(dir) });
        // (kept copies of the saves, of the folder the Randomizer setting names: more than the game's one save of the player's own)
        widgets.Add(new Btn { Text = "Save copies", R = new RectangleF(cx + 380, 612, 122, 42), HideOn = 8,
                              Click = () => { using (var f = new SaveCopiesForm(dir, SaveFolder())) f.ShowDialog(this); } });

        // (Mako) the Recommended tab: this PC read once, and its Apply button
        BuildRecommendations();
        widgets.Add(new Btn { Text = "Apply these", Style = Btn.Kind.Primary, R = new RectangleF(cx + 510, 612, cw - 510, 42), Page = 0, Click = OnApplyRecommended });

        LoadAll();
        int first;
        string[] cmd = Environment.GetCommandLineArgs();
        ShowPage(cmd.Length > 2 && int.TryParse(cmd[2], out first) && first >= 0 && first < tabs.Count ? first : 0);
        tabX = tabs[PageNow].R.X; tabW = tabs[PageNow].R.Width;
        float scroll0;   // (a third argument: the Recommended tab scrolled, for screenshots)
        if (cmd.Length > 3 && float.TryParse(cmd[3], out scroll0)) recScroll = scroll0;

        timer = new System.Windows.Forms.Timer { Interval = 16 };
        timer.Tick += (s, e) => Step();
        timer.Start();
        CheckUpdate();
    }

    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e);
        try { int round = 2; DwmSetWindowAttribute(Handle, 33, ref round, 4); } catch { }   // (Windows 11: rounded corners)
    }

    void AddSelectors(object[][] rows, int page, float x0, float colW, Dictionary<string, Selector> into = null, int pitch = 70, int height = 62) {
        for (int i = 0; i < rows.Length; i++) {
            var row = rows[i];
            int col = i % 2, line = i / 2;
            var s = new Selector { Key = (string)row[0], Label = (string)row[1], Items = (string[])row[2], Values = (int[])row[3], HelpText = (string)row[4],
                                   Page = page, R = new RectangleF(x0 + col * (colW + 14), 112 + line * pitch, colW, height) };
            if (into == null) { s.Changed = OnSetting; settings[s.Key] = s; }
            else { s.Changed = OnCosmetic; into[s.Key] = s; }
            widgets.Add(s);
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
            bool visible = (w.Page < 0 && w.HideOn != PageNow) || w.Page == PageNow;
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
        if (PageNow == 8) PaintMqScene(g);
        using (var b = new LinearGradientBrush(new RectangleF(tabX, 88, Math.Max(1, tabW), 3), PageNow == 8 ? Color.FromArgb(196, 150, 70) : Theme.Blue,
                                               PageNow == 8 ? Color.FromArgb(232, 196, 128) : Theme.Cyan, 0f))
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
        foreach (var w in widgets) if (w.Page < 0 && w.HideOn != PageNow) w.Paint(g, this);
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
        if (PageNow == 0) PaintRecommended(g, x);
        if (PageNow == 2)
            Theme.Text_(g, "Controls are set in game: press Insert or F1 for the menu.", Theme.Small, Theme.Faint, new RectangleF(x, 112 + (GameRows.Length + 2) / 2 * 70 + 6, 500, 20),
                        StringAlignment.Near, StringAlignment.Near);
        if (PageNow == 3) {   // (the randomizer: the seed beside its button, and what the page does not do yet)
            string seed = randoSeed != 0 ? SeedId() : "No seed yet";
            Theme.Text_(g, seed, Theme.Small, Theme.Dim, new RectangleF(x + 420, 542, W - LeftW - 72 - 420, 36), StringAlignment.Near, StringAlignment.Center);
            Theme.Text_(g, "Placed when Play is pressed. The seed's ID holds the seed and every setting above: the same ID is the same seed.",
                        Theme.Small, Theme.Faint, new RectangleF(x, 584, W - LeftW - 72, 18), StringAlignment.Near, StringAlignment.Near);
        }
        if (PageNow == 4)
            Theme.Text_(g, "Written when Play is pressed: about half a minute after a colour is changed, nothing after that. " +
                        "The equipment menu's pictures of the tunics keep the game's colours.",
                        Theme.Small, Theme.Faint, new RectangleF(x, 112 + 3 * 70 + 6, W - LeftW - 72, 40), StringAlignment.Near, StringAlignment.Near);
        if (PageNow == 5)
            Theme.Text_(g, "Read by the game when it starts.", Theme.Small, Theme.Faint, new RectangleF(x, 112 + Fixes.Length * FixPitch, 500, 20),
                        StringAlignment.Near, StringAlignment.Near);
        if (PageNow == 6) PaintFsr(g, x);
        if (PageNow == 8) PaintMasterQuest(g, x);
        if (PageNow == 7) {
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

    // (Mako) the Master Quest page's backdrop: dark, a little warm light behind the logo. Still, drawn once
    Bitmap mqBack;
    void PaintMqScene(Graphics g) {
        var area = new RectangleF(LeftW + 1, 96, W - LeftW - 1, H - 96);
        if (mqBack == null) {
            mqBack = new Bitmap((int)area.Width, (int)area.Height);
            using (var bg = Graphics.FromImage(mqBack)) {
                bg.SmoothingMode = SmoothingMode.AntiAlias;
                var r = new RectangleF(0, 0, area.Width, area.Height);
                using (var br = new LinearGradientBrush(r, Theme.Bg1, Color.FromArgb(14, 12, 12), LinearGradientMode.Vertical)) bg.FillRectangle(br, r);
                using (var path = new GraphicsPath()) {
                    path.AddEllipse(r.Width / 2 - 260, 0, 520, 340);
                    using (var pb = new PathGradientBrush(path) { CenterColor = Color.FromArgb(26, 255, 200, 120), SurroundColors = new[] { Color.FromArgb(0, 255, 200, 120) } })
                        bg.FillPath(pb, path);
                }
            }
        }
        g.DrawImageUnscaled(mqBack, (int)area.X, (int)area.Y);
    }

    // (Mako) the Master Quest page: the logo the build made from the player's files, the line under it
    void PaintMasterQuest(Graphics g, float x) {
        float cw = W - LeftW - 72, mid = x + cw / 2;
        var lr = new RectangleF(mid - 208, 100, 416, 320);
        if (mqLogo != null) {   // (its own proportions, centred in that space)
            float lw = Math.Min(416f, 300f * mqLogo.Width / mqLogo.Height), lh = lw * mqLogo.Height / mqLogo.Width;
            lr = new RectangleF(mid - lw / 2, 100 + (310 - lh) / 2, lw, lh);
        }
        if (mqLogo != null) {
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.DrawImage(mqLogo, lr);
        } else {
            using (var b = new SolidBrush(Color.FromArgb(232, 196, 128)))
                Theme.Spaced(g, "MASTER QUEST", Theme.Pick(30f, FontStyle.Bold, "Constantia", "Georgia"), b, mid, lr.Y + 120, 4);
            Theme.Text_(g, "The logo appears once the game is built with this version.", Theme.Small, Theme.Faint,
                        new RectangleF(x, lr.Y + 176, cw, 20), StringAlignment.Center, StringAlignment.Center);
        }
        Theme.Text_(g, "Enemies hit harder. Master Quest keeps its own saves, apart from the normal game's.", Theme.Small, Theme.Dim,
                    new RectangleF(x, 426, cw, 20), StringAlignment.Center, StringAlignment.Center);
        Theme.Text_(g, "DIFFICULTY", Theme.Caps, Theme.Faint, new RectangleF(x, 526, 300, 16), StringAlignment.Near, StringAlignment.Center);
        Theme.Text_(g, "Applies at the next start.", Theme.Small, Theme.Faint, new RectangleF(x, 622, 300, 26), StringAlignment.Near, StringAlignment.Center);
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
            if (((w.Page < 0 && w.HideOn != PageNow) || w.Page == PageNow) && w.Hit(p)) return w;
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
    Dictionary<string, int> ReadOptions() { return ReadNumbers(optionsPath); }

    // (a file of key=number lines)
    static Dictionary<string, int> ReadNumbers(string path) {
        var d = new Dictionary<string, int>();
        if (!File.Exists(path)) return d;
        foreach (var raw in File.ReadAllLines(path)) {
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
        if (key == "frame_generation" && value == 2 && IsRedstone()) return;   // (2x stays AMD's when it was)
        int best = 0;
        for (int i = 0; i < s.Values.Length; i++) if (Math.Abs(s.Values[i] - value) < Math.Abs(s.Values[best] - value)) best = i;
        if (s.Index < 0) s.Index = best; else s.Set(best, false);
    }

    bool IsRedstone() { Selector s; return settings.TryGetValue("frame_generation", out s) && s.Index == s.Items.Length - 1; }

    void LoadAll() {
        loading = true;
        var o = ReadOptions();
        // (the game's own defaults where the file has nothing yet: options.ini is written by the game's Insert menu)
        var defaults = new Dictionary<string, int> { { "quality_preset", 0 }, { "output_res", 0 }, { "resolution", 0 }, { "upscaling", 2 }, { "sharpness", 30 },
            { "frame_generation", 0 }, { "frame_pacing", 1 }, { "vsync", 0 }, { "fullscreen", 1 }, { "ultrawide", 0 }, { "handheld_profile", 0 },
            { "fps_counter", 0 }, { "dlss", 0 }, { "frame_rate_cap", 0 }, { "amd_anti-lag_2", 0 }, { "game_speed", 1 }, { "text_speed", 0 }, { "fast_forward", 0 }, { "controller_in_background", 0 },
            { "master_quest_damage", 2 } };
        foreach (var row in RandoRows) defaults[(string)row[0]] = 0;   // (the randomizer: off, every setting the game's own)
        foreach (var kv in defaults) SetSetting(kv.Key, o.ContainsKey(kv.Key) ? o[kv.Key] : kv.Value);
        randoSeed = o.ContainsKey("rando_seed") ? Math.Max(0, o["rando_seed"]) : 0;
        var c = ReadNumbers(cosmeticsPath);
        foreach (var kv in cosmetics) {   // (a colour this launcher does not have: the game's own)
            int v = c.ContainsKey(kv.Key) ? c[kv.Key] : 0;
            kv.Value.Index = Math.Max(0, Array.IndexOf(kv.Value.Values, v));
        }
        var env = ReadEnv();
        foreach (var f in Fixes) {
            string v;
            fixes[f[0]].On = env.TryGetValue(f[0], out v) ? v == f[1] : f[1].Length == 0;
            fixes[f[0]].Snap();
        }
        string rs;
        if (env.TryGetValue("RX_VK_REDSTONE", out rs) && rs == "1" && settings["frame_generation"].Value == 2)
            settings["frame_generation"].Index = settings["frame_generation"].Items.Length - 1;
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
        if (s.Key == "frame_generation") SaveEnv();
    }

    void OnCosmetic(Selector s) { if (!loading) SaveCosmetics(); }

    // (Randomize all: each of the page's selectors gets one of its colours, never the game's own, the first choice)
    void OnRandomCosmetics() {
        var r = new Random(Environment.TickCount ^ Guid.NewGuid().GetHashCode());
        loading = true;
        foreach (var s in cosmetics.Values) s.Set(r.Next(1, s.Items.Length), false);
        loading = false;
        SaveCosmetics();
    }

    // (the Cosmetics page's lines; the file's other lines are kept)
    void SaveCosmetics() {
        try {
            var lines = File.Exists(cosmeticsPath) ? new List<string>(File.ReadAllLines(cosmeticsPath)) : new List<string>();
            var done = new HashSet<string>();
            for (int i = 0; i < lines.Count; i++) {
                int eq = lines[i].IndexOf('=');
                if (eq <= 0) continue;
                string k = lines[i].Substring(0, eq).Trim();
                if (cosmetics.ContainsKey(k)) { lines[i] = k + "=" + cosmetics[k].Value; done.Add(k); }
            }
            foreach (var k in cosmetics.Keys)
                if (!done.Contains(k)) lines.Add(k + "=" + cosmetics[k].Value);
            File.WriteAllLines(cosmeticsPath, lines.ToArray(), new UTF8Encoding(false));
        } catch (Exception ex) {
            MessageBox.Show(this, "The cosmetic settings could not be saved:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    // (a seed's random part, 1 to 2^31 - 2: 0 is "none yet", as in the Insert menu)
    static int NewSeed() { return new Random(Environment.TickCount ^ Guid.NewGuid().GetHashCode()).Next(1, int.MaxValue); }

    // (the game keeps a seed's saves apart from its own: host/oot_rando.c hos_save_folder. The Saves button opens the ones
    // the next Play uses)
    string SaveFolder() { return settings.ContainsKey("rando_on") && settings["rando_on"].Value != 0 ? "save_rando" : "save"; }

    void OnNewSeed() {
        randoSeed = NewSeed();
        randoDropImport = true;
        SaveOptions();
    }

    // (the settings' choices in the table's order, without the on / off selector: what a seed ID holds)
    int[] RandoChoices() {
        var v = new int[RandoRows.Length - 1];
        for (int i = 1; i < RandoRows.Length; i++) v[i - 1] = settings[(string)RandoRows[i][0]].Value;
        return v;
    }
    string SeedId() { return RandoId.Make(randoSeed, RandoChoices()); }

    void OnCopySeedId() {
        if (randoSeed == 0) { randoSeed = NewSeed(); randoDropImport = true; SaveOptions(); }
        try { Clipboard.SetText(SeedId()); }
        catch (Exception ex) { MessageBox.Show(this, "The seed ID could not be copied:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    // (the clipboard's text as a seed ID: its seed and every setting, the randomizer on)
    void OnPasteSeedId() {
        string text = "";
        try { text = Clipboard.ContainsText() ? Clipboard.GetText() : ""; } catch { }
        int seed = 0; int[] v = null;
        var counts = new int[RandoRows.Length - 1];
        for (int i = 1; i < RandoRows.Length; i++) counts[i - 1] = ((string[])RandoRows[i][2]).Length;
        string bad = "no text in the clipboard";
        if (text.Trim().Length != 0) bad = RandoId.Read(text, counts, out seed, out v);
        if (bad != null) {
            MessageBox.Show(this, "That is not a seed ID: " + bad + ".", Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        loading = true;
        SetSetting("rando_on", 1);
        for (int i = 1; i < RandoRows.Length; i++) SetSetting((string)RandoRows[i][0], v[i - 1]);
        loading = false;
        randoSeed = seed;
        randoDropImport = true;
        SaveOptions();
    }

    // (the Insert menu's presets, gpu/vk/vk_menu.cpp apply_preset)
    void ApplyPreset(int p) {
        int[][] t = {
            null,
            new[] { 4, 2, 30, 1, 1, 1 },
            new[] { 2, 2, 30, 1, 1, 1 },
            new[] { 1, 1, 30, 1, 1, 0 },
            new[] { 1, 2, 40, 1, 1, 0 },
            new[] { 1, 2, 50, 1, 1, 0 },
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
            lines.RemoveAll(l => { var t = l.Trim(); return !t.StartsWith("#") && t.StartsWith("RX_VK_REDSTONE="); });
            if (IsRedstone()) lines.Add("RX_VK_REDSTONE=1");
            if (lines.Count == 0 && File.Exists(envPath)) File.Delete(envPath);
            else if (lines.Count > 0) File.WriteAllLines(envPath, lines.ToArray(), new UTF8Encoding(false));
        } catch (Exception ex) {
            MessageBox.Show(this, "The fix switches could not be saved:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
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
                        // (Mako 3.3: the new names first; the old ones are what releases up to 3.0.2 have)
                        if (u.EndsWith("/mako_vk_update.txt") || (manifest == null && u.EndsWith("/hookshot_vk_update.txt"))) manifest = u;
                        if (u.EndsWith("/mako_vk.dll") || (dll == null && u.EndsWith("/hookshot_vk.dll"))) dll = u;
                        if (u.EndsWith("/MakoBuilder.zip") || (zip == null && u.EndsWith("/HookshotBuilder.zip"))) zip = u;
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
    public static bool GameRunning() { return Process.GetProcessesByName(Path.GetFileNameWithoutExtension(Fork.GameExe)).Length > 0; }

    void OpenFolder(string path) {
        try {
            Directory.CreateDirectory(path);
            Process.Start("explorer.exe", "\"" + path + "\"");
        } catch (Exception ex) { MessageBox.Show(this, ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    void OpenUrl(string url) { try { Process.Start(url); } catch { } }

    // ---- (Mako) the FSR tab ------------------------------------------------------------------------------------------------
    // AMD's FSR files (loader, FSR 4 upscaler, FSR frame generation) are AMD's: Mako never ships them. The button fetches the
    // signed ones from AMD's own repository (Fsr.Base), checks each is signed by AMD (Authenticode, Fsr.SignedByAmd) and puts
    // them beside the game, where the game looks for them (gpu/vk/vk_fsr4.cpp).

    // ---- (Mako) the Recommended tab ----
    PcInfo pc;
    Bitmap recPage; float recScroll, recHeight;
    List<RecRow> recGraphics, recFixes;
    List<string[]> recNotes;   // (heading, text)
    string recVerdict = "";

    string ItemOf(string key, int value) {
        foreach (var row in GraphicsRows)
            if ((string)row[0] == key) {
                var items = (string[])row[2]; var values = (int[])row[3];
                for (int i = 0; i < values.Length; i++) if (values[i] == value) return items[i];
            }
        foreach (var row in GameRows)
            if ((string)row[0] == key) {
                var items = (string[])row[2]; var values = (int[])row[3];
                for (int i = 0; i < values.Length; i++) if (values[i] == value) return items[i];
            }
        return value.ToString();
    }
    RecRow Opt(string what, string key, int value, string why) {
        var r = new RecRow(what, ItemOf(key, value), why) { Key = key, Set = value };
        recGraphics.Add(r);
        return r;
    }

    void BuildRecommendations() {
        pc = PcInfo.Read();
        recGraphics = new List<RecRow>(); recFixes = new List<RecRow>(); recNotes = new List<string[]>();
        int v = pc.VramGB, h = pc.ScreenH, hz = pc.Hz;
        bool knownVram = pc.VramMB > 0;
        bool low = pc.Integrated || (knownVram && v < 5);
        string card = pc.Gpu.Length > 0 ? pc.Gpu : "your graphics card";

        // (the verdict)
        if (pc.Integrated) recVerdict = "A graphics chip built into the processor: Mako runs, at the lightest settings. Expect around 30 fps.";
        else if (!knownVram) recVerdict = "The graphics card's memory could not be read: these are middle settings. Lower the Quality preset if it stutters.";
        else if (v >= 14) recVerdict = "A strong PC for Mako: high settings, with room for AMD FSR 4 and frame generation.";
        else if (v >= 10) recVerdict = "A good PC for Mako: high settings at your screen's resolution.";
        else if (v >= 7) recVerdict = "A solid PC for Mako: balanced settings. 8 GB of video memory is the limit to watch.";
        else recVerdict = "A light PC for Mako: low settings keep it smooth. Video memory is the limit here.";

        // (Quality preset: from the video memory, as its own names say)
        int preset = low ? 1 : !knownVram ? 3 : v < 7 ? 2 : v < 10 ? 3 : v < 14 ? 4 : 5;
        Opt("Quality preset", "quality_preset", preset,
            knownVram ? "Your card has " + v + " GB of video memory. The preset fits the game's textures and effects to it; one step lower if the game stutters after a while."
                      : "Set from a middle guess. One step lower if the game stutters after a while.");

        // (Output resolution: the screen's, no higher than the memory allows)
        int cap = low ? 720 : !knownVram ? 1080 : v < 7 ? 1080 : v < 14 ? 1440 : 2160;
        int target = Math.Min(h > 0 ? h : 1080, cap);
        int[][] outs = { new[] { 2160, 2 }, new[] { 1440, 1 }, new[] { 1152, 0 }, new[] { 1080, 3 }, new[] { 900, 5 }, new[] { 720, 6 } };
        int outVal = 6;
        foreach (var o in outs) if (o[0] <= target) { outVal = o[1]; break; }
        Opt("Output resolution", "output_res", outVal,
            "Your screen is " + pc.ScreenW + " x " + pc.ScreenH + "." + (target < h ? " Higher would ask more video memory than your card has: the picture is fitted to your screen." : " The game draws at your screen's own size: the sharpest picture."));

        // (Upscaler)
        int up; string upWhy;
        if (pc.Tier == 2) { up = 4; upWhy = "Radeon RX 9000: AMD FSR 4 is the sharpest. It needs AMD's files: one click in the FSR tab. Native AA is sharper still but much heavier: only with 16 GB and power to spare."; }
        else if (pc.Tier == 1) { up = 3; upWhy = "Radeon RX 6000 / 7000: AMD FSR 3.1 is light and clean. FSR 4 also works on this card (FSR tab), sharper but heavier: try it if you have fps to spare."; }
        else if (low) { up = 0; upWhy = "The game's own upscaler is the lightest: best for a graphics chip in the processor."; }
        else { up = 3; upWhy = "AMD FSR 3.1 works on every graphics card and is sharper than the game's own when the 3D is drawn smaller."; }
        Opt("Upscaler", "dlss", up, upWhy);

        Opt("3D resolution", "resolution", low ? 4 : 0,
            low ? "Half the output resolution: what keeps a built-in graphics chip near 30 fps." : "Auto lowers the 3D's sharpness only when the graphics card is busy, so the frame rate stays steady.");
        Opt("Screen filter", "upscaling", low ? 1 : 2, low ? "Catmull-Rom: sharp and light." : "Lanczos: the sharpest fit to your screen.");
        Opt("Sharpness", "sharpness", up == 4 ? 20 : 30, up == 4 ? "FSR 4 is sharp already: a little more is enough." : "A little sharpening; above 50% shows halos around edges.");

        // (Frame generation and the frame rate: the screen's refresh decides)
        bool fg = hz >= 100 && !low && (!knownVram || v >= 8);
        Opt("Frame generation", "frame_generation", fg ? 2 : 0,
            fg ? "Your screen shows " + hz + " Hz: 2x fills it with smoother motion. Made frames do not make the game react faster. 3x and more show more mistakes in the picture: not recommended."
               : hz < 100 ? "Your screen shows " + hz + " Hz: made frames would not be shown, so they only cost. Off."
                          : "Off: made frames need video memory and power this PC is better using for the game itself.");
        int[][] caps = { new[] { 240, 5 }, new[] { 165, 4 }, new[] { 144, 3 }, new[] { 120, 2 }, new[] { 90, 1 }, new[] { 0, 0 } };
        int capVal = 0;
        foreach (var c in caps) if (c[0] <= hz) { capVal = c[1]; break; }
        Opt("Frame rate cap", "frame_rate_cap", capVal, "Your screen's refresh (" + hz + " Hz): frames above it are never shown.");
        Opt("Frame pacing", "frame_pacing", 1, "Spaces the frames evenly: steadier motion on every PC.");
        Opt("VSync", "vsync", hz <= 75 ? 1 : 0,
            hz <= 75 ? "On a 60 Hz screen VSync stops the picture tearing." : "Off with frame pacing on: less delay. Turn it on if you see the picture tear (screens without FreeSync / G-Sync).");
        Opt("AMD Anti-Lag 2", "amd_anti-lag_2", pc.Amd && !pc.Integrated ? 1 : 0,
            pc.Amd && !pc.Integrated ? "Less delay between your button and the screen on AMD cards (no effect while frame generation is on)." : "AMD graphics cards only.");
        Opt("Display", "fullscreen", 1, "Fullscreen: the smoothest frame timing. Alt+Enter switches in game.");
        bool wide = pc.ScreenH > 0 && pc.ScreenW / (double)pc.ScreenH > 1.9;
        Opt("Screen shape", "ultrawide", wide ? 1 : 0, wide ? "Your screen is wider than 16:9: the camera widens to fill it." : "Your screen is 16:9 (or close): the game's own shape.");
        Opt("Handheld profile", "handheld_profile", low ? 1 : 0, low ? "The console's undocked mode: lighter on a built-in graphics chip." : "Off: the docked console's sharper picture.");
        Opt("Game speed", "game_speed", 1, "Real time keeps the game at its normal speed even when the frame rate drops.");

        // (the Fixes tab and the FSR tab: advice, the Apply button leaves them)
        recFixes.Add(new RecRow("No blue light flashes", "On", "Stops the one-frame blue light flashes in Hyrule Field. Costs a few fps, worth it."));
        recFixes.Add(new RecRow("Occlusion tests off", pc.Amd ? "On" : "Off", pc.Amd ? "Steadier sun glare on AMD cards, at a small cost." : "Only needed on AMD cards."));
        recFixes.Add(new RecRow("Basic controller mode", "Off", "Only if your controller is not detected, presses twice or has wrong buttons."));
        recFixes.Add(new RecRow("Quick first start", "Off", "Off, the game prepares every effect once after each update" + (pc.Threads < 8 ? " (longer on your " + pc.Threads + "-thread processor)" : "") +
                                ", then plays smoothly. On reaches the title sooner, but the preparation then runs during play for hours, with stutters and objects appearing late."));
        bool redstone = pc.Tier == 2 && (!knownVram || v >= 12);
        recFixes.Add(new RecRow("Redstone frame gen.", redstone ? "On, with FSR 4 and 2x" : "Off",
                                pc.Tier == 2 ? (redstone ? "Your RX 9000 has the memory for it: AMD's frame generation, made by AI, gives cleaner motion and a steady HUD. Needs AMD's files (FSR tab), the Upscaler on AMD FSR 4 and Frame generation on 2x."
                                                         : "Your RX 9000 has " + v + " GB: Redstone takes video memory the game needs. Keep it off, or try it with the Quality preset one step lower.")
                                             : "Made for Radeon RX 9000 cards only.") { Good = redstone });
        recFixes.Add(new RecRow("AMD FSR files (FSR tab)", pc.Tier >= 1 ? "Download" : "Not needed",
                                pc.Tier >= 1 ? "One click, about 110 MB from AMD's own GitHub, checked as signed by AMD. Needed for FSR 4 and Redstone." : "FSR 4 needs a Radeon RX 6000 or newer; FSR 3.1 works without these files."));

        // (good to know: from this PC)
        if (pc.RamMB > 0 && pc.RamGB < 12) recNotes.Add(new[] { "Memory: " + pc.RamGB + " GB", "Below what the game likes (16 GB). Close the web browser and other large programs before playing; long sessions can freeze." });
        else if (pc.RamMB > 0 && pc.RamGB < 24) recNotes.Add(new[] { "Memory: " + pc.RamGB + " GB", "Enough. For long sessions, close large programs (web browser with many tabs, video editors) while you play." });
        else if (pc.RamMB > 0) recNotes.Add(new[] { "Memory: " + pc.RamGB + " GB", "Plenty: nothing to do." });
        if (pc.Threads > 0 && pc.Threads < 8) recNotes.Add(new[] { "Processor: " + pc.Threads + " threads", "The first start after each update takes longer here: let it finish once, the next starts are quick." });
        if (pc.Integrated) recNotes.Add(new[] { "Laptop or built-in graphics", "Keep it plugged in. If the PC also has a graphics card, in Windows Settings > System > Display > Graphics set hookshot.exe to High performance." });
        if (pc.Nvidia) recNotes.Add(new[] { "NVIDIA card", "Mako is tuned and tested on AMD cards first. NVIDIA works; tell us on GitHub if something looks wrong." });
        if (knownVram && v <= 8) recNotes.Add(new[] { "Video memory: " + v + " GB", "The limit to watch. If the game starts to stutter after a while, lower the Quality preset one step. Leave Native AA and Redstone off." });
        recNotes.Add(new[] { "After every update", "The first start prepares the game's effects (up to about 40 minutes on AMD cards, once). Let it finish: the following starts are quick." });
        recNotes.Add(new[] { "Graphics driver", "Keep it up to date: AMD Software: Adrenalin Edition, the NVIDIA App or Intel Graphics Software." });
        recNotes.Add(new[] { "In game", "Insert opens the menu: the same settings, applied at once. The launcher's tabs change the same file." });
        recNotes.Add(new[] { "Troubleshooting", "Blue flashes: No blue light flashes (Fixes). Controller problems: Basic controller mode. Stutters for hours after an update: Quick first start off. " +
                                                       "Shaking HUD with frame generation: Redstone on an RX 9000, or Frame generation off. Too slow: Quality preset one step lower." });
    }

    float LayoutRec(Graphics g, float w, bool draw) {
        float y = 0, pad = 18;
        Func<string, Font, float, float> hgt = (s, f, ww) => g.MeasureString(s, f, (int)ww).Height;
        // (title and verdict)
        if (draw) Theme.Text_(g, "Recommended for this PC", Theme.Pick(22f, FontStyle.Bold, "Bahnschrift", "Segoe UI"), Color.White, new RectangleF(0, y, w, 30), StringAlignment.Near, StringAlignment.Near);
        y += 34;
        float vh = hgt(recVerdict, Theme.Body, w);
        if (draw) g.DrawString(recVerdict, Theme.Body, new SolidBrush(Theme.Cyan), new RectangleF(0, y, w, vh + 2));
        y += vh + 10;
        // (the PC card)
        string[][] facts = {
            new[] { "Graphics card", (pc.Gpu.Length > 0 ? pc.Gpu : "not found") + (pc.VramMB > 0 ? "  ·  " + pc.VramGB + " GB of video memory" : "") },
            new[] { "Processor", (pc.Cpu.Length > 0 ? pc.Cpu : "unknown") + "  ·  " + pc.Threads + " threads" },
            new[] { "Memory", pc.RamMB > 0 ? pc.RamGB + " GB" : "unknown" },
            new[] { "Screen", pc.ScreenW + " x " + pc.ScreenH + " at " + pc.Hz + " Hz" },
        };
        float cardH = 16 + facts.Length * 24 + 8;
        if (draw) {
            var r = new RectangleF(0, y, w, cardH);
            using (var p = Theme.Round(r, 12)) { using (var b = new SolidBrush(Theme.Card)) g.FillPath(b, p); using (var pen = new Pen(Theme.Line)) g.DrawPath(pen, p); }
            float fy = y + 12;
            foreach (var f in facts) {
                Theme.Text_(g, f[0].ToUpperInvariant(), Theme.Label, Theme.Dim, new RectangleF(pad, fy + 2, 130, 20), StringAlignment.Near, StringAlignment.Near);
                Theme.Text_(g, f[1], Theme.Body, Theme.Text, new RectangleF(pad + 130, fy, w - pad * 2 - 130, 22), StringAlignment.Near, StringAlignment.Near);
                fy += 24;
            }
        }
        y += cardH + 18;
        // (the sections)
        y = RecSection(g, w, y, draw, "GRAPHICS  ·  the Apply button sets these", recGraphics);
        y = RecSection(g, w, y, draw, "FIXES AND FSR TABS  ·  set them yourself", recFixes);
        if (draw) Theme.Text_(g, "GOOD TO KNOW", Theme.Label, Theme.Cyan, new RectangleF(0, y, w, 18), StringAlignment.Near, StringAlignment.Near);
        y += 24;
        foreach (var n in recNotes) {
            float th = hgt(n[1], Theme.Small, w - 190);
            if (draw) {
                Theme.Text_(g, n[0], Theme.Strong, Theme.Text, new RectangleF(0, y, 180, 22), StringAlignment.Near, StringAlignment.Near);
                g.DrawString(n[1], Theme.Small, new SolidBrush(Theme.Dim), new RectangleF(190, y + 2, w - 190, th + 2));
            }
            y += Math.Max(24, th + 4) + 10;
        }
        return y + 10;
    }

    float RecSection(Graphics g, float w, float y, bool draw, string title, List<RecRow> rows) {
        if (draw) Theme.Text_(g, title, Theme.Label, Theme.Cyan, new RectangleF(0, y, w, 18), StringAlignment.Near, StringAlignment.Near);
        y += 24;
        foreach (var r in rows) {
            float th = g.MeasureString(r.Why, Theme.Small, (int)(w - 190)).Height;
            if (draw) {
                Theme.Text_(g, r.What, Theme.Small, Theme.Dim, new RectangleF(0, y + 3, 180, 20), StringAlignment.Near, StringAlignment.Near);
                Theme.Text_(g, r.Value, Theme.Strong, r.Good ? Color.White : Theme.Amber, new RectangleF(190, y, w - 190, 22), StringAlignment.Near, StringAlignment.Near);
                g.DrawString(r.Why, Theme.Small, new SolidBrush(Theme.Dim), new RectangleF(190, y + 23, w - 190, th + 2));
            }
            y += 23 + th + 10;
            if (draw) using (var pen = new Pen(Theme.A(Theme.Line, 140))) g.DrawLine(pen, 0, y - 5, w, y - 5);
        }
        return y + 12;
    }

    void PaintRecommended(Graphics g, float x) {
        float w = W - LeftW - 72;
        var area = new RectangleF(x, 104, w + 14, 496);
        if (recPage == null) {
            using (var probe = new Bitmap(1, 1)) using (var pg = Graphics.FromImage(probe)) {
                pg.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                recHeight = LayoutRec(pg, w - 12, false);
            }
            recPage = new Bitmap((int)w, (int)Math.Ceiling(recHeight) + 4);
            using (var pg = Graphics.FromImage(recPage)) {
                pg.SmoothingMode = SmoothingMode.AntiAlias; pg.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                LayoutRec(pg, w - 12, true);
            }
        }
        recScroll = Math.Max(0, Math.Min(recScroll, Math.Max(0, recHeight - area.Height + 8)));
        var state = g.Save();
        g.SetClip(area);
        g.DrawImageUnscaled(recPage, (int)x, (int)(area.Y + 8 - recScroll));
        g.Restore(state);
        // (scroll bar, and a fade at the bottom while there is more)
        if (recHeight > area.Height) {
            float track = area.Height - 16, bar = Math.Max(30, track * area.Height / recHeight);
            float by = area.Y + 8 + (track - bar) * recScroll / Math.Max(1, recHeight - area.Height + 8);
            using (var p = Theme.Round(new RectangleF(x + w + 6, by, 4, bar), 2)) using (var b = new SolidBrush(Theme.A(Theme.Cyan, 120))) g.FillPath(b, p);
            if (recScroll < recHeight - area.Height)
                using (var b = new LinearGradientBrush(new RectangleF(x, area.Bottom - 40, w, 41), Theme.A(Theme.Bg1, 0), Theme.A(Theme.Bg1, 230), LinearGradientMode.Vertical))
                    g.FillRectangle(b, x, area.Bottom - 40, w, 40);
            Theme.Text_(g, "Scroll for more", Theme.Small, Theme.Faint, new RectangleF(x, area.Bottom - 2, w, 16), StringAlignment.Center, StringAlignment.Near);
        }
    }

    protected override void OnMouseWheel(MouseEventArgs e) {
        base.OnMouseWheel(e);
        if (PageNow == 0) recScroll = Math.Max(0, Math.Min(recScroll - e.Delta * 0.6f, Math.Max(0, recHeight - 488)));
    }

    void OnApplyRecommended() {
        if (MessageBox.Show(this, "This sets the Graphics tab to the values shown here. Your current graphics settings are replaced.\n" +
                            "(The Fixes and FSR tabs are left as they are.)\n\nApply?", Fork.Name, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        loading = true;
        foreach (var r in recGraphics) if (r.Key != null) SetSetting(r.Key, r.Set);
        loading = false;
        SaveOptions();
        MessageBox.Show(this, "Done: the recommended settings are saved. You can still change any of them in the Graphics tab.", Fork.Name,
                        MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    void PaintFsr(Graphics g, float x) {
        var r = new RectangleF(x, 112, W - LeftW - 72, 340);
        using (var p = Theme.Round(r, 14)) {
            using (var b = new SolidBrush(Theme.Card)) g.FillPath(b, p);
            using (var pen = new Pen(Theme.Line)) g.DrawPath(pen, p);
        }
        Theme.Text_(g, "AMD FSR", Theme.Pick(22f, FontStyle.Bold, "Bahnschrift", "Segoe UI"), Color.White, new RectangleF(r.X + 24, r.Y + 16, 400, 30), StringAlignment.Near, StringAlignment.Near);
        string gpu = Fsr.Gpu();
        int tier = Fsr.Tier(gpu);
        string what = tier == 2 ? "FSR 4 upscaling and FSR Redstone frame generation (switch in the Fixes tab) are made for this card."
                    : tier == 1 ? "FSR 4 upscaling works on this card. FSR frame generation needs a Radeon RX 9000."
                    : "FSR 4 needs an AMD Radeon RX 6000 or newer. FSR 3.1 works on every card without these files.";
        Theme.Text_(g, "Graphics card: " + (gpu.Length > 0 ? gpu : "unknown"), Theme.Body, Theme.Cyan, new RectangleF(r.X + 24, r.Y + 52, r.Width - 48, 22), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, what, Theme.Body, Theme.Text, new RectangleF(r.X + 24, r.Y + 76, r.Width - 48, 22), StringAlignment.Near, StringAlignment.Near);
        float y = r.Y + 116;
        foreach (var f in Fsr.Files) {
            string path = Path.Combine(dir, f[0]);
            bool have = File.Exists(path);
            string ver = "";
            if (have) try { ver = FileVersionInfo.GetVersionInfo(path).FileVersion ?? ""; } catch { }
            using (var b = new SolidBrush(have ? Theme.Green : Theme.Amber)) g.FillEllipse(b, r.X + 26, y + 6, 9, 9);
            Theme.Text_(g, f[1] + (have ? "  ·  installed" + (ver.Length > 0 ? " (" + ver.Trim() + ")" : "") : "  ·  missing"), Theme.Body,
                        have ? Theme.Text : Theme.Dim, new RectangleF(r.X + 44, y, r.Width - 68, 22), StringAlignment.Near, StringAlignment.Near);
            y += 28;
        }
        Theme.Text_(g, "One click: the files are downloaded from AMD's official GitHub (about 110 MB), checked (signed by AMD) and put in " +
                    "the game folder. Then choose AMD FSR 4 as the Upscaler (Graphics tab, or in game with Insert).",
                    Theme.Small, Theme.Dim, new RectangleF(r.X + 24, y + 10, r.Width - 48, 40), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, fsrLine, Theme.Small, fsrLineColor, new RectangleF(r.X + 24, r.Bottom - 34, r.Width - 48, 22), StringAlignment.Near, StringAlignment.Near);
    }

    void OnFsrDownload() {
        if (fsrBusy) return;
        foreach (var pr in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(Fork.GameExe))) {
            string exe = "";
            try { exe = pr.MainModule.FileName; } catch { }
            if (exe.Length > 0 && string.Equals(Path.GetDirectoryName(exe), dir, StringComparison.OrdinalIgnoreCase)) {
                fsrLine = "Close the game first: its files are in use."; fsrLineColor = Theme.Amber; return;
            }
        }
        fsrBusy = true; fsrButton.Enabled = false;
        fsrLine = "Downloading..."; fsrLineColor = Theme.Cyan;
        new Thread(() => {
            string done;
            Color col;
            try {
                long all = 0;
                foreach (var f in Fsr.Files) all += long.Parse(f[2]);
                long got = 0;
                var tmp = new List<string>();
                foreach (var f in Fsr.Files) {
                    string part = Path.Combine(dir, f[0] + ".download");
                    tmp.Add(part);
                    using (var c = new WebClient()) {
                        c.Headers[HttpRequestHeader.UserAgent] = "Mako-launcher";
                        long before = got;
                        var ev = new ManualResetEvent(false); Exception err = null;
                        c.DownloadProgressChanged += (s, e) => {
                            long now = before + e.BytesReceived;
                            try { BeginInvoke((Action)(() => { fsrLine = "Downloading  " + (now >> 20) + " / " + (all >> 20) + " MB"; })); } catch { }
                        };
                        c.DownloadFileCompleted += (s, e) => { err = e.Error; ev.Set(); };
                        c.DownloadFileAsync(new Uri(Fsr.Base + f[0]), part);
                        ev.WaitOne();
                        if (err != null) throw err;
                    }
                    got += new FileInfo(part).Length;
                    if (!Fsr.SignedByAmd(part)) throw new Exception(f[0] + " is not signed by AMD: not installed");
                }
                for (int i = 0; i < Fsr.Files.Length; i++) {
                    string target = Path.Combine(dir, Fsr.Files[i][0]);
                    if (File.Exists(target)) File.Delete(target);
                    File.Move(tmp[i], target);
                }
                done = "Done: AMD FSR is installed. Choose AMD FSR 4 as the Upscaler."; col = Theme.Green;
            } catch (Exception ex) {
                foreach (var f in Fsr.Files) try { File.Delete(Path.Combine(dir, f[0] + ".download")); } catch { }
                done = "Could not install AMD FSR: " + ex.Message; col = Theme.Red;
            }
            try { BeginInvoke((Action)(() => { fsrLine = done; fsrLineColor = col; fsrBusy = false; fsrButton.Enabled = true; })); } catch { }
        }) { IsBackground = true }.Start();
    }

    void OnImport() {
        OpenFolder(Path.Combine(dir, "SAVE FOLDER"));
        MessageBox.Show(this, "Put saves from another emulator here (the folder holding slot_00, slot_01… or a folder above it).\n" +
                        "They are copied into the game at the next start, and the saves you had are kept in a backup folder.",
                        "Import saves", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    void OnPlay() { OnPlay(false); }
    void OnPlay(bool masterQuest) {
        string exe = Path.Combine(dir, Fork.GameExe);
        if (!File.Exists(exe)) {
            MessageBox.Show(this, "The game is not in this folder:\n" + dir + "\n\nThe launcher must sit beside it.", Fork.Name,
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (GameRunning()) { MessageBox.Show(this, "The game is already running.", Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
        if (!RunRandomizer()) return;
        if (!RunCosmetics()) return;
        try {
            var psi = new ProcessStartInfo(exe) { WorkingDirectory = dir, UseShellExecute = false };
            psi.EnvironmentVariables["HOOKSHOT_NO_UPDATE_CHECK"] = "1";   // (the launcher did it)
            psi.EnvironmentVariables["HOS_MASTER_QUEST"] = masterQuest ? "1" : "0";   // (Mako: host/master_quest.c, its own saves)
            Process.Start(psi);
            Close();
        } catch (Exception ex) { MessageBox.Show(this, "The game could not start:\n" + ex.Message, Fork.Name, MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    // (the randomizer: a seed's chests are placed by <game folder>\rando\rando_seed.py (tools/rando in the source: the build puts
    // it there), run with the player's Python before the game starts. It writes mods\rando-seed, does nothing when that is
    // already this seed's, and takes it away when the randomizer is off. What it said is kept in rando\last_run.txt.
    // false: it failed and the player chose not to start the game)
    bool RunRandomizer() {
        bool on = settings.ContainsKey("rando_on") && settings["rando_on"].Value != 0;
        return RunAtPlay("rando_seed.py", "rando-seed", on, "last_run.txt", "The randomizer seed could not be made");
    }

    // (cosmetics: the tunics' colours are written by <game folder>\rando\rando_cosmetics.py (tools/rando in the source), as the
    // seed is: mods\cosmetics, nothing done when it is already these colours', taken away when every colour is the game's own.
    // What it said is kept in rando\last_cosmetics.txt)
    bool RunCosmetics() {
        bool on = false;
        foreach (var s in cosmetics.Values) on |= s.Value != 0;
        return RunAtPlay("rando_cosmetics.py", "cosmetics", on, "last_cosmetics.txt", "The cosmetic colours could not be written");
    }

    // (a script of <game folder>\rando run with the player's Python before the game starts: it makes mods\<mod> when `on`, and
    // takes it away when not. false: it failed and the player chose not to start the game)
    bool RunAtPlay(string name, string mod, bool on, string log, string failed) {
        string script = Path.Combine(dir, "rando", name), romfs = Path.Combine(dir, "romfs");
        if (!File.Exists(script) || !Directory.Exists(romfs)) return true;   // (a game folder without it: as before)
        if (!on && !Directory.Exists(Path.Combine(dir, "mods", mod))) return true;   // (nothing to place, nothing to take away)
        string said = "", problem = null;
        Cursor = Cursors.WaitCursor;
        try {
            foreach (string python in new[] { "python", "py" }) {
                try {
                    var psi = new ProcessStartInfo(python, "-I \"" + script + "\" \"" + romfs + "\" --if-changed") {
                        WorkingDirectory = dir, UseShellExecute = false, CreateNoWindow = true,
                        RedirectStandardOutput = true, RedirectStandardError = true };
                    var errors = new System.Text.StringBuilder();
                    using (var p = new Process { StartInfo = psi }) {
                        p.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (errors) errors.AppendLine(e.Data); };
                        p.Start();
                        p.BeginErrorReadLine();
                        said = p.StandardOutput.ReadToEnd();
                        p.WaitForExit();
                        lock (errors) said += errors.ToString();
                        problem = p.ExitCode == 0 ? null : said.Trim();
                    }
                    break;   // (it ran: what it said is the answer, whichever Python it was)
                } catch (System.ComponentModel.Win32Exception) {
                    problem = "Python was not found. This needs Python 3 (python.org) with the zstandard package:\n    python -m pip install zstandard";
                }
            }
        } catch (Exception ex) { problem = ex.Message; }
        finally { Cursor = Cursors.Default; }
        try { File.WriteAllText(Path.Combine(dir, "rando", log), said); } catch { }
        if (problem == null) return true;
        if (problem.Length > 900) problem = problem.Substring(problem.Length - 900);
        return MessageBox.Show(this, failed + ":\n\n" + problem + "\n\nStart the game anyway?", Fork.Name,
                               MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes;
    }

    [STAThread]
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int how);
    // (a name for the folder that a mutex's name can hold: no backslash, the same however the path's letters are cased)
    public static string OnceName(string dir) {
        uint h = 0x811c9dc5u;
        unchecked { foreach (char c in dir.TrimEnd('\\').ToLowerInvariant()) h = (h ^ c) * 0x01000193u; }
        return h.ToString("x8");
    }
    static void Main(string[] args) {
        if (args.Length == 3 && args[0] == "--seed-id") {   // (tests/test_rando_settings.py: the ID of a seed and its choices, "3,0,0,...")
            var parts = args[2].Length == 0 ? new string[0] : args[2].Split(',');
            Console.Out.WriteLine(RandoId.Make(int.Parse(args[1]), Array.ConvertAll(parts, int.Parse)));
            return;
        }
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;   // (TLS 1.2: GitHub)
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string dir = args.Length > 0 && Directory.Exists(args[0]) ? Path.GetFullPath(args[0]) : AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        // (one launcher a game folder: each keeps the settings it read and writes the whole options file when one changes,
        // so of two open the last to save put back what the other had changed. Seen: the Randomizer found Off, and with it
        // the Saves and Save copies buttons showing the normal game's folder, its list of copies empty. A second start
        // brings the first one's window to the front and ends)
        bool first;
        var once = new Mutex(true, "MakoLauncher_" + OnceName(dir), out first);
        if (!first) {
            try {
                int me = Process.GetCurrentProcess().Id;
                foreach (var other in Process.GetProcessesByName(Process.GetCurrentProcess().ProcessName))
                    if (other.Id != me && other.MainWindowHandle != IntPtr.Zero) {
                        ShowWindow(other.MainWindowHandle, 9);   // (9: restored, if it was minimized)
                        SetForegroundWindow(other.MainWindowHandle);
                    }
            } catch { }
            return;
        }
        Application.Run(new LauncherForm(dir));
        GC.KeepAlive(once);
    }
}
