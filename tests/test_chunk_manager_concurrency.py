import time
import threading
from concurrent.futures import Future

from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.infrastructure.cache.chunk_manager import ChunkManager
from src.monitoring.metrics.metrics import MetricsRegistry
from src.domain.contracts.interfaces import IStorageClient
import tempfile
import os


class MockStorageLatency(IStorageClient):
    def download_file_chunk_from_api(self, file_id: str, start: int, end: int) -> bytes:
        time.sleep(0.1)  # low latency just for the test
        return b"x" * (end - start + 1)

    def list_children(self, parent_id):
        pass

    def get_file_content(self, file_id):
        pass

    def upload_new_file_to_drive(self, parent_id, name, content):
        pass

    def create_folder(self, parent_id, name):
        pass

    def delete_file(self, file_id):
        pass

    def upload_local_file_to_drive(self, file_id, path):
        pass


def test_chunk_manager_concurrent_reads_no_deadlock():
    metrics = MetricsRegistry()
    dispatcher = RequestDispatcher(metrics, read_workers=2, prefetch_workers=2)
    storage = MockStorageLatency()

    with tempfile.TemporaryDirectory() as temp_dir:
        cm = ChunkManager(
            storage,
            chunk_size=1024,
            max_chunks=20,
            cache_dir=temp_dir,
            dispatcher=dispatcher,
            metrics=metrics,
        )

        file_id = "test_file_deadlock"
        total_size = 100 * 1024  # 100KB

        # We spawn 3 threads to simulate interleaved reads
        results = []

        def read_thread(offset, length):
            start = time.time()
            data = cm.read_content_range_with_caching(
                file_id, offset, length, total_size, file_handle=1
            )
            results.append((offset, time.time() - start, len(data)))

        # Dolphin reads start of file
        t1 = threading.Thread(target=read_thread, args=(0, 10))
        t1.start()

        # Dolphin starts reading another chunk concurrently
        t2 = threading.Thread(target=read_thread, args=(10 * 1024, 10))
        t2.start()

        # Dolphin seeks to end of file
        t3 = threading.Thread(target=read_thread, args=(90 * 1024, 10))
        t3.start()

        t1.join()
        t2.join()
        t3.join()

        assert len(results) == 3
        for offset, duration, size in results:
            assert size == 10
            # Test that none of them deadlocked (completed within reasonable time)
            assert duration < 2.0

        # Clean shutdown
        dispatcher.shutdown(wait=True)
