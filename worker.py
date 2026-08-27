"""Background job worker.

Runs as a daemon thread inside the Flask process (App Platform). Polls the
`jobs` table, does the heavy Gemini work, caches results, and notifies the
requesting user over WhatsApp. Jobs are claimed with a single conditional
UPDATE ... RETURNING; libSQL serialises writes so this is atomic. Run a
single worker instance (instance_count: 1).
"""
from dotenv import load_dotenv
load_dotenv()
import json
import time
import threading
import datetime
import urllib.request

import config
import db
import ai
import wa

_started = False
_lock = threading.Lock()

RETRY_DELAY_SECONDS = 60


def start():
    """Start the worker thread once per process."""
    global _started
    with _lock:
        if _started or not config.WORKER_ENABLED:
            return
        _started = True
    t = threading.Thread(target=_loop, name="paperbot-worker", daemon=True)
    t.start()
    print("PaperBot worker started")


def _loop():
    while True:
        try:
            job = _claim_job()
            if not job:
                time.sleep(config.WORKER_POLL_SECONDS)
                continue
            _process(job)
        except Exception as e:
            print("worker loop error:", repr(e))
            time.sleep(config.WORKER_POLL_SECONDS)


def _claim_job():
    # libSQL/SQLite serialises writes, so a single conditional UPDATE claims a
    # job atomically without Postgres' FOR UPDATE SKIP LOCKED.
    rows = db.execute(
        """UPDATE jobs SET status='processing', attempts=attempts+1,
                          updated_at=CURRENT_TIMESTAMP
           WHERE id = (
               SELECT id FROM jobs
               WHERE status='pending' AND run_after <= CURRENT_TIMESTAMP
               ORDER BY id LIMIT 1)
           RETURNING id, type, payload, attempts, max_attempts""",
        (), returning=True)
    return rows[0] if rows else None


def _process(job):
    job_id = job["id"]
    jtype = job["type"]
    payload = job["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    try:
        if jtype == "ingest_paper":
            _ingest_paper(payload)
        elif jtype == "generate_solution":
            _generate_and_cache(payload, "solution")
        elif jtype == "generate_mcq":
            _generate_and_cache(payload, "mcq")
        elif jtype == "generate_practice":
            _generate_and_cache(payload, "practice")
        else:
            raise RuntimeError(f"unknown job type: {jtype}")
        db.execute("UPDATE jobs SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                   (job_id,))
    except Exception as e:
        _fail(job, str(e))


def _fail(job, error):
    print(f"job {job['id']} ({job['type']}) failed:", error[:300])
    if job["attempts"] >= job["max_attempts"]:
        db.execute("UPDATE jobs SET status='failed', last_error=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                   (error[:1000], job["id"]))
    else:
        run_after = datetime.datetime.utcnow() + datetime.timedelta(seconds=RETRY_DELAY_SECONDS)
        db.execute(
            """UPDATE jobs SET status='pending', last_error=%s, run_after=%s,
                   updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
            (error[:1000], run_after, job["id"]))


# ---------------------------------------------------------------------------
# Job handlers
# ---------------------------------------------------------------------------

def _ingest_paper(payload):
    """Parse a freshly uploaded paper and pre-generate its solution."""
    paper_id = payload.get("paper_id")
    paper = db.one("SELECT id, file_url, extracted_text FROM papers WHERE id=%s",
                   (paper_id,))
    if not paper:
        raise RuntimeError("paper not found")

    db.execute("UPDATE papers SET status='processing', error=NULL WHERE id=%s", (paper_id,))

    pdf_bytes = _download(paper["file_url"]) if paper.get("file_url") else None
    if not pdf_bytes:
        raise RuntimeError("no PDF file to ingest (file_url missing/unreachable)")

    # 1) structured questions (powers search / syllabus / predictor / insights)
    questions = ai.structure_questions(pdf_bytes)
    db.execute("DELETE FROM paper_questions WHERE paper_id=%s", (paper_id,))
    for q in questions:
        db.execute(
            """INSERT INTO paper_questions (paper_id, q_number, q_text, topic, difficulty, marks)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (paper_id, q["q_number"], q["q_text"], q["topic"], q["difficulty"], q["marks"]))

    # 2) raw text (used later for MCQ / practice generation)
    extracted = ai.extract_text_from_pdf(pdf_bytes) or ""

    # 3) full solution (eager, per spec)
    solution = ai.generate_solution(pdf_bytes=pdf_bytes)
    _cache_content(paper_id, "solution", solution)

    db.execute(
        "UPDATE papers SET status='ready', extracted_text=%s, processed_at=CURRENT_TIMESTAMP WHERE id=%s",
        (extracted[:200000], paper_id))
    print(f"ingested paper {paper_id}: {len(questions)} questions")


def _generate_and_cache(payload, kind):
    paper_id = payload.get("paper_id")
    notify = payload.get("notify")

    existing = db.one(
        "SELECT content FROM generated_content WHERE paper_id=%s AND kind=%s",
        (paper_id, kind))
    if existing:
        content = existing["content"]
    else:
        paper = db.one("SELECT extracted_text, file_url FROM papers WHERE id=%s", (paper_id,))
        if not paper:
            raise RuntimeError("paper not found")
        paper_text = paper.get("extracted_text") or ""
        if not paper_text and paper.get("file_url"):
            pdf = _download(paper["file_url"])
            if pdf:
                paper_text = ai.extract_text_from_pdf(pdf)
        if kind == "solution":
            content = ai.generate_solution(paper_text=paper_text)
        elif kind == "mcq":
            content = ai.generate_mcqs(paper_text)
        else:
            content = ai.generate_practice(paper_text)
        _cache_content(paper_id, kind, content)

    if notify and content:
        wa.send_long(notify, content)


def _cache_content(paper_id, kind, content):
    db.execute(
        """INSERT INTO generated_content (paper_id, kind, content, model)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (paper_id, kind) DO UPDATE
               SET content=EXCLUDED.content, model=EXCLUDED.model, created_at=CURRENT_TIMESTAMP""",
        (paper_id, kind, content or "", config.GEMINI_MODEL))


def _download(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PaperBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print("download error:", repr(e), url)
        return None
