import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from civora.locking import LockTimeoutError, ProcessFileLock
from civora.persistence import AtomicJsonStore


class ProcessFileLockTests(unittest.TestCase):
    def test_current_process_is_reported_alive(self):
        self.assertTrue(ProcessFileLock._pid_alive(os.getpid()))

    def test_impossible_process_is_reported_dead(self):
        self.assertFalse(ProcessFileLock._pid_alive(99999999))

    def test_exclusive_acquisition_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            with ProcessFileLock(path, timeout=0.1):
                self.assertTrue(path.exists())
                with self.assertRaises(LockTimeoutError):
                    ProcessFileLock(path, timeout=0.02, poll_interval=0.005).acquire()
            self.assertFalse(path.exists())

    def test_abandoned_same_host_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            path.write_text(json.dumps({
                "token": "abandoned",
                "pid": 99999999,
                "hostname": socket.gethostname(),
                "acquired_at": time.time() - 3600,
            }), encoding="utf-8")
            old = time.time() - 3600
            os.utime(path, (old, old))
            with ProcessFileLock(path, timeout=0.1, poll_interval=0.005, stale_after=1.0):
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())

    def test_foreign_host_lock_is_not_broken(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            path.write_text(json.dumps({
                "token": "foreign",
                "pid": 99999999,
                "hostname": "other-host",
                "acquired_at": time.time() - 3600,
            }), encoding="utf-8")
            old = time.time() - 3600
            os.utime(path, (old, old))
            with self.assertRaises(LockTimeoutError):
                ProcessFileLock(path, timeout=0.02, poll_interval=0.005, stale_after=1.0).acquire()
            self.assertTrue(path.exists())

    def test_release_does_not_delete_replaced_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.lock"
            lock = ProcessFileLock(path, timeout=0.1).acquire()
            path.write_text(json.dumps({
                "token": "replacement",
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": time.time(),
            }), encoding="utf-8")
            lock.release()
            self.assertTrue(path.exists())


class AtomicJsonStoreLockTests(unittest.TestCase):
    def test_save_holds_lock_for_critical_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = AtomicJsonStore(path, schema_version=1)
            observations = []
            original = store._atomic_write

            def observe(target, payload):
                observations.append(store.lock_path.exists())
                original(target, payload)

            with patch.object(store, "_atomic_write", side_effect=observe):
                store.save({"value": 1})
            self.assertTrue(all(observations))
            self.assertFalse(store.lock_path.exists())


if __name__ == "__main__":
    unittest.main()
