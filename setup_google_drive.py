"""One-time local OAuth setup for Google Drive storage used by Railway.

1. Enable Google Drive API in Google Cloud Console.
2. Configure OAuth consent screen and create an OAuth Client ID of type Desktop app.
3. Download the OAuth client JSON and save it as credentials.json in this folder.
4. Run: python setup_google_drive.py
5. Copy the printed GOOGLE_DRIVE_FOLDER_ID and GOOGLE_DRIVE_TOKEN_JSON_B64 to Railway Variables.
"""
import base64
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BASE = Path(__file__).resolve().parent
CLIENT_FILE = Path(os.getenv("GOOGLE_OAUTH_CLIENT_FILE", str(BASE / "credentials.json")))
TOKEN_FILE = BASE / "google_drive_token.json"
FOLDER_NAME = "AI Resume HR Uploads"


def main():
    if not CLIENT_FILE.exists():
        raise SystemExit(
            f"File OAuth client tidak ditemukan: {CLIENT_FILE}\n"
            "Download OAuth Client ID (Desktop app) JSON dari Google Cloud Console, "
            "lalu simpan sebagai credentials.json."
        )

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        try:
            TOKEN_FILE.chmod(0o600)
        except OSError:
            pass

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    # Reuse the existing folder created by this OAuth app when rerunning setup.
    escaped = FOLDER_NAME.replace("'", "\\'")
    response = service.files().list(
        q=f"name = '{escaped}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id,name,createdTime)",
        pageSize=100,
        orderBy="createdTime",
    ).execute()
    folders = response.get("files", [])
    if folders:
        folder_id = folders[0]["id"]
    else:
        folder = service.files().create(
            body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
            fields="id,name",
        ).execute()
        folder_id = folder["id"]

    token_json = creds.to_json()
    token_b64 = base64.b64encode(token_json.encode("utf-8")).decode("ascii")
    print("\nSetup Google Drive berhasil. Jangan commit token atau credentials ke GitHub.\n")
    print("Tambahkan dua variable berikut di Railway → Variables:\n")
    print("GOOGLE_DRIVE_FOLDER_ID=" + folder_id)
    print("GOOGLE_DRIVE_TOKEN_JSON_B64=" + token_b64)
    print("\nFolder Drive dibuat privat; jangan membagikannya secara publik.")
    print("OAuth token lokal tersimpan di google_drive_token.json. Jaga kerahasiaannya.\n")
    print("PENTING: jika OAuth consent screen berstatus Testing, refresh token untuk akun Gmail eksternal dapat kedaluwarsa setelah 7 hari.")
    print("Untuk deployment berkelanjutan, konfigurasi publishing status/verification yang sesuai di Google Cloud Console.\n")


if __name__ == "__main__":
    main()
