# Builds "Lost Woods Launcher.exe" from Launcher.cs with the .NET Framework's own compiler (on every Windows, nothing to install).
# lostwoods_logo.png is embedded; the icon is lostwoods.ico (both drawn by make_tree_logo.py).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ico = Join-Path $here "lostwoods.ico"
if (-not (Test-Path $ico) -or -not (Test-Path (Join-Path $here "lostwoods_logo.png"))) { & py -I (Join-Path $here "make_tree_logo.py") }
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$exe = Join-Path $here "Lost Woods Launcher.exe"
# (Mako 4.0) Send logs: the reports webhook, kept out of the public source (report_webhook.txt is git-ignored)
$hook = Join-Path $here "report_webhook.txt"
$extra = @(); if (Test-Path $hook) { $extra += "/resource:$hook,report_webhook.txt" } else { "note: no report_webhook.txt, Send logs is off in this build" }
& $csc /nologo /target:winexe /optimize+ /platform:anycpu "/out:$exe" "/win32icon:$ico" "/resource:$(Join-Path $here 'lostwoods_logo.png'),lostwoods_logo.png" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /r:Microsoft.VisualBasic.dll /r:System.Core.dll @extra (Join-Path $here "Launcher.cs") (Join-Path $here "Mods.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed" }
"built $exe ($((Get-Item $exe).Length) bytes)"
