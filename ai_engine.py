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

