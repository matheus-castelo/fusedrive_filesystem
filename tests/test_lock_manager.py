import threading
import time
import pytest
from src.infrastructure.concurrency.lock_manager import LockManager
from src.monitoring.metrics.metrics import MetricsRegistry


@pytest.fixture
def metrics():
    registry = MetricsRegistry()
    registry.reset()
    return registry


@pytest.fixture
def lock_manager(metrics):
    return LockManager(metrics)


def test_shared_locks_concurrent(lock_manager):
    results = []
    with lock_manager.shared_lock("file_1"):
        results.append(1)
        with lock_manager.shared_lock("file_1"):
            results.append(2)
    assert results == [1, 2]


def test_exclusive_lock_blocks_shared(lock_manager):
    results = []

    def try_read():
        with lock_manager.shared_lock("file_2"):
            results.append("read")

    event = threading.Event()

    def exclusive_holder():
        with lock_manager.exclusive_lock("file_2"):
            event.set()
            time.sleep(0.3)

    t1 = threading.Thread(target=exclusive_holder)
    t1.start()

    event.wait(timeout=1.0)

    t2 = threading.Thread(target=try_read)
    t2.start()

    time.sleep(0.1)
    assert len(results) == 0  # Read was blocked

    t1.join()
    t2.join(timeout=1.0)
    assert len(results) == 1


def test_shared_blocks_exclusive(lock_manager):
    results = []
    event = threading.Event()

    def shared_holder():
        with lock_manager.shared_lock("file_4"):
            event.set()
            time.sleep(0.3)

    def try_write():
        with lock_manager.exclusive_lock("file_4"):
            results.append("write")

    t1 = threading.Thread(target=shared_holder)
    t1.start()
    event.wait(timeout=1.0)

    t2 = threading.Thread(target=try_write)
    t2.start()

    time.sleep(0.1)
    assert len(results) == 0

    t1.join()
    t2.join(timeout=1.0)
    assert len(results) == 1


def test_lock_manager_eviction(lock_manager):
    with lock_manager.shared_lock("file_5"):
        assert "file_5" in lock_manager._locks

    assert "file_5" not in lock_manager._locks


def test_metrics_active_locks(lock_manager, metrics):
    with lock_manager.exclusive_lock("file_6"):
        assert metrics.get("active_locks") == 1
    assert metrics.get("active_locks") == 0
