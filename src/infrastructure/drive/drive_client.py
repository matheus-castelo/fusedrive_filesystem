import io
import threading
import time
from typing import List

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError, ResumableUploadError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.domain.contracts.interfaces import DriveNodeMetadata, IStorageClient

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


from tenacity import retry_if_exception


def _is_retryable(exception):
    if isinstance(exception, HttpError):
        if exception.resp.status == 404:
            return False
        if exception.resp.status == 403:
            try:
                import json

                content = json.loads(exception.content.decode("utf-8"))
                errors = content.get("error", {}).get("errors", [])
                for err in errors:
                    reason = err.get("reason")
                    if reason == "storageQuotaExceeded":
                        from src.infrastructure.drive.circuit_breaker import (
                            GoogleDriveQuotaCircuitBreaker,
                        )

                        GoogleDriveQuotaCircuitBreaker().trip()
                        return False
                    if reason == "insufficientFilePermissions":
                        return False
            except ValueError:
                pass
    return isinstance(exception, (HttpError, ResumableUploadError))


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(_is_retryable),
)
def _execute_with_retry(request):
    return request.execute()


class GoogleDriveStorageClient(IStorageClient):
    def __init__(self, credentials_path: str):
        import json
        import os

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        with open(credentials_path, "r") as f:
            data = json.load(f)

        if data.get("type") == "service_account":
            self._creds = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=SCOPES
            )
        else:

            creds = None
            token_path = os.path.join(os.path.dirname(credentials_path), "token.json")

            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                with open(token_path, "w") as token:
                    token.write(creds.to_json())

            self._creds = creds

        self._local = threading.local()

    def _get_service(self):
        if not hasattr(self._local, "service"):
            self._local.service = build(
                "drive", "v3", credentials=self._creds, cache_discovery=False
            )
        return self._local.service

    def _map_google_api_file_to_metadata(self, f: dict) -> DriveNodeMetadata:
        is_directory = f.get("mimeType") == FOLDER_MIME
        size = int(f.get("size", 0))
        mtime_str = f.get("modifiedTime")

        modified_at_timestamp = time.time()
        if mtime_str:
            import datetime

            dt = datetime.datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
            modified_at_timestamp = dt.timestamp()

        return DriveNodeMetadata(
            file_id=f.get("id", ""),
            name=f.get("name", ""),
            is_directory=is_directory,
            size=size,
            modified_at_timestamp=modified_at_timestamp,
        )

    def list_children(self, parent_id: str) -> List[DriveNodeMetadata]:
        all_files = []
        page_token = None
        while True:
            query = f"'{parent_id }' in parents and trashed = false"
            request = (
                self._get_service()
                .files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageSize=1000,
                    pageToken=page_token,
                )
            )
            response = _execute_with_retry(request)
            all_files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [self._map_google_api_file_to_metadata(f) for f in all_files]

    def get_file_content(self, file_id: str) -> bytes:
        request = self._get_service().files().get_media(fileId=file_id)
        return _execute_with_retry(request)

    def download_file_chunk_from_api(self, file_id: str, start: int, end: int) -> bytes:
        import google_auth_httplib2
        import httplib2

        request = self._get_service().files().get_media(fileId=file_id)
        request.headers["Range"] = f"bytes={start }-{end }"

        http = google_auth_httplib2.AuthorizedHttp(
            self._creds, http=httplib2.Http(timeout=30)
        )

        @retry(
            wait=wait_exponential(multiplier=1, min=1, max=10),
            stop=stop_after_attempt(5),
        )
        def _fetch():
            return http.request(request.uri, method="GET", headers=request.headers)

        resp, content = _fetch()
        if resp.status in [200, 206]:
            return content
        raise RuntimeError(f"Error fetching chunk: {resp .status } - {content }")

    def upload_new_file_to_drive(
        self, parent_id: str, name: str, content: bytes
    ) -> DriveNodeMetadata:
        body = {"name": name, "parents": [parent_id]}
        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype="application/octet-stream"
        )
        request = (
            self._get_service()
            .files()
            .create(body=body, media_body=media, fields="id,name,mimeType,size")
        )
        result = _execute_with_retry(request)
        return self._map_google_api_file_to_metadata(result)

    def upload_local_file_to_drive(
        self, file_id: str, local_file_path: str
    ) -> DriveNodeMetadata:
        import os

        size = os.path.getsize(local_file_path)
        use_resumable = size > 5 * 1024 * 1024

        media = MediaFileUpload(
            local_file_path,
            mimetype="application/octet-stream",
            resumable=use_resumable,
        )
        request = (
            self._get_service()
            .files()
            .update(fileId=file_id, media_body=media, fields="id,name,mimeType,size")
        )
        result = _execute_with_retry(request)
        return self._map_google_api_file_to_metadata(result)

    def create_folder(self, parent_id: str, name: str) -> DriveNodeMetadata:
        body = {"name": name, "parents": [parent_id], "mimeType": FOLDER_MIME}
        request = (
            self._get_service()
            .files()
            .create(body=body, fields="id,name,mimeType,size")
        )
        result = _execute_with_retry(request)
        return self._map_google_api_file_to_metadata(result)

    def delete_file(self, file_id: str) -> None:
        try:
            request = self._get_service().files().delete(fileId=file_id)
            _execute_with_retry(request)
        except HttpError as error:
            if error.resp.status == 403:
                raise PermissionError("insufficientFilePermissions") from error
            if error.resp.status == 404:
                raise FileNotFoundError("fileNotFound") from error
            raise OSError("API error") from error
