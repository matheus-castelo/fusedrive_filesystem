import pytest

from src.domain.contracts.interfaces import DriveNodeMetadata
from src.infrastructure.cache.memory_cache import MemoryMetadataCache


def _make_meta(file_id="id1", name="f.txt", is_directory=False, size=10):
    return DriveNodeMetadata(
        file_id=file_id,
        name=name,
        is_directory=is_directory,
        size=size,
        modified_at_timestamp=0.0,
    )


class TestMemoryCacheIdMapping:
    def test_set_and_get(self):
        cache = MemoryMetadataCache()
        cache.map_path_to_node_id("/a/b.txt", "id1")
        assert cache.resolve_path_to_node_id("/a/b.txt") == "id1"

    def test_get_missing_returns_none(self):
        cache = MemoryMetadataCache()
        assert cache.resolve_path_to_node_id("/nope") is None


class TestMemoryCacheMetadata:
    def test_set_and_get(self):
        cache = MemoryMetadataCache()
        node_metadata = _make_meta()
        cache.set_metadata("id1", node_metadata)
        assert cache.get_metadata("id1") == node_metadata

    def test_get_missing_returns_none(self):
        cache = MemoryMetadataCache()
        assert cache.get_metadata("nope") is None


class TestMemoryCacheChildren:
    def test_returns_direct_children_only(self):
        cache = MemoryMetadataCache()
        cache.map_path_to_node_id("/root", "r")
        cache.map_path_to_node_id("/root/a.txt", "a")
        cache.map_path_to_node_id("/root/b.txt", "b")
        cache.map_path_to_node_id("/other/c.txt", "c")

        children = cache.get_children_paths("/root")
        assert sorted(children) == ["/root/a.txt", "/root/b.txt"]

    def test_no_children(self):
        cache = MemoryMetadataCache()
        cache.map_path_to_node_id("/empty", "e")
        assert cache.get_children_paths("/empty") == []


class TestMemoryCacheInvalidate:
    def test_invalidate_removes_path_and_metadata(self):
        cache = MemoryMetadataCache()
        cache.map_path_to_node_id("/x.txt", "x1")
        cache.set_metadata("x1", _make_meta(file_id="x1"))

        cache.invalidate_path("/x.txt")
        assert cache.resolve_path_to_node_id("/x.txt") is None
        assert cache.get_metadata("x1") is None

    def test_invalidate_nonexistent_no_error(self):
        cache = MemoryMetadataCache()
        cache.invalidate_path("/ghost")
