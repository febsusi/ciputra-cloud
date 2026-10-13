
"""Google Drive storage for Flask applications on Railway.

OAuth configuration uses separate environment variables:
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REFRESH_TOKEN
GOOGLE_DRIVE_FOLDER_ID

The app does not create public sharing permissions.
"""

import os
import threading

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveStorageError(Exception):
    """Safe, user-displayable Google Drive error."""


class GoogleDriveStorage:
    def __init__(self, folder_id=""):
        # Never perform OAuth network requests during Flask startup.
        self.folder_id = (folder_id or "").strip()
        self._credentials = None
        self._service_instance = None
        self._lock = threading.RLock()

    def _service(self):
        """Create the Drive client lazily and refresh OAuth credentials."""
        with self._lock:
            client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
            refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()

            missing = [
                name for name, value in (
                    ("GOOGLE_CLIENT_ID", client_id),
                    ("GOOGLE_CLIENT_SECRET", client_secret),
                    ("GOOGLE_REFRESH_TOKEN", refresh_token),
                    ("GOOGLE_DRIVE_FOLDER_ID", self.folder_id),
                )
                if not value
            ]

            if missing:
                raise GoogleDriveStorageError(
                    "Google Drive belum dikonfigurasi. Variabel yang kosong: "
                    + ", ".join(missing)
                )

            try:
                if self._credentials is None:
                    self._credentials = Credentials(
                        token=None,
                        refresh_token=refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=SCOPES,
                    )

                # Refresh automatically when the access token is expired.
                if not self._credentials.valid:
                    if not self._credentials.refresh_token:
                        raise GoogleDriveStorageError(
                            "Refresh token tidak tersedia. "
                            "Buat ulang OAuth token."
                        )

                    self._credentials.refresh(Request())

                if self._service_instance is None:
                    self._service_instance = build(
                        "drive",
                        "v3",
                        credentials=self._credentials,
                        cache_discovery=False,
                    )

                return self._service_instance

            except GoogleDriveStorageError:
                raise
            except Exception as exc:
                # Do not log credentials, token JSON, or client secrets.
                error_type = type(exc).__name__
                error_text = str(exc)[:300]

                print(
                    f"[Google Drive] OAuth initialization failed: "
                    f"{error_type}: {error_text}",
                    flush=True,
                )

                raise GoogleDriveStorageError(
                    "Google Drive gagal diinisialisasi. Periksa "
                    "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                    "GOOGLE_REFRESH_TOKEN, dan log Railway."
                ) from exc

    @staticmethod
    def _file_id(storage_path):
        value = str(storage_path or "")
        if value.startswith("gdrive:"):
            return value[len("gdrive:"):]
        return ""

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
        if not uid:
            raise GoogleDriveStorageError(
                "UID pengguna tidak tersedia."
            )

        if not data:
            raise GoogleDriveStorageError("File yang diunggah kosong.")

        if not self.folder_id:
            raise GoogleDriveStorageError(
                "GOOGLE_DRIVE_FOLDER_ID belum diatur."
            )

        service = self._service()
        filename = os.path.basename(original_filename or "resume")
        mime_type = content_type or "application/octet-stream"

        metadata = {
            "name": filename,
            "mimeType": mime_type,
            "parents": [self.folder_id],
            "appProperties": {
                "owner_uid": str(uid),
                "category": str(category),
                "object_id": str(object_id),
                "app": "ai-resume-hr-platform",
            },
        }

        media = MediaIoBaseUpload(
            __import__("io").BytesIO(data),
            mimetype=mime_type,
            resumable=False,
        )

        try:
            result = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name",
            ).execute(num_retries=2)

            return "gdrive:" + result["id"]

        except HttpError as exc:
            status = getattr(exc.resp, "status", 0)

            print(
                f"[Google Drive] Upload failed: HTTP {status}",
                flush=True,
            )

            if status == 401:
                message = (
                    "Autentikasi Google Drive ditolak. "
                    "Periksa refresh token dan OAuth Client."
                )
            elif status == 403:
                message = (
                    "Google Drive menolak upload. Periksa Drive API, "
                    "scope OAuth, serta izin folder."
                )
            elif status == 404:
                message = (
                    "Folder Google Drive tidak ditemukan atau "
                    "tidak dapat diakses."
                )
            else:
                message = f"Upload Google Drive gagal (HTTP {status or 'unknown'})."

            raise GoogleDriveStorageError(message) from exc

        except GoogleDriveStorageError:
            raise

        except Exception as exc:
            print(
                f"[Google Drive] Upload error: {type(exc).__name__}",
                flush=True,
            )
            raise GoogleDriveStorageError(
                "Terjadi kesalahan saat mengunggah CV ke Google Drive."
            ) from exc

    def delete(self, storage_path, id_token=None, uid=None):
        if not storage_path:
            return

        # Ignore legacy paths belonging to other storage providers.
        file_id = self._file_id(storage_path)
        if not file_id:
            return

        service = self._service()

        try:
            existing = service.files().get(
                fileId=file_id,
                fields="id,appProperties,trashed",
            ).execute()

            properties = existing.get("appProperties") or {}

            # Do not delete a file belonging to another user.
            if uid is not None and properties.get("owner_uid") != str(uid):
                raise GoogleDriveStorageError(
                    "Penghapusan ditolak: file bukan milik pengguna ini."
                )

            service.files().delete(
                fileId=file_id,
            ).execute(num_retries=2)

        except GoogleDriveStorageError:
            raise

        except HttpError as exc:
            status = getattr(exc.resp, "status", 0)

            if status == 404:
                return

            print(
                f"[Google Drive] Delete failed: HTTP {status}",
                flush=True,
            )

            if status in (401, 403):
                message = (
                    "Google Drive menolak penghapusan. "
                    "Periksa OAuth dan izin file."
                )
            else:
                message = (
                    f"Penghapusan Google Drive gagal "
                    f"(HTTP {status or 'unknown'})."
                )

            raise GoogleDriveStorageError(message) from exc

        except Exception as exc:
            print(
                f"[Google Drive] Delete error: {type(exc).__name__}",
                flush=True,
            )
            raise GoogleDriveStorageError(
                "Terjadi kesalahan saat menghapus file Google Drive."
            ) from exc
