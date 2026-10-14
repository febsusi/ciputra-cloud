import os, re, io, csv, json, secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_session import Session
from dotenv import load_dotenv

from ai_engine import (
    analyze_resume,
    extract_document_text,
    rank_resume,
    analyze_skill_gap,
)
from firebase_store import FirebaseStore, FirebaseError
from supabase_storage import SupabaseStorage, SupabaseStorageError

load_dotenv()
app = Flask(__name__)

_secret = os.getenv("FLASK_SECRET_KEY")
if not _secret and os.getenv("RAILWAY_ENVIRONMENT"):
    raise RuntimeError("FLASK_SECRET_KEY wajib diatur di Railway Variables.")
app.secret_key = _secret or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=15 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv(
        "SESSION_COOKIE_SECURE",
        "true" if os.getenv("RAILWAY_ENVIRONMENT") else "false",
    ).lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_TYPE="filesystem",
    SESSION_FILE_DIR=os.getenv("SESSION_FILE_DIR", "/tmp/flask_session"),
    SESSION_USE_SIGNER=True,
    SESSION_PERMANENT=False,
)
os.makedirs(app.config["SESSION_FILE_DIR"], mode=0o700, exist_ok=True)
Session(app)

if os.getenv("RAILWAY_ENVIRONMENT"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "")
DB_URL = os.getenv("FIREBASE_DATABASE_URL", "").rstrip("/")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "hr-files")

store = FirebaseStore(DB_URL)

storage = None
try:
    storage = SupabaseStorage(SUPABASE_URL, SUPABASE_KEY, SUPABASE_BUCKET)
except SupabaseStorageError as e:
    import logging
    logging.warning("Supabase storage belum siap: %s", e)


def _require_storage():
    if storage is None:
        raise SupabaseStorageError(
            "Supabase storage belum terkonfigurasi. Periksa SUPABASE_URL / "
            "SUPABASE_SERVICE_KEY / SUPABASE_BUCKET di environment."
        )
    return storage


ALLOWED = {"pdf", "docx", "txt", "png", "jpg", "jpeg", "webp"}


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED


def firebase_auth(endpoint, payload):
    if not FIREBASE_API_KEY:
        raise FirebaseError("FIREBASE_API_KEY belum diisi di file .env.")
    url = f"https://identitytoolkit.googleapis.com/v1/{endpoint}?key={FIREBASE_API_KEY}"
    try:
        r = requests.post(url, json=payload, timeout=20)
        data = r.json()
    except requests.RequestException:
        raise FirebaseError("Tidak dapat terhubung ke Firebase Authentication.")
    if not r.ok:
        message = data.get("error", {}).get("message", "AUTH_ERROR")
        messages = {
            "EMAIL_EXISTS": "Email sudah terdaftar.",
            "INVALID_EMAIL": "Format email tidak valid.",
            "WEAK_PASSWORD : Password should be at least 6 characters": "Password minimal 6 karakter.",
            "INVALID_PASSWORD": "Email atau password salah.",
            "EMAIL_NOT_FOUND": "Akun tidak ditemukan.",
            "INVALID_LOGIN_CREDENTIALS": "Email atau password salah.",
            "USER_DISABLED": "Akun dinonaktifkan.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": "Terlalu banyak percobaan. Coba lagi nanti.",
        }
        raise FirebaseError(messages.get(message, message.replace("_", " ").capitalize()))
    return data


def current_user():
    return session.get("user")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def user_store():
    user = current_user()
    if not user:
        raise FirebaseError("Sesi login berakhir. Silakan login kembali.")
    return FirebaseStore(DB_URL, user["idToken"], user["localId"])


@app.route("/")
def index():
    if not current_user():
        return render_template("landing.html")
    try:
        db = user_store()
        jobs = db.list("jobs")
        candidates = db.list("candidates")
        recent = db.list("rankings")
        return render_template("dashboard.html", jobs=jobs, candidates=candidates, recent=recent[:5])
    except FirebaseError as e:
        flash(str(e), "danger")
        return render_template("dashboard.html", jobs=[], candidates=[], recent=[])


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        if not name or not email or len(password) < 6:
            flash("Nama dan email wajib diisi. Password minimal 6 karakter.", "danger")
            return render_template("register.html")
        try:
            data = firebase_auth("accounts:signUp", {
                "email": email, "password": password, "returnSecureToken": True
            })
            firebase_auth("accounts:sendOobCode", {
                "requestType": "VERIFY_EMAIL", "idToken": data["idToken"]
            })
            flash("Akun dibuat. Buka email Anda dan klik tautan verifikasi dari Firebase sebelum login.", "success")
            return redirect(url_for("login"))
        except FirebaseError as e:
            flash(str(e), "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        try:
            data = firebase_auth("accounts:signInWithPassword", {
                "email": email, "password": password, "returnSecureToken": True
            })
            lookup = firebase_auth("accounts:lookup", {"idToken": data["idToken"]})
            users = lookup.get("users", [])
            if not users or not users[0].get("emailVerified", False):
                try:
                    firebase_auth("accounts:sendOobCode", {
                        "requestType": "VERIFY_EMAIL", "idToken": data["idToken"]
                    })
                except FirebaseError:
                    pass
                flash("Email belum diverifikasi. Periksa inbox/spam; tautan verifikasi baru mungkin telah dikirim.", "warning")
                return render_template("login.html")
            session["user"] = {
                "localId": data["localId"], "email": data["email"],
                "idToken": data["idToken"], "refreshToken": data.get("refreshToken", ""),
                "displayName": users[0].get("displayName", "")
            }
            return redirect(url_for("index"))
        except FirebaseError as e:
            flash(str(e), "danger")
    return render_template("login.html")


@app.route("/resend-verification", methods=["POST"])
def resend_verification():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    try:
        data = firebase_auth("accounts:signInWithPassword", {
            "email": email, "password": password, "returnSecureToken": True
        })
        lookup = firebase_auth("accounts:lookup", {"idToken": data["idToken"]})
        if lookup.get("users") and lookup["users"][0].get("emailVerified"):
            flash("Email sudah diverifikasi. Silakan login.", "success")
        else:
            firebase_auth("accounts:sendOobCode", {
                "requestType": "VERIFY_EMAIL", "idToken": data["idToken"]
            })
            flash("Email verifikasi dikirim ulang. Periksa inbox/spam.", "success")
    except FirebaseError as e:
        flash(str(e), "danger")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "success")
    return redirect(url_for("login"))


@app.route("/jobs", methods=["GET", "POST"])
@login_required
def jobs():
    db = user_store()
    if request.method == "POST":
        job_id = secrets.token_urlsafe(10)
        item = {
            "id": job_id, "title": request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "required_skills": [x.strip().lower() for x in request.form.get("required_skills", "").split(",") if x.strip()],
            "min_education": request.form.get("min_education", "SMA"),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        if not item["title"] or not item["description"]:
            flash("Judul dan deskripsi lowongan wajib diisi.", "danger")
        else:
            try:
                db.put(f"jobs/{job_id}", item)
                flash("Lowongan berhasil ditambahkan.", "success")
            except FirebaseError as e:
                flash(str(e), "danger")
        return redirect(url_for("jobs"))
    return render_template("jobs.html", jobs=db.list("jobs"))


@app.route("/jobs/<job_id>/edit", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    db = user_store()
    try:
        job = db.get(f"jobs/{job_id}")
    except FirebaseError as e:
        flash(str(e), "danger")
        return redirect(url_for("jobs"))
    if not job:
        flash("Lowongan tidak ditemukan.", "warning")
        return redirect(url_for("jobs"))
    if request.method == "POST":
        job.update({
            "title": request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "required_skills": [x.strip().lower() for x in request.form.get("required_skills", "").split(",") if x.strip()],
            "min_education": request.form.get("min_education", "SMA"),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        db.put(f"jobs/{job_id}", job)
        flash("Lowongan diperbarui.", "success")
        return redirect(url_for("jobs"))
    return render_template("job_edit.html", job=job)


@app.route("/jobs/<job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id):
    try:
        db = user_store()
        db.delete(f"jobs/{job_id}")
        flash("Lowongan dihapus.", "success")
    except FirebaseError as e:
        flash(str(e), "danger")
    return redirect(url_for("jobs"))


@app.route("/candidates")
@login_required
def candidates():
    try:
        items = user_store().list("candidates")
    except FirebaseError as e:
        flash(str(e), "danger")
        items = []
    return render_template("candidates.html", candidates=items)


@app.route("/candidates/add", methods=["GET", "POST"])
@login_required
def add_candidate():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        file = request.files.get("resume")
        if not name or not file or not file.filename or not allowed_file(file.filename):
            flash("Nama dan file CV (PDF/DOCX/TXT/PNG/JPG/WEBP) wajib diisi.", "danger")
            return render_template("candidate_form.html", candidate=None)
        safe = secure_filename(file.filename)
        ext = safe.rsplit(".", 1)[1].lower()
        try:
            raw = file.read()
            if not raw:
                flash("File yang diunggah kosong.", "warning")
                return render_template("candidate_form.html", candidate=None)

            extracted = extract_document_text(raw, ext)
            ai = analyze_resume(extracted)
            cid = secrets.token_urlsafe(10)
            db = user_store()

            storage_path = _require_storage().upload(
                uid=current_user()["localId"],
                category="resumes",
                object_id=cid,
                original_filename=safe,
                data=raw,
                content_type=file.mimetype or "application/octet-stream",
                id_token=current_user()["idToken"],
            )

            item = {
                "id": cid, "name": name, "email": email,
                "filename": safe, "storage_path": storage_path,
                "resume_text": extracted[:30000],
                "skills": ai["skills"], "education": ai["education"],
                "experience_years": ai["experience_years"],
                "ai_summary": ai["summary"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                db.put(f"candidates/{cid}", item)
            except Exception:
                try:
                    storage.delete(storage_path, id_token=current_user()["idToken"], uid=current_user()["localId"])
                except SupabaseStorageError:
                    pass
                raise
            flash("Kandidat ditambahkan. File CV disimpan privat di Supabase Storage dan berhasil dianalisis AI.", "success")
            return redirect(url_for("candidates"))
        except Exception as e:
            flash(f"Gagal memproses CV: {e}", "danger")
    return render_template("candidate_form.html", candidate=None)


@app.route("/candidates/<cid>/edit", methods=["GET", "POST"])
@login_required
def edit_candidate(cid):
    db = user_store()
    candidate = db.get(f"candidates/{cid}")
    if not candidate:
        flash("Kandidat tidak ditemukan.", "warning")
        return redirect(url_for("candidates"))
    if request.method == "POST":
        candidate["name"] = request.form.get("name", "").strip()
        candidate["email"] = request.form.get("email", "").strip()
        db.put(f"candidates/{cid}", candidate)
        flash("Data kandidat diperbarui.", "success")
        return redirect(url_for("candidates"))
    return render_template("candidate_form.html", candidate=candidate)


@app.route("/candidates/<cid>/delete", methods=["POST"])
@login_required
def delete_candidate(cid):
    try:
        db = user_store()
        candidate = db.get(f"candidates/{cid}")
        if candidate and candidate.get("storage_path"):
            storage.delete(
                candidate["storage_path"],
                id_token=current_user()["idToken"],
                uid=current_user()["localId"],
            )
        db.delete(f"candidates/{cid}")
        flash("Kandidat dan file CV terkait dihapus.", "success")
    except (FirebaseError, SupabaseStorageError) as e:
        flash(str(e), "danger")
    return redirect(url_for("candidates"))


# ======================== RANKING ========================

@app.route("/rank", methods=["GET", "POST"])
@login_required
def rank():
    db = user_store()
    jobs_data = db.list("jobs")
    if request.method == "POST":
        job_id = request.form.get("job_id", "")
        job = db.get(f"jobs/{job_id}")
        if not job:
            flash("Pilih lowongan yang valid.", "danger")
            return render_template("rank.html", jobs=jobs_data, results=[])
        candidates_data = db.list("candidates")
        results = [rank_resume(c, job) for c in candidates_data]
        results.sort(key=lambda x: x["score"], reverse=True)
        ranking_id = secrets.token_urlsafe(10)
        saved = {
            "id": ranking_id, "job_id": job_id, "job_title": job["title"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "results": results[:100]
        }
        db.put(f"rankings/{ranking_id}", saved)
        return render_template("rank.html", jobs=jobs_data, results=results, selected_job=job_id)
    return render_template("rank.html", jobs=jobs_data, results=[], selected_job="")


@app.route("/rankings")
@login_required
def rankings():
    try:
        items = user_store().list("rankings")
    except FirebaseError as e:
        flash(str(e), "danger")
        items = []
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return render_template("rankings.html", rankings=items)


@app.route("/rankings/<rid>/delete", methods=["POST"])
@login_required
def delete_ranking(rid):
    try:
        user_store().delete(f"rankings/{rid}")
        flash("Riwayat ranking dihapus.", "success")
    except FirebaseError as e:
        flash(str(e), "danger")
    return redirect(url_for("rankings"))


@app.route("/export/<rid>.csv")
@login_required
def export_csv(rid):
    item = user_store().get(f"rankings/{rid}")
    if not item:
        flash("Riwayat ranking tidak ditemukan.", "warning")
        return redirect(url_for("rankings"))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nama", "Email", "Skor", "Kecocokan teks", "Skill cocok",
                     "Pendidikan", "Pengalaman", "Penjelasan AI"])
    for r in item.get("results", []):
        writer.writerow([
            r.get("name"), r.get("email"), r.get("score"),
            r.get("text_match"), r.get("skill_match"), r.get("education_score"),
            r.get("experience_years"), r.get("explanation"),
        ])
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(
        mem, mimetype="text/csv", as_attachment=True,
        download_name=f"ranking_{secure_filename(item.get('job_title', 'job'))}.csv",
    )


@app.route("/hr-policy", methods=["GET", "POST"])
@login_required
def hr_policy():
    """Document-grounded HR policy Q&A using TF-IDF retrieval (not generative)."""
    db = user_store()
    answer = None
    if request.method == "POST":
        action = request.form.get("action", "ask")
        if action == "delete":
            doc_id = request.form.get("doc_id", "")
            try:
                doc = db.get(f"hr_policy_docs/{doc_id}")
                if doc and doc.get("storage_path"):
                    storage.delete(
                        doc["storage_path"],
                        id_token=current_user()["idToken"],
                        uid=current_user()["localId"],
                    )
                db.delete(f"hr_policy_docs/{doc_id}")
                flash("Dokumen kebijakan dan file terkait dihapus.", "success")
            except (FirebaseError, SupabaseStorageError) as e:
                flash(str(e), "danger")
            return redirect(url_for("hr_policy"))
        if action == "upload":
            file = request.files.get("policy_file")
            title = request.form.get("title", "").strip()
            if (not file or not file.filename or not allowed_file(file.filename)
                    or file.filename.rsplit(".", 1)[1].lower() not in {"pdf", "docx", "txt"}):
                flash("Unggah dokumen PDF, DOCX, atau TXT.", "warning")
            else:
                try:
                    raw = file.read()
                    if not raw:
                        flash("File yang diunggah kosong.", "warning")
                        return redirect(url_for("hr_policy"))
                    content = extract_document_text(
                        raw, file.filename.rsplit(".", 1)[1].lower()
                    ).strip()
                    if len(content) < 30:
                        flash("Teks dokumen terlalu pendek atau tidak berhasil diekstrak.", "warning")
                    else:
                        doc_id = secrets.token_urlsafe(10)
                        safe_name = secure_filename(file.filename)
                        storage_path = _require_storage().upload(
                            uid=current_user()["localId"],
                            category="hr-policy",
                            object_id=doc_id,
                            original_filename=safe_name,
                            data=raw,
                            content_type=file.mimetype or "application/octet-stream",
                            id_token=current_user()["idToken"],
                        )
                        doc = {
                            "id": doc_id, "title": title or safe_name,
                            "filename": safe_name, "storage_path": storage_path,
                            "text": content[:40000],
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        try:
                            db.put(f"hr_policy_docs/{doc_id}", doc)
                        except Exception:
                            try:
                                storage.delete(
                                    storage_path,
                                    id_token=current_user()["idToken"],
                                    uid=current_user()["localId"],
                                )
                            except SupabaseStorageError:
                                pass
                            raise
                        flash("Dokumen kebijakan tersimpan privat di Supabase Storage dan siap dicari.", "success")
                except Exception as e:
                    flash(f"Gagal membaca dokumen: {e}", "danger")
        elif action == "ask":
            question = request.form.get("question", "").strip()
            docs = db.list("hr_policy_docs")
            if len(question) < 4:
                flash("Masukkan pertanyaan yang lebih lengkap.", "warning")
            elif not docs:
                flash("Unggah dokumen kebijakan terlebih dahulu.", "info")
            else:
                # Chunk each document into paragraph-sized passages, then retrieve with TF-IDF cosine similarity.
                passages = []
                for doc in docs:
                    chunks = [x.strip() for x in re.split(r"\n\s*\n|(?<=[.!?])\s+", doc.get("text", ""))
                              if len(x.strip()) >= 25]
                    for chunk in chunks:
                        passages.append({
                            "title": doc.get("title", "Dokumen"),
                            "filename": doc.get("filename", ""),
                            "text": chunk[:1200],
                            "doc_id": doc.get("id"),
                        })
                if passages:
                    corpus = [x["text"] for x in passages] + [question]
                    try:
                        vec = TfidfVectorizer(ngram_range=(1, 2), stop_words=None).fit_transform(corpus)
                        sims = cosine_similarity(vec[-1], vec[:-1]).ravel()
                        order = sims.argsort()[::-1][:3]
                        best = float(sims[order[0]]) if len(order) else 0
                        if best < 0.05:
                            answer = {"question": question, "found": False, "sources": [], "score": round(best * 100, 1)}
                        else:
                            answer = {
                                "question": question, "found": True,
                                "sources": [{**passages[i], "similarity": round(float(sims[i]) * 100, 1)}
                                            for i in order if sims[i] >= max(0.04, best * 0.45)],
                                "score": round(best * 100, 1),
                            }
                    except ValueError:
                        answer = {"question": question, "found": False, "sources": [], "score": 0}
    try:
        docs = user_store().list("hr_policy_docs")
    except FirebaseError as e:
        flash(str(e), "danger")
        docs = []
    docs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return render_template("hr_policy.html", docs=docs, answer=answer)


@app.errorhandler(413)
def too_large(_):
    flash("File terlalu besar. Maksimal 15 MB.", "danger")
    return redirect(request.referrer or url_for("candidates"))

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
