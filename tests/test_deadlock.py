import threading
import time
import pytest
from src.infrastructure.concurrency.lock_manager import LockManager, DeadlockError
from src.monitoring.metrics.metrics import MetricsRegistry


def test_deadlock_detection():
    metrics = MetricsRegistry()
    metrics.reset()
    manager = LockManager(metrics)

    barrier = threading.Barrier(2)
    exceptions = []

    def thread_1():
        try:
            with manager.exclusive_lock("lock_A"):
                barrier.wait(timeout=2)
                time.sleep(0.1)  # Ensure T2 acquires B and waits for A
                with manager.exclusive_lock("lock_B"):
                    pass
        except Exception as error:
            exceptions.append(error)

    def thread_2():
        try:
            with manager.exclusive_lock("lock_B"):
                barrier.wait(timeout=2)
                with manager.exclusive_lock("lock_A"):
                    pass
        except Exception as error:
            exceptions.append(error)

    t1 = threading.Thread(target=thread_1, name="Thread-1")
    t2 = threading.Thread(target=thread_2, name="Thread-2")

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # One of the threads must have raised a DeadlockError
    assert any(isinstance(e, DeadlockError) for e in exceptions)
    assert metrics.get("deadlocks_detected") == 1


def test_no_deadlock():
    metrics = MetricsRegistry()
    metrics.reset()
    manager = LockManager(metrics)

    def thread_1():
        with manager.exclusive_lock("lock_A"):
            with manager.exclusive_lock("lock_B"):
                pass

    def thread_2():
        with manager.exclusive_lock("lock_A"):
            with manager.exclusive_lock("lock_B"):
                pass

    t1 = threading.Thread(target=thread_1, name="Thread-1")
    t2 = threading.Thread(target=thread_2, name="Thread-2")

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    assert metrics.get("deadlocks_detected") == 0
