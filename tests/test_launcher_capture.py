"""Capture isolation and build-policy regressions; no .NET SDK or Launcher needed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('launcher_capture', ROOT / 'scripts/screenshots/capture_launcher.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class LauncherCapture(unittest.TestCase):
    def test_build_policy_is_in_staged_and_fingerprinted_inputs(self):
        files = ['App/App.axaml', 'Core/Saves.cs', 'Directory.Build.props', 'Directory.Build.targets',
                 'Directory.Packages.props', 'NuGet.Config']
        self.assertEqual(capture.capture_inputs(files + ['Tests/Test.cs', 'README.md']), sorted(files))

    def test_missing_telemetry_or_feed_policy_stops_capture(self):
        for missing in ('Directory.Build.targets', 'NuGet.Config'):
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, missing):
                capture.capture_inputs([f for f in capture.BUILD_CONFIG if f != missing])

    def test_existing_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'hookshot-guide-example'
            state.mkdir()
            sentinel = state / 'keep.txt'
            sentinel.write_text('pre-existing data')
            with self.assertRaises(FileExistsError):
                with capture.example_state(state):
                    self.fail('existing state must not be used')
            self.assertEqual(sentinel.read_text(), 'pre-existing data')

    def test_owned_state_is_cleaned_after_failed_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'hookshot-guide-example'
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                with capture.example_state(state) as reserved:
                    self.assertEqual(reserved, state)
                    (state / 'fixture.txt').write_text('synthetic')
                    raise RuntimeError('capture failed')
            self.assertFalse(state.exists())


if __name__ == '__main__':
    unittest.main()
