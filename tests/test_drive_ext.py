import os
from unittest.mock import MagicMock, patch

import pytest

from src.domain.contracts.interfaces import DriveNodeMetadata
from src.infrastructure.drive.drive_client import GoogleDriveStorageClient


def test_drive_client_init_and_methods(tmp_path):
    cred_file = tmp_path / "cred.json"
    cred_file.write_text('{"installed": {}}')

    with patch("src.infrastructure.drive.drive_client.Credentials"), patch(
        "google_auth_oauthlib.flow.InstalledAppFlow"
    ) as flow_mock, patch("google.auth.transport.requests.Request"), patch(
        "src.infrastructure.drive.drive_client.build"
    ) as build_mock:

        flow_mock.from_client_secrets_file.return_value.run_local_server.return_value.to_json.return_value = (
            "{}"
        )

        # Mocking the service
        service_mock = MagicMock()
        build_mock.return_value = service_mock

        client = GoogleDriveStorageClient(str(cred_file))
        assert client._get_service() == service_mock

        # list_children
        service_mock.files().list().execute.return_value = {
            "files": [
                {
                    "id": "1",
                    "name": "folder1",
                    "mimeType": "application/vnd.google-apps.folder",
                    "size": "0",
                    "modifiedTime": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "2",
                    "name": "file1.txt",
                    "mimeType": "text/plain",
                    "size": "100",
                    "modifiedTime": "2026-01-01T00:00:00Z",
                },
            ]
        }
        children = client.list_children("root")
        assert len(children) == 2
        assert children[0].is_directory == True
        assert children[1].is_directory == False

        # get_file_content
        service_mock.files().get_media().execute.return_value = b"full_content"
        assert client.get_file_content("2") == b"full_content"

        # download_file_chunk_from_api
        mock_req = MagicMock()
        service_mock.files().get_media.return_value = mock_req
        mock_req.headers = {}
        mock_req.uri = "http://mock.uri"

        with patch("google_auth_httplib2.AuthorizedHttp.request") as mock_http_request:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_http_request.return_value = (mock_resp, b"chunk")
            assert client.download_file_chunk_from_api("2", 0, 4) == b"chunk"
        assert mock_req.headers["Range"] == "bytes=0-4"

        # upload_new_file_to_drive
        service_mock.files().create().execute.return_value = {
            "id": "3",
            "name": "new.txt",
            "mimeType": "text/plain",
            "size": "10",
            "modifiedTime": "2026-01-01T00:00:00Z",
        }
        node_metadata = client.upload_new_file_to_drive(
            "root", "new.txt", b"0123456789"
        )
        assert node_metadata.file_id == "3"

        # create_folder
        service_mock.files().create().execute.return_value = {
            "id": "4",
            "name": "new_folder",
            "mimeType": "application/vnd.google-apps.folder",
            "size": "0",
            "modifiedTime": "2026-01-01T00:00:00Z",
        }
        node_metadata = client.create_folder("root", "new_folder")
        assert node_metadata.file_id == "4"
        assert node_metadata.is_directory == True

        # delete_file
        client.delete_file("4")
        service_mock.files().delete.assert_called_with(fileId="4")


def test_drive_client_update_file(tmp_path):
    cred_file = tmp_path / "cred.json"
    cred_file.write_text('{"installed": {}}')

    with patch("src.infrastructure.drive.drive_client.Credentials"), patch(
        "google_auth_oauthlib.flow.InstalledAppFlow"
    ) as flow_mock, patch("google.auth.transport.requests.Request"), patch(
        "src.infrastructure.drive.drive_client.build"
    ) as build_mock:

        flow_mock.from_client_secrets_file.return_value.run_local_server.return_value.to_json.return_value = (
            "{}"
        )

        service_mock = MagicMock()
        build_mock.return_value = service_mock
        service_mock.files().update().execute.return_value = {
            "id": "1",
            "name": "file1.txt",
            "mimeType": "text/plain",
            "size": "20",
            "modifiedTime": "2026-01-01T00:00:00Z",
        }

        client = GoogleDriveStorageClient(str(cred_file))
        node_metadata = client.upload_local_file_to_drive("1", str(cred_file))
        assert node_metadata.file_id == "1"
        assert node_metadata.size == 20
