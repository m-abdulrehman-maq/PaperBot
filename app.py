"""PaperBot admin panel (Flask) + background worker host.

Deploy on DigitalOcean App Platform. Serves the admin UI/API and runs the
job worker thread in-process.
"""
from dotenv import load_dotenv
load_dotenv()
import json
import functools
import datetime

from flask import (Flask, request, redirect, url_for, render_template,
                   session, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash

import config
import db
import storage
import worker

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB per upload


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def ensure_bootstrap_admin():
    """Create the first admin from env vars if the table is empty."""
    try:
        count = db.scalar("SELECT COUNT(*) FROM admins")
        if count == 0 and config.ADMIN_PASSWORD:
            db.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                (config.ADMIN_USERNAME, generate_password_hash(config.ADMIN_PASSWORD)))
            print("Bootstrap admin created:", config.ADMIN_USERNAME)
    except Exception as e:
        print("ensure_bootstrap_admin error:", repr(e))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = db.one("SELECT id, password_hash FROM admins WHERE username=%s", (username,))
        if row and check_password_hash(row["password_hash"], password):
            session["admin_id"] = row["id"]
            session["admin_user"] = username
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard + analytics
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    stats = {}
    try:
        stats["total_users"] = db.scalar("SELECT COUNT(*) FROM users") or 0
        stats["total_messages"] = db.scalar("SELECT COUNT(*) FROM messages") or 0
        stats["total_papers"] = db.scalar("SELECT COUNT(*) FROM papers") or 0
        stats["active_users"] = db.scalar(
            "SELECT COUNT(*) FROM users WHERE last_active_at > datetime('now', '-7 days')") or 0

        peak_hours = db.query(
            """SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hour, COUNT(*) AS c
               FROM messages GROUP BY hour ORDER BY hour""")
        top_subjects = db.query(
            """SELECT s.name, SUM(p.view_count) AS views
               FROM papers p JOIN subjects s ON s.id = p.subject_id
               GROUP BY s.name ORDER BY views IS NULL, views DESC LIMIT 8""")
        top_papers = db.query(
            """SELECT s.name AS subject, p.year, p.paper_type, p.download_count
               FROM papers p JOIN subjects s ON s.id = p.subject_id
               ORDER BY p.download_count DESC LIMIT 8""")
        dept_traffic = db.query(
            """SELECT d.name, COUNT(*) AS c
               FROM events e
               JOIN papers p ON p.id = CAST(json_extract(e.meta, '$.paper_id') AS INTEGER)
               JOIN subjects s ON s.id = p.subject_id
               JOIN departments d ON d.id = s.department_id
               WHERE e.type = 'view_paper' AND json_extract(e.meta, '$.paper_id') IS NOT NULL
               GROUP BY d.name ORDER BY c DESC LIMIT 8""")
        feature_usage = db.query(
            """SELECT type, COUNT(*) AS c FROM events
               GROUP BY type ORDER BY c DESC LIMIT 12""")
    except Exception as e:
        print("dashboard analytics error:", repr(e))
        peak_hours = top_subjects = top_papers = dept_traffic = feature_usage = []

    return render_template(
        "dashboard.html", stats=stats, peak_hours=peak_hours,
        top_subjects=top_subjects, top_papers=top_papers,
        dept_traffic=dept_traffic, feature_usage=feature_usage)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@app.route("/users")
@login_required
def users():
    q = (request.args.get("q") or "").strip()
    if q:
        rows = db.query(
            """SELECT id, wa_phone, name, is_blocked, last_active_at
               FROM users WHERE wa_phone LIKE %s OR name LIKE %s
               ORDER BY last_active_at DESC LIMIT 200""",
            (f"%{q}%", f"%{q}%"))
    else:
        rows = db.query(
            """SELECT id, wa_phone, name, is_blocked, last_active_at
               FROM users ORDER BY last_active_at DESC LIMIT 200""")
    return render_template("users.html", users=rows, q=q)


@app.route("/users/<int:user_id>")
@login_required
def user_detail(user_id):
    user = db.one("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        abort(404)
    msgs = db.query(
        """SELECT direction, body, created_at FROM messages
           WHERE wa_phone=%s ORDER BY created_at DESC LIMIT 200""",
        (user["wa_phone"],))
    usage = db.one(
        "SELECT count FROM rate_limits WHERE wa_phone=%s AND day=CURRENT_DATE",
        (user["wa_phone"],))
    return render_template("user_detail.html", user=user,
                           messages=list(reversed(msgs)),
                           usage=(usage["count"] if usage else 0))


@app.route("/users/<int:user_id>/block", methods=["POST"])
@login_required
def toggle_block(user_id):
    user = db.one("SELECT is_blocked FROM users WHERE id=%s", (user_id,))
    if user:
        db.execute("UPDATE users SET is_blocked = NOT is_blocked WHERE id=%s", (user_id,))
        flash("User block status updated.", "ok")
    return redirect(url_for("user_detail", user_id=user_id))


# ---------------------------------------------------------------------------
# Paper management
# ---------------------------------------------------------------------------

@app.route("/papers")
@login_required
def papers():
    rows = db.query(
        """SELECT p.id, p.year, p.paper_type, p.status, p.view_count, p.download_count,
                  s.name AS subject, d.name AS department, i.name AS instructor
           FROM papers p
           JOIN subjects s ON s.id = p.subject_id
           JOIN departments d ON d.id = s.department_id
           LEFT JOIN instructors i ON i.id = p.instructor_id
           ORDER BY p.created_at DESC LIMIT 300""")
    return render_template("papers.html", papers=rows,
                           storage_ok=storage.is_configured())


@app.route("/papers/upload", methods=["GET", "POST"])
@login_required
def paper_upload():
    if request.method == "POST":
        try:
            _handle_upload(single=True)
            flash("Paper uploaded. Processing has started in the background.", "ok")
            return redirect(url_for("papers"))
        except Exception as e:
            flash(f"Upload failed: {e}", "error")
    ctx = _content_lists()
    return render_template("paper_upload.html", bulk=False, **ctx)


@app.route("/papers/bulk", methods=["GET", "POST"])
@login_required
def paper_bulk():
    if request.method == "POST":
        try:
            n = _handle_upload(single=False)
            flash(f"{n} paper(s) uploaded and queued for processing.", "ok")
            return redirect(url_for("papers"))
        except Exception as e:
            flash(f"Bulk upload failed: {e}", "error")
    ctx = _content_lists()
    return render_template("paper_upload.html", bulk=True, **ctx)


def _handle_upload(single):
    subject_id = int(request.form["subject_id"])
    year = int(request.form["year"])
    paper_type = request.form["paper_type"]
    if paper_type not in ("midterm", "final"):
        raise ValueError("paper type must be midterm or final")
    instructor_id = request.form.get("instructor_id") or None
    if instructor_id:
        instructor_id = int(instructor_id)

    files = request.files.getlist("file") if not single else [request.files.get("file")]
    files = [f for f in files if f and f.filename]
    if not files:
        raise ValueError("no file selected")

    count = 0
    for f in files:
        data = f.read()
        if not data:
            continue
        url, key = storage.upload_pdf(data, f.filename)
        rows = db.execute(
            """INSERT INTO papers (subject_id, instructor_id, year, paper_type,
                                   title, file_url, file_key, status, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'uploaded', %s) RETURNING id""",
            (subject_id, instructor_id, year, paper_type, f.filename, url, key,
             session.get("admin_user")), returning=True)
        paper_id = rows[0]["id"]
        db.execute("INSERT INTO jobs (type, payload) VALUES ('ingest_paper', %s)",
                   (json.dumps({"paper_id": paper_id}),))
        count += 1
    return count


@app.route("/papers/<int:paper_id>/reprocess", methods=["POST"])
@login_required
def paper_reprocess(paper_id):
    db.execute("INSERT INTO jobs (type, payload) VALUES ('ingest_paper', %s)",
               (json.dumps({"paper_id": paper_id}),))
    flash("Re-processing queued.", "ok")
    return redirect(url_for("papers"))


@app.route("/papers/<int:paper_id>/delete", methods=["POST"])
@login_required
def paper_delete(paper_id):
    db.execute("DELETE FROM papers WHERE id=%s", (paper_id,))
    flash("Paper deleted.", "ok")
    return redirect(url_for("papers"))


# ---------------------------------------------------------------------------
# Content management (departments / subjects / instructors)
# ---------------------------------------------------------------------------

@app.route("/content")
@login_required
def content():
    ctx = _content_lists()
    return render_template("content.html", **ctx)


@app.route("/content/department", methods=["POST"])
@login_required
def add_department():
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip() or None
    if name:
        try:
            db.execute("INSERT INTO departments (name, code) VALUES (%s, %s)", (name, code))
            flash("Department added.", "ok")
        except Exception:
            flash("That department already exists.", "error")
    return redirect(url_for("content"))


@app.route("/content/subject", methods=["POST"])
@login_required
def add_subject():
    name = (request.form.get("name") or "").strip()
    dept_id = request.form.get("department_id")
    code = (request.form.get("code") or "").strip() or None
    if name and dept_id:
        try:
            db.execute(
                "INSERT INTO subjects (department_id, name, code) VALUES (%s, %s, %s)",
                (int(dept_id), name, code))
            flash("Subject added.", "ok")
        except Exception:
            flash("That subject already exists in this department.", "error")
    return redirect(url_for("content"))


@app.route("/content/instructor", methods=["POST"])
@login_required
def add_instructor():
    name = (request.form.get("name") or "").strip()
    dept_id = request.form.get("department_id") or None
    if name:
        try:
            db.execute("INSERT INTO instructors (name, department_id) VALUES (%s, %s)",
                       (name, int(dept_id) if dept_id else None))
            flash("Instructor added.", "ok")
        except Exception:
            flash("That instructor already exists.", "error")
    return redirect(url_for("content"))


@app.route("/content/<kind>/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_content(kind, item_id):
    table = {"department": "departments", "subject": "subjects",
             "instructor": "instructors"}.get(kind)
    if table:
        db.execute(f"DELETE FROM {table} WHERE id=%s", (item_id,))
        flash(f"{kind.title()} deleted.", "ok")
    return redirect(url_for("content"))


# ---------------------------------------------------------------------------
# AI management
# ---------------------------------------------------------------------------

@app.route("/ai")
@login_required
def ai_admin():
    queue = db.query(
        """SELECT status, COUNT(*) c FROM jobs GROUP BY status ORDER BY status""")
    recent = db.query(
        """SELECT id, type, status, attempts, last_error, updated_at
           FROM jobs ORDER BY updated_at DESC LIMIT 30""")
    generated = db.query(
        """SELECT g.kind, COUNT(*) c FROM generated_content g GROUP BY g.kind""")
    papers = db.query(
        """SELECT p.id, s.name AS subject, p.year, p.paper_type,
                  EXISTS(SELECT 1 FROM generated_content g
                         WHERE g.paper_id=p.id AND g.kind='solution') AS has_solution,
                  EXISTS(SELECT 1 FROM generated_content g
                         WHERE g.paper_id=p.id AND g.kind='mcq') AS has_mcq
           FROM papers p JOIN subjects s ON s.id=p.subject_id
           ORDER BY p.created_at DESC LIMIT 100""")
    return render_template("ai.html", queue=queue, recent=recent,
                           generated=generated, papers=papers)


@app.route("/ai/regenerate/<int:paper_id>/<kind>", methods=["POST"])
@login_required
def ai_regenerate(paper_id, kind):
    if kind not in ("solution", "mcq", "practice"):
        abort(400)
    db.execute("DELETE FROM generated_content WHERE paper_id=%s AND kind=%s",
               (paper_id, kind))
    db.execute("INSERT INTO jobs (type, payload) VALUES (%s, %s)",
               (f"generate_{kind}", json.dumps({"paper_id": paper_id})))
    flash(f"{kind.title()} regeneration queued.", "ok")
    return redirect(url_for("ai_admin"))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SETTING_MESSAGES = [
    ("msg_welcome", "Welcome message"),
    ("msg_help", "Help message"),
    ("msg_not_found", "Paper not found message"),
    ("msg_limit_reached", "Daily limit reached message"),
    ("msg_blocked", "Blocked user message"),
    ("msg_maintenance", "Maintenance message"),
    ("msg_generating", "Generating message"),
]


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        try:
            limit = int(request.form.get("daily_ai_limit", "3"))
            _set_setting("daily_ai_limit", limit)
            _set_setting("maintenance_mode",
                         request.form.get("maintenance_mode") == "on")
            for key, _ in SETTING_MESSAGES:
                val = request.form.get(key)
                if val is not None:
                    _set_setting(key, val)
            flash("Settings saved.", "ok")
        except Exception as e:
            flash(f"Could not save settings: {e}", "error")
        return redirect(url_for("settings"))

    rows = db.query("SELECT key, value FROM settings")
    current = {r["key"]: _coerce_json(r["value"]) for r in rows}
    return render_template("settings.html", current=current,
                           messages=SETTING_MESSAGES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_lists():
    return {
        "departments": db.query("SELECT id, name FROM departments ORDER BY name"),
        "subjects": db.query(
            """SELECT s.id, s.name, d.name AS department
               FROM subjects s JOIN departments d ON d.id = s.department_id
               ORDER BY d.name, s.name"""),
        "instructors": db.query("SELECT id, name FROM instructors ORDER BY name"),
    }


def _set_setting(key, value):
    db.execute(
        """INSERT INTO settings (key, value) VALUES (%s, %s)
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
        (key, json.dumps(value)))


def _coerce_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


@app.template_filter("dt")
def _fmt_dt(value):
    if not value:
        return ""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


@app.route("/health")
def health():
    return {"status": "ok"}


# Start worker + ensure admin on import (App Platform runs via gunicorn).
ensure_bootstrap_admin()
worker.start()


# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=8080, debug=True)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080, use_reloader=False)
