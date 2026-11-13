# Builds "Mako Launcher.exe" from Launcher.cs with the .NET Framework's own compiler (on every Windows, nothing to install).
# mako_logo.png is embedded; the icon is mako.ico (both made by make_assets.ps1 from mako_source.png).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ico = Join-Path $here "mako.ico"
if (-not (Test-Path $ico) -or -not (Test-Path (Join-Path $here "mako_logo.png"))) { & (Join-Path $here "make_assets.ps1") }
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$exe = Join-Path $here "Mako Launcher.exe"
# (Mako 4.0) Send logs: the reports webhook, kept out of the public source (report_webhook.txt is git-ignored)
$hook = Join-Path $here "report_webhook.txt"
$extra = @(); if (Test-Path $hook) { $extra += "/resource:$hook,report_webhook.txt" } else { "note: no report_webhook.txt, Send logs is off in this build" }
& $csc /nologo /target:winexe /optimize+ /platform:anycpu "/out:$exe" "/win32icon:$ico" "/resource:$(Join-Path $here 'mako_logo.png'),mako_logo.png" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll @extra (Join-Path $here "Launcher.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed" }
"built $exe ($((Get-Item $exe).Length) bytes)"
