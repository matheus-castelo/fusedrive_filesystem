import errno
import logging
import os
import stat
import tempfile
import threading
import time
from typing import Dict

from fuse import FuseOSError, Operations
from src.domain.contracts.interfaces import (
    DriveNodeMetadata,
    IMetadataCache,
    IStorageClient,
)
from src.infrastructure.cache.chunk_manager import ChunkManager
from src.infrastructure.drive.upload_manager import UploadManager
from src.monitoring.metrics.metrics import MetricsRegistry
from src.fuse.virtual_files.stats_vfs import StatsVFS
from src.infrastructure.concurrency.dispatcher import RequestDispatcher

logger = logging.getLogger("fuse_ops")


class FuseOps(Operations):
    def __init__(
        self,
        storage: IStorageClient,
        cache: IMetadataCache,
        dispatcher: RequestDispatcher,
        root_id: str = "root",
    ):
        self.storage = storage
        self.cache = cache
        self.dispatcher = dispatcher
        self.root_id = root_id
        self.metrics = self.dispatcher.metrics
        self.chunk_manager = ChunkManager(
            storage, dispatcher=self.dispatcher, metrics=self.metrics
        )
        self.upload_manager = UploadManager(
            storage, dispatcher=self.dispatcher, metrics=self.metrics
        )
        self.lock_manager = self.chunk_manager.lock_manager
        self.stats_vfs = StatsVFS(self.metrics, self.lock_manager)

        self.cache.on_metadata_changed = self.chunk_manager.invalidate_file_chunks_cache

        self.open_files: Dict[int, dict] = {}
        self.local_only_files: Dict[str, str] = {}
        self.fd_lock = threading.Lock()
        self.next_fd = 1000

        self.journal_dir = os.path.join(
            getattr(self.cache, "cache_dir", ".cache"), "journal"
        )
        os.makedirs(self.journal_dir, exist_ok=True)

        root_meta = DriveNodeMetadata(
            file_id=root_id,
            name="",
            is_directory=True,
            size=0,
            modified_at_timestamp=time.time(),
        )
        self.cache.map_path_to_node_id("/", root_id)
        self.cache.set_metadata(root_id, root_meta)

    def is_temporary_editor_swap_file(self, name: str) -> bool:
        import re

        return bool(re.match(r".*\.swp$|.*\.kate-swp$|.*~$|^\.~lock.*", name))

    def resolve_path_to_drive_node_id(self, path: str) -> str:
        if path == "/":
            return self.root_id

        cached_id = self.cache.resolve_path_to_node_id(path)
        if cached_id:
            self.metrics.inc("cache_hits")
            return cached_id

        self.metrics.inc("cache_misses")
        parent_path = os.path.dirname(path)
        parent_id = self.resolve_path_to_drive_node_id(parent_path)

        if not parent_id:
            return None

        if self.cache.is_directory_children_loaded(parent_id):
            return None

        self._load_children(parent_id, parent_path)
        return self.cache.resolve_path_to_node_id(path)

    def _load_children(self, parent_id: str, parent_path: str):
        if self.cache.is_directory_children_loaded(parent_id):
            return

        self.metrics.inc("api_requests")
        items = self.storage.list_children(parent_id)
        for item in items:
            child_path = os.path.join(parent_path, item.name)
            self.cache.map_path_to_node_id(child_path, item.file_id)
            self.cache.set_metadata(item.file_id, item)

        self.cache.mark_directory_children_loaded(parent_id)

    def getattr(self, path, file_handle=None):
        logger.debug("getattr %s", path)
        if path.startswith("/stats"):
            return self.stats_vfs.getattr(path)

        if path in self.local_only_files:
            stat_info = os.stat(self.local_only_files[path])
            return {
                "st_mode": (stat.S_IFREG | 0o644),
                "st_nlink": 1,
                "st_size": stat_info.st_size,
                "st_ctime": stat_info.st_ctime,
                "st_mtime": stat_info.st_mtime,
                "st_atime": stat_info.st_atime,
            }

        file_id = self.resolve_path_to_drive_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        node_metadata = self.cache.get_metadata(file_id)
        if not node_metadata:

            if file_id == self.root_id:
                node_metadata = DriveNodeMetadata(
                    file_id=self.root_id,
                    name="",
                    is_directory=True,
                    size=0,
                    modified_at_timestamp=time.time(),
                )
                self.cache.set_metadata(self.root_id, node_metadata)
            else:
                try:
                    self.metrics.inc("api_requests")
                    node_metadata = self.storage.get_file_metadata(file_id)
                    if node_metadata:
                        self.cache.set_metadata(file_id, node_metadata)
                except Exception as error:
                    logger.error("Erro fetch metadata %s: %s", file_id, error)
                    node_metadata = None

        if not node_metadata:
            raise FuseOSError(errno.ENOENT)

        mode = (
            (stat.S_IFDIR | 0o755)
            if node_metadata.is_directory
            else (stat.S_IFREG | 0o644)
        )
        return {
            "st_mode": mode,
            "st_nlink": 2 if node_metadata.is_directory else 1,
            "st_size": node_metadata.size,
            "st_ctime": node_metadata.modified_at_timestamp,
            "st_mtime": node_metadata.modified_at_timestamp,
            "st_atime": node_metadata.modified_at_timestamp,
        }

    def readdir(self, path, file_handle):
        logger.debug("readdir %s", path)
        if path.startswith("/stats"):
            yield from self.stats_vfs.readdir(path)
            return

        file_id = self.resolve_path_to_drive_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        self._load_children(file_id, path)
        children = self.cache.get_children_paths(path)
        entries = [".", ".."] + [os.path.basename(c) for c in children]
        if path == "/":
            if "stats" not in entries:
                entries.append("stats")
        yield from entries

    def open(self, path: str, flags: int) -> int:
        logger.debug("open %s flags=%s", path, flags)
        if path.startswith("/stats"):
            return 0

        if path in self.local_only_files:
            temp_path = self.local_only_files[path]
            flags_os = (
                os.O_RDWR if (flags & os.O_WRONLY or flags & os.O_RDWR) else os.O_RDONLY
            )
            temp_fd = os.open(temp_path, flags_os)
            with self.fd_lock:
                fd = self.next_fd
                self.next_fd += 1
                self.open_files[fd] = {
                    "path": path,
                    "temp_fd": temp_fd,
                    "temp_path": temp_path,
                    "is_modified": False,
                    "is_write": (flags_os != os.O_RDONLY),
                    "is_local_only": True,
                }
            return fd

        file_id = self.cache.resolve_path_to_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        is_write = (flags & os.O_WRONLY) or (flags & os.O_RDWR)
        is_truncate = bool(flags & os.O_TRUNC)

        with self.fd_lock:
            fd = self.next_fd
            self.next_fd += 1

            if is_write:
                logger.info("Opening %s for writing. Lazy fetching enabled.", path)
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=self.journal_dir, prefix=f"edit_{file_id }_"
                )

                self.open_files[fd] = {
                    "path": path,
                    "temp_fd": temp_fd,
                    "temp_path": temp_path,
                    "is_modified": is_truncate,
                    "is_write": True,
                    "file_id": file_id,
                    "base_downloaded": is_truncate,
                }
            else:
                self.open_files[fd] = {
                    "path": path,
                    "is_write": False,
                    "file_id": file_id,
                }

        return fd

    def _ensure_downloaded(self, file_descriptor_info):
        if (
            file_descriptor_info["is_write"]
            and not file_descriptor_info["base_downloaded"]
        ):
            node_metadata = self.cache.get_metadata(file_descriptor_info["file_id"])
            if node_metadata and node_metadata.size > 0:
                logger.debug(
                    "Lazy fetching content for %s", file_descriptor_info["path"]
                )
                pending_path = self.upload_manager.get_pending_path(
                    file_descriptor_info["file_id"]
                )

                if pending_path and os.path.exists(pending_path):
                    with open(pending_path, "rb") as f:
                        data = f.read()
                else:
                    data = self.storage.get_file_content(
                        file_descriptor_info["file_id"]
                    )

                os.write(file_descriptor_info["temp_fd"], data)
            file_descriptor_info["base_downloaded"] = True

    def read(self, path: str, length: int, offset: int, file_handle: int) -> bytes:
        logger.debug("read %s offset=%s len=%s", path, offset, length)

        if path.startswith("/stats"):
            return self.stats_vfs.read(path, length, offset)

        with self.fd_lock:
            file_descriptor_info = self.open_files.get(file_handle)

        if not file_descriptor_info:
            raise FuseOSError(errno.EBADF)

        if file_descriptor_info.get("is_local_only"):
            os.lseek(file_descriptor_info["temp_fd"], offset, os.SEEK_SET)
            data = os.read(file_descriptor_info["temp_fd"], length)
            self.metrics.add("bytes_read", len(data))
            return data

        if file_descriptor_info["is_write"]:
            with self.lock_manager.exclusive_lock(f"file_handle:{file_handle}"):
                self._ensure_downloaded(file_descriptor_info)
                os.lseek(file_descriptor_info["temp_fd"], offset, os.SEEK_SET)
                data = os.read(file_descriptor_info["temp_fd"], length)
                self.metrics.add("bytes_read", len(data))
                return data
        else:
            file_id = file_descriptor_info["file_id"]

            pending_path = self.upload_manager.get_pending_path(file_id)
            if pending_path and os.path.exists(pending_path):
                self.metrics.inc("cache_hits")
                with open(pending_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                    self.metrics.add("bytes_read", len(data))
                    return data

            node_metadata = self.cache.get_metadata(file_id)
            if not node_metadata:
                raise FuseOSError(errno.ENOENT)
            data = self.chunk_manager.read_content_range_with_caching(
                file_id, offset, length, node_metadata.size, file_handle=file_handle
            )
            self.metrics.add("bytes_read", len(data))
            return data

    def write(
        self, path: str, data_buffer: bytes, offset: int, file_handle: int
    ) -> int:
        logger.debug("write %s offset=%s len=%s", path, offset, len(data_buffer))

        with self.fd_lock:
            file_descriptor_info = self.open_files.get(file_handle)

        if not file_descriptor_info or not file_descriptor_info["is_write"]:
            raise FuseOSError(errno.EBADF)

        if file_descriptor_info.get("is_local_only"):
            os.lseek(file_descriptor_info["temp_fd"], offset, os.SEEK_SET)
            written = os.write(file_descriptor_info["temp_fd"], data_buffer)
            file_descriptor_info["is_modified"] = True
            self.metrics.add("bytes_written", written)
            return written

        with self.lock_manager.exclusive_lock(f"file_handle:{file_handle}"):
            self._ensure_downloaded(file_descriptor_info)
            os.lseek(file_descriptor_info["temp_fd"], offset, os.SEEK_SET)
            written = os.write(file_descriptor_info["temp_fd"], data_buffer)
            file_descriptor_info["is_modified"] = True
            self.metrics.add("bytes_written", written)
            return written

    def release(self, path: str, file_handle: int) -> int:
        logger.debug("release %s", path)

        with self.fd_lock:
            file_descriptor_info = self.open_files.pop(file_handle, None)

        if not file_descriptor_info:
            return 0

        if file_descriptor_info.get("is_local_only"):
            os.close(file_descriptor_info["temp_fd"])
            return 0

        if file_descriptor_info["is_write"]:
            os.close(file_descriptor_info["temp_fd"])

            if file_descriptor_info.get("is_new"):
                self.upload_manager.enqueue_file_for_upload(
                    file_descriptor_info["file_id"],
                    file_descriptor_info["temp_path"],
                    is_new=True,
                    parent_id=file_descriptor_info["parent_id"],
                    name=file_descriptor_info["name"],
                )
            elif file_descriptor_info["is_modified"]:
                logger.info("File %s modified. Enqueuing for upload...", path)

                try:
                    new_size = os.path.getsize(file_descriptor_info["temp_path"])
                    node_metadata = self.cache.get_metadata(
                        file_descriptor_info["file_id"]
                    )
                    if node_metadata:
                        node_metadata.size = new_size
                        node_metadata.modified_at_timestamp = time.time()
                        self.cache.set_metadata(
                            file_descriptor_info["file_id"], node_metadata
                        )
                except Exception as error:
                    logger.error("Error updating local metadata after edit: %s", error)

                self.upload_manager.enqueue_file_for_upload(
                    file_descriptor_info["file_id"], file_descriptor_info["temp_path"]
                )

                self.chunk_manager.invalidate_file_chunks_cache(
                    file_descriptor_info["file_id"]
                )
            else:
                os.remove(file_descriptor_info["temp_path"])

        return 0

    def create(self, path, mode, file_info=None):
        logger.debug("create %s", path)
        name = os.path.basename(path)

        if self.is_temporary_editor_swap_file(name):
            temp_fd, temp_path = tempfile.mkstemp(prefix="fuse_swap_")
            self.local_only_files[path] = temp_path
            with self.fd_lock:
                fd = self.next_fd
                self.next_fd += 1
                self.open_files[fd] = {
                    "path": path,
                    "temp_fd": temp_fd,
                    "temp_path": temp_path,
                    "is_modified": True,
                    "is_write": True,
                    "is_local_only": True,
                }
            return fd

        from src.infrastructure.drive.circuit_breaker import (
            GoogleDriveQuotaCircuitBreaker,
        )

        if GoogleDriveQuotaCircuitBreaker().is_quota_exceeded():
            raise FuseOSError(errno.ENOSPC)

        parent_path = os.path.dirname(path)
        parent_id = self.resolve_path_to_drive_node_id(parent_path)
        if not parent_id:
            raise FuseOSError(errno.ENOENT)

        import uuid

        fake_id = "local_" + str(uuid.uuid4())
        node_metadata = DriveNodeMetadata(
            file_id=fake_id,
            name=name,
            is_directory=False,
            size=0,
            modified_at_timestamp=time.time(),
        )
        self.cache.map_path_to_node_id(path, fake_id)
        self.cache.set_metadata(fake_id, node_metadata)

        with self.fd_lock:
            fd = self.next_fd
            self.next_fd += 1
            import base64

            safe_name = base64.urlsafe_b64encode(name.encode("utf-8")).decode("utf-8")
            temp_fd, temp_path = tempfile.mkstemp(
                dir=self.journal_dir, prefix=f"create_{parent_id }_{safe_name }_"
            )

            self.open_files[fd] = {
                "path": path,
                "temp_fd": temp_fd,
                "temp_path": temp_path,
                "is_modified": True,
                "is_write": True,
                "file_id": fake_id,
                "base_downloaded": True,
                "is_new": True,
                "parent_id": parent_id,
                "name": name,
            }
        return fd

    def truncate(self, path, length, file_handle=None):
        logger.debug("truncate %s para %s bytes", path, length)

        if path in self.local_only_files:
            os.truncate(self.local_only_files[path], length)
            return 0

        file_id = self.resolve_path_to_drive_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        with self.fd_lock:
            if file_handle is not None and file_handle in self.open_files:
                file_descriptor_info = self.open_files[file_handle]
                if file_descriptor_info["is_write"]:
                    self._ensure_downloaded(file_descriptor_info)
                    os.ftruncate(file_descriptor_info["temp_fd"], length)
                    file_descriptor_info["is_modified"] = True
                    return 0

        return 0

    def mkdir(self, path: str, mode: int) -> int:
        logger.debug("mkdir %s mode=%s", path, oct(mode))
        from src.infrastructure.drive.circuit_breaker import (
            GoogleDriveQuotaCircuitBreaker,
        )

        if GoogleDriveQuotaCircuitBreaker().is_quota_exceeded():
            raise FuseOSError(errno.ENOSPC)

        parent_path = os.path.dirname(path)
        name = os.path.basename(path)

        parent_id = self.resolve_path_to_drive_node_id(parent_path)
        if not parent_id:
            raise FuseOSError(errno.ENOENT)

        try:
            node_metadata = self.storage.create_folder(parent_id, name)
            self.cache.map_path_to_node_id(path, node_metadata.file_id)
            self.cache.set_metadata(node_metadata.file_id, node_metadata)
            return 0
        except Exception as error:
            logger.error("Erro no mkdir: %s", error)
            raise FuseOSError(errno.EIO)

    def rename(self, old, new):
        logger.debug("rename %s para %s", old, new)

        if old in self.local_only_files:
            if self.is_temporary_editor_swap_file(new):
                self.local_only_files[new] = self.local_only_files.pop(old)
                return
            else:

                new_id = self.resolve_path_to_drive_node_id(new)
                if new_id:
                    temp_path = self.local_only_files[old]
                    safe_path = os.path.join(
                        self.journal_dir, f"fuse_atomic_{int (time .time ())}.tmp"
                    )
                    import shutil

                    shutil.copy(temp_path, safe_path)

                    self.upload_manager.enqueue_file_for_upload(new_id, safe_path)
                    self.chunk_manager.invalidate_file_chunks_cache(new_id)

                    try:
                        new_size = os.path.getsize(safe_path)
                        node_metadata = self.cache.get_metadata(new_id)
                        if node_metadata:
                            node_metadata.size = new_size
                            node_metadata.modified_at_timestamp = time.time()
                            self.cache.set_metadata(new_id, node_metadata)
                    except Exception:
                        pass

                    self.unlink(old)
                    self.cache.invalidate_path(new)
                    return

        from src.infrastructure.drive.circuit_breaker import (
            GoogleDriveQuotaCircuitBreaker,
        )

        if GoogleDriveQuotaCircuitBreaker().is_quota_exceeded():
            raise FuseOSError(errno.ENOSPC)

        file_id = self.resolve_path_to_drive_node_id(old)
        new_parent_path = os.path.dirname(new)
        new_name = os.path.basename(new)
        new_parent_id = self.resolve_path_to_drive_node_id(new_parent_path)

        if not file_id or not new_parent_id:
            raise FuseOSError(errno.ENOENT)

        if hasattr(self.storage, "_get_service"):
            from src.infrastructure.drive.drive_client import _execute_with_retry

            request = (
                self.storage._get_service()
                .files()
                .update(
                    fileId=file_id,
                    addParents=new_parent_id,
                    removeParents=self.resolve_path_to_drive_node_id(
                        os.path.dirname(old)
                    ),
                    body={"name": new_name},
                )
            )
            _execute_with_retry(request)

        self.cache.invalidate_path(old)
        self.cache.invalidate_path(new_parent_path)

    def unlink(self, path):
        logger.debug("unlink %s", path)
        if path in self.local_only_files:
            try:
                os.remove(self.local_only_files[path])
            except OSError:
                pass
            del self.local_only_files[path]
            return

        from src.infrastructure.drive.circuit_breaker import (
            GoogleDriveQuotaCircuitBreaker,
        )

        if GoogleDriveQuotaCircuitBreaker().is_quota_exceeded():
            raise FuseOSError(errno.ENOSPC)

        file_id = self.resolve_path_to_drive_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        try:
            self.storage.delete_file(file_id)
            self.cache.invalidate_path(path)
        except PermissionError:
            raise FuseOSError(errno.EACCES)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)
        except OSError:
            raise FuseOSError(errno.EIO)

    def rmdir(self, path):
        logger.debug("rmdir %s", path)
        file_id = self.resolve_path_to_drive_node_id(path)
        if not file_id:
            raise FuseOSError(errno.ENOENT)

        try:
            self.storage.delete_file(file_id)
            self.cache.invalidate_path(path)
        except PermissionError:
            raise FuseOSError(errno.EACCES)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)
        except OSError:
            raise FuseOSError(errno.EIO)

    def statfs(self, path):
        logger.debug("statfs %s", path)

        return {
            "f_bsize": 4096,
            "f_blocks": 268435456,
            "f_bfree": 268435456,
            "f_bavail": 268435456,
        }
