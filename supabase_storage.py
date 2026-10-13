
import os
import uuid
from pathlib import Path
from supabase import create_client


class SupabaseStorageError(Exception):
    pass


class SupabaseFileStorage:
    def __init__(self):
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        self.bucket = os.getenv(
            "SUPABASE_BUCKET", "resume-files"
        ).strip()

        if not url or not key:
            raise SupabaseStorageError(
                "SUPABASE_URL atau SUPABASE_SERVICE_KEY belum diatur."
            )

        self.client = create_client(url, key)

    def upload(
        self,
        uid,
        category,
        object_id,
        original_filename,
        data,
        content_type=None,
        id_token=None,
    ):
        # Buat path unik untuk setiap file.
        safe_name = Path(original_filename).name
        safe_name = safe_name.replace("/", "_").replace("\\", "_")
        path = (
            f"{uid}/{category}/{object_id}/"
            f"{uuid.uuid4().hex}_{safe_name}"
        )

        try:
            self.client.storage.from_(self.bucket).upload(
                path=path,
                file=data,
                file_options={
                    "content-type": (
                        content_type or "application/octet-stream"
                    ),
                    "upsert": "false",
                },
            )
            return path
        except Exception as exc:
            raise SupabaseStorageError(
                f"Gagal upload file ke Supabase: {exc}"
            ) from exc

    def delete(self, storage_path, **kwargs):
        if not storage_path:
            return

        try:
            self.client.storage.from_(self.bucket).remove(
                [storage_path]
            )
        except Exception as exc:
            raise SupabaseStorageError(
                f"Gagal menghapus file dari Supabase: {exc}"
            ) from exc
