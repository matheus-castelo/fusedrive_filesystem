from unittest.mock import MagicMock

import pytest

from src.domain.contracts.interfaces import DriveNodeMetadata


def _fake_file(file_id="f1", name="doc.txt"):
    return DriveNodeMetadata(
        file_id=file_id,
        name=name,
        is_directory=False,
        size=42,
        modified_at_timestamp=1.0,
    )


def _fake_folder(file_id="d1", name="pasta"):
    return DriveNodeMetadata(
        file_id=file_id, name=name, is_directory=True, size=0, modified_at_timestamp=1.0
    )


class TestDriveClientListChildren:
    def test_list_parses_files_and_folders(self):
        from src.infrastructure.drive.drive_client import GoogleDriveStorageClient

        client = GoogleDriveStorageClient.__new__(GoogleDriveStorageClient)
        mock_service = MagicMock()
        client._get_service = MagicMock(return_value=mock_service)

        mock_service.files().list().execute.return_value = {
            "files": [
                {
                    "id": "f1",
                    "name": "doc.txt",
                    "mimeType": "text/plain",
                    "size": "100",
                },
                {
                    "id": "d1",
                    "name": "pasta",
                    "mimeType": "application/vnd.google-apps.folder",
                },
            ]
        }

        results = client.list_children("root")
        assert len(results) == 2
        assert results[0].name == "doc.txt"
        assert results[0].is_directory is False
        assert results[0].size == 100
        assert results[1].name == "pasta"
        assert results[1].is_directory is True

    def test_list_empty_returns_empty(self):
        from src.infrastructure.drive.drive_client import GoogleDriveStorageClient

        client = GoogleDriveStorageClient.__new__(GoogleDriveStorageClient)
        mock_service = MagicMock()
        client._get_service = MagicMock(return_value=mock_service)

        mock_service.files().list().execute.return_value = {"files": []}
        assert client.list_children("root") == []


class TestDriveClientGetContent:
    def test_get_file_content_returns_bytes(self):
        from src.infrastructure.drive.drive_client import GoogleDriveStorageClient

        client = GoogleDriveStorageClient.__new__(GoogleDriveStorageClient)
        mock_service = MagicMock()
        client._get_service = MagicMock(return_value=mock_service)

        mock_service.files().get_media().execute.return_value = b"hello world"
        data = client.get_file_content("f1")
        assert data == b"hello world"


class TestDriveClientDelete:
    def test_delete_calls_api(self):
        from src.infrastructure.drive.drive_client import GoogleDriveStorageClient

        client = GoogleDriveStorageClient.__new__(GoogleDriveStorageClient)
        mock_service = MagicMock()
        client._get_service = MagicMock(return_value=mock_service)

        client.delete_file("f1")
        mock_service.files().delete.assert_called_once_with(fileId="f1")

    def test_delete_raises_permission_error_on_403(self):
        from src.infrastructure.drive.drive_client import GoogleDriveStorageClient
        from googleapiclient.errors import HttpError
        from unittest.mock import Mock

        client = GoogleDriveStorageClient.__new__(GoogleDriveStorageClient)
        mock_service = MagicMock()
        client._get_service = MagicMock(return_value=mock_service)

        resp = Mock(status=403)
        error_content = (
            b'{"error": {"errors": [{"reason": "insufficientFilePermissions"}]}}'
        )
        mock_service.files().delete.return_value.execute.side_effect = HttpError(
            resp, error_content
        )

        with pytest.raises(PermissionError):
            client.delete_file("f1")
