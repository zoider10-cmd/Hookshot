using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using HookshotBuilder;

/// The Windows builder's --cli (builder/HookshotBuilder/Runner.cs, as Program.Cli runs it): make_game.py started with the
/// arguments as given, the environment the builder passes on (the build workers and memory as inherited, its home, no DLSS or
/// FSR SDK folder from the PC), and its lines and result delivered. An authored make_game.py stands in for the real one.
static class Program
{
    static readonly MethodInfo InfoMethod = typeof(Runner).GetMethod("Info", BindingFlags.Static | BindingFlags.NonPublic)!;
    static int checks;

    static void Require(bool ok, string message)
    {
        if (!ok) throw new Exception(message);
        checks++;
    }

    static ProcessStartInfo Info(Tools tools, string[] args) => (ProcessStartInfo)InfoMethod.Invoke(null, new object?[] { tools, args })!;

    static async Task<JsonElement> Delivery(ProcessStartInfo info)
    {
        using var child = Process.Start(info)!;
        var output = await child.StandardOutput.ReadToEndAsync();
        var error = await child.StandardError.ReadToEndAsync();
        await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        Require(child.ExitCode == 0 && error.Length == 0, "The authored argument/environment child failed.");
        using var json = JsonDocument.Parse(output.Trim().Split('\n')[0]);
        return json.RootElement.Clone();
    }

    static string? Env(ProcessStartInfo info, string key) => info.Environment.TryGetValue(key, out var v) ? v : null;

    static void CheckInfo(ProcessStartInfo info, Tools tools, string[] args)
    {
        Require(info.FileName == tools.Python, "make_game.py must run with the tools' Python.");
        Require(info.ArgumentList.SequenceEqual(new[] { "-I", Path.Combine(tools.Root, "nx2", "make_game.py") }.Concat(args)),
            "The builder changed the arguments it was given.");
        Require(info.WorkingDirectory == tools.Root && !info.UseShellExecute && info.CreateNoWindow
            && info.RedirectStandardOutput && info.RedirectStandardError, "Runner process options changed.");
        Require(Env(info, "PYTHONIOENCODING") == "utf-8", "make_game.py must write UTF-8.");
        Require(Env(info, "HOOKSHOT_BUILDER_EXE") == Environment.ProcessPath, "The game folder's builder= must name this program.");
        Require(Env(info, "HOOKSHOT_SETUP_BASE") == BuilderHome.Base, "The builder's home was not passed on.");
        Require(Env(info, "HOOKSHOT_NGX_SDK") == null && Env(info, "HOOKSHOT_FFX_SDK") == null,
            "An SDK folder set on the PC must not reach the build: DLSS and FSR only when its arguments ask.");
        foreach (var key in new[] { "HOOKSHOT_JOBS", "HOOKSHOT_MEM_LIMIT_GB" })
            Require(Env(info, key) == Environment.GetEnvironmentVariable(key), key + " must be passed on as inherited.");
    }

    static async Task<(string? Failure, List<string> Lines)> Run(Tools tools, params string[] args)
    {
        var completed = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var lines = new List<string>();
        var runner = new Runner(tools, args.ToList());
        runner.Line += line => { lock (lines) lines.Add(line); };
        runner.Finished += failure => completed.TrySetResult(failure);
        runner.Start();
        var result = await completed.Task.WaitAsync(TimeSpan.FromSeconds(15));
        return (result, lines);
    }

    static async Task EmptyParent(Tools tools)
    {
        // Environment.SetEnvironmentVariable(key, "") may remove the variable on Windows instead of keeping it empty.
        // Start a real parent with an explicit empty environment entry, then exercise the actual Runner.Info inheritance.
        Require(Environment.GetEnvironmentVariable("HOOKSHOT_JOBS") == "", "The empty-parent fixture did not inherit an empty entry.");
        var info = Info(tools, new[] { "--out", "authored output" });
        CheckInfo(info, tools, new[] { "--out", "authored output" });
        var value = await Delivery(info);
        Require(value.GetProperty("jobs").GetString() == "", "An inherited empty entry changed.");
    }

    static async Task Main(string[] args)
    {
        if (args.Length is < 1 or > 2) throw new Exception("Pass the Python executable for the authored child.");
        var emptyParent = args.Length == 2 && args[0] == "--empty-parent";
        var python = Path.GetFullPath(args[^1]);
        var saved = new[] { "HOOKSHOT_JOBS", "HOOKSHOT_MEM_LIMIT_GB", "HOOKSHOT_NGX_SDK", "HOOKSHOT_FFX_SDK", "HOOKSHOT_SETUP_BASE",
                            "HOOKSHOT_BUILDER_PORTABLE" }.ToDictionary(k => k, Environment.GetEnvironmentVariable);
        var root = Path.Combine(Path.GetTempPath(), "hookshot-builder-cli-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(root, "nx2"));
        Environment.SetEnvironmentVariable("HOOKSHOT_SETUP_BASE", root);
        Environment.SetEnvironmentVariable("HOOKSHOT_BUILDER_PORTABLE", null);
        try
        {
            Require(BuilderHome.Base == root && !BuilderHome.Portable, "The fixture did not use its isolated standard home.");
            // This is authored test content, not the real pipeline, game files or a compiler invocation.
            File.WriteAllText(Path.Combine(root, "nx2", "make_game.py"), """
                import json, os, sys
                keys = ('HOOKSHOT_JOBS', 'HOOKSHOT_MEM_LIMIT_GB', 'HOOKSHOT_NGX_SDK', 'HOOKSHOT_FFX_SDK', 'HOOKSHOT_SETUP_BASE')
                print(json.dumps({'argv': sys.argv[1:], 'jobs': os.environ.get('HOOKSHOT_JOBS'),
                                  'env': {k: os.environ.get(k) for k in keys}}), flush=True)
                if '--authored-fail' in sys.argv:
                    print('@@error authored reason', flush=True)
                    sys.exit(3)
                if '--authored-silent-fail' in sys.argv:
                    print('authored diagnostics', file=sys.stderr, flush=True)
                    sys.exit(4)
                print('@@done', flush=True)
                """);
            var tools = new Tools(root, python);
            if (emptyParent)
            {
                await EmptyParent(tools);
                Console.WriteLine("Empty inherited worker entry passed.");
                return;
            }

            var sourceArguments = new[]
            {
                new[] { "--nup", "authored file with spaces.nup", "--out", "authored output", "--language", "en" },
                new[] { "--romfs", "authored romfs", "--exefs", "authored exefs", "--out", "authored output", "--language", "fr" },
                new[] { "--update", "authored existing game" },
                new[] { "--prepare", "--game", "authored ü, game" },
            };
            Environment.SetEnvironmentVariable("HOOKSHOT_NGX_SDK", Path.Combine(root, "authored ngx"));
            Environment.SetEnvironmentVariable("HOOKSHOT_FFX_SDK", Path.Combine(root, "authored ffx"));
            foreach (var inherited in new string?[] { null, "4", "0", "not a number" })
            {
                Environment.SetEnvironmentVariable("HOOKSHOT_JOBS", inherited);
                Environment.SetEnvironmentVariable("HOOKSHOT_MEM_LIMIT_GB", inherited);
                foreach (var command in sourceArguments)
                {
                    var info = Info(tools, command);
                    CheckInfo(info, tools, command);
                    Require(Environment.GetEnvironmentVariable("HOOKSHOT_JOBS") == inherited, "Runner.Info changed its parent environment.");
                }
                var value = await Delivery(Info(tools, sourceArguments[3]));
                Require(value.GetProperty("argv").EnumerateArray().Select(e => e.GetString()).SequenceEqual(sourceArguments[3]),
                    "The child's arguments changed.");
                var env = value.GetProperty("env");
                Require(env.GetProperty("HOOKSHOT_JOBS").GetString() == inherited && env.GetProperty("HOOKSHOT_MEM_LIMIT_GB").GetString() == inherited,
                    "The inherited build workers or memory did not reach the child unchanged.");
                Require(env.GetProperty("HOOKSHOT_NGX_SDK").ValueKind == JsonValueKind.Null && env.GetProperty("HOOKSHOT_FFX_SDK").ValueKind == JsonValueKind.Null,
                    "An SDK folder set on the PC reached the child.");
                Require(env.GetProperty("HOOKSHOT_SETUP_BASE").GetString() == root, "The builder's home did not reach the child.");
            }

            // (Runner.Start: every line, in order, then how it ended; Program.Cli turns that into its exit code and "error" line)
            var ok = await Run(tools, "--update", "authored existing game");
            Require(ok.Failure == null && ok.Lines.Count == 2 && ok.Lines[1] == "@@done", "A build that ended well must deliver its lines and no failure.");
            var failed = await Run(tools, "--authored-fail");
            Require(failed.Failure == "authored reason" && failed.Lines.Contains("@@error authored reason"),
                "A failed build must end with its own @@error reason.");
            var silent = await Run(tools, "--authored-silent-fail");
            Require(silent.Failure == "The build tools stopped without saying why. See the details." && silent.Lines.Contains("authored diagnostics"),
                "A build that stopped without @@error must say so, with its stderr among the lines.");
            var none = await Run(new Tools(root, Path.Combine(root, "no python here")), "--version");
            Require(none.Failure != null && none.Failure.StartsWith("The build tools could not start: "), "A missing Python must be said.");
            Directory.CreateDirectory(Path.Combine(root, "python"));
            var gone = await Run(new Tools(root, Path.Combine(root, "python", "python.exe")), "--version");
            Require(gone.Failure == Tools.OwnPythonMissingText, "The package's own Python removed must say how to get it back.");
            Directory.Delete(Path.Combine(root, "python"));

            var self = new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
            if (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase))
                self.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
            self.ArgumentList.Add("--empty-parent"); self.ArgumentList.Add(python);
            self.Environment["HOOKSHOT_JOBS"] = "";
            using var empty = Process.Start(self)!;
            var emptyOutput = await empty.StandardOutput.ReadToEndAsync();
            var emptyError = await empty.StandardError.ReadToEndAsync();
            await empty.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            Require(empty.ExitCode == 0 && emptyError.Length == 0 && emptyOutput.Contains("Empty inherited worker entry passed."), "Empty inheritance check failed: " + emptyError);
            Console.WriteLine($"Windows Builder --cli checks passed ({checks} assertions). Only an authored make_game.py was run.");
        }
        finally
        {
            foreach (var (key, value) in saved) Environment.SetEnvironmentVariable(key, value);
            Directory.Delete(root, recursive: true);
        }
    }
}
