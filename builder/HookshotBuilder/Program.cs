using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace HookshotBuilder;

/// The Windows builder has no window: players use the Hookshot Launcher, which builds and starts the game. What is left:
///   HookshotBuilder.exe --cli <make_game.py's options>   (RecompLauncher, through the setup) no window; make_game.py's lines on
///                                                        stdout, and its result as the exit code
///   HookshotBuilder.exe                                  anything else: a message, get the Hookshot Launcher
static class Program
{
    /// Where players get the launcher (README, "Install and play")
    public const string LauncherDownload = "https://hookshot.magicbean.dev/download";

    public const string UseTheLauncher =
        "The Hookshot Builder has no window of its own: the Hookshot Launcher builds the game and starts it. Get the launcher from " +
        LauncherDownload;

    // (RecompLauncher) --cli <make_game.py's options>: no window; its lines on stdout, and its result as the exit code.
    // Why it stopped is one "error <text>" line on stdout (the stream a launcher reads) and again on stderr
    [STAThread]
    static int Main(string[] args)
    {
        var cli = args.Length > 0 && args[0] == "--cli";
        if (cli)
        {
            try { _ = BuilderHome.Base; }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
            {
                var why = "The Builder home could not be opened. " + error.Message;
                using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
                output.WriteLine("error " + why);
                Console.Error.WriteLine("error " + why);
                return 1;
            }
            return Cli(args.Skip(1).ToList());
        }
        Say(UseTheLauncher);
        return 1;
    }

    static int Cli(List<string> args)
    {
        using var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
        var tools = Tools.Find();
        if (tools == null)
        {
            const string missing = "error The build tools were not found next to this program.";
            stdout.WriteLine(missing);
            Console.Error.WriteLine(missing);
            return 1;
        }
        var done = new ManualResetEventSlim();
        string? failure = null, said = null;   // (said: make_game's own "error" line in --prepare mode, already passed on to stdout)
        var runner = new Runner(tools, args);
        runner.Line += line =>
        {
            if (line.StartsWith("error ")) said = line[6..];
            lock (stdout) stdout.WriteLine(line);
        };
        runner.Finished += result => { failure = result; done.Set(); };
        runner.Start();
        done.Wait();
        if (failure == null) return 0;
        var reason = said ?? failure;
        if (said == null) lock (stdout) stdout.WriteLine("error " + reason);
        Console.Error.WriteLine("error " + reason);
        return 1;
    }

    /// A message on stderr (for whoever started this from a command line or a script) and in a message box
    static void Say(string text)
    {
        try { Console.Error.WriteLine(text); } catch (IOException) { }
        try { MessageBoxW(IntPtr.Zero, text, "Hookshot Builder", 0x40 /* MB_ICONINFORMATION */); }
        catch (Exception e) when (e is DllNotFoundException or EntryPointNotFoundException) { }   // (no user32: a server core, a test)
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);
}
