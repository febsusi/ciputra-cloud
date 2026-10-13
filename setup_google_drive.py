
import json
import os

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    if not os.path.exists("credentials.json"):
        raise SystemExit(
            "credentials.json tidak ditemukan. "
            "Download OAuth Client Desktop JSON dari Google Cloud."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json",
        SCOPES,
    )

    creds = flow.run_local_server(port=0)

    drive = build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )

    # Create the folder using the same OAuth client and account.
    folder = drive.files().create(
        body={
            "name": "AI Resume HR Private Storage",
            "mimeType": "application/vnd.google-apps.folder",
        },
        fields="id,name",
    ).execute()

    # This file contains secrets. Never commit it to Git.
    with open("token.json", "w", encoding="utf-8") as f:
        json.dump(
            json.loads(creds.to_json()),
            f,
            indent=2,
        )

    client_config = json.load(
        open("credentials.json", encoding="utf-8")
    )
    client = (
        client_config.get("installed")
        or client_config.get("web")
        or {}
    )

    print("\nSetup selesai.")
    print("GOOGLE_CLIENT_ID =", client.get("client_id", ""))
    print("GOOGLE_CLIENT_SECRET =", client.get("client_secret", ""))
    print("GOOGLE_DRIVE_FOLDER_ID =", folder["id"])

    if not creds.refresh_token:
        print(
            "\nPERINGATAN: refresh_token tidak diterima. "
            "Periksa consent dan konfigurasi OAuth sebelum deploy."
        )
    else:
        print(
            "\nRefresh token tersimpan di token.json. "
            "Buka file itu secara lokal untuk mengambil refresh_token."
        )
        print(
            "Jangan membagikan token.json atau mengunggahnya ke GitHub."
        )


if __name__ == "__main__":
    main()
