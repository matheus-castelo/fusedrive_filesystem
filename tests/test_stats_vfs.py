import pytest
import stat
from fuse import FuseOSError
import errno

from src.monitoring.metrics.metrics import MetricsRegistry

# This class will be created during implementation
from src.fuse.virtual_files.stats_vfs import StatsVFS


@pytest.fixture
def metrics():
    registry = MetricsRegistry()
    registry.reset()
    return registry


@pytest.fixture
def stats_vfs(metrics):
    return StatsVFS(metrics)


def test_stats_readdir(stats_vfs):
    # O readdir deve listar as metricas disponiveis
    # No caso padrao se estivermos na raiz /stats
    children = stats_vfs.readdir("/stats")
    assert "cache_hits" in children
    assert "cache_misses" in children
    assert "cache_evictions" in children
    assert "downloads" in children


def test_stats_getattr_dir(stats_vfs):
    attrs = stats_vfs.getattr("/stats")
    assert stat.S_ISDIR(attrs["st_mode"])
    assert attrs["st_nlink"] == 2


def test_stats_getattr_file(stats_vfs, metrics):
    metrics.set("cache_hits", 42)
    attrs = stats_vfs.getattr("/stats/cache_hits")
    assert stat.S_ISREG(attrs["st_mode"])
    assert attrs["st_size"] == len("cache_hits          : 42\n")


def test_stats_getattr_not_found(stats_vfs):
    with pytest.raises(FuseOSError) as error:
        stats_vfs.getattr("/stats/not_exist")
    assert error.value.errno == errno.ENOENT


def test_stats_read(stats_vfs, metrics):
    metrics.set("cache_hits", 999)
    # read(path, length, offset)
    data = stats_vfs.read("/stats/cache_hits", 100, 0)
    assert data == b"cache_hits          : 999\n"

    # test offset
    data = stats_vfs.read("/stats/cache_hits", 100, 1)
    assert data == b"ache_hits          : 999\n"

    data = stats_vfs.read("/stats/cache_hits", 1, 0)
    assert data == b"c"
