"""Offline guide screenshot integrity, safe paths and UI drift checks; no game or image libraries needed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guide_screenshots', ROOT / 'scripts/check_guide_screenshots.py')
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (guide.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' + bytes(8))) + chunk(b'IEND', b''))


class Screenshots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / guide.GUIDE
        self.assets.mkdir(parents=True)
        self.ui = self.root / 'gpu/vk/menu.cpp'
        self.ui.parent.mkdir(parents=True)
        self.ui.write_text('visible setting label\n')
        image = png()
        (self.assets / 'menu.png').write_bytes(image)
        self.entry = {'file': 'menu.png', 'width': 2, 'height': 1, 'sha256': hashlib.sha256(image).hexdigest(),
                      'reviewed_source': {'repository': guide.HOOKSHOT, 'revision': 'reviewed-commit',
                                          'files': {'gpu/vk/menu.cpp': hashlib.sha256(self.ui.read_bytes()).hexdigest()}}}

    def check(self, review=True, launcher=None):
        (self.assets / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'screenshots': [self.entry]}))
        return guide.check(self.root, review, launcher)

    def test_intact_sources_and_png(self):
        errors, notices = self.check()
        self.assertEqual(errors, [])
        self.assertIn('ASSET OK: menu.png (2x1)', notices)

    def test_changed_source_names_affected_screenshot_and_file(self):
        self.ui.write_text('renamed visible setting\n')
        errors, _ = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn('REVIEW REQUIRED: menu.png: gpu/vk/menu.cpp changed', errors[0])
        self.assertEqual(self.check(review=False)[0], [])  # asset checks do not claim UI review

    def test_external_source_absence_is_explicit(self):
        self.entry['reviewed_source']['repository'] = guide.LAUNCHER
        errors, notices = self.check()
        self.assertEqual(errors, [])
        self.assertTrue(any('NOT CHECKED: menu.png: Launcher UI sources' in n for n in notices))
        self.ui.write_text('new launcher UI\n')
        errors, _ = self.check(launcher=self.root)
        self.assertTrue(any('REVIEW REQUIRED: menu.png' in e for e in errors))

    def test_missing_source_requires_review(self):
        self.ui.unlink()
        self.assertTrue(any('REVIEW REQUIRED: menu.png: gpu/vk/menu.cpp' in e for e in self.check()[0]))

    def test_dimensions_and_fingerprints_are_checked(self):
        for field, value, message in [('width', 3, 'dimensions'), ('height', True, 'positive integers'),
                                      ('sha256', 'a' * 64, 'SHA-256 differs'), ('sha256', 'bad', 'SHA-256 fingerprint')]:
            with self.subTest(field=field, value=value):
                old = self.entry[field]
                self.entry[field] = value
                self.assertTrue(any(message in e for e in self.check()[0]))
                self.entry[field] = old

    def test_invalid_png_is_rejected_even_with_matching_digest(self):
        for payload in [b'not a PNG', png()[:29] + bytes(4) + png()[33:]]:
            (self.assets / 'menu.png').write_bytes(payload)
            self.entry['sha256'] = hashlib.sha256(payload).hexdigest()
            self.assertTrue(any('PNG' in e for e in self.check()[0]))

    def test_image_and_source_traversal_are_rejected(self):
        for name in ['../outside.png', '/outside.png', 'nested/menu.png', 'C:\\outside.png']:
            with self.subTest(name=name):
                self.entry['file'] = name
                self.assertTrue(any('unsafe relative path' in e for e in self.check()[0]))
        self.entry['file'] = 'menu.png'
        self.entry['reviewed_source']['files'] = {'../secret': 'a' * 64}
        self.assertTrue(any('unsafe relative path' in e for e in self.check()[0]))

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'private'
            target.write_text('outside')
            try:
                (self.root / 'escape').symlink_to(target)
            except OSError:
                self.skipTest('platform does not permit creating symlinks')
            self.entry['reviewed_source']['files'] = {'escape': 'a' * 64}
            self.assertTrue(any('path escapes its root' in e for e in self.check()[0]))

    def test_changed_fixture_requires_review(self):
        self.entry['fixture_files'] = {'gpu/vk/menu.cpp': '0' * 64}
        self.assertTrue(any('fixture gpu/vk/menu.cpp changed' in e for e in self.check()[0]))

    def test_missing_external_still_validates_manifest_paths(self):
        self.entry['reviewed_source']['repository'] = guide.LAUNCHER
        self.entry['reviewed_source']['files'] = {'../secret': 'a' * 64}
        self.assertTrue(any('unsafe relative path' in e for e in self.check()[0]))

    def test_menu_fixture_requires_both_capture_sources(self):
        self.entry['kind'] = 'menu-fixture'
        errors, _ = self.check(review=False)
        self.assertTrue(any('menu-fixture must fingerprint' in e for e in errors))

    def test_launcher_fixture_requires_source_and_package_lock(self):
        self.entry['kind'] = 'launcher-fixture'
        names = ['scripts/screenshots/LauncherCapture.cs', 'scripts/screenshots/capture_launcher.py',
                 'scripts/screenshots/launcher-packages.lock.json']
        self.entry['fixture_files'] = {name: 'a' * 64 for name in names}
        self.assertEqual(self.check(review=False)[0], [])
        for name in names:
            with self.subTest(missing=name):
                del self.entry['fixture_files'][name]
                self.assertTrue(any('launcher-fixture must fingerprint' in e for e in self.check(review=False)[0]))
                self.entry['fixture_files'][name] = 'a' * 64

    def test_review_never_rewrites_capture_or_review_records(self):
        self.entry['captured_source'] = {'revision': 'original-release'}
        self.ui.write_text('changed later\n')
        self.check()
        manifest = self.assets / 'manifest.json'
        before = manifest.read_bytes()
        guide.check(self.root, review_sources=True)
        self.assertEqual(manifest.read_bytes(), before)

    def test_repository_assets(self):
        errors, notices = guide.check(ROOT)
        self.assertEqual(errors, [])
        self.assertTrue(any('ASSET OK:' in n for n in notices))
        self.assertTrue(any('NOT CHECKED: UI-source drift' in n for n in notices))


if __name__ == '__main__':
    unittest.main()
