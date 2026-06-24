from src.monitoring.metrics.metrics import MetricsRegistry
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
import os
import threading
import time
from unittest.mock import MagicMock, patch

from src.infrastructure.cache.chunk_manager import ChunkManager


def test_read_from_disk(tmp_path):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    # Write directly to disk
    path = manager._get_disk_path("file_1", 0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"0123456789")

    data = manager.read_chunk_from_disk_cache("file_1", 0)
    assert data == b"0123456789"


def test_write_to_disk_exception(tmp_path, caplog):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    with patch("os.replace", side_effect=Exception("Disk error")):
        manager.write_chunk_to_disk_cache("file_1", 0, b"data")
        assert "Falha ao salvar chunk no disco" in caplog.text


def test_download_chunk_concurrency(tmp_path):
    storage_mock = MagicMock()
    storage_mock.download_file_chunk_from_api.side_effect = lambda f, s, error: b"a" * (
        e - s + 1
    )
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    def simulate_other_thread():
        with manager.lock_manager.exclusive_lock("chunk:file_1:0"):
            time.sleep(0.1)
            with manager.mem_cache_lock:
                manager.memory_chunk_cache[("file_1", 0)] = b"0123456789"

    threading.Thread(target=simulate_other_thread).start()
    time.sleep(0.02)

    data = manager.download_chunk_from_drive_api("file_1", 0, 100)
    assert data == b"0123456789"
    assert storage_mock.download_file_chunk_from_api.call_count == 0


def test_download_chunk_concurrency_disk(tmp_path):
    storage_mock = MagicMock()
    storage_mock.download_file_chunk_from_api.return_value = b"fail"
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    def simulate_other_thread():
        with manager.lock_manager.exclusive_lock("chunk:file_1:0"):
            time.sleep(0.1)
            manager.write_chunk_to_disk_cache("file_1", 0, b"0123456789")

    threading.Thread(target=simulate_other_thread).start()
    time.sleep(0.02)

    data = manager.download_chunk_from_drive_api("file_1", 0, 100)
    assert data == b"0123456789"
    assert storage_mock.download_file_chunk_from_api.call_count == 0


def test_download_chunk_concurrency_timeout(tmp_path):
    storage_mock = MagicMock()
    storage_mock.download_file_chunk_from_api.return_value = b"downloaded"
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    def simulate_other_thread():
        with manager.lock_manager.exclusive_lock("chunk:file_1:0"):
            time.sleep(0.1)
            # Fails to write to cache or disk

    threading.Thread(target=simulate_other_thread).start()
    time.sleep(0.02)

    data = manager.download_chunk_from_drive_api("file_1", 0, 100)
    assert data == b"downloaded"
    assert storage_mock.download_file_chunk_from_api.call_count == 1


def test_prefetch_exists_on_disk(tmp_path):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    manager.write_chunk_to_disk_cache("file_1", 0, b"data")
    manager._prefetch("file_1", 0, 100)
    # Should not submit task
    assert len(manager.memory_chunk_cache) == 0


def test_get_data_out_of_bounds(tmp_path):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )
    data = manager.read_content_range_with_caching("file_1", 200, 10, 100)
    assert data == b""


def test_get_data_read_from_disk(tmp_path):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    manager.write_chunk_to_disk_cache("file_1", 0, b"0123456789")
    data = manager.read_content_range_with_caching("file_1", 0, 5, 100)
    assert data == b"01234"
    assert ("file_1", 0) in manager.memory_chunk_cache


def test_invalidate_file(tmp_path):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )

    manager.memory_chunk_cache[("file_1", 0)] = b"data"
    manager.memory_chunk_cache[("file_1", 1)] = b"data2"
    manager.memory_chunk_cache[("file_2", 0)] = b"data"

    manager.write_chunk_to_disk_cache("file_1", 0, b"data")
    manager.invalidate_file_chunks_cache("file_1")

    assert ("file_1", 0) not in manager.memory_chunk_cache
    assert ("file_2", 0) in manager.memory_chunk_cache
    assert not os.path.exists(manager._get_disk_path("file_1", 0))


def test_invalidate_file_exception(tmp_path, caplog):
    storage_mock = MagicMock()
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        disable_disk_cache=False,
    )
    manager.write_chunk_to_disk_cache("file_1", 0, b"data")

    with patch("shutil.rmtree", side_effect=Exception("rmtree err")):
        manager.invalidate_file_chunks_cache("file_1")
        assert "Erro ao invalidar cache de disco" in caplog.text


def test_disable_disk_cache(tmp_path):
    storage_mock = MagicMock()
    with patch.dict(os.environ, {"DISABLE_DISK_CACHE": "1"}):
        manager = ChunkManager(
            storage_mock,
            chunk_size=10,
            cache_dir=str(tmp_path),
            dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
        )
        manager.write_chunk_to_disk_cache("file_1", 0, b"data")
        assert not os.path.exists(manager._get_disk_path("file_1", 0))
        assert manager.read_chunk_from_disk_cache("file_1", 0) is None
