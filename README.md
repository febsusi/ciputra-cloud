# Firebase AI Resume Ranker (Flask)

Aplikasi rekrutmen dengan:
- Firebase Authentication (register/login) dan verifikasi email Firebase.
- Firebase Realtime Database untuk data lowongan, kandidat, dan riwayat ranking.
- CRUD lowongan, kandidat, dan riwayat ranking.
- AI resume ranking berbasis TF-IDF/cosine similarity + kecocokan skill + pendidikan + pengalaman + Logistic Regression baseline.
- AI ekstraksi skill, pendidikan, estimasi pengalaman, dan ringkasan singkat.
- Computer vision OCR untuk gambar CV serta OCR fallback untuk PDF scan (OpenCV + Tesseract).
- Ekspor hasil ranking ke CSV.
- Tidak membutuhkan `joblib` atau model hasil training; TF-IDF dihitung saat ranking, sehingga tidak ada model `.joblib`.

## 1. Siapkan Firebase

1. Buka Firebase Console dan buat project.
2. Authentication → Sign-in method → aktifkan **Email/Password**.
3. Authentication → Settings → Authorized domains: tambahkan domain deployment Anda bila dipakai online.
4. Authentication → Templates → Email address verification: atur nama pengirim, subjek, dan template email verifikasi. Firebase Authentication yang mengirim email; aplikasi tidak menyimpan password atau mengirim password lewat email.
5. Realtime Database → Create Database. Pilih region yang sesuai.
6. Project settings → General → Your apps → buat/ambil Web App config. Salin **Web API Key**.
7. Masukkan URL Realtime Database dan API key ke `.env`.
8. Realtime Database → Rules: salin isi `database.rules.json`, lalu Publish. Data tiap user tersimpan di `/users/{uid}` dan hanya UID yang login boleh membacanya.

> Jangan gunakan rules publik `".read": true` / `".write": true`. Jangan pernah taruh service-account private key atau password Firebase di source code.

## 2. Jalankan di Mac/Windows/Linux

Install Python 3.11 atau 3.12 disarankan.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, isi `FIREBASE_API_KEY` dan `FIREBASE_DATABASE_URL`, serta ganti `FLASK_SECRET_KEY`.

Lalu:
```bash
python app.py
```
Buka http://127.0.0.1:5000

## 3. OCR computer vision (opsional tetapi disarankan)

Untuk membaca gambar CV dan PDF hasil scan, pasang binary **Tesseract OCR** dan **Poppler** di sistem operasi, bukan hanya package Python.

macOS (Homebrew):
```bash
brew install tesseract poppler
```

Ubuntu/Debian:
```bash
sudo apt update
sudo apt install tesseract-ocr poppler-utils
```

Windows: install Tesseract OCR dan Poppler, lalu tambahkan folder executable ke PATH. PDF teks biasa tidak memerlukan OCR.

## 4. Alur fitur

- Register → Firebase membuat akun → Firebase mengirim email verifikasi.
- Login ditolak sampai email diverifikasi. Jika belum, aplikasi mencoba mengirim ulang tautan verifikasi setelah kredensial benar.
- Setelah login, semua data berada di Realtime Database per UID.
- Tambahkan lowongan dan kandidat. Upload CV PDF/DOCX/TXT atau gambar.
- Buka AI Ranking, pilih lowongan, dan hasil diberi skor serta penjelasan.
- Hasil ranking disimpan sebagai riwayat dan bisa diekspor CSV.

## Catatan AI

Skor adalah **alat bantu penyaringan**, bukan keputusan otomatis. TF-IDF/cosine similarity mengukur kemiripan teks; Logistic Regression di versi demo dilatih dari contoh fitur sintetis yang transparan, bukan data historis kandidat atau keputusan perekrut. Probabilitasnya bukan probabilitas sukses kerja dan tidak tervalidasi. Untuk produksi, ganti contoh sintetis dengan dataset berlabel yang sah, audit bias, dan lakukan evaluasi. Ekstraksi skill/pendidikan berbasis kamus dan pencocokan teks; hasil OCR bisa salah. Periksa CV asli dan evaluasi kandidat secara adil. Model ini tidak menginferensikan atribut sensitif. Pengalaman hanya diambil dari frasa eksplisit seperti “3 years experience”; tidak menghitung tanggal kerja secara otomatis.


## AI Tools tambahan
- **Skill Gap Analysis**: membandingkan skill CV dengan persyaratan lowongan, mengukur cakupan skill dan kemiripan teks TF-IDF, serta memberi saran penyempurnaan CV berdasarkan skill yang belum terdeteksi.
- **Deteksi CV Duplikat/Sangat Mirip**: TF-IDF + cosine similarity untuk menandai pasangan CV dengan teks yang mirip. Hasilnya hanya sinyal pemeriksaan manual, bukan bukti kecurangan.

Kedua fitur berjalan pada data kandidat dan lowongan milik akun yang sedang login. Akurasi ekstraksi skill bergantung pada daftar skill dan teks CV yang berhasil dibaca.
- **AI CV Quality Analyzer**: audit CV dengan rubrik heuristik yang transparan berdasarkan kelengkapan bagian, jumlah kata, kata kerja tindakan, dan bukti pencapaian terukur. Skor bukan prediksi keberhasilan kerja.
- **AI CV Consistency Checker**: menandai pola teks yang perlu diperiksa, seperti beberapa kontak, rentang tanggal terbalik/bertumpang tindih, dan perbedaan kasar antara klaim pengalaman dengan rentang tanggal. Temuan tidak membuktikan kecurangan dan wajib ditinjau manusia.


## Modul HR tambahan

- **HR Feedback AI** (`/hr-feedback`): klasifikasi sentimen positif/netral/negatif dengan TF-IDF + Logistic Regression, deteksi topik berbasis kata kunci, riwayat feedback tersimpan per UID Firebase. Model seed kecil hanya demonstrasi; kumpulkan label yang ditinjau manusia sebelum produksi.
- **HR Policy Assistant** (`/hr-policy`): unggah PDF/DOCX/TXT dan cari kutipan kebijakan menggunakan TF-IDF + cosine similarity. Sistem tidak membuat jawaban generatif; hasil selalu berupa potongan dokumen sumber.

Kedua modul berada di luar alur CV/Jobs. Feedback dan dokumen kebijakan tersimpan di bawah `users/{uid}/hr_feedback` dan `users/{uid}/hr_policy_docs`.

## 5. Deploy ke Railway dengan Google Drive sebagai penyimpanan file

Folder lokal Railway bersifat sementara. **Jangan menyimpan file upload permanen di folder `uploads/` lokal.** Versi ini menyimpan file CV dan dokumen HR langsung ke folder privat di Google Drive melalui Google Drive API. Firebase Authentication tetap digunakan untuk login dan Firebase Realtime Database tetap menyimpan data aplikasi serta metadata file. Firebase Storage tidak diperlukan.

### A. Aktifkan Google Drive API dan siapkan OAuth

1. Buka Google Cloud Console dan pilih/buat project.
2. Aktifkan **Google Drive API**.
3. Konfigurasikan OAuth consent screen. Tambahkan akun Google yang akan menjadi pemilik penyimpanan sebagai test user jika aplikasi masih dalam Testing.
4. Buat **OAuth Client ID → Desktop app**, lalu download JSON credentials.
5. Simpan file tersebut di folder proyek sebagai `credentials.json`. File ini hanya untuk setup lokal dan tidak boleh diunggah ke GitHub.
6. Instal dependensi lalu jalankan setup:

```bash
pip install -r requirements.txt
python setup_google_drive.py
```

7. Browser akan terbuka untuk login dan memberikan izin Drive. Script membuat folder `AI Resume HR Uploads` secara privat, lalu menampilkan dua variable Railway: `GOOGLE_DRIVE_FOLDER_ID` dan `GOOGLE_DRIVE_TOKEN_JSON_B64`.

### B. Konfigurasi Railway

Di Railway → service → **Variables**, isi:

- `FLASK_SECRET_KEY`: secret acak yang panjang, minimal 32 byte.
- `FLASK_DEBUG`: `false`.
- `SESSION_COOKIE_SECURE`: `true`.
- `FIREBASE_API_KEY`: Web API key Firebase, bukan private key service account.
- `FIREBASE_DATABASE_URL`: URL Realtime Database persis dari Firebase Console.
- `GOOGLE_DRIVE_FOLDER_ID`: folder ID yang dicetak setup script.
- `GOOGLE_DRIVE_TOKEN_JSON_B64`: seluruh nilai base64 yang dicetak setup script.

Jangan menambahkan `FIREBASE_STORAGE_BUCKET`; versi ini tidak menggunakan Firebase Storage. Jangan menaruh `credentials.json`, `google_drive_token.json`, `.env`, atau token OAuth di GitHub. Nilai token harus disimpan sebagai Railway Variable rahasia.

### C. Cara penyimpanan bekerja

- Firebase Authentication: login dan identitas pengguna.
- Firebase Realtime Database: data aplikasi, teks hasil ekstraksi yang diperlukan AI, dan metadata file.
- Google Drive: file asli CV dan dokumen kebijakan HR, disimpan di folder privat akun Google yang memberi izin OAuth.
- Railway `/tmp`: sesi server sementara dan pemrosesan request saja; bukan tempat penyimpanan file permanen.

Aplikasi tidak membuat permission berbagi publik. Metadata Drive menyimpan UID pemilik dalam `appProperties`; penghapusan file memeriksa UID tersebut. Batas upload aplikasi 15 MB. File terkait akan dihapus dari Drive saat record kandidat atau dokumen HR dihapus melalui aplikasi.

### D. Penting untuk OAuth yang berkelanjutan

Jika OAuth consent screen untuk akun Gmail eksternal berstatus **Testing**, refresh token dapat kedaluwarsa setelah 7 hari. Untuk penggunaan berkelanjutan, sesuaikan publishing status dan persyaratan verifikasi Google Cloud Console. Untuk organisasi Google Workspace, opsi OAuth internal dapat sesuai jika kebijakan admin mengizinkan. Jangan pernah membuat folder/file publik hanya untuk mempermudah akses.

Folder Drive yang dibuat setup script dimiliki oleh akun Google yang melakukan otorisasi. File akan memakai kuota penyimpanan Drive akun tersebut. Jika akun Drive mencapai batas penyimpanan, upload akan gagal. Google Drive bukan penyimpanan tanpa batas dan kebijakan/kuota Google tetap berlaku.

### E. Data lama dari Firebase Storage

Jika versi sebelumnya sudah menyimpan file ke Firebase Storage, data lama di Realtime Database masih mungkin berisi `storage_path` lama. Versi Google Drive ini tidak menghapus objek lama dari Firebase Storage; path lama diabaikan saat menghapus record agar tidak salah menghapus file dari provider berbeda. Setelah memastikan file lama tidak lagi dibutuhkan, lakukan migrasi/penghapusan manual secara hati-hati melalui Firebase Console. File baru akan memakai path internal berawalan `gdrive:`.

### F. Deploy dan tes

Railway memakai `Procfile`/`railway.json` dan Gunicorn. Setelah mengisi semua variable, deploy lalu tes: register/verifikasi/login, unggah satu CV, unggah dokumen HR Policy, dan hapus keduanya. Uji juga restart/redeploy untuk memastikan file tetap ada di Drive. Python dan template diperiksa secara lokal; koneksi Google Drive/Firebase harus diuji pada environment dengan OAuth credentials aktif.

Untuk multi-replica Railway, pindahkan Flask-Session ke session store bersama. Konfigurasi saat ini memakai `/tmp` dan cocok untuk satu instance; sesi dapat hilang saat restart.
