# Mako randomizer fork: puts this fork on a Mako game folder that is already built. Share this one file.
#
# What it does, on the PC it is run on:
#   1. downloads the fork's source from GitHub (source only: no game files, and nothing made from them, is downloaded or sent);
#   2. builds the game folder again from the game files that folder keeps (nx2/make_game.py --update), with the tools the Mako
#      builder that made the folder already has (its Python and its compiler). Saves (user\), settings and mods stay;
#   3. builds the fork's launcher and puts it in the game folder.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1                      (asks for the game folder)
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Game "D:\Games\Mako"
#
#   -Tools   the Mako builder's "tools" folder (the one with nx2, python and llvm-mingw in it), when it is not found by itself
#   -Source  a folder with the fork's source already in it, instead of downloading (a clone)
#   -Ref     the branch, tag or commit to download (the fork's main branch when left out)
#   -Repo    the GitHub repository, "owner/name"
#
# The randomizer makes its seed with Python when Play is pressed: Python 3 from python.org with the zstandard package
# (python -m pip install zstandard). The script says so at its end when it is missing.
# The launcher's Update button installs the original Mako over this fork: do not press it.
param(
    [string]$Game,
    [string]$Tools,
    [string]$Source,
    [string]$Ref = "amd-fix-sharkiix-version",
    [string]$Repo = "zoider10-cmd/Hookshot"
)
$ErrorActionPreference = "Stop"
function Stop-With($text) { Write-Host ""; Write-Host $text -ForegroundColor Red; exit 1 }
function Say($text) { Write-Host $text -ForegroundColor Cyan }

# ---- the game folder ----
if (-not $Game) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $here "hookshot.exe")) { $Game = $here }
    else { $Game = Read-Host "The Mako game folder (the one with hookshot.exe in it)" }
}
$Game = $Game.Trim('"').TrimEnd('\')
if (-not (Test-Path (Join-Path $Game "hookshot.exe"))) { Stop-With "hookshot.exe is not in:`n  $Game`nGive the folder Mako was built into." }
if (-not (Test-Path (Join-Path $Game ".hookshot_exefs")) -or -not (Test-Path (Join-Path $Game "romfs"))) {
    Stop-With "This folder does not keep its game files (.hookshot_exefs, romfs), so it cannot be built again.`nBuild Mako into a folder once with the Mako builder first, then run this."
}
if (Get-Process -Name "hookshot", "Mako Launcher" -ErrorAction SilentlyContinue) { Stop-With "Close the game and the Mako launcher first." }
$Game = (Resolve-Path $Game).Path

# ---- the tools: the Mako builder's, else the source folder's own ----
if (-not $Tools) {
    $vf = Join-Path $Game "hookshot_version.txt"
    if (Test-Path $vf) {
        $line = Get-Content $vf | Where-Object { $_ -like "builder=*" } | Select-Object -First 1
        if ($line) {
            $builder = $line.Substring(8).Trim()
            $beside = Join-Path (Split-Path -Parent $builder) "tools"
            if ((Test-Path $builder) -and (Test-Path (Join-Path $beside "nx2\make_game.py"))) { $Tools = $beside }
        }
    }
}
if (-not $Tools -and $Source -and (Test-Path (Join-Path $Source "llvm-mingw\bin\clang.exe"))) { $Tools = $Source }
if (-not $Tools) {
    Stop-With ("The Mako builder that made this folder was not found, and its tools are needed to build.`n" +
               "Run this again with -Tools `"<the builder's folder>\tools`" (the folder with nx2, python and llvm-mingw in it).")
}
$Tools = (Resolve-Path $Tools).Path
$python = Join-Path $Tools "python\python.exe"
if (-not (Test-Path $python)) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) { Stop-With "No Python: not in $Tools\python, and none on this PC." }
    $python = $found.Source
}
Say "Game folder: $Game"
Say "Tools:       $Tools"
Say "Python:      $python"

# ---- the fork's source ----
$work = Join-Path $env:TEMP "mako-randomizer-install"
if ($Source) {
    $src = (Resolve-Path $Source).Path
} else {
    if (Test-Path $work) { Remove-Item -Recurse -Force $work }
    New-Item -ItemType Directory -Force $work | Out-Null
    $zip = Join-Path $work "source.zip"
    $url = "https://github.com/$Repo/archive/$Ref.zip"
    Say "Downloading the source: $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"
    try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing } catch { Stop-With "The source could not be downloaded:`n  $($_.Exception.Message)" }
    Expand-Archive -Path $zip -DestinationPath (Join-Path $work "src") -Force
    $src = (Get-ChildItem (Join-Path $work "src") -Directory | Select-Object -First 1).FullName
}
if (-not (Test-Path (Join-Path $src "nx2\make_game.py")) -or -not (Test-Path (Join-Path $src "tools\rando\rando_seed.py"))) {
    Stop-With "That is not the fork's source (no nx2\make_game.py or tools\rando\rando_seed.py in it):`n  $src"
}
Say "Source:      $src"

# ---- the build: the folder's own compiler, headers and libraries, as the builder gives them ----
$env:PYTHONIOENCODING = "utf-8"
foreach ($pair in @(@("HOOKSHOT_MINGW", "llvm-mingw"), @("EMSDK", "emsdk"), @("RX_CPM", "cpm"), @("WGPU_NATIVE", "wgpu-native"))) {
    $path = Join-Path $Tools $pair[1]
    if (Test-Path $path) { Set-Item -Path ("Env:" + $pair[0]) -Value $path }
}
Say "Building the game folder again (this takes a while; saves and settings are kept)..."
& $python -I (Join-Path $src "nx2\make_game.py") --update $Game
if ($LASTEXITCODE -ne 0) { Stop-With "The build failed (exit code $LASTEXITCODE). The game folder may be half built: run the Mako builder on it to put it back." }

# ---- the launcher ----
Say "Building the launcher..."
& (Join-Path $src "launcher\build.ps1") | Out-Null
$launcher = Join-Path $src "launcher\Mako Launcher.exe"
if (-not (Test-Path $launcher)) { Stop-With "The launcher was not built." }
Copy-Item $launcher (Join-Path $Game "Mako Launcher.exe") -Force

# ---- what the randomizer needs at Play ----
$note = ""
$own = Get-Command python -ErrorAction SilentlyContinue
if (-not $own) { $note = "The randomizer needs Python 3 (python.org), then:  python -m pip install zstandard" }
else {
    & $own.Source -c "import zstandard" 2>$null
    if ($LASTEXITCODE -ne 0) { $note = "The randomizer needs one Python package:  python -m pip install zstandard" }
}
if (-not $Source -and (Test-Path $work)) { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
Write-Host ""
Write-Host "Done. Start the game with Mako Launcher.exe in:" -ForegroundColor Green
Write-Host "  $Game"
if ($note) { Write-Host $note -ForegroundColor Yellow }
Write-Host "Do not press the launcher's Update button: it installs the original Mako over this fork." -ForegroundColor Yellow
