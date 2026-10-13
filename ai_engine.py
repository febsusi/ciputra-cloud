import io, re, os
from collections import Counter

SKILL_VOCAB = {
    "python","sql","machine learning","deep learning","artificial intelligence","ai",
    "data analysis","data analytics","data engineering","etl","airflow","dbt",
    "bigquery","postgresql","mysql","mongodb","firebase","docker","kubernetes",
    "pandas","numpy","scikit-learn","tensorflow","pytorch","keras","opencv",
    "computer vision","ocr","nlp","llm","rag","faiss","transformers","power bi",
    "tableau","looker","metabase","spark","hadoop","statistics","excel","git",
    "aws","azure","gcp","rest api","flask","django","fastapi","java","kotlin",
    "communication","leadership","project management","data visualization"
}
EDU_LEVELS = [
    ("S3", 4), ("doktor", 4), ("phd", 4), ("s2", 3), ("magister", 3), ("master", 3),
    ("s1", 2), ("sarjana", 2), ("bachelor", 2), ("d4", 2), ("diploma iv", 2),
    ("d3", 1), ("diploma iii", 1), ("associate", 1), ("sma", 0), ("smk", 0), ("high school", 0)
]

def extract_document_text(raw_bytes, ext):
    ext = ext.lower()
    if ext == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if len(text.strip()) > 40:
                return text[:30000]
        except Exception:
            pass
        # OCR fallback for scanned PDF
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            images = convert_from_bytes(raw_bytes, first_page=1, last_page=8)
            return "\n".join(pytesseract.image_to_string(img) for img in images)[:30000]
        except Exception as e:
            raise ValueError("PDF tampaknya hasil scan. OCR membutuhkan Tesseract dan Poppler terpasang.") from e
    if ext == "docx":
        from docx import Document
        doc = Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs)[:30000]
    if ext == "txt":
        return raw_bytes.decode("utf-8", errors="ignore")[:30000]
    if ext in {"png","jpg","jpeg","webp"}:
        try:
            from PIL import Image
            import pytesseract
            image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            # Computer vision preprocessing: grayscale + contrast + threshold.
            import cv2, numpy as np
            arr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
            arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            return pytesseract.image_to_string(arr)[:30000]
        except Exception as e:
            raise ValueError("OCR gambar gagal. Pastikan OpenCV, Pillow, pytesseract dan Tesseract terpasang.") from e
    raise ValueError("Format file tidak didukung.")

def clean(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def extract_skills(text):
    t = clean(text)
    found = [s for s in sorted(SKILL_VOCAB, key=len, reverse=True) if re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", t)]
    return sorted(set(found))

def extract_education(text):
    t = clean(text)
    for term, level in EDU_LEVELS:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", t):
            return {"label": term.upper(), "level": level}
    return {"label": "Tidak terdeteksi", "level": 0}

def extract_experience(text):
    t = clean(text)
    vals = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?|tahun)\s+(?:of\s+)?(?:work\s+)?experience", t):
        try: vals.append(float(m.group(1).replace(",", ".")))
        except ValueError: pass
    # Handle phrases such as "5 years experience"
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:years?|yrs?|tahun)\s+(?:experience|pengalaman)", t):
        try: vals.append(float(m.group(1).replace(",", ".")))
        except ValueError: pass
    return round(min(max(vals, default=0), 40), 1)

def analyze_resume(text):
    skills = extract_skills(text)
    education = extract_education(text)
    years = extract_experience(text)
    chunks = re.split(r"(?<=[.!?])\s+", clean(text))
    summary = " ".join(chunks[:3])[:450] if chunks else "Belum ada ringkasan yang dapat dibuat."
    return {"skills": skills, "education": education["label"], "education_level": education["level"],
            "experience_years": years, "summary": summary or "Teks CV terlalu sedikit untuk diringkas."}

def rank_resume(candidate, job):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    resume_text = candidate.get("resume_text", "")
    job_text = (job.get("title", "") + " " + job.get("description", "") + " " +
                " ".join(job.get("required_skills", [])))
    try:
        matrix = TfidfVectorizer(ngram_range=(1,2), stop_words=None, max_features=12000).fit_transform([job_text, resume_text])
        text_match = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0]) * 100
    except ValueError:
        text_match = 0.0
    required = set(s.lower() for s in job.get("required_skills", []) if s)
    found = set(s.lower() for s in candidate.get("skills", []))
    if not required:
        required = set(extract_skills(job_text))
    skill_match = 100 * len(required & found) / len(required) if required else 0.0
    edu = candidate.get("education", "Tidak terdeteksi")
    edu_level = next((n for term, n in EDU_LEVELS if term.lower() == str(edu).lower()), 0)
    min_edu = str(job.get("min_education", "SMA")).lower()
    min_level = next((n for term, n in EDU_LEVELS if term.lower() == min_edu), 0)
    education_score = 100 if edu_level >= min_level else (max(0, 100 - (min_level-edu_level)*25))
    years = float(candidate.get("experience_years", 0) or 0)
    experience_score = min(years / 5 * 100, 100)
    # Logistic Regression score over the four interpretable feature values.
    # It is a demo baseline trained on transparent synthetic examples, not a
    # hiring model trained on historical recruiter decisions. Replace the
    # synthetic training rows with audited, consented labels for production.
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    features = np.array([[text_match, skill_match, education_score, experience_score]], dtype=float)
    training_x = np.array([
        [95, 95, 100, 100], [85, 80, 100, 80], [75, 70, 75, 60],
        [65, 60, 75, 40], [50, 45, 50, 20], [35, 25, 50, 0],
        [20, 10, 25, 0], [10, 0, 0, 0], [90, 30, 100, 100], [30, 90, 100, 20]
    ], dtype=float)
    training_y = np.array([1,1,1,1,0,0,0,0,0,0])
    lr = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    lr.fit(training_x, training_y)
    logistic_probability = float(lr.predict_proba(features)[0][list(lr.classes_).index(1)]) * 100
    base_score = text_match*0.40 + skill_match*0.35 + education_score*0.15 + experience_score*0.10
    score = round(max(0, min(100, base_score*0.80 + logistic_probability*0.20)), 2)
    missing = sorted(required - found)
    explanation = (f"TF-IDF teks {text_match:.0f}/100; skill {skill_match:.0f}/100; "
                   f"pendidikan {education_score:.0f}/100; pengalaman {experience_score:.0f}/100; "
                   f"Logistic Regression {logistic_probability:.0f}%.")
    if missing: explanation += " Skill belum terdeteksi: " + ", ".join(missing[:10]) + "."
    return {
        "candidate_id": candidate.get("id"), "name": candidate.get("name", "Tanpa nama"),
        "email": candidate.get("email", ""), "score": score,
        "text_match": round(text_match, 2), "skill_match": round(skill_match, 2),
        "education_score": round(education_score, 2), "experience_years": years,
        "logistic_probability": round(logistic_probability, 2),
        "skills": candidate.get("skills", []), "missing_skills": missing,
        "explanation": explanation
    }


# ---------- Practical ML features: skill-gap analysis and duplicate CV detection ----------

def analyze_skill_gap(candidate, job):
    """Compare a candidate CV with one vacancy and produce actionable skill gaps."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    cv_text = candidate.get("resume_text", "") or candidate.get("cv_text", "")
    job_text = " ".join([job.get("title", ""), job.get("description", ""),
                         " ".join(job.get("required_skills", []) or [])])
    required = {str(x).strip().lower() for x in (job.get("required_skills") or []) if str(x).strip()}
    if not required:
        required = set(extract_skills(job_text))
    found = set(s.lower() for s in (candidate.get("skills") or extract_skills(cv_text)))
    matched = sorted(required & found)
    missing = sorted(required - found)
    try:
        matrix = TfidfVectorizer(ngram_range=(1, 2), max_features=10000).fit_transform([job_text, cv_text])
        similarity = round(float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0]) * 100, 2)
    except ValueError:
        similarity = 0.0
    coverage = round(100 * len(matched) / len(required), 2) if required else 0.0
    # Actionable recommendations based only on skills missing from the CV text.
    suggestions = [f"Jika benar dikuasai, tambahkan '{skill}' pada bagian Skills dan jelaskan contoh penggunaannya di pengalaman/proyek." for skill in missing[:8]]
    return {"candidate_name": candidate.get("name", "Tanpa nama"), "job_title": job.get("title", "Lowongan"),
            "matched_skills": matched, "missing_skills": missing, "skill_coverage": coverage,
            "text_similarity": similarity, "required_count": len(required), "matched_count": len(matched),
            "suggestions": suggestions,
            "note": "Skill yang tidak terdeteksi di CV belum tentu tidak dikuasai; periksa CV dan lakukan wawancara sebelum mengambil keputusan."}


def detect_duplicate_resumes(candidates, threshold=0.72):
    """Find likely duplicate/near-duplicate CV text using TF-IDF and cosine similarity."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    rows = []
    for candidate in candidates:
        skills_value = candidate.get("skills", [])
        skills_text = " ".join(skills_value) if isinstance(skills_value, list) else str(skills_value or "")
        text = clean(" ".join([candidate.get("resume_text", "") or candidate.get("cv_text", ""), skills_text]))
        if text:
            rows.append((candidate, text))
    if len(rows) < 2:
        return {"pairs": [], "candidate_count": len(rows), "message": "Minimal dua CV dengan teks hasil ekstraksi diperlukan."}
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=15000, sublinear_tf=True)
    matrix = vectorizer.fit_transform([x[1] for x in rows])
    similarities = cosine_similarity(matrix)
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            score = float(similarities[i, j])
            if score >= threshold:
                pairs.append({"name_a": rows[i][0].get("name", "Tanpa nama"),
                              "email_a": rows[i][0].get("email", ""),
                              "name_b": rows[j][0].get("name", "Tanpa nama"),
                              "email_b": rows[j][0].get("email", ""),
                              "similarity": round(score * 100, 2),
                              "level": "Sangat mirip" if score >= 0.88 else "Perlu ditinjau"})
    pairs.sort(key=lambda x: x["similarity"], reverse=True)
    return {"pairs": pairs, "candidate_count": len(rows), "threshold": round(threshold * 100, 1),
            "message": "Tidak ditemukan pasangan di atas ambang kemiripan. Ini bukan bukti pasti CV duplikat." if not pairs else "Pasangan ditampilkan berdasarkan kemiripan teks; periksa manual sebelum menggabungkan/menghapus data."}


# ---------- Extra AI/NLP tools: CV quality and consistency review ----------

def analyze_cv_quality(candidate):
    """Heuristic NLP quality audit for one CV; outputs explainable signals, not hiring scores."""
    text = candidate.get("resume_text", "") or candidate.get("cv_text", "")
    normalized = clean(text)
    words = re.findall(r"\b[\w+#.-]+\b", text)
    word_count = len(words)
    sections = {
        "Kontak": bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text) or re.search(r"(?:\+?\d[\d ()-]{7,}\d)", text)),
        "Ringkasan / Profil": bool(re.search(r"\b(summary|profile|profil|about me|tentang saya|objective|career objective)\b", normalized)),
        "Pengalaman": bool(re.search(r"\b(experience|employment|work history|pengalaman kerja|riwayat pekerjaan)\b", normalized)),
        "Pendidikan": bool(re.search(r"\b(education|pendidikan|academic background|riwayat pendidikan)\b", normalized)),
        "Skills": bool(re.search(r"\b(skills|technical skills|keahlian|kompetensi)\b", normalized)),
        "Proyek / Sertifikasi": bool(re.search(r"\b(projects?|proyek|certifications?|sertifikasi|licenses?)\b", normalized)),
    }
    quantified = len(re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|persen|k|m|million|juta|years?|tahun|users?|records?|projects?|proyek|hours?|jam)\b", normalized))
    action_verbs = ["developed", "built", "implemented", "improved", "reduced", "increased", "managed", "led", "created", "analyzed", "designed", "automated", "mengembangkan", "membangun", "menerapkan", "meningkatkan", "mengurangi", "memimpin", "menganalisis", "merancang", "mengotomatisasi"]
    action_count = sum(1 for v in action_verbs if re.search(r"\b" + re.escape(v) + r"\b", normalized))
    skills = extract_skills(text)
    # Explainable 100-point rubric: sections 60, useful detail 20, action/results evidence 20.
    section_score = round(60 * sum(sections.values()) / len(sections))
    length_score = 20 if 250 <= word_count <= 1200 else (12 if 120 <= word_count < 250 or 1200 < word_count <= 1800 else 5)
    evidence_score = min(10, quantified * 2) + min(10, action_count * 2)
    score = min(100, section_score + length_score + evidence_score)
    recommendations = []
    for section, present in sections.items():
        if not present:
            recommendations.append(f"Pertimbangkan menambahkan bagian {section.lower()} jika relevan.")
    if word_count < 250:
        recommendations.append("CV relatif singkat; tambahkan konteks proyek, tanggung jawab, dan hasil yang dapat diverifikasi.")
    elif word_count > 1800:
        recommendations.append("CV cukup panjang; prioritaskan pengalaman dan pencapaian yang paling relevan.")
    if quantified == 0:
        recommendations.append("Tambahkan metrik yang benar-benar dapat dibuktikan, misalnya skala data, waktu proses, atau dampak hasil.")
    if action_count < 2:
        recommendations.append("Gunakan kata kerja tindakan yang spesifik untuk menjelaskan kontribusi pribadi.")
    if not skills:
        recommendations.append("Skill belum terdeteksi dari kamus aplikasi; tuliskan nama skill secara eksplisit jika memang dikuasai.")
    return {"candidate_name": candidate.get("name", "Tanpa nama"), "score": score,
            "word_count": word_count, "sections": sections, "sections_present": sum(sections.values()),
            "section_total": len(sections), "skills": skills[:20], "quantified_evidence": quantified,
            "action_verb_count": action_count, "recommendations": recommendations,
            "note": "Skor memakai rubrik heuristik yang dapat dijelaskan, bukan prediksi keberhasilan kerja. Periksa CV asli sebelum menyimpulkan."}


def check_cv_consistency(candidate):
    """Flag potential CV inconsistencies for manual review; never labels a CV as fraudulent."""
    text = candidate.get("resume_text", "") or candidate.get("cv_text", "")
    normalized = clean(text)
    flags = []
    emails = sorted(set(re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)))
    if len(emails) > 1:
        flags.append({"level": "info", "title": "Beberapa alamat email ditemukan", "detail": "Email terdeteksi: " + ", ".join(emails[:5]) + ". Pastikan alamat kontak utama jelas."})
    phones = sorted(set(re.findall(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", text)))
    if len(phones) > 1:
        flags.append({"level": "info", "title": "Beberapa nomor telepon ditemukan", "detail": f"Ditemukan {len(phones)} pola nomor telepon. Bisa jadi wajar; pastikan nomor kontak yang aktif ditandai."})

    # Parse common month-year and year-only ranges (e.g. Jan 2020 - Mar 2022, 2021 - Present).
    month_map = {m.lower(): i for i, m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
    month_map.update({m[:3].lower(): i for m, i in list(month_map.items()) if len(m) > 3})
    month_pattern = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(20\d{2})"
    date_token = rf"(?:{month_pattern}|(20\d{{2}}))"
    range_pattern = re.compile(rf"(?P<start>{date_token})\s*(?:-|–|—|to|through)\s*(?P<end>{date_token}|present|current|sekarang|now)", re.I)
    def date_value(token, end=False):
        t = token.strip().lower()
        if t in {"present", "current", "sekarang", "now"}:
            from datetime import datetime
            d = datetime.now()
            return d.year * 12 + d.month
        year_match = re.search(r"20\d{2}", t)
        if not year_match: return None
        year = int(year_match.group())
        mon_match = re.search(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)", t, re.I)
        month = 12 if end else 1
        if mon_match:
            key = mon_match.group(1).lower()[:3]
            month = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}.get(key, month)
        return year * 12 + month
    ranges = []
    for m in range_pattern.finditer(text):
        # Avoid accidentally treating numeric values elsewhere as a date range.
        start, end = m.group("start"), m.group("end")
        sv, ev = date_value(start), date_value(end, True)
        if sv is not None and ev is not None and 1900 * 12 < sv < 2100 * 12 and 1900 * 12 < ev < 2100 * 12:
            ranges.append((m.start(), m.end(), sv, ev, m.group(0)))
    for item in ranges:
        if item[3] < item[2]:
            flags.append({"level": "warning", "title": "Rentang tanggal tampak terbalik", "detail": f"Periksa rentang '{item[4]}'; tanggal akhir terlihat lebih awal dari tanggal mulai."})
    overlaps = []
    for i, a in enumerate(ranges):
        for b in ranges[i+1:]:
            if a[2] <= b[3] and b[2] <= a[3] and a[4] != b[4]:
                # Deduplicate identical/near-identical ranges and only flag if both ranges are distinct.
                pair = tuple(sorted((a[4], b[4])))
                if pair not in overlaps:
                    overlaps.append(pair)
                    flags.append({"level": "warning", "title": "Rentang tanggal pengalaman bertumpang tindih", "detail": f"'{a[4]}' dan '{b[4]}' tampak bertumpang tindih. Ini dapat wajar untuk pekerjaan paralel; verifikasi konteksnya."})
    claimed = []
    for m in re.finditer(r"(\d{1,2}(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?|tahun)\s+(?:of\s+)?(?:work\s+)?experience|(?:pengalaman)\s+(\d{1,2}(?:[.,]\d+)?)\s*(?:tahun|years?)", normalized):
        raw = next((x for x in m.groups() if x), None)
        if raw:
            try: claimed.append(float(raw.replace(",", ".")))
            except ValueError: pass
    inferred = None
    if ranges:
        starts = [r[2] for r in ranges if r[2] <= r[3]]
        ends = [r[3] for r in ranges if r[2] <= r[3]]
        if starts and ends:
            inferred = round(max(0, (max(ends) - min(starts)) / 12), 1)
    if claimed and inferred is not None and abs(max(claimed) - inferred) >= 3:
        flags.append({"level": "warning", "title": "Klaim durasi pengalaman perlu dikonfirmasi", "detail": f"Teks menyebut sekitar {max(claimed):g} tahun pengalaman, sementara rentang tanggal yang terbaca mencakup sekitar {inferred:g} tahun kalender. Metode ini perkiraan kasar dan dapat menghitung jeda atau pekerjaan paralel."})
    if not flags:
        flags.append({"level": "success", "title": "Tidak ada pola inkonsistensi umum yang terdeteksi", "detail": "Ini tidak menjamin seluruh informasi benar; pemeriksaan hanya mencakup pola teks dan tanggal yang didukung."})
    return {"candidate_name": candidate.get("name", "Tanpa nama"), "flags": flags,
            "flag_count": sum(1 for f in flags if f["level"] == "warning"),
            "date_ranges_found": len(ranges),
            "note": "Semua temuan adalah sinyal untuk ditinjau manual. Tanggal yang tumpang tindih, beberapa kontak, atau perbedaan estimasi bukan bukti bahwa CV palsu."}
