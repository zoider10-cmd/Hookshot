#!/usr/bin/env python3
"""Render real Launcher views in memory using synthetic state; no desktop or game needed."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BUILD_CONFIG = ('Directory.Build.props', 'Directory.Build.targets', 'Directory.Packages.props', 'NuGet.Config')


def capture_inputs(tracked):
    missing = set(BUILD_CONFIG) - set(tracked)
    if missing:
        raise ValueError('Launcher capture requires tracked build configuration: ' + ', '.join(sorted(missing)))
    return sorted(f for f in tracked if f.startswith(('App/', 'Core/')) or f in BUILD_CONFIG)


@contextmanager
def example_state(path):
    # A stable, neutral path is visible in the real views. Never reuse or remove
    # an existing directory: another capture or a user's data may own it.
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path, help='clean HookshotLauncher source checkout')
    p.add_argument('--version', required=True, help='Launcher release tag matching the source revision')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--dotnet', default='dotnet', help='.NET 10 SDK executable')
    a = p.parse_args()
    source, output = a.source.resolve(), a.output.resolve()
    tracked = run(['git', '-C', str(source), 'ls-files'], capture_output=True).stdout.splitlines()
    try:
        inputs = capture_inputs(tracked)
    except ValueError as exc:
        p.error(str(exc))
    if run(['git', '-C', str(source), 'diff', '--name-only', 'HEAD', '--', *inputs], capture_output=True).stdout:
        p.error('Launcher capture inputs must match the named clean source revision')
    hashes = {f: hashlib.sha256((source / f).read_bytes()).hexdigest() for f in inputs}
    revision = run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True).stdout.strip()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hookshot-launcher-capture-') as tmp:
        stage = Path(tmp)
        for f in inputs:
            target = stage / f
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / f, target)
        # Keep all maintained rendering, labels, bindings and transfer logic intact.
        # Disable discovery in the disposable copy only, before constructing the UI.
        wizard = stage / 'App/ViewModels/WizardViewModel.cs'
        old = '        StartSearch();'
        if wizard.read_text().count(old) != 1:
            p.error('Launcher source changed: review the fixture discovery suppression')
        wizard.write_text(wizard.read_text().replace(old, '        searching = false; // UI capture: no game-file discovery.'))
        old = 'SystemRequirements.Check(job.InstallDir)'
        if wizard.read_text().count(old) != 1:
            p.error('Launcher source changed: review the fixture requirements input')
        wizard.write_text(wizard.read_text().replace(old,
            'SystemRequirements.Evaluate(true, 16, 12, true, true, 100L << 30, new[] { new GpuRequirement(true, 8UL << 30, true) })'))
        fixture = stage / 'Capture'
        fixture.mkdir()
        shutil.copyfile(Path(__file__).with_name('LauncherCapture.cs'), fixture / 'LauncherCapture.cs')
        package_lock = Path(__file__).with_name('launcher-packages.lock.json')
        if not package_lock.is_file():
            p.error('missing launcher-packages.lock.json; restore the reviewed fixture dependency lock')
        shutil.copyfile(package_lock, fixture / 'packages.lock.json')
        (fixture / 'Capture.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><ManagePackageVersionsCentrally>false</ManagePackageVersionsCentrally></PropertyGroup>
  <ItemGroup><ProjectReference Include="../App/HookshotLauncher.csproj"/>
    <PackageReference Include="Avalonia.Headless" Version="[12.1.6]"/>
  </ItemGroup>
</Project>
''')
        env = dict(os.environ, DOTNET_CLI_HOME=str(stage / 'dotnet-home'), DOTNET_CLI_TELEMETRY_OPTOUT='1',
                   DOTNET_GENERATE_ASPNET_CERTIFICATE='false',
                   NUGET_PACKAGES='/tmp/hookshot-guide-nuget')
        # Preserve both the Launcher's AvaloniaStats opt-out target and its feed
        # policy. Explicit config excludes ambient machine/user NuGet sources.
        restore_options = ['--locked-mode', '--configfile', str(stage / 'NuGet.Config')]
        run([a.dotnet, 'restore', str(stage / 'App/HookshotLauncher.csproj'), *restore_options], env=env)
        run([a.dotnet, 'restore', str(fixture / 'Capture.csproj'), *restore_options], env=env)
        shutil.copyfile(fixture / 'packages.lock.json', output / 'launcher-packages.lock.json')
        run([a.dotnet, 'build', str(fixture / 'Capture.csproj'), '--no-restore', '-c', 'Release', '-p:HookshotTag=' + a.version], env=env)
        with example_state(Path(tempfile.gettempdir()) / 'hookshot-guide-example') as state:
            run([a.dotnet, str(fixture / 'bin/Release/net10.0/Capture.dll'), str(state), str(output)], env=env)
    metadata = {'source_revision': revision, 'launcher_version': a.version, 'source_files': hashes,
                'fixture_files': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in
                                  ('scripts/screenshots/LauncherCapture.cs', 'scripts/screenshots/capture_launcher.py')},
                'framework': 'Avalonia.Headless 12.1.6 with Skia; maintained views/view models',
                'source_adapter': 'Only in temporary build: suppress FilesStepViewModel StartSearch(); replace host requirements probe with maintained Evaluate() on explicit illustrative 16 GB RAM, 12 threads, AVX2, 100 GB free, Vulkan 1.3/8 GB VRAM/mesh inputs. UI labels and layout unchanged.',
                'state': 'Synthetic build marker, empty file selector, text-only import/target fixture; real confirmation dry run only.',
                'sdk': run([a.dotnet, '--version'], capture_output=True).stdout.strip(),
                'images': {f: hashlib.sha256((output / f).read_bytes()).hexdigest() for f in
                           ('launcher-home.png', 'launcher-saves.png', 'launcher-import.png',
                            'launcher-manage-saves.png', 'launcher-game-files.png', 'launcher-import-confirm.png')}}
    metadata['fixture_files']['scripts/screenshots/launcher-packages.lock.json'] = hashlib.sha256(package_lock.read_bytes()).hexdigest()
    (output / 'launcher-capture.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    main()
