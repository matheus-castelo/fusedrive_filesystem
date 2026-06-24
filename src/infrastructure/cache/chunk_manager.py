import logging
import os
import threading
import time
from typing import Dict, Tuple, Optional

from collections import OrderedDict

from src.domain.contracts.interfaces import IStorageClient
from concurrent.futures import Future
from src.infrastructure.concurrency.lock_manager import LockManager
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry

logger = logging.getLogger("chunk_manager")


class InMemoryChunkEvictionCache:
    def __init__(
        self, max_chunks: int, max_memory_bytes: int, metrics: MetricsRegistry
    ):
        self.max_chunks = max_chunks
        self.max_memory_bytes = max_memory_bytes
        self.metrics = metrics
        self.cache = OrderedDict()
        self.prefetch_status = {}
        self.current_bytes = 0

    def __contains__(self, key):
        return key in self.cache

    def __iter__(self):
        return iter(list(self.cache.keys()))

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            if key in self.prefetch_status:
                self.metrics.inc("prefetch_hits")
                del self.prefetch_status[key]
            return self.cache[key]
        return None

    def __getitem__(self, key):
        return self.get(key)

    def __len__(self):
        return len(self.cache)

    def put(self, key, value: bytes, is_prefetch: bool = False):
        if key in self.cache:
            if key in self.prefetch_status:
                del self.prefetch_status[key]
            old_size = len(self.cache[key])
            self.current_bytes -= old_size
            del self.cache[key]

        self.cache[key] = value
        if is_prefetch:
            self.prefetch_status[key] = True

        self.current_bytes += len(value)
        self.cache.move_to_end(key)

        self._evict_if_needed()
        self._update_metrics()

    def __setitem__(self, key, value):
        self.put(key, value)

    def invalidate(self, key):
        if key in self.cache:
            if key in self.prefetch_status:
                del self.prefetch_status[key]
            self.current_bytes -= len(self.cache[key])
            del self.cache[key]
            self._update_metrics()

    def __delitem__(self, key):
        self.invalidate(key)

    def _evict_if_needed(self):
        while self.cache and (
            len(self.cache) > self.max_chunks
            or self.current_bytes > self.max_memory_bytes
        ):
            key, val = self.cache.popitem(last=False)
            self.current_bytes -= len(val)
            if key in self.prefetch_status:
                self.metrics.inc("prefetch_waste")
                del self.prefetch_status[key]
            self.metrics.inc("cache_evictions")

    def _update_metrics(self):
        self.metrics.set("cache_size_chunks", len(self.cache))
        self.metrics.set("cache_size_bytes", self.current_bytes)
        self.metrics.set("cache_memory_usage", self.current_bytes)


class ChunkManager:
    def __init__(
        self,
        storage: IStorageClient,
        chunk_size: int = 5 * 1024 * 1024,
        max_chunks: int = 20,
        cache_dir: str = None,
        dispatcher: RequestDispatcher = None,
        metrics: Optional[MetricsRegistry] = None,
        meta_cache=None,
        disable_disk_cache: Optional[bool] = None,
    ):
        self.storage = storage
        self.chunk_size = chunk_size
        self.cache_dir = cache_dir or os.getenv(
            "CACHE_DIR", os.path.expanduser("~/.cache/gdrive-fuse")
        )
        self.disable_disk_cache = (
            disable_disk_cache
            if disable_disk_cache is not None
            else os.getenv("DISABLE_DISK_CACHE", "0") == "1"
        )

        self.metrics = metrics or MetricsRegistry()
        self.meta_cache = meta_cache

        max_mem = int(os.getenv("CACHE_MAX_MEMORY_MB", 512)) * 1024 * 1024
        self.memory_chunk_cache = InMemoryChunkEvictionCache(
            max_chunks=max_chunks, max_memory_bytes=max_mem, metrics=self.metrics
        )

        self.dispatcher = dispatcher
        self.lock_manager = LockManager(self.metrics)
        self.mem_cache_lock = threading.Lock()

        self.active_downloads: Dict[Tuple[str, int], Future] = {}
        self.active_downloads_lock = threading.Lock()

        from collections import deque, defaultdict

        self.recent_chunks = defaultdict(lambda: deque(maxlen=10))

        os.makedirs(self.cache_dir, exist_ok=True)

    def is_video_file_by_extension(self, file_id: str) -> bool:
        if not self.meta_cache:
            return False
        node_metadata = self.meta_cache.get_metadata(file_id)
        if not node_metadata:
            return False
        return node_metadata.name.lower().endswith(
            (".mp4", ".mkv", ".avi", ".mov", ".webm")
        )

    def _get_disk_path(self, file_id: str, chunk_index: int) -> str:
        return os.path.join(self.cache_dir, file_id, str(chunk_index))

    def read_chunk_from_disk_cache(self, file_id: str, chunk_index: int) -> bytes:
        if self.disable_disk_cache and not self.is_video_file_by_extension(file_id):
            return None

        path = self._get_disk_path(file_id, chunk_index)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        return None

    def write_chunk_to_disk_cache(self, file_id: str, chunk_index: int, data: bytes):
        if self.disable_disk_cache and not self.is_video_file_by_extension(file_id):
            return

        path = self._get_disk_path(file_id, chunk_index)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = path + f".tmp.{time .time ()}"
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
            os.replace(temp_path, path)
        except Exception as error:
            logger.error("Falha ao salvar chunk no disco: %s", error)
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def download_chunk_from_drive_api(
        self, file_id: str, chunk_index: int, total_size: int, is_prefetch: bool = False
    ) -> bytes:
        start = chunk_index * self.chunk_size
        end = min(start + self.chunk_size - 1, total_size - 1)

        if start >= total_size:
            return b""

        chunk_key = f"chunk:{file_id }:{chunk_index }"

        with self.lock_manager.exclusive_lock(chunk_key):
            with self.mem_cache_lock:
                cached = self.memory_chunk_cache.get((file_id, chunk_index))
            if cached is not None:
                return cached

            cached = self.read_chunk_from_disk_cache(file_id, chunk_index)
            if cached is not None:
                with self.mem_cache_lock:
                    self.memory_chunk_cache.put(
                        (file_id, chunk_index), cached, is_prefetch=is_prefetch
                    )
                return cached

            logger.info(
                "Baixando chunk",
                extra={
                    "event": "chunk_download",
                    "file_id": file_id,
                    "chunk": chunk_index,
                    "size": end - start + 1,
                },
            )
            try:
                self.metrics.inc("api_requests")
                self.metrics.inc("downloads")
                data = self.storage.download_file_chunk_from_api(file_id, start, end)
                self.metrics.add("bytes_downloaded", len(data))

                with self.mem_cache_lock:
                    self.memory_chunk_cache.put(
                        (file_id, chunk_index), data, is_prefetch=is_prefetch
                    )

                self.write_chunk_to_disk_cache(file_id, chunk_index, data)
                return data
            except Exception as error:
                logger.error("Erro baixando chunk: %s", error)
                raise

    def _prefetch(self, file_id: str, chunk_index: int, total_size: int):
        chunk_key = f"chunk:{file_id }:{chunk_index }"
        if self.lock_manager.has_lock(chunk_key):
            return

        with self.mem_cache_lock:
            if (file_id, chunk_index) in self.memory_chunk_cache:
                return

        if os.path.exists(self._get_disk_path(file_id, chunk_index)):
            return

        self.schedule_or_get_chunk_download_task(file_id, chunk_index, total_size, True)

    def schedule_or_get_chunk_download_task(
        self, file_id: str, chunk_index: int, total_size: int, is_prefetch: bool = False
    ) -> Future:
        chunk_key = (file_id, chunk_index)

        with self.active_downloads_lock:
            if chunk_key in self.active_downloads:
                future, was_prefetch = self.active_downloads[chunk_key]
                if not is_prefetch and was_prefetch:

                    if future.cancel():
                        self.metrics.inc("prefetch_promoted")
                        future = self.dispatcher.submit(
                            "read",
                            self.download_chunk_from_drive_api,
                            file_id,
                            chunk_index,
                            total_size,
                            False,
                        )
                        self.active_downloads[chunk_key] = (future, False)

                        def _remove_future(f):
                            with self.active_downloads_lock:
                                self.active_downloads.pop(chunk_key, None)

                        pass
                    else:
                        self.metrics.inc("shared_futures")
                        return future
                else:
                    self.metrics.inc("shared_futures")
                    return future

            pool_name = "prefetch" if is_prefetch else "read"
            future = self.dispatcher.submit(
                pool_name,
                self.download_chunk_from_drive_api,
                file_id,
                chunk_index,
                total_size,
                is_prefetch,
            )
            self.active_downloads[chunk_key] = (future, is_prefetch)

        def _remove_future(f):
            with self.active_downloads_lock:
                self.active_downloads.pop(chunk_key, None)

        future.add_done_callback(_remove_future)
        return future

    def read_content_range_with_caching(
        self,
        file_id: str,
        offset: int,
        length: int,
        total_size: int,
        file_handle: int = 0,
    ) -> bytes:
        if offset >= total_size:
            return b""

        start_chunk = offset // self.chunk_size
        end_chunk = (offset + length - 1) // self.chunk_size

        recent = self.recent_chunks[file_id]
        is_sequential = False

        recent_list = list(recent)
        if not recent_list:
            is_sequential = True
        elif (
            start_chunk in recent_list
            or (start_chunk - 1) in recent_list
            or (start_chunk - 2) in recent_list
        ):
            is_sequential = True

        if is_sequential:
            self._prefetch(file_id, end_chunk + 1, total_size)
            self._prefetch(file_id, end_chunk + 2, total_size)

        recent.append(end_chunk)

        result = bytearray()
        for chunk_idx in range(start_chunk, end_chunk + 1):
            cached_data = None

            with self.mem_cache_lock:
                cached_data = self.memory_chunk_cache.get((file_id, chunk_idx))

            if cached_data is None:
                cached_data = self.read_chunk_from_disk_cache(file_id, chunk_idx)
                if cached_data is not None:
                    self.metrics.inc("cache_hits")
                    self.metrics.add("bytes_from_cache", len(cached_data))
                    with self.mem_cache_lock:
                        self.memory_chunk_cache.put(
                            (file_id, chunk_idx), cached_data, is_prefetch=False
                        )
            else:
                self.metrics.inc("cache_hits")
                self.metrics.add("bytes_from_cache", len(cached_data))

            if cached_data is None:
                self.metrics.inc("cache_misses")
                future = self.schedule_or_get_chunk_download_task(
                    file_id, chunk_idx, total_size, is_prefetch=False
                )

                if isinstance(future, tuple):
                    future = future[0]
                cached_data = future.result()

            chunk_start_offset = chunk_idx * self.chunk_size
            rel_start = max(0, offset - chunk_start_offset)
            rel_end = min(self.chunk_size, offset + length - chunk_start_offset)

            result.extend(cached_data[rel_start:rel_end])

        return bytes(result)

    def invalidate_file_chunks_cache(self, file_id: str):
        with self.mem_cache_lock:

            keys_to_delete = [k for k in self.memory_chunk_cache if k[0] == file_id]
            for k in keys_to_delete:
                del self.memory_chunk_cache[k]

        path = os.path.join(self.cache_dir, file_id)
        if os.path.exists(path):
            import shutil

            try:
                shutil.rmtree(path)
                logger.info("Cache de disco invalidado para arquivo %s", file_id)
            except Exception as error:
                logger.error("Erro ao invalidar cache de disco: %s", error)
