from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry
import errno
import os
import stat
from unittest.mock import MagicMock, patch

import pytest

from fuse import FuseOSError
from src.domain.contracts.interfaces import DriveNodeMetadata
from src.fuse.operations.fuse_ops import FuseOps


@pytest.fixture
def ops():
    storage = MagicMock()
    cache = MagicMock()
    metrics = MetricsRegistry()
    dispatcher = RequestDispatcher(metrics, 1, 1, 1)
    return FuseOps(storage, cache, dispatcher=dispatcher, root_id="root")


def test_fuse_ops_getattr_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.getattr("/not_found")
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_getattr_file(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    ops.cache.get_metadata.return_value = DriveNodeMetadata(
        "file_1", "f", False, 100, 1000.0
    )
    attrs = ops.getattr("/f")
    assert attrs["st_mode"] == (stat.S_IFREG | 0o644)
    assert attrs["st_size"] == 100


def test_fuse_ops_readdir_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        list(ops.readdir("/not_found", 0))
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_open_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.open("/not_found", 0)
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_open_write(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    fd = ops.open("/file_1", os.O_WRONLY)
    assert fd in ops.open_files
    assert ops.open_files[fd]["is_write"] == True


def test_fuse_ops_read_bad_fd(ops):
    with pytest.raises(FuseOSError) as error:
        ops.read("/f", 10, 0, 9999)
    assert error.value.errno == errno.EBADF


def test_fuse_ops_read_write_fd(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    ops.cache.get_metadata.return_value = DriveNodeMetadata(
        "file_1", "f", False, 4, 1000.0
    )
    ops.storage.get_file_content.return_value = b"abcd"

    fd = ops.open("/file_1", os.O_WRONLY)
    data = ops.read("/file_1", 2, 0, fd)
    assert data == b"ab"


def test_fuse_ops_read_read_fd_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    fd = ops.open("/file_1", os.O_RDONLY)
    ops.cache.get_metadata.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.read("/file_1", 10, 0, fd)
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_write_bad_fd(ops):
    with pytest.raises(FuseOSError) as error:
        ops.write("/f", b"data", 0, 9999)
    assert error.value.errno == errno.EBADF


def test_fuse_ops_release_not_found(ops):
    assert ops.release("/f", 9999) == 0


def test_fuse_ops_release_write_modified(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    ops.cache.get_metadata.return_value = DriveNodeMetadata(
        "file_1", "f", False, 0, 1000.0
    )

    fd = ops.open("/file_1", os.O_WRONLY)
    ops.write("/file_1", b"abc", 0, fd)

    with patch.object(ops.dispatcher, "submit") as mock_submit:
        ops.release("/file_1", fd)
        assert fd not in ops.open_files
        mock_submit.assert_called_once()


def test_fuse_ops_create_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.create("/dir/new_file", 0)
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_truncate_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.truncate("/not_found", 0)
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_truncate_file_handle(ops):
    ops.cache.resolve_path_to_node_id.return_value = "file_1"
    ops.cache.get_metadata.return_value = DriveNodeMetadata(
        "file_1", "f", False, 0, 1000.0
    )
    fd = ops.open("/file_1", os.O_WRONLY)
    ops.truncate("/file_1", 10, file_handle=fd)
    assert ops.open_files[fd]["is_modified"] == True


def test_fuse_ops_mkdir_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.mkdir("/dir/new_dir", 0)
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_mkdir_exception(ops):
    ops.cache.resolve_path_to_node_id.return_value = "root"
    ops.storage.create_folder.side_effect = Exception("Err")
    with pytest.raises(FuseOSError) as error:
        ops.mkdir("/dir/new_dir", 0)
    assert error.value.errno == errno.EIO


def test_fuse_ops_rename_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.rename("/old", "/new")
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_rename_success(ops):
    ops.cache.resolve_path_to_node_id.side_effect = lambda p: (
        "file_id" if p == "/old" else "parent_id"
    )
    ops.storage._get_service = MagicMock()

    ops.rename("/old", "/new")
    ops.cache.invalidate_path.assert_called()


def test_fuse_ops_unlink_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.unlink("/not_found")
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_rmdir_not_found(ops):
    ops.cache.resolve_path_to_node_id.return_value = None
    with pytest.raises(FuseOSError) as error:
        ops.rmdir("/not_found")
    assert error.value.errno == errno.ENOENT


def test_fuse_ops_statfs(ops):
    stat_info = ops.statfs("/")
    assert stat_info["f_bsize"] == 4096
