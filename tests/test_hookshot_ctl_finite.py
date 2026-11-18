"""CLI floats must reject non-finite values before opening the control bridge.

Game-free: python -I -B tests/test_hookshot_ctl_finite.py
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class FiniteCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ctl-finite-")
        self.addCleanup(self.tmp.cleanup)
        env = {"HOME": self.tmp.name, "TMPDIR": self.tmp.name, "TEMP": self.tmp.name,
               "TMP": self.tmp.name, "XDG_CONFIG_HOME": self.tmp.name, "XDG_DATA_HOME": self.tmp.name,
               "XDG_CACHE_HOME": self.tmp.name, "XDG_RUNTIME_DIR": self.tmp.name}
        self.environment = mock.patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.no_socket = mock.patch("socket.socket", side_effect=AssertionError("real socket forbidden"))
        self.no_socket.start()
        self.addCleanup(self.no_socket.stop)
        spec = importlib.util.spec_from_file_location("ctl_finite", ROOT / "scripts" / "hookshot_ctl.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main(["--sock", "never-open", "--json", *argv])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_nonfinite_rejected_before_connect(self):
        commands = [(["wait", "in_play"], "--timeout"), (["press", "A"], "--timeout"),
                    (["stick", "L", "0", "1"], "--timeout"), (["sequence", "0:A/8"], "--timeout"),
                    (["shot"], "--timeout"), (["teleport", "1"], "--timeout"),
                    (["age", "adult"], "--timeout"), (["teleport", "1"], "--arrive"),
                    (["age", "adult"], "--arrive")]
        for command, flag in commands:
            for value in ("nan", "inf", "-inf", "1e999"):
                with self.subTest(command=command, flag=flag, value=value):
                    with mock.patch.object(self.m, "connect", side_effect=self.m.Failed("I/O reached", 9)) as connect:
                        code, out, err = self.invoke([*command, flag + "=" + value])
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, "")
                    self.assertIn("finite", err)
                    connect.assert_not_called()
        for axis in (0, 1):
            for value in ("nan", "inf", "1e999"):
                xy = ["0", "1"]
                xy[axis] = value
                with self.subTest(axis=axis, value=value):
                    with mock.patch.object(self.m, "connect", side_effect=self.m.Failed("I/O reached", 9)) as connect:
                        code, out, err = self.invoke(["stick", "L", *xy])
                    self.assertEqual(code, 2, err)
                    self.assertIn("finite", err)
                    connect.assert_not_called()

    def test_finite_values_keep_request_routing(self):
        for command in (["wait", "in_play"], ["press", "A"], ["stick", "l", "-1", "1"],
                        ["sequence", "0:A/8"], ["shot"], ["teleport", "1"], ["age", "adult"]):
            for value in ("0", "-1", "0.25", "120"):
                with self.subTest(command=command, value=value):
                    bridge = mock.Mock()
                    bridge.request.return_value = {"ok": True}
                    with mock.patch.object(self.m, "connect", return_value=bridge):
                        code, out, err = self.invoke([*command, "--timeout=" + value])
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(bridge.request.call_args.kwargs["timeout"], float(value))
                    self.assertEqual(bridge.request.call_args.args[0], command[0])
                    bridge.close.assert_called_once()
        for command, event in ((["teleport", "1"], "map"), (["age", "adult"], "loading_end")):
            bridge = mock.Mock()
            bridge.request.side_effect = [{"ok": True, "sent": True, "map": "test"}, {"ok": True}]
            with mock.patch.object(self.m, "connect", return_value=bridge):
                self.assertEqual(self.invoke([*command, "--arrive", "0.25"])[0], 0)
            self.assertEqual(bridge.request.call_args.kwargs["timeout"], 0.25)
            self.assertEqual(bridge.request.call_args.kwargs["event"], event)

    def test_watch_integer_validation_and_normal_routing(self):
        for flag in ("--every", "--count"):
            with mock.patch.object(self.m, "connect") as connect:
                code, out, err = self.invoke(["watch", flag, "nan"])
            self.assertEqual(code, 2)
            connect.assert_not_called()
        bridge = mock.Mock()
        bridge.request.return_value = {"ok": True}
        bridge.line.return_value = {"event": "present", "frame": 1}
        with mock.patch.object(self.m, "connect", return_value=bridge):
            self.assertEqual(self.invoke(["watch", "--every", "6", "--count", "1"])[0], 0)
        self.assertEqual(bridge.request.call_args.args, ("subscribe",))
        self.assertEqual(bridge.request.call_args.kwargs["every"], 6)
        bridge.line.assert_called_once_with(86400)
        bridge.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
