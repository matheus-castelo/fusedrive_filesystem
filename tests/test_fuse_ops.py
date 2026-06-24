from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry
import errno
import os
from unittest.mock import MagicMock

import pytest

from fuse import FuseOSError
from src.domain.contracts.interfaces import DriveNodeMetadata
from src.fuse.operations.fuse_ops import FuseOps
from src.infrastructure.cache.memory_cache import MemoryMetadataCache


def _mock_storage(children=None):
    storage = MagicMock()
    storage.list_children.return_value = children or []
    return storage


def _make_ops(storage=None, cache=None):
    if storage is None:
        storage = _mock_storage()
    cache = cache or MemoryMetadataCache()
    return FuseOps(
        storage=storage,
        cache=cache,
        dispatcher=RequestDispatcher(MetricsRegistry(), 1, 1, 1),
    )


class TestFuseGetattr:
    def test_root_returns_directory(self):
        ops = _make_ops()
        attr = ops.getattr("/")
        assert attr["st_nlink"] == 2

    def test_missing_path_raises_enoent(self):
        ops = _make_ops()
        with pytest.raises(FuseOSError) as error:
            ops.getattr("/nonexistent")
        assert error.value.errno == errno.ENOENT

    def test_cached_file_returns_file_attrs(self):
        node_metadata = DriveNodeMetadata(
            file_id="f1",
            name="doc.txt",
            is_directory=False,
            size=999,
            modified_at_timestamp=1.0,
        )
        storage = _mock_storage(children=[node_metadata])
        ops = _make_ops(storage=storage)

        attr = ops.getattr("/doc.txt")
        assert attr["st_size"] == 999
        assert attr["st_nlink"] == 1


class TestFuseReaddir:
    def test_root_has_dot_entries(self):
        ops = _make_ops()
        entries = list(ops.readdir("/", None))
        assert "." in entries
        assert ".." in entries

    def test_lists_children(self):
        children = [
            DriveNodeMetadata(
                file_id="a",
                name="a.txt",
                is_directory=False,
                size=1,
                modified_at_timestamp=1.0,
            ),
            DriveNodeMetadata(
                file_id="b",
                name="b.txt",
                is_directory=False,
                size=2,
                modified_at_timestamp=1.0,
            ),
        ]
        storage = _mock_storage(children=children)
        ops = _make_ops(storage=storage)
        entries = list(ops.readdir("/", None))
        assert "a.txt" in entries
        assert "b.txt" in entries


class TestFuseRead:
    def test_read_returns_slice(self):
        ops = _make_ops()
        ops.cache.map_path_to_node_id("/f.txt", "f1")
        ops.cache.set_metadata(
            "f1",
            DriveNodeMetadata(
                file_id="f1",
                name="f.txt",
                is_directory=False,
                size=15,
                modified_at_timestamp=0,
            ),
        )
        ops.chunk_manager.read_content_range_with_caching = MagicMock(
            return_value=b"hello"
        )

        file_handle = ops.open("/f.txt", os.O_RDONLY)
        data = ops.read("/f.txt", 5, 0, file_handle)
        assert data == b"hello"
        ops.chunk_manager.read_content_range_with_caching.assert_called_once_with(
            "f1", 0, 5, 15, file_handle=file_handle
        )

    def test_read_with_offset(self):
        ops = _make_ops()
        ops.cache.map_path_to_node_id("/f.txt", "f1")
        ops.cache.set_metadata(
            "f1",
            DriveNodeMetadata(
                file_id="f1",
                name="f.txt",
                is_directory=False,
                size=15,
                modified_at_timestamp=0,
            ),
        )
        ops.chunk_manager.read_content_range_with_caching = MagicMock(
            return_value=b"world"
        )

        file_handle = ops.open("/f.txt", os.O_RDONLY)
        data = ops.read("/f.txt", 5, 6, file_handle)
        assert data == b"world"
        ops.chunk_manager.read_content_range_with_caching.assert_called_once_with(
            "f1", 6, 5, 15, file_handle=file_handle
        )


class TestFuseMkdir:
    def test_mkdir_creates_folder(self):
        new_meta = DriveNodeMetadata(
            file_id="new_dir",
            name="nova",
            is_directory=True,
            size=0,
            modified_at_timestamp=1.0,
        )
        storage = _mock_storage()
        storage.create_folder.return_value = new_meta

        ops = _make_ops(storage=storage)
        ops.mkdir("/nova", 0o755)
        storage.create_folder.assert_called_once_with("root", "nova")


class TestFuseUnlink:
    def test_unlink_deletes_and_invalidates(self):
        node_metadata = DriveNodeMetadata(
            file_id="f1",
            name="f.txt",
            is_directory=False,
            size=10,
            modified_at_timestamp=1.0,
        )
        storage = _mock_storage(children=[node_metadata])
        cache = MemoryMetadataCache()
        ops = _make_ops(storage=storage, cache=cache)

        ops.getattr("/f.txt")

        storage.list_children.return_value = []
        ops.unlink("/f.txt")
        storage.delete_file.assert_called_once_with("f1")
        assert cache.resolve_path_to_node_id("/f.txt") is None

    def test_unlink_permission_error_raises_eacces(self):
        from fuse import FuseOSError

        node_metadata = DriveNodeMetadata(
            file_id="f1",
            name="f.txt",
            is_directory=False,
            size=10,
            modified_at_timestamp=1.0,
        )
        storage = _mock_storage(children=[node_metadata])
        storage.delete_file.side_effect = PermissionError("insufficientFilePermissions")
        cache = MemoryMetadataCache()
        ops = _make_ops(storage=storage, cache=cache)

        ops.getattr("/f.txt")

        with pytest.raises(FuseOSError) as error:
            ops.unlink("/f.txt")
        assert error.value.errno == errno.EACCES
