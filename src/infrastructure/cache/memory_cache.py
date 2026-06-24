import collections
import os
import threading
from typing import List, Optional

from cachetools import TTLCache

from src.domain.contracts.interfaces import DriveNodeMetadata, IMetadataCache


class MemoryMetadataCache(IMetadataCache):
    def __init__(self, ttl: int = 60, maxsize: int = 10000):

        self._path_to_node_id_map = TTLCache(maxsize=maxsize, ttl=ttl)

        self._node_id_to_metadata_map = TTLCache(maxsize=maxsize, ttl=ttl)

        self._fully_loaded_directories_set = TTLCache(maxsize=maxsize, ttl=ttl)
        self._parent_path_to_children_paths_map = collections.defaultdict(set)
        self._lock = threading.RLock()
        self.on_metadata_changed = None

    def resolve_path_to_node_id(self, path: str) -> Optional[str]:
        with self._lock:
            return self._path_to_node_id_map.get(path)

    def map_path_to_node_id(self, path: str, file_id: str) -> None:
        with self._lock:
            self._path_to_node_id_map[path] = file_id
            if path != "/":
                parent = os.path.dirname(path)
                self._parent_path_to_children_paths_map[parent].add(path)

    def get_metadata(self, file_id: str) -> Optional[DriveNodeMetadata]:
        with self._lock:
            return self._node_id_to_metadata_map.get(file_id)

    def set_metadata(self, file_id: str, metadata: DriveNodeMetadata) -> None:
        with self._lock:
            old_meta = self._node_id_to_metadata_map.get(file_id)
            self._node_id_to_metadata_map[file_id] = metadata

            if (
                old_meta
                and not metadata.is_directory
                and old_meta.modified_at_timestamp != metadata.modified_at_timestamp
            ):
                if self.on_metadata_changed:
                    self.on_metadata_changed(file_id)

    def get_children_paths(self, parent_path: str) -> List[str]:
        with self._lock:

            return list(self._parent_path_to_children_paths_map.get(parent_path, set()))

    def invalidate_path(self, path: str) -> None:
        with self._lock:
            file_id = self._path_to_node_id_map.pop(path, None)
            if file_id:
                self._node_id_to_metadata_map.pop(file_id, None)
            if path != "/":
                parent = os.path.dirname(path)
                if parent in self._parent_path_to_children_paths_map:
                    self._parent_path_to_children_paths_map[parent].discard(path)

    def is_directory_children_loaded(self, dir_id: str) -> bool:
        with self._lock:
            return dir_id in self._fully_loaded_directories_set

    def mark_directory_children_loaded(self, dir_id: str) -> None:
        with self._lock:
            self._fully_loaded_directories_set[dir_id] = True
