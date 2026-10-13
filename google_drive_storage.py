"""Private Google Drive storage adapter for Railway deployments.

Files are uploaded by a dedicated Google account authorized through OAuth.
The app never creates public sharing permissions. Firebase remains the identity
and metadata database; Drive stores the binary file contents.
"""
import base64
import io
import json
import os
from functools import lru_cache

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

# drive.file is intentionally narrower than full Drive access. The setup script
# creates the storage folder using this same OAuth client, so the app can access it.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveStorageError(Exception):
    pass


class GoogleDriveStorage:
    def __init__(self, folder_id=""):
        self.folder_id = (folder_id or "").strip()

    def _service(self):
        encoded = os.getenv("GOOGLE_DRIVE_TOKEN_JSON_B64", "").strip()
        if not encoded:
            raise GoogleDriveStorageError(
                "Google Drive belum dikonfigurasi. Jalankan setup_google_drive.py dan isi "
                "GOOGLE_DRIVE_TOKEN_JSON_B64 serta GOOGLE_DRIVE_FOLDER_ID di Railway Variables."
            )
        if not self.folder_id:
            raise GoogleDriveStorageError("GOOGLE_DRIVE_FOLDER_ID belum diatur di Railway Variables.")
        try:
            token_info = json.loads(base64.b64decode(encoded).decode("utf-8"))
            creds = Credentials.from_authorized_user_info(token_info, scopes=SCOPES)
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    raise GoogleDriveStorageError(
                        "Token Google Drive tidak valid atau tidak memiliki refresh token. Jalankan ulang setup_google_drive.py."
                    )
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        except GoogleDriveStorageError:
            raise
        except Exception as exc:
            raise GoogleDriveStorageError(
                "Gagal menginisialisasi Google Drive. Periksa token OAuth dan konfigurasi Railway."
            ) from exc

    def upload(self, uid, category, object_id, original_filename, data, content_type, id_token=None):
        if not uid:
            raise GoogleDriveStorageError("UID pengguna tidak tersedia; file tidak diunggah.")
        if not data:
            raise GoogleDriveStorageError("File kosong tidak dapat diunggah.")
        service = self._service()
        metadata = {
            "name": original_filename,
            "mimeType": content_type or "application/octet-stream",
            "parents": [self.folder_id],
            "appProperties": {
                "owner_uid": str(uid),
                "category": str(category),
                "object_id": str(object_id),
                "app": "ai-resume-hr-platform",
            },
        }
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype=content_type or "application/octet-stream",
            resumable=False,
        )
        try:
            created = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType",
            ).execute(num_retries=2)
            # The path is an opaque internal identifier, not a public URL.
            return "gdrive:" + created["id"]
        except HttpError as exc:
            status = getattr(exc.resp, "status", "?")
            if status in (401, 403):
                raise GoogleDriveStorageError(
                    "Google Drive menolak akses. Periksa token OAuth, izin Drive API, dan folder tujuan."
                ) from exc
            raise GoogleDriveStorageError(f"Upload Google Drive gagal (HTTP {status}).") from exc
        except GoogleDriveStorageError:
            raise
        except Exception as exc:
            raise GoogleDriveStorageError("Gagal mengunggah file ke Google Drive.") from exc

    def delete(self, storage_path, id_token=None, uid=None):
        if not storage_path:
            return
        # Gracefully ignore legacy Firebase Storage paths during provider migration.
        # This app will not delete a file from a different provider.
        if not str(storage_path).startswith("gdrive:"):
            return
        file_id = str(storage_path)[len("gdrive:"):]
        if not file_id:
            return
        service = self._service()
        try:
            # Verify the file belongs to the current UID before deletion.
            existing = service.files().get(
                fileId=file_id,
                fields="id,appProperties,trashed",
            ).execute()
            properties = existing.get("appProperties") or {}
            if uid and properties.get("owner_uid") != str(uid):
                raise GoogleDriveStorageError("Akses ditolak: file Google Drive bukan milik pengguna ini.")
            service.files().delete(fileId=file_id).execute()
        except GoogleDriveStorageError:
            raise
        except HttpError as exc:
            status = getattr(exc.resp, "status", "?")
            if status == 404:
                return
            if status in (401, 403):
                raise GoogleDriveStorageError(
                    "Google Drive menolak penghapusan. Periksa token OAuth dan izin file."
                ) from exc
            raise GoogleDriveStorageError(f"Penghapusan Google Drive gagal (HTTP {status}).") from exc
        except Exception as exc:
            raise GoogleDriveStorageError("Gagal menghapus file dari Google Drive.") from exc
