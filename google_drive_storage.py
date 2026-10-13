import os
import io

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError


class GoogleDriveStorageError(Exception):
    pass


class GoogleDriveStorage:
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, folder_id):
        self.folder_id = (folder_id or "").strip()
        self.service = None

        if not self.folder_id:
            raise GoogleDriveStorageError(
                "GOOGLE_DRIVE_FOLDER_ID belum diatur di Railway."
            )

        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()

        if not client_id or not client_secret or not refresh_token:
            raise GoogleDriveStorageError(
                "OAuth Google Drive belum lengkap. Periksa "
                "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "dan GOOGLE_REFRESH_TOKEN."
            )

        try:
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=self.SCOPES,
            )

            credentials.refresh(Request())

            self.service = build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )

            # Verify that the configured folder is accessible.
            self.service.files().get(
                fileId=self.folder_id,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            ).execute()

        except Exception as exc:
            self.service = None
            raise GoogleDriveStorageError(
                "Gagal menginisialisasi Google Drive. "
                "Periksa OAuth, refresh token, izin folder, "
                "dan konfigurasi Railway."
            ) from exc

    def upload(
        self,
        uid,
        category,
        object_id,
        original_filename,
        data,
        content_type,
        id_token=None,
    ):
        if not self.service:
            raise GoogleDriveStorageError(
                "Koneksi Google Drive belum tersedia."
            )

        # Separate files by user and category.
        safe_name = os.path.basename(original_filename)
        filename = f"{object_id}_{safe_name}"

        metadata = {
            "name": filename,
            "mimeType": content_type,
            "parents": [self.folder_id],
            "appProperties": {
                "uid": str(uid),
                "category": str(category),
                "object_id": str(object_id),
            },
        }

        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype=content_type,
            resumable=True,
        )

        try:
            result = self.service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()

            # Store the Drive file ID, not a public URL.
            return result["id"]

        except HttpError as exc:
            raise GoogleDriveStorageError(
                "Gagal mengunggah file ke Google Drive."
            ) from exc

    def delete(self, storage_path, id_token=None, uid=None):
        if not self.service or not storage_path:
            return

        try:
            # Verify ownership before deleting.
            result = self.service.files().get(
                fileId=storage_path,
                fields="id,appProperties",
                supportsAllDrives=True,
            ).execute()

            properties = result.get("appProperties", {})
            if uid is not None and properties.get("uid") != str(uid):
                raise GoogleDriveStorageError(
                    "Tidak memiliki izin menghapus file ini."
                )

            self.service.files().delete(
                fileId=storage_path,
                supportsAllDrives=True,
            ).execute()

        except GoogleDriveStorageError:
            raise
        except HttpError as exc:
            raise GoogleDriveStorageError(
                "Gagal menghapus file Google Drive."
            ) from exc
