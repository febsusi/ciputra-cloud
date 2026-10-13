import requests

class FirebaseError(Exception):
    pass

class FirebaseStore:
    """Small Firebase Realtime Database REST wrapper. Data is scoped by Firebase Auth UID."""
    def __init__(self, database_url, id_token=None, uid=None):
        self.database_url = (database_url or "").rstrip("/")
        self.id_token = id_token
        self.uid = uid
        if not self.database_url:
            raise FirebaseError("FIREBASE_DATABASE_URL belum diisi di file .env.")

    def _url(self, path):
        if not self.uid:
            raise FirebaseError("UID pengguna tidak tersedia.")
        path = path.strip("/")
        return f"{self.database_url}/users/{self.uid}/{path}.json"

    def _request(self, method, path, payload=None):
        url = self._url(path)
        params = {"auth": self.id_token} if self.id_token else {}
        try:
            r = requests.request(method, url, params=params, json=payload, timeout=20)
            if r.status_code >= 400:
                if r.status_code in (401, 403):
                    raise FirebaseError(
                        "Firebase Realtime Database menolak akses (401/403 Permission denied). "
                        "Pastikan URL database persis dari Firebase Console, Rules sudah di-Publish, "
                        "user sudah login dan email terverifikasi, serta token belum kedaluwarsa. "
                        f"Detail Firebase: {r.text[:180]}"
                    )
                raise FirebaseError(f"Firebase Realtime Database error ({r.status_code}): {r.text[:300]}")
            return r.json() if r.text else None
        except requests.RequestException as e:
            raise FirebaseError(f"Gagal terhubung ke Firebase Realtime Database: {e}")

    def get(self, path):
        return self._request("GET", path)

    def put(self, path, data):
        return self._request("PUT", path, data)

    def delete(self, path):
        return self._request("DELETE", path)

    def list(self, path):
        data = self.get(path)
        if not isinstance(data, dict):
            return []
        result = []
        for key, value in data.items():
            if isinstance(value, dict):
                value.setdefault("id", key)
                result.append(value)
        return result
