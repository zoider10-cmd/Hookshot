"""Check shared guide PNGs and, optionally, review their UI-source fingerprints.

Offline, standard library only; never builds or runs the game or downloads sources.
Default: validate manifest paths, PNG signature/IHDR dimensions and SHA-256.
--review-sources: compare the recorded review hashes with the working source files;
Hookshot uses --root, HookshotLauncher uses --launcher-source when supplied.
A missing external checkout is explicitly NOT CHECKED, not a passed source review.
This check never updates capture provenance or stamps a human review automatically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
GUIDE = Path('docs/images/guide')
HOOKSHOT = 'https://git.magicbean.dev/MagicBeanDev/Hookshot'
LAUNCHER = 'https://git.magicbean.dev/MagicBeanDev/HookshotLauncher'
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
PNG = b'\x89PNG\r\n\x1a\n'


def safe_path(root, name, basename=False):
    """Reject platform-dependent paths and symlinks escaping the selected checkout."""
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or '\0' in name
            or any(part in ('', '.', '..') for part in name.split('/'))
            or (basename and '/' in name)):
        raise ValueError('unsafe relative path: ' + repr(name))
    root = root.resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('path escapes its root: ' + name)
    return target


def digest(value):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError('expected a lowercase SHA-256 fingerprint')
    return value


def hashes(value, root):
    if not isinstance(value, dict) or not value:
        raise ValueError('source files must be a nonempty path-to-SHA-256 map')
    for name, expected in value.items():
        safe_path(root, name)
        digest(expected)
    return value


def png_size(data):
    if len(data) < 33 or data[:8] != PNG or data[8:16] != b'\0\0\0\rIHDR':
        raise ValueError('not a PNG with a complete IHDR header')
    if zlib.crc32(data[12:29]) != struct.unpack('>I', data[29:33])[0]:
        raise ValueError('invalid PNG IHDR checksum')
    width, height = struct.unpack('>II', data[16:24])
    if not (0 < width < 2**31 and 0 < height < 2**31):
        raise ValueError('invalid PNG dimensions')
    return width, height


def check(root, review_sources=False, launcher_source=None):
    root = Path(root).resolve()
    launcher_source = Path(launcher_source).resolve() if launcher_source is not None else None
    errors, notices = [], []
    try:
        manifest = json.loads((root / GUIDE / 'manifest.json').read_text(encoding='utf-8'))
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1):
            raise ValueError('unsupported manifest schema_version')
        entries = manifest.get('screenshots')
        if not isinstance(entries, list) or not entries:
            raise ValueError('screenshots must be a nonempty list')
    except (OSError, ValueError) as exc:
        return [f'manifest: {exc}'], notices
    seen = set()
    for entry in entries:
        name = entry.get('file', '(unnamed screenshot)') if isinstance(entry, dict) else '(invalid screenshot)'
        try:
            if not isinstance(entry, dict):
                raise ValueError('screenshot entry must be an object')
            image = safe_path(root / GUIDE, name, basename=True)
            if not name.endswith('.png'):
                raise ValueError('guide screenshots must be PNG files')
            if name in seen:
                raise ValueError('duplicate screenshot filename')
            seen.add(name)
            expected_size = (entry.get('width'), entry.get('height'))
            if any(type(n) is not int or n <= 0 for n in expected_size):
                raise ValueError('width and height must be positive integers')
            data = image.read_bytes()
            actual_size = png_size(data)
            if actual_size != expected_size:
                raise ValueError(f'PNG dimensions {actual_size} differ from manifest {expected_size}')
            if hashlib.sha256(data).hexdigest() != digest(entry.get('sha256')):
                raise ValueError('PNG SHA-256 differs from manifest')
            source = entry.get('reviewed_source')
            if not isinstance(source, dict) or not isinstance(source.get('revision'), str) or not source['revision']:
                raise ValueError('reviewed_source must name its reviewed revision')
            repository = source.get('repository')
            if repository not in (HOOKSHOT, LAUNCHER):
                raise ValueError('unrecognized reviewed_source repository')
            source_root = root if repository == HOOKSHOT else launcher_source
            # Validate paths/hashes even when an external checkout is not available.
            files = hashes(source.get('files'), source_root or root)
            fixture_files = hashes(entry['fixture_files'], root) if 'fixture_files' in entry else {}
            fixture_inputs = {
                'menu-fixture': {'scripts/screenshots/menu.cpp', 'scripts/screenshots/capture_menu.py'},
                'launcher-fixture': {'scripts/screenshots/LauncherCapture.cs', 'scripts/screenshots/capture_launcher.py',
                                     'scripts/screenshots/launcher-packages.lock.json'},
            }
            if entry.get('kind') in fixture_inputs:
                required = fixture_inputs[entry['kind']]
                if not required.issubset(fixture_files):
                    raise ValueError(entry['kind'] + ' must fingerprint its capture source and dependencies in fixture_files')
            notices.append(f'ASSET OK: {name} ({actual_size[0]}x{actual_size[1]})')
            if review_sources:
                if source_root is None:
                    notices.append(f'NOT CHECKED: {name}: Launcher UI sources; supply --launcher-source CHECKOUT')
                else:
                    for filename, expected in files.items():
                        try:
                            actual = hashlib.sha256(safe_path(source_root, filename).read_bytes()).hexdigest()
                        except OSError as exc:
                            errors.append(f'REVIEW REQUIRED: {name}: {filename}: {exc}')
                            continue
                        if actual != expected:
                            errors.append(f'REVIEW REQUIRED: {name}: {filename} changed since reviewed revision {source["revision"]}')
                for filename, expected in fixture_files.items():
                    try:
                        actual = hashlib.sha256(safe_path(root, filename).read_bytes()).hexdigest()
                    except OSError as exc:
                        errors.append(f'REVIEW REQUIRED: {name}: fixture {filename}: {exc}')
                        continue
                    if actual != expected:
                        errors.append(f'REVIEW REQUIRED: {name}: fixture {filename} changed')
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'{name}: {exc}')
    if not review_sources:
        notices.append('NOT CHECKED: UI-source drift (use --review-sources). Asset integrity does not establish UI freshness.')
    return errors, notices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Hookshot checkout (default: this script\'s checkout)')
    parser.add_argument('--review-sources', action='store_true', help='flag changed UI/fixture files for human review')
    parser.add_argument('--launcher-source', type=Path, help='local HookshotLauncher checkout to review; never downloaded')
    args = parser.parse_args()
    if args.launcher_source is not None and not args.review_sources:
        parser.error('--launcher-source requires --review-sources')
    errors, notices = check(args.root, args.review_sources, args.launcher_source)
    for line in notices + errors:
        print(line)
    if errors:
        print(f'Guide screenshot check failed: {len(errors)} issue(s). Review the affected UI and guide before updating review hashes.')
        return 1
    if any(line.startswith('NOT CHECKED:') for line in notices):
        print('Guide screenshot checks passed for the inputs checked above; NOT CHECKED items remain outstanding.')
    else:
        print('Guide screenshot integrity and all recorded UI/fixture source checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
