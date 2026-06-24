import time
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry


def test_dispatcher_queues():
    metrics = MetricsRegistry()
    metrics.reset()
    dispatcher = RequestDispatcher(
        metrics, read_workers=1, write_workers=1, meta_workers=1
    )

    def slow_task():
        time.sleep(0.1)
        return "done"

    # Submit 3 tasks to read pool
    f1 = dispatcher.submit("read", slow_task)
    f2 = dispatcher.submit("read", slow_task)
    f3 = dispatcher.submit("read", slow_task)

    # Submit 1 to node_metadata pool
    f4 = dispatcher.submit("metadata", lambda: "meta_done")

    # The node_metadata task should finish almost instantly, unblocked by read tasks
    assert f4.result(timeout=0.05) == "meta_done"

    dispatcher.update_metrics()

    # We submitted 3, 1 is running, 2 are in queue (or similar, depending on timing)
    # The active/queue metrics should have been updated
    assert metrics.get("pool_read_queue") is not None
    assert metrics.get("pool_read_active") is not None

    f1.result()
    f2.result()
    f3.result()

    dispatcher.shutdown()
