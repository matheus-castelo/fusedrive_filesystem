import pytest
from src.infrastructure.cache.chunk_manager import InMemoryChunkEvictionCache
from src.monitoring.metrics.metrics import MetricsRegistry


@pytest.fixture
def metrics():
    registry = MetricsRegistry()
    registry.metrics.clear()  # reset state for test
    return registry


def test_lru_cache_max_chunks(metrics):
    cache = InMemoryChunkEvictionCache(
        max_chunks=3, max_memory_bytes=1000, metrics=metrics
    )

    # Inserindo 3 items (cada um com 10 bytes)
    cache.put("k1", b"0123456789")
    cache.put("k2", b"0123456789")
    cache.put("k3", b"0123456789")

    assert cache.get("k1") == b"0123456789"
    assert cache.get("k2") == b"0123456789"
    assert cache.get("k3") == b"0123456789"

    # Inserindo o 4o item, deve remover o mais antigo em uso (agora seria k1 pq acessamos na ordem)
    # Mas se só inserimos k1, k2, k3 e dps acessamos k1, k2, k3, a ordem de mais recente é k3, k2, k1.
    # Vamos acessar explicitamente k1 para deixá-lo fresco
    cache.get("k1")
    cache.put("k4", b"0123456789")

    # k2 deve ser evictado
    assert cache.get("k2") is None
    assert cache.get("k1") is not None
    assert cache.get("k3") is not None
    assert cache.get("k4") is not None

    assert metrics.get("cache_evictions") == 1
    assert metrics.get("cache_size_chunks") == 3
    assert metrics.get("cache_size_bytes") == 30


def test_lru_cache_max_memory(metrics):
    # Max mem = 25 bytes. max_chunks = 10.
    cache = InMemoryChunkEvictionCache(
        max_chunks=10, max_memory_bytes=25, metrics=metrics
    )

    cache.put("k1", b"1234567890")  # 10 bytes
    cache.put("k2", b"1234567890")  # 10 bytes -> total 20
    cache.put("k3", b"1234567890")  # 10 bytes -> total 30, excede 25, remove k1

    assert cache.get("k1") is None
    assert cache.get("k2") is not None
    assert cache.get("k3") is not None

    assert metrics.get("cache_evictions") == 1
    assert metrics.get("cache_size_bytes") == 20

    # Atualizar k2 com algo muito grande
    cache.put(
        "k2", b"12345678901234567890"
    )  # 20 bytes -> total 30, excede 25, remove k3
    assert cache.get("k3") is None
    assert cache.get("k2") is not None
    assert metrics.get("cache_evictions") == 2
    assert metrics.get("cache_size_bytes") == 20


def test_lru_cache_delete_and_invalidate(metrics):
    cache = InMemoryChunkEvictionCache(
        max_chunks=10, max_memory_bytes=1000, metrics=metrics
    )
    cache.put("k1", b"12345")
    cache.put("k2", b"12345")

    assert metrics.get("cache_size_bytes") == 10
    cache.invalidate("k1")

    assert cache.get("k1") is None
    assert metrics.get("cache_size_bytes") == 5
    assert metrics.get("cache_size_chunks") == 1
