# supabase_storage.py
import os
import logging

try:
    from supabase import create_client, Client
except ImportError as e:
    raise ImportError(
        "Library 'supabase' belum terpasang. Jalankan: pip install supabase"
    ) from e


class SupabaseStorageError(Exception):
    """Error khusus untuk operasi Supabase Storage."""


class SupabaseStorage:
    """
    Wrapper sederhana untuk Supabase Storage dengan interface kompatibel
    dengan GoogleDriveStorage (upload/delete) sehingga app.py tidak perlu
    banyak berubah.

    Struktur path:
        {uid}/{category}/{object_id}/{filename}

    Contoh:
        abc123/resumes/xyz789/cv_budi.pdf
        abc123/hr-policy/doc001/kebijakan.pdf
    """

    def __init__(self, url: str | None = None, key: str | None = None, bucket: str | None = None):
        self.url = url or os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = (
            key
            or os.getenv("SUPABASE_SERVICE_KEY", "")
            or os.getenv("SUPABASE_KEY", "")
        )
        self.bucket = bucket or os.getenv("SUPABASE_BUCKET", "hr-files")

        if not self.url or not self.key:
            raise SupabaseStorageError(
                "SUPABASE_URL dan SUPABASE_SERVICE_KEY (atau SUPABASE_KEY) wajib diisi di .env."
            )

        self.client: Client = create_client(self.url, self.key)
        self._ensure_bucket()

    # ---------- internal ----------
    def _ensure_bucket(self):
        """Buat bucket bila belum ada (private)."""
        try:
            self.client.storage.get_bucket(self.bucket)
        except Exception:
            try:
                self.client.storage.create_bucket(
                    self.bucket, options={"public": False}
                )
            except Exception as e:
                # Bisa jadi karena RLS / permission; tetap lanjut saja.
                logging.warning(f"[SupabaseStorage] Gagal membuat bucket '{self.bucket}': {e}")

    @staticmethod
    def _safe_name(name: str) -> str:
        return name.replace("/", "_").replace("\\", "_").strip() or "file"

    def _build_path(self, uid: str, category: str, object_id: str, filename: str) -> str:
        return f"{uid}/{category}/{object_id}/{self._safe_name(filename)}"

    # ---------- public API ----------
    def upload(
        self,
        uid: str,
        category: str,
        object_id: str,
        original_filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        id_token: str | None = None,   # tidak dipakai, hanya untuk kompatibilitas
    ) -> str:
        """Upload file, kembalikan storage path di Supabase."""
        path = self._build_path(uid, category, object_id, original_filename)
        try:
            self.client.storage.from_(self.bucket).upload(
                path=path,
                file=data,
                file_options={
                    "content-type": content_type or "application/octet-stream",
                    "upsert": "true",
                },
            )
        except Exception as e:
            raise SupabaseStorageError(f"Gagal upload ke Supabase Storage: {e}")
        return path

    def delete(self, path: str, id_token: str | None = None, uid: str | None = None) -> None:
        """Hapus file dari Supabase Storage. Tidak error bila file tidak ada."""
        if not path:
            return
        try:
            self.client.storage.from_(self.bucket).remove([path])
        except Exception as e:
            # Jangan crash proses utama; cukup catat.
            logging.warning(f"[SupabaseStorage] Gagal menghapus '{path}': {e}")

    def get_signed_url(self, path: str, expires_in: int = 3600) -> str | None:
        """Buat signed URL sementara untuk file private."""
        if not path:
            return None
        try:
            res = self.client.storage.from_(self.bucket).create_signed_url(path, expires_in)
            return res.get("signedURL") or res.get("signedUrl")
        except Exception as e:
            raise SupabaseStorageError(f"Gagal membuat signed URL: {e}")

    def download(self, path: str) -> bytes:
        """Ambil isi file (untuk validasi/backup)."""
        try:
            return self.client.storage.from_(self.bucket).download(path)
        except Exception as e:
            raise SupabaseStorageError(f"Gagal mengunduh file dari Supabase: {e}")
