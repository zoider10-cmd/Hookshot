"""Real Windows named-pipe busy, recovery, timeout and missing-pipe regression."""
import ctypes
from ctypes import wintypes
import importlib.util
import os
from pathlib import Path
import threading
import time
import unittest
from unittest import mock


@unittest.skipUnless(os.name == "nt", "Windows named pipes")
class WindowsPipeBusy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("ctl_pipe_test", Path(__file__).resolve().parents[1] / "scripts/hookshot_ctl.py")
        cls.ctl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ctl)
        cls.k = ctypes.WinDLL("kernel32", use_last_error=True)
        cls.k.CreateNamedPipeW.restype = wintypes.HANDLE
        cls.k.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        cls.k.CloseHandle.argtypes = [wintypes.HANDLE]
        cls.k.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        cls.k.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        cls.invalid = ctypes.c_void_p(-1).value

    def setUp(self):
        self.name = r"\\.\pipe\hookshot-busy-test-%d-%d" % (os.getpid(), time.monotonic_ns())
        self.server = self.k.CreateNamedPipeW(self.name, 3, 0, 1, 4096, 4096, 0, None)
        self.assertNotEqual(self.server, self.invalid)
        self.held = open(self.name, "r+b", buffering=0)
        self.assertFalse(self.k.ConnectNamedPipe(self.server, None))
        self.assertEqual(ctypes.get_last_error(), 535)  # already connected

    def tearDown(self):
        self.held.close()
        self.k.CloseHandle(self.server)

    def test_busy_timeout_and_recovery(self):
        start = time.monotonic()
        with self.assertRaises(self.ctl.Failed) as caught:
            self.ctl.Bridge(self.name, timeout=0.12)
        self.assertGreaterEqual(time.monotonic() - start, 0.1)
        self.assertEqual(caught.exception.__context__.winerror, 231)
        # Releasing the occupied server instance models the real bridge's rearm.
        def rearm():
            time.sleep(0.1)
            self.held.close()
            self.k.DisconnectNamedPipe(self.server)
            self.k.ConnectNamedPipe(self.server, None)
        thread = threading.Thread(target=rearm, daemon=True)
        thread.start()
        try:
            bridge = self.ctl.Bridge(self.name, timeout=2)
            bridge.close()
        finally:
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_missing_pipe_fails_without_retry(self):
        start = time.monotonic()
        with self.assertRaises(self.ctl.Failed) as caught:
            self.ctl.Bridge(self.name + "-missing", timeout=2)
        self.assertEqual(caught.exception.__context__.winerror, 2)
        self.assertLess(time.monotonic() - start, 1)

    def test_access_denied_is_not_retried(self):
        class Call:
            def __init__(self):
                self.count = 0
            def __call__(self, *args):
                self.count += 1
                ctypes.set_last_error(5)  # simulated ERROR_ACCESS_DENIED
                return ctypes.c_void_p(-1).value
        kernel = mock.Mock()
        kernel.CreateFileW = Call()
        kernel.CloseHandle = Call()
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel):
            with self.assertRaises(OSError) as caught:
                self.ctl.open_windows_pipe(self.name, 2)
        self.assertEqual(caught.exception.winerror, 5)
        self.assertEqual(kernel.CreateFileW.count, 1)
        self.assertEqual(kernel.CloseHandle.count, 0)

    def test_handle_closed_if_fd_conversion_fails(self):
        import msvcrt
        self.held.close()
        self.k.DisconnectNamedPipe(self.server)
        listener = threading.Thread(target=lambda: self.k.ConnectNamedPipe(self.server, None), daemon=True)
        listener.start()
        with mock.patch.object(msvcrt, "open_osfhandle", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.ctl.open_windows_pipe(self.name, 2)
        listener.join(timeout=2)
        self.assertFalse(listener.is_alive())
        # A closed client gives the connected server a broken-pipe error.
        available = wintypes.DWORD()
        self.k.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                         wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        self.assertFalse(self.k.PeekNamedPipe(self.server, None, 0, None, ctypes.byref(available), None))
        self.assertEqual(ctypes.get_last_error(), 109)  # ERROR_BROKEN_PIPE

    def test_fd_cleanup_preserves_file_wrapper_failure(self):
        import errno
        import msvcrt
        original = msvcrt.open_osfhandle
        for closes_first in (False, True):
            with self.subTest(wrapper_closed_fd=closes_first):
                self.held.close()
                self.k.DisconnectNamedPipe(self.server)
                listener = threading.Thread(target=lambda: self.k.ConnectNamedPipe(self.server, None), daemon=True)
                listener.start()
                seen = []

                def remember(handle, flags):
                    fd = original(handle, flags)
                    seen.append(fd)
                    return fd

                def failed_wrapper(fd, *args, **kwargs):
                    if closes_first:
                        os.close(fd)
                    raise OSError("injected file wrapper failure")

                with mock.patch.object(msvcrt, "open_osfhandle", side_effect=remember), \
                        mock.patch.object(self.ctl.os, "fdopen", side_effect=failed_wrapper):
                    with self.assertRaisesRegex(OSError, "injected file wrapper failure"):
                        self.ctl.open_windows_pipe(self.name, 2)
                listener.join(timeout=2)
                self.assertFalse(listener.is_alive())
                self.assertEqual(len(seen), 1)
                with self.assertRaises(OSError) as caught:
                    os.fstat(seen[0])
                self.assertEqual(caught.exception.errno, errno.EBADF)


if __name__ == "__main__":
    unittest.main()
