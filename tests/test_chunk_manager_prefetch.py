from src.infrastructure.concurrency.dispatcher import RequestDispatcher
import pytest
from unittest.mock import MagicMock
from src.infrastructure.cache.chunk_manager import (
    ChunkManager,
    InMemoryChunkEvictionCache,
)
from src.monitoring.metrics.metrics import MetricsRegistry


def test_lru_prefetch_metrics():
    metrics = MetricsRegistry()
    metrics.reset()
    cache = InMemoryChunkEvictionCache(
        max_chunks=2, max_memory_bytes=1000, metrics=metrics
    )

    # Inserir chunk normal
    cache.put(("file_1", 0), b"123", is_prefetch=False)
    # Inserir chunk via prefetch
    cache.put(("file_1", 1), b"456", is_prefetch=True)

    # Hit no prefetch
    val = cache.get(("file_1", 1))
    assert val == b"456"
    assert metrics.get("prefetch_hits") == 1

    # Adicionar 2 chunks para forçar a evicção
    cache.put(("file_1", 2), b"789", is_prefetch=False)
    cache.put(("file_1", 3), b"abc", is_prefetch=True)

    assert metrics.get("cache_evictions") == 2
    assert (
        metrics.get("prefetch_waste") == 0
    )  # Pois o chunk 1 foi lido antes da evicção!

    # Adicionar chunks para ejetar o chunk 3, que NUNCA foi lido
    cache.put(("file_1", 4), b"def", is_prefetch=False)
    cache.put(("file_1", 5), b"ghi", is_prefetch=False)

    assert metrics.get("prefetch_waste") == 1


def test_prefetch_sequential_heuristic(tmp_path):
    storage_mock = MagicMock()
    storage_mock.download_file_chunk_from_api.return_value = b"0123456789"
    manager = ChunkManager(
        storage_mock,
        chunk_size=10,
        cache_dir=str(tmp_path),
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
    )

    # Mock _prefetch to see if it gets called
    manager._prefetch = MagicMock()

    # Leitura 1: chunk 0 -> considerado sequencial (primeira leitura)
    manager.read_content_range_with_caching("file_2", 0, 10, 100, file_handle=1)
    assert 0 in manager.recent_chunks["file_2"]
    assert manager._prefetch.call_count == 2
    manager._prefetch.reset_mock()

    # Leitura 2: chunk 1 -> sequencial
    manager.read_content_range_with_caching("file_2", 10, 10, 100, file_handle=1)
    assert 1 in manager.recent_chunks["file_2"]
    assert manager._prefetch.call_count == 2
    manager._prefetch.reset_mock()

    # Seek brusco: chunk 5
    manager.read_content_range_with_caching("file_2", 50, 10, 100, file_handle=1)
    assert 5 in manager.recent_chunks["file_2"]
    # Prefetch NÃO DEVE ser chamado
    assert manager._prefetch.call_count == 0
    manager._prefetch.reset_mock()

    # Volta a ser sequencial: chunk 6
    manager.read_content_range_with_caching("file_2", 60, 10, 100, file_handle=1)
    assert 6 in manager.recent_chunks["file_2"]
    assert manager._prefetch.call_count == 2
