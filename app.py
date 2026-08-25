"""
Douala Power Alert
A participatory map and alert system of electricity outages in Douala.
School coding challenge – simple, elegant, bilingual (French default & English).
"""

import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import Error

from services.ai_service import ask_ai
from translations import get_text

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")


# ---------------------------------------------------------------------------
# Template Context Processor & Language Helper
# ---------------------------------------------------------------------------

@app.context_processor
def inject_translations():
    """Inject translation helper and active language into all templates."""
    current_lang = session.get("lang", "fr")
    return {
        "t": lambda key, **kwargs: get_text(key, lang=session.get("lang", "fr"), **kwargs),
        "current_lang": current_lang,
        "languages": [("fr", "Français 🇫🇷"), ("en", "English 🇬🇧")],
    }


def get_current_lang():
    return session.get("lang", "fr")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Create a new MySQL connection."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "douala_power_alert"),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )


def get_cursor(conn, dictionary=True):
    return conn.cursor(dictionary=dictionary)


def init_db():
    """Ensure database and required tables exist on startup."""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                phone VARCHAR(20) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                neighborhood VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS outages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                neighborhood VARCHAR(100) NOT NULL,
                location VARCHAR(200) NOT NULL,
                description TEXT,
                start_time DATETIME NOT NULL,
                estimated_restore DATETIME NULL,
                status ENUM('PENDING', 'VERIFIED', 'RESTORED', 'REJECTED') DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS confirmations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                outage_id INT NOT NULL,
                user_id INT NOT NULL,
                confirmation ENUM('STILL_OFF', 'RESTORED') NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (outage_id) REFERENCES outages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE KEY unique_user_outage (outage_id, user_id)
            ) ENGINE=InnoDB;
        """)
        conn.commit()
        cur.close()
        conn.close()
        ensure_admin()
    except Exception as e:
        print(f"Database initialization warning: {e}")


def ensure_admin():
    """Ensure default admin account exists."""
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("SELECT id FROM admins WHERE username = %s", ("admin",))
        row = cur.fetchone()
        hashed = generate_password_hash("admin123")
        if not row:
            cur.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                ("admin", hashed),
            )
        else:
            cur.execute(
                "UPDATE admins SET password_hash = %s WHERE username = %s",
                (hashed, "admin"),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Error:
        pass


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash(get_text("msg_login_required", lang=get_current_lang()), "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            flash(get_text("msg_admin_required", lang=get_current_lang()), "warning")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Language switcher route
# ---------------------------------------------------------------------------

@app.route("/set-language/<lang>")
def set_language(lang):
    """Switch language between 'fr' (French) and 'en' (English)."""
    if lang in ("fr", "en"):
        session["lang"] = lang
    referrer = request.referrer
    if referrer and request.host in referrer:
        return redirect(referrer)
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    lang = get_current_lang()
    form_data = {}
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        neighborhood = request.form.get("neighborhood", "").strip()
        form_data = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "neighborhood": neighborhood
        }

        # Server-side validation
        if not all([full_name, email, phone, password, neighborhood]):
            flash(get_text("msg_all_fields_required", lang=lang), "danger")
            return render_template("register.html", form_data=form_data)

        if len(password) < 6:
            flash(get_text("msg_password_length", lang=lang), "danger")
            return render_template("register.html", form_data=form_data)

        password_hash = generate_password_hash(password)

        try:
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute(
                """INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                   VALUES (%s, %s, %s, %s, %s)""",
                (full_name, email, phone, password_hash, neighborhood),
            )
            conn.commit()
            cur.close()
            conn.close()
            flash(get_text("msg_reg_success", lang=lang), "success")
            return redirect(url_for("login"))
        except Error as e:
            if e.errno == 1062:  # Duplicate entry
                flash(get_text("msg_email_phone_exists", lang=lang), "danger")
            else:
                flash(get_text("msg_db_error", lang=lang), "danger")
            return render_template("register.html", form_data=form_data)

    return render_template("register.html", form_data=form_data)


@app.route("/login", methods=["GET", "POST"])
def login():
    lang = get_current_lang()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash(get_text("msg_email_password_required", lang=lang), "danger")
            return render_template("login.html", email=email)

        try:
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()

            if user and check_password_hash(user["password_hash"], password):
                saved_lang = session.get("lang", "fr")
                session.clear()
                session["lang"] = saved_lang
                session["user_id"] = user["id"]
                session["user_name"] = user["full_name"]
                session["user_neighborhood"] = user["neighborhood"]
                flash(get_text("msg_welcome_back", lang=saved_lang, name=user["full_name"]), "success")
                return redirect(url_for("dashboard"))
            else:
                flash(get_text("msg_invalid_credentials", lang=lang), "danger")
        except Error:
            flash(get_text("msg_db_error", lang=lang), "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    saved_lang = session.get("lang", "fr")
    session.clear()
    session["lang"] = saved_lang
    flash(get_text("msg_logged_out", lang=saved_lang), "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    try:
        conn = get_db()
        cur = get_cursor(conn)

        cur.execute(
            "SELECT COUNT(*) AS c FROM outages WHERE status IN ('PENDING', 'VERIFIED')"
        )
        active = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM outages WHERE user_id = %s", (user_id,)
        )
        my_reports = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM outages WHERE status = 'VERIFIED'"
        )
        verified = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM outages WHERE status = 'RESTORED'"
        )
        restored = cur.fetchone()["c"]

        cur.execute("""
            SELECT o.*, 
                   (SELECT COUNT(*) FROM confirmations c 
                    WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
            FROM outages o
            WHERE o.status IN ('PENDING', 'VERIFIED')
            ORDER BY o.created_at DESC
            LIMIT 5
        """)
        recent = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "dashboard.html",
            active=active,
            my_reports=my_reports,
            verified=verified,
            restored=restored,
            recent=recent,
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template(
            "dashboard.html", active=0, my_reports=0, verified=0, restored=0, recent=[]
        )


@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    lang = get_current_lang()
    if request.method == "POST":
        neighborhood = request.form.get("neighborhood", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        start_time_str = request.form.get("start_time", "").strip()

        if not all([neighborhood, location, start_time_str]):
            flash(get_text("msg_missing_report_fields", lang=lang), "danger")
            return render_template("report.html")

        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash(get_text("msg_invalid_datetime", lang=lang), "danger")
            return render_template("report.html")

        try:
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute(
                """INSERT INTO outages
                   (user_id, neighborhood, location, description, start_time, status)
                   VALUES (%s, %s, %s, %s, %s, 'PENDING')""",
                (session["user_id"], neighborhood, location, description, start_time),
            )
            conn.commit()
            cur.close()
            conn.close()
            flash(get_text("msg_report_success", lang=lang), "success")
            return redirect(url_for("outages"))
        except Error:
            flash(get_text("msg_report_error", lang=lang), "danger")

    return render_template("report.html")


@app.route("/outages")
def outages():
    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    try:
        conn = get_db()
        cur = get_cursor(conn)

        sql = """
            SELECT o.*,
                   (SELECT COUNT(*) FROM confirmations c
                    WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
            FROM outages o
            WHERE 1=1
        """
        params = []

        if search:
            sql += " AND (o.neighborhood LIKE %s OR o.location LIKE %s OR o.description LIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like])

        if status_filter and status_filter in ("PENDING", "VERIFIED", "RESTORED", "REJECTED"):
            sql += " AND o.status = %s"
            params.append(status_filter)
        else:
            sql += " AND o.status != 'REJECTED'"

        sql += " ORDER BY o.created_at DESC LIMIT 50"

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return render_template(
            "outages.html", outages=rows, search=search, status_filter=status_filter
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template("outages.html", outages=[], search=search, status_filter=status_filter)


@app.route("/outage/<int:outage_id>")
def outage_details(outage_id):
    lang = get_current_lang()
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("""
            SELECT o.*, u.full_name,
                   (SELECT COUNT(*) FROM confirmations c
                    WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_off,
                   (SELECT COUNT(*) FROM confirmations c
                    WHERE c.outage_id = o.id AND c.confirmation = 'RESTORED') AS conf_restored
            FROM outages o
            JOIN users u ON o.user_id = u.id
            WHERE o.id = %s
        """, (outage_id,))
        outage = cur.fetchone()

        user_confirmed = False
        if "user_id" in session and outage:
            cur.execute(
                "SELECT id FROM confirmations WHERE outage_id = %s AND user_id = %s",
                (outage_id, session["user_id"]),
            )
            user_confirmed = cur.fetchone() is not None

        cur.close()
        conn.close()

        if not outage:
            flash(get_text("msg_outage_not_found", lang=lang), "danger")
            return redirect(url_for("outages"))

        return render_template(
            "outage_details.html",
            outage=outage,
            user_confirmed=user_confirmed,
        )
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
        return redirect(url_for("outages"))


@app.route("/outage/<int:outage_id>/confirm", methods=["POST"])
@login_required
def confirm_outage(outage_id):
    lang = get_current_lang()
    confirmation = request.form.get("confirmation", "").strip()
    if confirmation not in ("STILL_OFF", "RESTORED"):
        flash(get_text("msg_invalid_credentials", lang=lang), "danger")
        return redirect(url_for("outage_details", outage_id=outage_id))

    try:
        conn = get_db()
        cur = get_cursor(conn)

        cur.execute("SELECT status FROM outages WHERE id = %s", (outage_id,))
        outage = cur.fetchone()
        if not outage or outage["status"] == "REJECTED":
            flash(get_text("msg_outage_not_found", lang=lang), "danger")
            cur.close()
            conn.close()
            return redirect(url_for("outages"))

        cur.execute(
            "SELECT id FROM confirmations WHERE outage_id = %s AND user_id = %s",
            (outage_id, session["user_id"]),
        )
        if cur.fetchone():
            flash(get_text("msg_already_confirmed", lang=lang), "warning")
            cur.close()
            conn.close()
            return redirect(url_for("outage_details", outage_id=outage_id))

        cur.execute(
            """INSERT INTO confirmations (outage_id, user_id, confirmation)
               VALUES (%s, %s, %s)""",
            (outage_id, session["user_id"], confirmation),
        )
        conn.commit()
        cur.close()
        conn.close()

        if confirmation == "STILL_OFF":
            flash(get_text("msg_confirm_saved_off", lang=lang), "success")
        else:
            flash(get_text("msg_confirm_saved_restored", lang=lang), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")

    return redirect(url_for("outage_details", outage_id=outage_id))


@app.route("/my-reports")
@login_required
def my_reports():
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("""
            SELECT o.*,
                   (SELECT COUNT(*) FROM confirmations c
                    WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
            FROM outages o
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        """, (session["user_id"],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return render_template("my_reports.html", reports=rows)
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template("my_reports.html", reports=[])


@app.route("/ai", methods=["GET", "POST"])
def ai_page():
    lang = get_current_lang()
    answer = None
    question = ""
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if not question:
            flash(get_text("msg_ask_question_empty", lang=lang), "warning")
        else:
            try:
                conn = get_db()
                cur = get_cursor(conn)
                answer = ask_ai(question, cur, lang=lang)
                cur.close()
                conn.close()
            except Exception:
                answer = (
                    "Désolé, l'assistant IA est temporairement indisponible. Veuillez réessayer plus tard."
                    if lang == "fr"
                    else "Sorry, the AI assistant is temporarily unavailable. Please try again later."
                )
    return render_template("ai.html", answer=answer, question=question)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    lang = get_current_lang()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash(get_text("msg_email_password_required", lang=lang), "danger")
            return render_template("admin/admin_login.html")

        try:
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute("SELECT * FROM admins WHERE username = %s", (username,))
            admin = cur.fetchone()
            cur.close()
            conn.close()

            if admin and check_password_hash(admin["password_hash"], password):
                saved_lang = session.get("lang", "fr")
                session.clear()
                session["lang"] = saved_lang
                session["admin_id"] = admin["id"]
                session["admin_username"] = admin["username"]
                flash(get_text("msg_admin_login_success", lang=saved_lang), "success")
                return redirect(url_for("admin_dashboard"))
            else:
                flash(get_text("msg_admin_invalid", lang=lang), "danger")
        except Error:
            flash(get_text("msg_db_error", lang=lang), "danger")

    return render_template("admin/admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    saved_lang = session.get("lang", "fr")
    session.clear()
    session["lang"] = saved_lang
    flash(get_text("msg_admin_logged_out", lang=saved_lang), "info")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    try:
        conn = get_db()
        cur = get_cursor(conn)

        cur.execute("SELECT COUNT(*) AS c FROM users")
        total_users = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM outages")
        total_reports = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM outages WHERE status = 'PENDING'")
        pending = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM outages WHERE status = 'VERIFIED'")
        verified = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM outages WHERE status = 'RESTORED'")
        restored = cur.fetchone()["c"]

        cur.execute("""
            SELECT o.*, u.full_name, u.email
            FROM outages o
            JOIN users u ON o.user_id = u.id
            ORDER BY
                CASE o.status
                    WHEN 'PENDING' THEN 1
                    WHEN 'VERIFIED' THEN 2
                    WHEN 'RESTORED' THEN 3
                    ELSE 4
                END,
                o.created_at DESC
            LIMIT 100
        """)
        reports = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "admin/admin_dashboard.html",
            total_users=total_users,
            total_reports=total_reports,
            pending=pending,
            verified=verified,
            restored=restored,
            reports=reports,
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template(
            "admin/admin_dashboard.html",
            total_users=0, total_reports=0, pending=0,
            verified=0, restored=0, reports=[],
        )


@app.route("/admin/approve/<int:outage_id>", methods=["POST"])
@admin_required
def admin_approve(outage_id):
    lang = get_current_lang()
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute(
            "UPDATE outages SET status = 'VERIFIED' WHERE id = %s",
            (outage_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(get_text("msg_admin_approved", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reject/<int:outage_id>", methods=["POST"])
@admin_required
def admin_reject(outage_id):
    lang = get_current_lang()
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute(
            "UPDATE outages SET status = 'REJECTED' WHERE id = %s",
            (outage_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(get_text("msg_admin_rejected", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/restore/<int:outage_id>", methods=["POST"])
@admin_required
def admin_restore(outage_id):
    lang = get_current_lang()
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute(
            "UPDATE outages SET status = 'RESTORED' WHERE id = %s",
            (outage_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(get_text("msg_admin_restored", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/update/<int:outage_id>", methods=["POST"])
@admin_required
def admin_update(outage_id):
    lang = get_current_lang()
    estimate_str = request.form.get("estimated_restore", "").strip()
    if not estimate_str:
        flash(get_text("msg_provide_estimate", lang=lang), "warning")
        return redirect(url_for("admin_dashboard"))

    try:
        estimate = datetime.strptime(estimate_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash(get_text("msg_invalid_datetime", lang=lang), "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute(
            "UPDATE outages SET estimated_restore = %s WHERE id = %s",
            (estimate, outage_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(get_text("msg_admin_estimate_updated", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/<int:outage_id>", methods=["POST"])
@admin_required
def admin_delete(outage_id):
    lang = get_current_lang()
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("DELETE FROM outages WHERE id = %s", (outage_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash(get_text("msg_admin_deleted", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# API endpoint for map markers (simple JSON)
# ---------------------------------------------------------------------------

@app.route("/api/outages/map")
def api_map_outages():
    """Return outages for the simple map markers."""
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("""
            SELECT id, neighborhood, location, status
            FROM outages
            WHERE status IN ('PENDING', 'VERIFIED', 'RESTORED')
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        coords = {
            "bonamoussadi": [4.0850, 9.7400],
            "deido": [4.0600, 9.7200],
            "akwa": [4.0500, 9.7000],
            "bonanjo": [4.0400, 9.6900],
            "bali": [4.0450, 9.7050],
            "new bell": [4.0300, 9.7100],
            "bassa": [4.0200, 9.7500],
            "logbaba": [4.0100, 9.7600],
            "makepe": [4.0900, 9.7300],
            "kotto": [4.1000, 9.7500],
            "ndokoti": [4.0550, 9.7450],
            "yassa": [4.0000, 9.7800],
            "bonapriso": [4.0350, 9.6950],
            "bonaberi": [4.0800, 9.6700],
            "pk 8": [4.0700, 9.7800],
            "pk 10": [4.0650, 9.8000],
            "pk 12": [4.0600, 9.8200],
            "pk 14": [4.0550, 9.8400],
            "pk 17": [4.0500, 9.8700],
        }

        markers = []
        for r in rows:
            key = r["neighborhood"].lower().strip()
            latlng = coords.get(key, [4.0511, 9.7679])
            markers.append({
                "id": r["id"],
                "neighborhood": r["neighborhood"],
                "location": r["location"],
                "status": r["status"],
                "lat": latlng[0],
                "lng": latlng[1],
            })
        return jsonify(markers)
    except Error:
        return jsonify([])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)

