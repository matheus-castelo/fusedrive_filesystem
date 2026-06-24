import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict
from src.monitoring.metrics.metrics import MetricsRegistry


class DeadlockError(Exception):
    pass


class RWLock:
    def __init__(self):
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writers = 0
        self._write_requests = 0

    def acquire_read(self):
        with self._condition:
            while self._writers > 0 or self._write_requests > 0:
                self._condition.wait()
            self._readers += 1

    def release_read(self):
        with self._condition:
            self._readers -= 1
            if self._readers == 0:
                self._condition.notify_all()

    def acquire_write(self):
        with self._condition:
            self._write_requests += 1
            while self._readers > 0 or self._writers > 0:
                self._condition.wait()
            self._write_requests -= 1
            self._writers += 1

    def release_write(self):
        with self._condition:
            self._writers -= 1
            self._condition.notify_all()


class LockManager:
    def __init__(self, metrics: MetricsRegistry):
        self.metrics = metrics
        self._locks: Dict[str, RWLock] = {}
        self._refs: Dict[str, int] = {}

        self._allocations = defaultdict(lambda: defaultdict(int))
        self._waiting: Dict[int, str] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, key: str) -> RWLock:
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = RWLock()
                self._refs[key] = 0
            self._refs[key] += 1
            return self._locks[key]

    def _release_ref(self, key: str):
        with self._global_lock:
            self._refs[key] -= 1
            if self._refs[key] <= 0:
                del self._locks[key]
                del self._refs[key]

    def has_lock(self, key: str) -> bool:
        with self._global_lock:
            return key in self._locks

    def _detect_cycle(self, start_thread_id: int, target_lock: str, is_write: bool):
        visited_threads = set()
        visited_locks = set()
        stack = [target_lock]

        while stack:
            current_lock = stack.pop()
            if current_lock in visited_locks:
                continue
            visited_locks.add(current_lock)

            owners = self._allocations.get(current_lock, {})
            for owner, count in owners.items():
                if count > 0 and owner == start_thread_id:
                    if current_lock == target_lock and not is_write:

                        continue
                    raise DeadlockError(
                        f"Deadlock detectado: Thread {start_thread_id } bloqueada no lock {target_lock }"
                    )

                if count > 0 and owner not in visited_threads:
                    visited_threads.add(owner)
                    waiting_for = self._waiting.get(owner)
                    if waiting_for:
                        stack.append(waiting_for)

    @contextmanager
    def shared_lock(self, key: str):
        lock = self._get_lock(key)
        tid = threading.get_ident()

        try:
            with self._global_lock:
                self._detect_cycle(tid, key, is_write=False)
                self._waiting[tid] = key
        except DeadlockError:
            self.metrics.inc("deadlocks_detected")
            self._release_ref(key)
            raise

        try:
            lock.acquire_read()
            self.metrics.inc("active_locks")
            try:
                with self._global_lock:
                    self._waiting.pop(tid, None)
                    self._allocations[key][tid] += 1
                yield
            finally:
                with self._global_lock:
                    self._allocations[key][tid] -= 1
                    if self._allocations[key][tid] <= 0:
                        del self._allocations[key][tid]
                self.metrics.add("active_locks", -1)
                lock.release_read()
        finally:
            with self._global_lock:
                self._waiting.pop(tid, None)
            self._release_ref(key)

    @contextmanager
    def exclusive_lock(self, key: str):
        lock = self._get_lock(key)
        tid = threading.get_ident()

        try:
            with self._global_lock:
                self._detect_cycle(tid, key, is_write=True)
                self._waiting[tid] = key
        except DeadlockError:
            self.metrics.inc("deadlocks_detected")
            self._release_ref(key)
            raise

        try:
            lock.acquire_write()
            self.metrics.inc("active_locks")
            try:
                with self._global_lock:
                    self._waiting.pop(tid, None)
                    self._allocations[key][tid] += 1
                yield
            finally:
                with self._global_lock:
                    self._allocations[key][tid] -= 1
                    if self._allocations[key][tid] <= 0:
                        del self._allocations[key][tid]
                self.metrics.add("active_locks", -1)
                lock.release_write()
        finally:
            with self._global_lock:
                self._waiting.pop(tid, None)
            self._release_ref(key)
