from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DriveNodeMetadata:
    file_id: str
    name: str
    is_directory: bool
    size: int
    modified_at_timestamp: float


class IStorageClient(ABC):

    @abstractmethod
    def list_children(self, parent_id: str) -> List[DriveNodeMetadata]: ...

    @abstractmethod
    def get_file_content(self, file_id: str) -> bytes:
        pass

    @abstractmethod
    def download_file_chunk_from_api(self, file_id: str, start: int, end: int) -> bytes:
        pass

    @abstractmethod
    def upload_new_file_to_drive(
        self, parent_id: str, name: str, content: bytes
    ) -> DriveNodeMetadata:
        pass

    @abstractmethod
    def upload_local_file_to_drive(
        self, file_id: str, local_file_path: str
    ) -> DriveNodeMetadata:
        pass

    @abstractmethod
    def create_folder(self, parent_id: str, name: str) -> DriveNodeMetadata: ...

    @abstractmethod
    def delete_file(self, file_id: str) -> None: ...


class IMetadataCache(ABC):

    @abstractmethod
    def resolve_path_to_node_id(self, path: str) -> Optional[str]: ...

    @abstractmethod
    def map_path_to_node_id(self, path: str, file_id: str) -> None: ...

    @abstractmethod
    def get_metadata(self, file_id: str) -> Optional[DriveNodeMetadata]: ...

    @abstractmethod
    def set_metadata(self, file_id: str, meta: DriveNodeMetadata) -> None:
        pass

    @abstractmethod
    def is_directory_children_loaded(self, dir_id: str) -> bool:
        pass

    @abstractmethod
    def mark_directory_children_loaded(self, dir_id: str) -> None:
        pass

    @abstractmethod
    def get_children_paths(self, parent_path: str) -> List[str]: ...

    @abstractmethod
    def invalidate_path(self, path: str) -> None: ...
