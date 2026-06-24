import time
import threading
from unittest.mock import MagicMock
from src.infrastructure.cache.chunk_manager import ChunkManager
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry


def test_future_sharing_concurrency(tmp_path):
    storage_mock = MagicMock()

    # Mock slowly to guarantee multiple threads ask for the same chunk while it's still running
    def slow_download(*args, **kwargs):
        time.sleep(0.1)
        return b"slow_data"

    storage_mock.download_file_chunk_from_api.side_effect = slow_download

    metrics = MetricsRegistry()
    metrics.reset()
    dispatcher = RequestDispatcher(
        metrics, read_workers=4, write_workers=1, meta_workers=1
    )
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=dispatcher,
        metrics=metrics,
    )

    results = []

    def worker():
        # offset 0, length 10 -> chunk 0
        data = manager.read_content_range_with_caching("file_1", 0, 10, 100)
        results.append(data)

    threads = []
    for _ in range(5):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # We asked 5 times concurrently. The slow download takes 0.1s.
    # Future sharing should guarantee storage_mock is only called ONCE for chunk 0, ONCE for chunk 1 (prefetch) and ONCE for chunk 2 (prefetch).
    assert storage_mock.download_file_chunk_from_api.call_count == 3

    assert len(results) == 5
    for r in results:
        # read_content_range_with_caching should return just the first 10 bytes of the chunk
        assert r == b"slow_data"[:10]

    # Check metrics
    # shared_futures should be at least 4 (from read_content_range_with_caching). Prefetch might also share futures depending on thread scheduling.
    assert metrics.get("shared_futures") >= 4

    dispatcher.shutdown()
