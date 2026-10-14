# Firebase AI Resume Ranker (Flask)

Aplikasi rekrutmen dengan:
- Firebase Authentication (register/login) dan verifikasi email Firebase.
- Firebase Realtime Database untuk data lowongan, kandidat, dan riwayat ranking.
- CRUD lowongan, kandidat, dan riwayat ranking.
- AI resume ranker berbasis TF-IDF/cosine similarity + Logistic Regression baseline.
- AI ekstraksi skill, pendidikan, estimasi pengalaman, dan ringkasan singkat.
- Computer vision OCR untuk gambar CV serta OCR fallback untuk PDF scan (OpenCV + Tesseract).
- Ekspor hasil ranking ke CSV.
- AI Policy Assistant : unggah PDF/DOCX/TXT dan cari kutipan kebijakan menggunakan TF-IDF + cosine similarity.

```bash
pip install -r requirements.txt
```

# Konfigurasi Railway

- `FLASK_SECRET_KEY`: secret acak yang panjang, minimal 32 byte.
- `FLASK_DEBUG`: `false`.
- `SESSION_COOKIE_SECURE`: `true`.
- `FIREBASE_API_KEY`: Web API key Firebase, bukan private key service account.
- `FIREBASE_DATABASE_URL`: URL Realtime Database persis dari Firebase Console.
- `SUPABASE_URL`
