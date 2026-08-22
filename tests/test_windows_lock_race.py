import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from civora.locking import ProcessFileLock


class WindowsDisappearingLockRaceTests(unittest.TestCase):
    def test_known_windows_contention_retries_when_lock_disappears_before_exists_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            original_open = os.open
            attempts = {"count": 0}

            def raced_open(*args, **kwargs):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise PermissionError(13, "transient windows contention")
                return original_open(*args, **kwargs)

            with patch("civora.locking.os.open", side_effect=raced_open), patch.object(
                ProcessFileLock, "_is_windows_lock_contention_error", return_value=True
            ):
                lock = ProcessFileLock(path, timeout=0.2, poll_interval=0.001).acquire()
                try:
                    self.assertTrue(path.exists())
                    self.assertGreaterEqual(attempts["count"], 2)
                finally:
                    lock.release()

    def test_errno_only_windows_eacces_gets_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            original_open = os.open
            attempts = {"count": 0}

            def raced_open(*args, **kwargs):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    exc = PermissionError(13, "transient errno-only contention")
                    exc.winerror = None
                    raise exc
                return original_open(*args, **kwargs)

            with patch("civora.locking.os.open", side_effect=raced_open), patch.object(
                ProcessFileLock, "_is_windows_lock_contention_error", return_value=False
            ), patch.object(
                ProcessFileLock, "_is_ambiguous_windows_eacces", return_value=True
            ):
                lock = ProcessFileLock(path, timeout=0.2, poll_interval=0.001).acquire()
                try:
                    self.assertTrue(path.exists())
                    self.assertEqual(attempts["count"], 2)
                finally:
                    lock.release()

    def test_persistent_errno_only_windows_eacces_fails_after_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            attempts = {"count": 0}

            def denied_open(*args, **kwargs):
                attempts["count"] += 1
                exc = PermissionError(13, "persistent permission denied")
                exc.winerror = None
                raise exc

            with patch("civora.locking.os.open", side_effect=denied_open), patch.object(
                ProcessFileLock, "_is_windows_lock_contention_error", return_value=False
            ), patch.object(
                ProcessFileLock, "_is_ambiguous_windows_eacces", return_value=True
            ):
                with self.assertRaises(PermissionError):
                    ProcessFileLock(path, timeout=0.2, poll_interval=0.001).acquire()
            self.assertEqual(attempts["count"], 3)

    def test_unknown_permission_error_without_lock_still_fails_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            with patch("civora.locking.os.open", side_effect=PermissionError(13, "denied")), patch.object(
                ProcessFileLock, "_is_windows_lock_contention_error", return_value=False
            ), patch.object(
                ProcessFileLock, "_is_ambiguous_windows_eacces", return_value=False
            ):
                with self.assertRaises(PermissionError):
                    ProcessFileLock(path, timeout=0.2, poll_interval=0.001).acquire()


if __name__ == "__main__":
    unittest.main()
