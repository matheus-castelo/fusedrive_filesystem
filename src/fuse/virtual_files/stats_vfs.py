import os
import stat
import time
import errno
from fuse import FuseOSError

from src.monitoring.metrics.metrics import MetricsRegistry


class StatsVFS:
    def __init__(self, metrics: MetricsRegistry, lock_manager=None):
        self.metrics = metrics
        self.lock_manager = lock_manager
        self.supported_keys = [
            "cache_hits",
            "cache_misses",
            "cache_evictions",
            "downloads",
            "uploads",
            "bytes_read",
            "bytes_written",
            "active_locks",
            "deadlocks_detected",
            "cache_memory_usage",
            "thread_pool_tasks",
            "upload_queue_size",
            "cache_size_bytes",
            "cache_size_chunks",
            "api_requests",
            "bytes_downloaded",
            "bytes_from_cache",
            "trigger_deadlock",
        ]

    def _get_val_str(self, key: str) -> bytes:
        val = self.metrics.get(key)
        return f"{key :<20}: {val }\n".encode("utf-8")

    def getattr(self, path: str):
        if path == "/stats":
            return {
                "st_mode": (stat.S_IFDIR | 0o555),
                "st_nlink": 2,
                "st_size": 0,
                "st_ctime": time.time(),
                "st_mtime": time.time(),
                "st_atime": time.time(),
            }

        basename = os.path.basename(path)
        if basename in self.supported_keys:
            val_bytes = self._get_val_str(basename)
            return {
                "st_mode": (stat.S_IFREG | 0o444),
                "st_nlink": 1,
                "st_size": len(val_bytes),
                "st_ctime": time.time(),
                "st_mtime": time.time(),
                "st_atime": time.time(),
            }

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path: str):
        if path == "/stats":
            return [".", ".."] + self.supported_keys
        raise FuseOSError(errno.ENOENT)

    def read(self, path: str, length: int, offset: int) -> bytes:
        basename = os.path.basename(path)
        if basename == "trigger_deadlock":
            if offset == 0:
                if self.lock_manager:
                    import threading
                    import time
                    from src.infrastructure.concurrency.lock_manager import (
                        DeadlockError,
                    )

                    def t1():
                        try:
                            with self.lock_manager.exclusive_lock("fake_A"):
                                time.sleep(0.5)
                                with self.lock_manager.exclusive_lock("fake_B"):
                                    pass
                        except DeadlockError:
                            pass

                    def t2():
                        try:
                            with self.lock_manager.exclusive_lock("fake_B"):
                                time.sleep(0.5)
                                with self.lock_manager.exclusive_lock("fake_A"):
                                    pass
                        except DeadlockError:
                            pass

                    th1 = threading.Thread(target=t1)
                    th2 = threading.Thread(target=t2)
                    th1.start()
                    th2.start()
                    th1.join()
                    th2.join()
                val_bytes = b"Deadlock forcado no FUSE VFS!\n"
            else:
                val_bytes = b""
            return val_bytes[offset : offset + length]

        if basename in self.supported_keys:
            val_bytes = self._get_val_str(basename)
            return val_bytes[offset : offset + length]
        raise FuseOSError(errno.ENOENT)
