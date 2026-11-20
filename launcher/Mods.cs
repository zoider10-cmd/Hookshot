// (Mako 4.1) The Mods tab: a mod dropped on the launcher (.zip, .7z, .rar, or a folder) is put in the game's mods folder, where
// the game reads it when it starts (host/mods.c: <game>\mods\<name>\romfs, the layout emulators use, so their RomFS mods work as
// they are). The launcher keeps each mod in a folder named "NN Name": the game loads them in name order and, when two mods have the
// same file, the later one wins. A folder whose name starts with '_' is off (the game leaves it out).
// .zip is opened by .NET; .7z and .rar by 7-Zip when installed, else by Windows' own tar.exe (libarchive: 7z and rar on Windows 10/11).
// exefs patches and cheats are not used by Mako (its code is compiled ahead of time): such parts are left out, and said so.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text.RegularExpressions;

class ModInfo {
    public string Folder, Name;
    public bool On, HasCode;
    public int Files;
    public int Lost;                                        // (its files another mod, lower in the list, replaces)
    public List<string> BeatenBy = new List<string>(), Beats = new List<string>();
    public HashSet<string> Rel = new HashSet<string>();     // (its RomFS files, lower case, '/')
}

static class Mods {
    public static string Root(string dir) { return Path.Combine(dir, "mods"); }
    public static readonly string[] Own = { "rando-seed", "cosmetics" };
    static readonly Regex Numbered = new Regex(@"^([_-]?)(\d{2,3}) (.+)$");

    // (the game's own order: folder names compared in lower case, a leading '_' or '-' aside)
    static string SortKey(string folderName) {
        string s = folderName.TrimStart('_', '-');
        return s.ToLowerInvariant();
    }

    // ---- the list ----
    public static List<ModInfo> List(string dir) {
        var list = new List<ModInfo>();
        string root = Root(dir);
        if (!Directory.Exists(root)) return list;
        var keyed = new List<KeyValuePair<string, ModInfo>>();
        foreach (var d in Directory.GetDirectories(root)) {
            string fn = Path.GetFileName(d);
            if (fn.StartsWith(".")) continue;   // (.installing-…: a mod being put in)
            // (the randomizer's fork: its seed and its colours are mods the launcher writes itself at Play, by these
            //  names (RunAtPlay): they are not in the list, which would rename them "NN Name" and switch them on and off)
            if (Array.IndexOf(Own, fn.ToLowerInvariant()) >= 0) continue;
            var m = new ModInfo { Folder = d };
            var mm = Numbered.Match(fn);
            if (mm.Success) { m.On = mm.Groups[1].Value.Length == 0; m.Name = mm.Groups[3].Value; }
            else { m.On = !(fn.StartsWith("_") || fn.StartsWith("-")); m.Name = fn.TrimStart('_', '-'); }
            var romfs = new List<string>(); bool code = false;
            FindParts(d, 0, romfs, ref code);
            m.HasCode = code;
            foreach (var r in romfs)
                foreach (var f in SafeFiles(r)) {
                    m.Rel.Add(f.Substring(r.Length + 1).Replace('\\', '/').ToLowerInvariant());
                }
            m.Files = m.Rel.Count;
            keyed.Add(new KeyValuePair<string, ModInfo>(SortKey(fn), m));
        }
        keyed.Sort((a, b) => string.CompareOrdinal(a.Key, b.Key));
        foreach (var k in keyed) list.Add(k.Value);
        // (who wins: for each file, the last mod that is on)
        var winner = new Dictionary<string, int>();
        for (int i = 0; i < list.Count; i++) if (list[i].On) foreach (var f in list[i].Rel) winner[f] = i;
        for (int i = 0; i < list.Count; i++) {
            if (!list[i].On) continue;
            foreach (var f in list[i].Rel) {
                int w = winner[f];
                if (w == i) continue;
                list[i].Lost++;
                if (!list[i].BeatenBy.Contains(list[w].Name)) list[i].BeatenBy.Add(list[w].Name);
                if (!list[w].Beats.Contains(list[i].Name)) list[w].Beats.Add(list[i].Name);
            }
        }
        return list;
    }

    // (the romfs folders in a mod, as the game looks for them: up to 4 levels down; exefs or cheats: code the game does not use)
    static void FindParts(string d, int depth, List<string> romfs, ref bool code) {
        string[] subs;
        try { subs = Directory.GetDirectories(d); } catch { return; }
        bool found = false;
        foreach (var s in subs) {
            string n = Path.GetFileName(s).ToLowerInvariant();
            if (n == "romfs") { romfs.Add(s); found = true; }
            else if (n == "exefs" || n == "cheats") { code = true; found = true; }
        }
        if (found || depth >= 4) return;
        foreach (var s in subs) {
            string n = Path.GetFileName(s);
            if (n.StartsWith(".") || n.StartsWith("_") || n.StartsWith("-")) continue;
            FindParts(s, depth + 1, romfs, ref code);
        }
    }

    static IEnumerable<string> SafeFiles(string d) {
        try { return Directory.GetFiles(d, "*", SearchOption.AllDirectories); } catch { return new string[0]; }
    }

    // (every folder named "NN Name" in the list's order, '_' in front when off)
    public static void Write(string dir, List<ModInfo> list) {
        string root = Root(dir);
        var temp = new List<string>();
        for (int i = 0; i < list.Count; i++) {
            string want = Path.Combine(root, (list[i].On ? "" : "_") + (i + 1).ToString("00") + " " + list[i].Name);
            if (string.Equals(list[i].Folder, want, StringComparison.Ordinal)) { temp.Add(null); continue; }
            string t = Path.Combine(root, ".rename-" + i + "-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.Move(list[i].Folder, t);
            temp.Add(t);
        }
        for (int i = 0; i < list.Count; i++) {
            if (temp[i] == null) continue;
            string want = Path.Combine(root, (list[i].On ? "" : "_") + (i + 1).ToString("00") + " " + list[i].Name);
            Directory.Move(temp[i], want);
            list[i].Folder = want;
        }
    }

    public static void Remove(string folder) {
        Microsoft.VisualBasic.FileIO.FileSystem.DeleteDirectory(folder, Microsoft.VisualBasic.FileIO.UIOption.OnlyErrorDialogs,
                                                                Microsoft.VisualBasic.FileIO.RecycleOption.SendToRecycleBin);
    }

    // ---- putting a mod in ----
    class Found { public string Root, Romfs, Label; public bool Code; public HashSet<string> Rel = new HashSet<string>(); }

    // (returns the line shown to the player)
    public static string Install(string dir, string source, out bool ok) {
        ok = false;
        string root = Root(dir);
        Directory.CreateDirectory(root);
        string work = null;
        bool isDir = Directory.Exists(source);
        string archiveName = CleanName(isDir ? Path.GetFileName(source.TrimEnd('\\')) : Path.GetFileNameWithoutExtension(source));
        try {
            string src = source;
            if (!isDir) {
                work = Path.Combine(root, ".i" + Guid.NewGuid().ToString("N").Substring(0, 6));   // (short: deep archives stay under Windows' 260-character paths)
                Directory.CreateDirectory(work);
                string err = Extract(source, work);
                if (err != null) return err;
                src = work;
            }
            var found = new List<Found>();
            FindMods(src, 0, found);
            if (found.Count == 0) {
                string bare = FindBareRomfs(dir, src, 0);
                if (bare != null) found.Add(new Found { Root = src, Romfs = bare });
            }
            if (found.Count == 0)
                return "No mod found in " + archiveName + ": it has no romfs folder (the game's files a mod replaces).";
            var usable = found.Where(f => f.Romfs != null).ToList();
            if (usable.Count == 0)
                return archiveName + " changes the game's code (exefs or cheats). Lost Woods's code is already built for PC: mods like this can't work, nothing was installed.";
            bool codeLeft = found.Any(f => f.Code);

            // (names: the folder's own, unless it says nothing (a title id, "contents", the archive's root): then the archive's)
            for (int i = 0; i < usable.Count; i++) {
                var f = usable[i];
                string own = f.Root == src ? "" : Path.GetFileName(f.Root);
                bool meaningless = own.Length == 0 || Regex.IsMatch(own, "^[0-9A-Fa-f]{16}$") ||
                                   new[] { "contents", "atmosphere", "mods", "switch", "romfs", "mod" }.Contains(own.ToLowerInvariant());
                string label = meaningless ? archiveName : CleanName(own);
                if (usable.Count > 1) {
                    // (several in one archive: the archive's name, then every folder down to it that says something, without the
                    // "1 - " numbers: "Classic Logo Version/1 - Default HUD Mod" -> "<archive> - Classic Logo Version - Default HUD Mod")
                    var parts = new List<string>();
                    string rel = f.Root.Length > src.Length ? f.Root.Substring(src.Length).Trim('\\') : "";
                    foreach (var part in rel.Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries)) {
                        string pl = part.ToLowerInvariant();
                        if (Regex.IsMatch(part, "^[0-9A-Fa-f]{16}$") || new[] { "contents", "atmosphere", "mods", "switch", "romfs", "mod" }.Contains(pl)) continue;
                        string clean = CleanName(Regex.Replace(part, @"^\s*\d+\s*[-.)_]\s*", ""));
                        if (clean.Length == 0 || clean.Equals(archiveName, StringComparison.OrdinalIgnoreCase)) continue;
                        parts.Add(clean);
                    }
                    // (short: the game opens its files with Windows' 260-character paths; the archive's name only when it fits)
                    string own2 = string.Join(" - ", parts.ToArray());
                    label = parts.Count == 0 ? archiveName + " " + (i + 1) : (archiveName.Length > 0 && archiveName.Length + 3 + own2.Length <= 50 ? archiveName + " - " + own2 : own2);
                    if (label.Length > 50) {   // (cut at a whole word)
                        int cut = label.LastIndexOf(' ', 50);
                        label = label.Substring(0, cut > 20 ? cut : 50).TrimEnd(' ', '-', '.');
                    }
                }
                f.Label = label.Length > 0 ? label : "Mod";
                foreach (var file in SafeFiles(f.Romfs)) f.Rel.Add(file.Substring(f.Romfs.Length + 1).Replace('\\', '/').ToLowerInvariant());
            }
            for (int i = 0; i < usable.Count; i++)   // (two with the same name: numbered)
                for (int j = i + 1; j < usable.Count; j++)
                    if (usable[j].Label.Equals(usable[i].Label, StringComparison.OrdinalIgnoreCase)) usable[j].Label += " " + (j + 1);
            // (versions of one mod: they change the same files; only the first is switched on)
            bool variants = false;
            for (int i = 1; i < usable.Count && !variants; i++)
                for (int j = 0; j < i && !variants; j++) if (usable[i].Rel.Overlaps(usable[j].Rel)) variants = true;

            var list = List(dir);
            int replaced = 0;
            for (int i = 0; i < usable.Count; i++) {
                var f = usable[i];
                if (f.Rel.Count == 0) continue;
                var old = list.FindIndex(m => m.Name.Equals(f.Label, StringComparison.OrdinalIgnoreCase));
                string dest = Path.Combine(root, ".new-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                Directory.CreateDirectory(dest);
                if (isDir) CopyDir(f.Romfs, Path.Combine(dest, "romfs"));
                else Directory.Move(f.Romfs, Path.Combine(dest, "romfs"));
                var info = new ModInfo { Folder = dest, Name = f.Label, On = !variants || i == 0 };
                if (old >= 0) {   // (the same mod again: the new files take its place, the old ones go to the Recycle Bin)
                    info.On = list[old].On;
                    try { Remove(list[old].Folder); } catch { try { Directory.Delete(list[old].Folder, true); } catch { } }
                    list[old] = info; replaced++;
                } else list.Add(info);
            }
            Write(dir, list);
            ok = true;
            string names = string.Join(", ", usable.Select(f => f.Label).ToArray());
            string line = (replaced > 0 ? "Updated: " : "Installed: ") + names + ".";
            if (variants) line = "Installed " + archiveName + ": it comes in " + usable.Count + " versions. The first is on; switch on the one you want in the list.";
            if (codeLeft) line += " Its code part (exefs or cheats) is left out: Lost Woods doesn't use those.";
            return line;
        } catch (PathTooLongException) {
            return "Could not install " + archiveName + ": its folders are too deep for this game folder's place. Move the game folder somewhere shorter (for example C:\\Lost Woods) and try again.";
        } catch (Exception e) {
            return "Could not install " + archiveName + ": " + e.Message;
        } finally {
            if (work != null) try { Directory.Delete(work, true); } catch { }
        }
    }

    // (a mod: a folder holding romfs, exefs or cheats)
    static void FindMods(string d, int depth, List<Found> found) {
        string[] subs;
        try { subs = Directory.GetDirectories(d); } catch { return; }
        Found f = null;
        foreach (var s in subs) {
            string n = Path.GetFileName(s).ToLowerInvariant();
            if (n == "romfs") { f = f ?? new Found { Root = d }; f.Romfs = s; }
            else if (n == "exefs" || n == "cheats") { f = f ?? new Found { Root = d }; f.Code = true; }
        }
        if (f != null) { found.Add(f); return; }
        if (depth >= 6) return;
        foreach (var s in subs) {
            string n = Path.GetFileName(s);
            if (n.StartsWith(".") || n.Equals("__MACOSX", StringComparison.OrdinalIgnoreCase)) continue;
            FindMods(s, depth + 1, found);
        }
    }

    // (no romfs folder: a folder whose subfolders are the game's own top folders (Model, Pack, Tex…) is the romfs itself)
    static string FindBareRomfs(string dir, string d, int depth) {
        var game = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try { foreach (var g in Directory.GetDirectories(Path.Combine(dir, "romfs"))) game.Add(Path.GetFileName(g)); } catch { }
        if (game.Count == 0) foreach (var n in new[] { "Model", "Pack", "Tex", "Banc", "Mals", "UI", "Font", "Sound", "Event", "Effect", "Layout", "Movie", "Shader", "Actor" }) game.Add(n);
        var queue = new Queue<KeyValuePair<string, int>>();
        queue.Enqueue(new KeyValuePair<string, int>(d, 0));
        while (queue.Count > 0) {
            var cur = queue.Dequeue();
            string[] subs;
            try { subs = Directory.GetDirectories(cur.Key); } catch { continue; }
            int match = subs.Count(s => game.Contains(Path.GetFileName(s)));
            if (match > 0 && match * 2 >= subs.Length) return cur.Key;
            if (cur.Value < 5) foreach (var s in subs) queue.Enqueue(new KeyValuePair<string, int>(s, cur.Value + 1));
        }
        return null;
    }

    static void CopyDir(string from, string to) {
        Directory.CreateDirectory(to);
        foreach (var f in Directory.GetFiles(from)) File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(from)) CopyDir(d, Path.Combine(to, Path.GetFileName(d)));
    }

    // (an archive's name without the download sites' numbers: "Mod-11734-0-15-1726415394", "Mod 16060 0.5 2026-06-26T23-15Z RXDpXNohy")
    public static string CleanName(string s) {
        s = Regex.Replace(s, @"-\d{3,}-[\d-]+$", "");
        s = Regex.Replace(s, @"\s\d{3,}\s[\w.]+\s\d{4}-\d\d-\d\dT[\w-]+\s\w+$", "");
        s = Regex.Replace(s, @"\s*\(\d+\)$", "");
        s = s.Replace('_', ' ');
        foreach (char c in Path.GetInvalidFileNameChars()) s = s.Replace(c.ToString(), "");
        s = Regex.Replace(s, @"\s+", " ").Trim().TrimStart('-', '.', ' ');
        s = Regex.Replace(s, @"^\d{2,3} ", "");   // (not to be read as a list position)
        if (s.Length > 50) s = s.Substring(0, 50).Trim();
        return s.TrimEnd('.', ' ');
    }

    // ---- archives ----
    public static readonly string[] Kinds = { ".zip", ".7z", ".rar" };

    static string Extract(string archive, string to) {
        string ext = Path.GetExtension(archive).ToLowerInvariant();
        if (ext == ".zip") {
            try { ExtractZip(archive, to); return null; }
            catch (InvalidDataException) { }   // (a zip .NET can't read, e.g. compressed in LZMA: the tools below)
            catch (NotSupportedException) { }
            foreach (var f in Directory.GetFileSystemEntries(to)) { try { if (Directory.Exists(f)) Directory.Delete(f, true); else File.Delete(f); } catch { } }
        }
        string seven = SevenZip();
        if (seven != null && Run(seven, "x -y -bd \"-o" + to + "\" -- \"" + archive + "\"") <= 1 && Directory.GetFileSystemEntries(to).Length > 0) return null;
        string tar = Path.Combine(Environment.SystemDirectory, "tar.exe");
        if (File.Exists(tar) && Run(tar, "-x -f \"" + archive + "\" -C \"" + to + "\"") == 0 && Directory.GetFileSystemEntries(to).Length > 0) return null;
        return "Windows could not open " + Path.GetFileName(archive) + ". If it has a password, or Windows is old, install 7-Zip (free, 7-zip.org) " +
               "and drop it again, or unzip it yourself and drop the folder.";
    }

    static void ExtractZip(string archive, string to) {
        string top = Path.GetFullPath(to).TrimEnd('\\') + "\\";
        using (var za = ZipFile.OpenRead(archive))
            foreach (var e in za.Entries) {
                string full = Path.GetFullPath(Path.Combine(to, e.FullName.Replace('/', '\\').TrimStart('\\')));
                if (!full.StartsWith(top, StringComparison.OrdinalIgnoreCase)) continue;   // (a path leaving the folder: left out)
                if (e.FullName.EndsWith("/") || e.FullName.EndsWith("\\")) { Directory.CreateDirectory(full); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(full));
                e.ExtractToFile(full, true);
            }
    }

    static string SevenZip() {
        foreach (var hive in new[] { Microsoft.Win32.Registry.LocalMachine, Microsoft.Win32.Registry.CurrentUser })
            try {
                using (var k = hive.OpenSubKey(@"SOFTWARE\7-Zip"))
                    if (k != null) foreach (var v in new[] { "Path64", "Path" }) {
                        string p = k.GetValue(v) as string;
                        if (p != null && File.Exists(Path.Combine(p, "7z.exe"))) return Path.Combine(p, "7z.exe");
                    }
            } catch { }
        foreach (var p in new[] { Environment.GetEnvironmentVariable("ProgramW6432"), Environment.GetEnvironmentVariable("ProgramFiles"),
                                  Environment.GetEnvironmentVariable("ProgramFiles(x86)") })
            if (!string.IsNullOrEmpty(p) && File.Exists(Path.Combine(p, "7-Zip", "7z.exe"))) return Path.Combine(p, "7-Zip", "7z.exe");
        return null;
    }

    static int Run(string exe, string args) {
        try {
            var psi = new ProcessStartInfo(exe, args) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            using (var p = Process.Start(psi)) {
                p.OutputDataReceived += (s, e) => { }; p.ErrorDataReceived += (s, e) => { };
                p.BeginOutputReadLine(); p.BeginErrorReadLine();
                if (!p.WaitForExit(15 * 60 * 1000)) { try { p.Kill(); } catch { } return -1; }
                return p.ExitCode;
            }
        } catch { return -1; }
    }
}

// ---- the Mods tab's widgets ----
// (the drop zone: a mod dropped anywhere on the window lands here; a click opens a file picker)
class ModDrop : Widget {
    public Action Click;
    public override void Down(PointF p, LauncherForm ui) { if (Click != null && !ui.ModBusy) Click(); }
    public override bool Animating { get { return true; } }
    public override void Paint(Graphics g, LauncherForm ui) {
        float lit = Math.Max(Hover, ui.DropHover ? 1 : 0);
        using (var path = Theme.Round(R, 14)) {
            using (var b = new SolidBrush(Theme.Mix(Theme.Card, Theme.A(Theme.Blue, 40), lit))) g.FillPath(b, path);
            using (var pen = new Pen(Theme.Mix(Theme.Line, Theme.Cyan, lit), 1.4f) { DashStyle = DashStyle.Dash }) g.DrawPath(pen, path);
        }
        // (an arrow into a tray)
        float ax = R.X + 40, ay = R.Y + R.Height / 2;
        using (var pen = new Pen(Theme.Mix(Theme.Dim, Theme.Cyan, lit), 2.2f) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round }) {
            float bob = ui.DropHover ? (float)Math.Sin(ui.Time * 8) * 2.5f : 0;
            g.DrawLine(pen, ax, ay - 14 + bob, ax, ay + 4 + bob);
            g.DrawLines(pen, new[] { new PointF(ax - 7, ay - 3 + bob), new PointF(ax, ay + 4 + bob), new PointF(ax + 7, ay - 3 + bob) });
            g.DrawLines(pen, new[] { new PointF(ax - 14, ay + 4), new PointF(ax - 14, ay + 13), new PointF(ax + 14, ay + 13), new PointF(ax + 14, ay + 4) });
        }
        string title = ui.ModBusy ? "Installing" + new string('.', 1 + (int)(ui.Time * 2.5f) % 3) : ui.DropHover ? "Drop it to install" : "Drop a mod here";
        Theme.Text_(g, title, Theme.Strong, Theme.Text, new RectangleF(R.X + 76, R.Y + 14, R.Width - 90, 24), StringAlignment.Near, StringAlignment.Near);
        Theme.Text_(g, ui.ModBusy ? ui.ModStatus : "A .zip, .7z or .rar file, or a folder. Or click here to choose one.", Theme.Small, Theme.Dim,
                    new RectangleF(R.X + 76, R.Y + 40, R.Width - 90, 22), StringAlignment.Near, StringAlignment.Near);
    }
}

// (the installed mods: a switch, the name, what it does to the others, up and down, remove)
class ModListW : Widget {
    public const float RowH = 60, Gap = 6;
    public override bool Animating { get { return false; } }
    RectangleF Row(int i, LauncherForm ui) { return new RectangleF(R.X, R.Y + i * (RowH + Gap) - ui.ModScroll, R.Width, RowH); }
    static RectangleF Switch(RectangleF r) { return new RectangleF(r.X + 16, r.Y + r.Height / 2 - 12, 44, 24); }
    static RectangleF Up(RectangleF r) { return new RectangleF(r.Right - 116, r.Y + 15, 32, 30); }
    static RectangleF DownR(RectangleF r) { return new RectangleF(r.Right - 80, r.Y + 15, 32, 30); }
    static RectangleF Del(RectangleF r) { return new RectangleF(r.Right - 44, r.Y + 15, 32, 30); }

    public override void Down(PointF p, LauncherForm ui) {
        var list = ui.ModItems;
        for (int i = 0; i < list.Count; i++) {
            var r = Row(i, ui);
            if (!r.Contains(p)) continue;
            if (Up(r).Contains(p)) ui.ModMove(i, -1);
            else if (DownR(r).Contains(p)) ui.ModMove(i, 1);
            else if (Del(r).Contains(p)) ui.ModRemove(i);
            else if (Switch(r).Contains(p) || p.X < r.X + r.Width - 130) ui.ModToggle(i);
            return;
        }
    }

    public override void Paint(Graphics g, LauncherForm ui) {
        var list = ui.ModItems;
        if (list.Count == 0) {
            Theme.Text_(g, "No mods yet.", Theme.Strong, Theme.Dim, new RectangleF(R.X, R.Y + 40, R.Width, 24), StringAlignment.Center, StringAlignment.Near);
            Theme.Text_(g, "Mods made for emulators work as they are: their romfs part (the game's files they replace). " +
                           "Code mods (exefs, cheats, fps patches) can't work: Lost Woods is already built for PC.", Theme.Small, Theme.Faint,
                        new RectangleF(R.X + 40, R.Y + 72, R.Width - 80, 44), StringAlignment.Center, StringAlignment.Near);
            return;
        }
        var state = g.Save();
        g.SetClip(new RectangleF(R.X - 2, R.Y - 2, R.Width + 4, R.Height + 4));
        for (int i = 0; i < list.Count; i++) {
            var r = Row(i, ui);
            if (r.Bottom < R.Y || r.Y > R.Bottom) continue;
            var m = list[i];
            bool over = ui.MouseIn(r) && ui.MouseIn(R);
            using (var path = Theme.Round(r, 12)) {
                using (var b = new SolidBrush(over ? Theme.CardHi : Theme.Card)) g.FillPath(b, path);
                using (var pen = new Pen(over ? Theme.A(Theme.Blue, 160) : Theme.Line, 1f)) g.DrawPath(pen, path);
            }
            // (the switch)
            var sw = Switch(r);
            using (var p = Theme.Round(sw, 12)) {
                using (var b = new SolidBrush(m.On ? Theme.Blue : Color.FromArgb(34, 44, 66))) g.FillPath(b, p);
                using (var pen = new Pen(m.On ? Theme.A(Theme.Cyan, 150) : Theme.Line, 1f)) g.DrawPath(pen, p);
            }
            using (var b = new SolidBrush(Color.White)) g.FillEllipse(b, m.On ? sw.Right - 21 : sw.X + 3, sw.Y + 3, 18, 18);
            // (its place, its name, its line)
            float tx = sw.Right + 16, tw = r.Width - (tx - r.X) - 130;
            Theme.Text_(g, (i + 1) + ".", Theme.Label, Theme.Faint, new RectangleF(tx, r.Y + 9, 26, 22), StringAlignment.Near, StringAlignment.Near);
            Theme.Text_(g, m.Name, Theme.Strong, m.On ? Theme.Text : Theme.Dim, new RectangleF(tx + 24, r.Y + 7, tw - 24, 24), StringAlignment.Near, StringAlignment.Near);
            string line; Color c = Theme.Dim;
            if (m.Files == 0) { line = m.HasCode ? "Code only (exefs or cheats): Lost Woods can't use it." : "No files the game reads."; c = Theme.Amber; }
            else if (!m.On) { line = "Off · " + m.Files + " file" + (m.Files > 1 ? "s" : ""); c = Theme.Faint; }
            else if (m.Lost > 0) {
                line = (m.Lost == m.Files ? "Fully replaced by " : m.Lost + " of its " + m.Files + " files replaced by ") + string.Join(", ", m.BeatenBy.ToArray());
                c = Theme.Amber;
            } else if (m.Beats.Count > 0) { line = m.Files + " file" + (m.Files > 1 ? "s" : "") + " · wins over " + string.Join(", ", m.Beats.ToArray()); c = Theme.Cyan; }
            else line = m.Files + " file" + (m.Files > 1 ? "s" : "") + (m.HasCode ? " · its code part (exefs) is left out" : "");
            Theme.Text_(g, line, Theme.Small, c, new RectangleF(tx, r.Y + 33, tw, 20), StringAlignment.Near, StringAlignment.Near);
            // (up, down, remove)
            Icon(g, Up(r), ui, i > 0, 0);
            Icon(g, DownR(r), ui, i < list.Count - 1, 1);
            Icon(g, Del(r), ui, true, 2);
        }
        g.Restore(state);
        // (more below / above: a thin bar)
        float total = list.Count * (RowH + Gap) - Gap;
        if (total > R.Height) {
            float bar = Math.Max(30, R.Height * R.Height / total), by = R.Y + (R.Height - bar) * ui.ModScroll / (total - R.Height);
            using (var p = Theme.Round(new RectangleF(R.Right + 8, by, 4, bar), 2)) using (var b = new SolidBrush(Theme.A(Theme.Dim, 110))) g.FillPath(b, p);
        }
    }

    static void Icon(Graphics g, RectangleF r, LauncherForm ui, bool on, int kind) {
        bool over = on && ui.MouseIn(r);
        if (over) using (var p = Theme.Round(r, 8)) using (var b = new SolidBrush(Theme.A(kind == 2 ? Theme.Red : Theme.Blue, 70))) g.FillPath(b, p);
        float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2, s = 5f;
        Color col = !on ? Theme.A(Theme.Faint, 110) : over ? Color.White : Theme.Dim;
        using (var pen = new Pen(col, 2f) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round }) {
            if (kind == 0) g.DrawLines(pen, new[] { new PointF(cx - s, cy + s * 0.5f), new PointF(cx, cy - s * 0.5f), new PointF(cx + s, cy + s * 0.5f) });
            else if (kind == 1) g.DrawLines(pen, new[] { new PointF(cx - s, cy - s * 0.5f), new PointF(cx, cy + s * 0.5f), new PointF(cx + s, cy - s * 0.5f) });
            else { g.DrawLine(pen, cx - 4.5f, cy - 4.5f, cx + 4.5f, cy + 4.5f); g.DrawLine(pen, cx - 4.5f, cy + 4.5f, cx + 4.5f, cy - 4.5f); }
        }
    }
}
