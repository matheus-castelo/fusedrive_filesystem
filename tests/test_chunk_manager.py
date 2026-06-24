from src.monitoring.metrics.metrics import MetricsRegistry
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
import os
import shutil
import tempfile
from unittest.mock import MagicMock

from src.infrastructure.cache.chunk_manager import ChunkManager


def test_chunk_disk_cache():
    storage_mock = MagicMock()
    storage_mock.download_file_chunk_from_api.return_value = b"chunk_data_mock_123"

    # Create a temporary directory for caching
    temp_cache_dir = tempfile.mkdtemp()
    try:
        manager = ChunkManager(
            storage_mock,
            chunk_size=1024,
            cache_dir=temp_cache_dir,
            dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
            disable_disk_cache=False,
        )

        # Act
        data = manager.read_content_range_with_caching("file123", 0, 1024, 2048)

        # Assert
        assert data == b"chunk_data_mock_123"

        # O prefetch tentará baixar o próximo chunk assincronamente.
        # Precisamos aguardar o ThreadPoolExecutor terminar as tarefas.
        import time

        time.sleep(0.5)

        # Check if file was saved to disk (chunk 0 and chunk 1 from prefetch)
        chunk_path_0 = os.path.join(temp_cache_dir, "file123", "0")
        chunk_path_1 = os.path.join(temp_cache_dir, "file123", "1")
        assert os.path.exists(chunk_path_0)
        with open(chunk_path_0, "rb") as f:
            assert f.read() == b"chunk_data_mock_123"

        # Call again, should not hit the API for chunk 0
        call_count_before = storage_mock.download_file_chunk_from_api.call_count
        data2 = manager.read_content_range_with_caching("file123", 0, 1024, 2048)
        assert data2 == b"chunk_data_mock_123"
        # Call count should not increase for chunk 0
        assert storage_mock.download_file_chunk_from_api.call_count == call_count_before

    finally:
        shutil.rmtree(temp_cache_dir)
