"""
Douala Power Alert
A participatory map and alert system of electricity outages in Douala.
School coding challenge – simple, elegant, bilingual (French default & English).
Enhanced with Connection Pooling, CSRF Protection, and Rate Limiting.
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
from mysql.connector import Error

from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from database import (
    get_db, get_cursor, get_db_cursor, init_db, ensure_admin
)
from services.ai_service import ask_ai
from translations import get_text

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "douala-power-alert-prod-secret-2026")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Initialize Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per hour", "60 per minute"],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded with localized message."""
    lang = get_current_lang()
    flash(get_text("msg_rate_limit_exceeded", lang=lang), "danger")
    referrer = request.referrer
    if referrer and request.host in referrer:
        return redirect(referrer)
    return redirect(url_for("index"))


@app.errorhandler(CSRFError)
def csrf_error_handler(e):
    """Handle CSRF validation failure with localized message."""
    lang = get_current_lang()
    flash(get_text("msg_csrf_error", lang=lang), "danger")
    referrer = request.referrer
    if referrer and request.host in referrer:
        return redirect(referrer)
    return redirect(url_for("index"))


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
@limiter.limit("5 per minute")
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
            with get_db_cursor(commit=True) as cur:
                cur.execute(
                    """INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (full_name, email, phone, password_hash, neighborhood),
                )
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
@limiter.limit("5 per minute")
def login():
    lang = get_current_lang()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash(get_text("msg_email_password_required", lang=lang), "danger")
            return render_template("login.html", email=email)

        try:
            with get_db_cursor() as cur:
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cur.fetchone()

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
        with get_db_cursor() as cur:
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
@limiter.limit("10 per minute")
def report():
    lang = get_current_lang()
    form_data = {
        "neighborhood": session.get("user_neighborhood", ""),
        "location": "",
        "description": "",
        "start_time": "",
        "latitude": "",
        "longitude": "",
    }

    if request.method == "POST":
        neighborhood = request.form.get("neighborhood", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        start_time_str = request.form.get("start_time", "").strip()
        latitude_str = request.form.get("latitude", "").strip()
        longitude_str = request.form.get("longitude", "").strip()
        is_distinct = request.form.get("is_distinct", "") == "1"

        lat = None
        lng = None
        if latitude_str and longitude_str:
            try:
                parsed_lat = float(latitude_str)
                parsed_lng = float(longitude_str)
                # Douala / Littoral bounding check (lat: 3.5 to 4.6, lng: 9.3 to 10.3)
                if 3.5 <= parsed_lat <= 4.6 and 9.3 <= parsed_lng <= 10.3:
                    lat = parsed_lat
                    lng = parsed_lng
            except ValueError:
                lat, lng = None, None

        form_data = {
            "neighborhood": neighborhood,
            "location": location,
            "description": description,
            "start_time": start_time_str,
            "latitude": str(lat) if lat is not None else "",
            "longitude": str(lng) if lng is not None else "",
        }

        if not all([neighborhood, location, start_time_str]):
            flash(get_text("msg_missing_report_fields", lang=lang), "danger")
            return render_template("report.html", form_data=form_data, existing_duplicate=None)

        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash(get_text("msg_invalid_datetime", lang=lang), "danger")
            return render_template("report.html", form_data=form_data, existing_duplicate=None)

        # Duplicate check: if user didn't explicitly tick "is_distinct", check for active outage in same neighborhood
        if not is_distinct:
            try:
                with get_db_cursor() as cur:
                    cur.execute("""
                        SELECT o.id, o.neighborhood, o.location, o.start_time, o.status,
                               (SELECT COUNT(*) FROM confirmations c WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                        FROM outages o
                        WHERE LOWER(o.neighborhood) = %s AND o.status IN ('PENDING', 'VERIFIED')
                        ORDER BY o.created_at DESC
                        LIMIT 1
                    """, (neighborhood.lower(),))
                    existing = cur.fetchone()

                if existing:
                    flash(
                        get_text("msg_duplicate_found", lang=lang,
                                 neighborhood=existing["neighborhood"],
                                 location=existing["location"]),
                        "warning"
                    )
                    return render_template("report.html", form_data=form_data, existing_duplicate=existing)
            except Exception:
                pass

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute(
                    """INSERT INTO outages
                       (user_id, neighborhood, location, description, start_time, status, latitude, longitude)
                       VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)""",
                    (session["user_id"], neighborhood, location, description, start_time, lat, lng),
                )
            flash(get_text("msg_report_success", lang=lang), "success")
            return redirect(url_for("outages"))
        except Error:
            flash(get_text("msg_report_error", lang=lang), "danger")

    return render_template("report.html", form_data=form_data, existing_duplicate=None)


@app.route("/outages")
def outages():
    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    try:
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

        with get_db_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

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
        with get_db_cursor() as cur:
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
@limiter.limit("20 per minute")
def confirm_outage(outage_id):
    lang = get_current_lang()
    confirmation = request.form.get("confirmation", "").strip()
    if confirmation not in ("STILL_OFF", "RESTORED"):
        flash(get_text("msg_invalid_credentials", lang=lang), "danger")
        return redirect(url_for("outage_details", outage_id=outage_id))

    try:
        auto_verified = False
        auto_restored = False
        total_confs = 0

        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT status FROM outages WHERE id = %s", (outage_id,))
            outage = cur.fetchone()
            if not outage or outage["status"] == "REJECTED":
                flash(get_text("msg_outage_not_found", lang=lang), "danger")
                return redirect(url_for("outages"))

            cur.execute(
                "SELECT id FROM confirmations WHERE outage_id = %s AND user_id = %s",
                (outage_id, session["user_id"]),
            )
            if cur.fetchone():
                flash(get_text("msg_already_confirmed", lang=lang), "warning")
                return redirect(url_for("outage_details", outage_id=outage_id))

            cur.execute(
                """INSERT INTO confirmations (outage_id, user_id, confirmation)
                   VALUES (%s, %s, %s)""",
                (outage_id, session["user_id"], confirmation),
            )

            # Community Auto-Verification: 3+ STILL_OFF confirmations auto-promote PENDING to VERIFIED
            if confirmation == "STILL_OFF" and outage["status"] == "PENDING":
                cur.execute(
                    "SELECT COUNT(*) AS c FROM confirmations WHERE outage_id = %s AND confirmation = 'STILL_OFF'",
                    (outage_id,)
                )
                total_confs = cur.fetchone()["c"]
                if total_confs >= 3:
                    cur.execute("UPDATE outages SET status = 'VERIFIED' WHERE id = %s", (outage_id,))
                    auto_verified = True

            # Community Auto-Restoration: 3+ RESTORED confirmations auto-promote to RESTORED
            elif confirmation == "RESTORED" and outage["status"] in ("PENDING", "VERIFIED"):
                cur.execute(
                    "SELECT COUNT(*) AS c FROM confirmations WHERE outage_id = %s AND confirmation = 'RESTORED'",
                    (outage_id,)
                )
                total_confs = cur.fetchone()["c"]
                if total_confs >= 3:
                    cur.execute("UPDATE outages SET status = 'RESTORED' WHERE id = %s", (outage_id,))
                    auto_restored = True

        if auto_verified:
            flash(get_text("msg_auto_verified_community", lang=lang, count=total_confs), "success")
        elif auto_restored:
            flash(get_text("msg_auto_restored_community", lang=lang, count=total_confs), "success")
        elif confirmation == "STILL_OFF":
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
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.*,
                       (SELECT COUNT(*) FROM confirmations c
                        WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                WHERE o.user_id = %s
                ORDER BY o.created_at DESC
            """, (session["user_id"],))
            rows = cur.fetchall()
        return render_template("my_reports.html", reports=rows)
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template("my_reports.html", reports=[])


@app.route("/ai", methods=["GET", "POST"])
@limiter.limit("15 per minute")
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
                with get_db_cursor() as cur:
                    answer = ask_ai(question, cur, lang=lang)
            except Exception:
                answer = (
                    "Désolé, l'assistant IA est temporairement indisponible. Veuillez réessayer plus tard."
                    if lang == "fr"
                    else "Sorry, the AI assistant is temporarily unavailable. Please try again later."
                )
    return render_template("ai.html", answer=answer, question=question)


# ---------------------------------------------------------------------------
# Analytics & Load-Shedding Severity View
# ---------------------------------------------------------------------------

@app.route("/analytics")
def analytics():
    lang = get_current_lang()
    try:
        with get_db_cursor() as cur:
            # 1. Total outages
            cur.execute("SELECT COUNT(*) AS c FROM outages")
            total_outages = cur.fetchone()["c"]

            # 2. Active outages
            cur.execute("SELECT COUNT(*) AS c FROM outages WHERE status IN ('PENDING', 'VERIFIED')")
            active_outages = cur.fetchone()["c"]

            # 3. Restored outages
            cur.execute("SELECT COUNT(*) AS c FROM outages WHERE status = 'RESTORED'")
            restored_outages = cur.fetchone()["c"]

            # Resolution rate
            resolution_rate = round((restored_outages / total_outages * 100), 1) if total_outages > 0 else 100.0

            # 4. Average duration across Douala (in hours)
            cur.execute("""
                SELECT AVG(CASE 
                    WHEN status = 'RESTORED' AND updated_at > start_time 
                    THEN TIMESTAMPDIFF(MINUTE, start_time, updated_at)
                    WHEN estimated_restore IS NOT NULL AND estimated_restore > start_time 
                    THEN TIMESTAMPDIFF(MINUTE, start_time, estimated_restore)
                    ELSE NULL 
                END) AS avg_duration_mins
                FROM outages
            """)
            dur_row = cur.fetchone()
            avg_duration_hours = round(float(dur_row["avg_duration_mins"]) / 60.0, 1) if dur_row and dur_row.get("avg_duration_mins") else 3.5

            # 5. Neighborhood Severity Ranking
            cur.execute("""
                SELECT 
                    neighborhood,
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('PENDING', 'VERIFIED') THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN status = 'RESTORED' THEN 1 ELSE 0 END) AS restored,
                    AVG(CASE 
                        WHEN status = 'RESTORED' AND updated_at > start_time 
                        THEN TIMESTAMPDIFF(MINUTE, start_time, updated_at)
                        WHEN estimated_restore IS NOT NULL AND estimated_restore > start_time 
                        THEN TIMESTAMPDIFF(MINUTE, start_time, estimated_restore)
                        ELSE NULL 
                    END) AS avg_duration_mins
                FROM outages
                GROUP BY neighborhood
                ORDER BY active DESC, total DESC
            """)
            ranking_rows = cur.fetchall()

        most_affected = ranking_rows[0]["neighborhood"] if ranking_rows else "—"
        max_total = max([r["total"] for r in ranking_rows]) if ranking_rows else 1

        neighborhood_stats = []
        for r in ranking_rows:
            tot = r["total"]
            act = int(r["active"] or 0)
            res = int(r["restored"] or 0)
            avg_m = r.get("avg_duration_mins")
            avg_h = round(float(avg_m) / 60.0, 1) if avg_m else avg_duration_hours
            percent = int((tot / max_total) * 100) if max_total > 0 else 0

            # Severity tier
            if act >= 2 or tot >= 6:
                sev_key = "severity_critical"
                sev_color = "#ef4444"
            elif act >= 1 or tot >= 3:
                sev_key = "severity_high"
                sev_color = "#f97316"
            elif tot >= 1:
                sev_key = "severity_moderate"
                sev_color = "#f59e0b"
            else:
                sev_key = "severity_low"
                sev_color = "#10b981"

            neighborhood_stats.append({
                "neighborhood": r["neighborhood"],
                "total": tot,
                "active": act,
                "restored": res,
                "avg_duration": avg_h,
                "percent": percent,
                "severity_key": sev_key,
                "severity_color": sev_color
            })

        return render_template(
            "analytics.html",
            total_outages=total_outages,
            active_outages=active_outages,
            restored_outages=restored_outages,
            resolution_rate=resolution_rate,
            avg_duration_hours=avg_duration_hours,
            most_affected=most_affected,
            neighborhood_stats=neighborhood_stats
        )
    except Exception:
        flash(get_text("msg_db_error", lang=lang), "danger")
        return render_template(
            "analytics.html",
            total_outages=0,
            active_outages=0,
            restored_outages=0,
            resolution_rate=0,
            avg_duration_hours=0,
            most_affected="—",
            neighborhood_stats=[]
        )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    lang = get_current_lang()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash(get_text("msg_email_password_required", lang=lang), "danger")
            return render_template("admin/admin_login.html")

        try:
            with get_db_cursor() as cur:
                cur.execute("SELECT * FROM admins WHERE username = %s", (username,))
                admin = cur.fetchone()

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
        with get_db_cursor() as cur:
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
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE outages SET status = 'VERIFIED' WHERE id = %s",
                (outage_id,),
            )
        flash(get_text("msg_admin_approved", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reject/<int:outage_id>", methods=["POST"])
@admin_required
def admin_reject(outage_id):
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE outages SET status = 'REJECTED' WHERE id = %s",
                (outage_id,),
            )
        flash(get_text("msg_admin_rejected", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/restore/<int:outage_id>", methods=["POST"])
@admin_required
def admin_restore(outage_id):
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE outages SET status = 'RESTORED' WHERE id = %s",
                (outage_id,),
            )
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
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE outages SET estimated_restore = %s WHERE id = %s",
                (estimate, outage_id),
            )
        flash(get_text("msg_admin_estimate_updated", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/<int:outage_id>", methods=["POST"])
@admin_required
def admin_delete(outage_id):
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM outages WHERE id = %s", (outage_id,))
        flash(get_text("msg_admin_deleted", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# API endpoints (JSON)
# ---------------------------------------------------------------------------

@app.route("/api/outages/active-by-neighborhood")
def api_active_by_neighborhood():
    """Return active outages for a neighborhood to detect duplicates."""
    neighborhood = request.args.get("neighborhood", "").strip().lower()
    if not neighborhood:
        return jsonify({"found": False, "outages": []})

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.id, o.neighborhood, o.location, o.start_time, o.status,
                       (SELECT COUNT(*) FROM confirmations c WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                WHERE LOWER(o.neighborhood) = %s AND o.status IN ('PENDING', 'VERIFIED')
                ORDER BY o.created_at DESC
                LIMIT 3
            """, (neighborhood,))
            rows = cur.fetchall()

        if not rows:
            return jsonify({"found": False, "outages": []})

        outages_list = []
        for r in rows:
            st = r["start_time"].strftime("%H:%M") if r.get("start_time") else ""
            outages_list.append({
                "id": r["id"],
                "neighborhood": r["neighborhood"],
                "location": r["location"],
                "status": r["status"],
                "start_time": st,
                "conf_count": r["conf_count"]
            })
        return jsonify({"found": True, "outages": outages_list})
    except Exception:
        return jsonify({"found": False, "outages": []})


@app.route("/api/analytics/heatmap")
def api_analytics_heatmap():
    """Return weighted coordinate points [lat, lng, intensity] for Leaflet Heatmap."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, neighborhood, status, latitude, longitude,
                       (SELECT COUNT(*) FROM confirmations c WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                WHERE status IN ('PENDING', 'VERIFIED', 'RESTORED')
                ORDER BY created_at DESC
                LIMIT 200
            """)
            rows = cur.fetchall()

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

        heat_points = []
        for r in rows:
            key = r["neighborhood"].lower().strip()
            if r.get("latitude") is not None and r.get("longitude") is not None:
                lat = float(r["latitude"])
                lng = float(r["longitude"])
            else:
                latlng = coords.get(key, [4.0511, 9.7679])
                lat, lng = latlng[0], latlng[1]

            conf = r.get("conf_count", 0) or 0
            if r["status"] == "VERIFIED":
                intensity = min(1.0, 0.75 + (conf * 0.08))
            elif r["status"] == "PENDING":
                intensity = min(0.7, 0.45 + (conf * 0.05))
            else:
                intensity = 0.25

            heat_points.append([lat, lng, round(intensity, 2)])

        return jsonify(heat_points)
    except Exception:
        return jsonify([])


@app.route("/api/outages/map")
def api_map_outages():
    """Return outages for the simple map markers."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, neighborhood, location, status, latitude, longitude
                FROM outages
                WHERE status IN ('PENDING', 'VERIFIED', 'RESTORED')
                ORDER BY created_at DESC
                LIMIT 100
            """)
            rows = cur.fetchall()

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
            if r.get("latitude") is not None and r.get("longitude") is not None:
                lat = float(r["latitude"])
                lng = float(r["longitude"])
            else:
                latlng = coords.get(key, [4.0511, 9.7679])
                lat = latlng[0]
                lng = latlng[1]

            markers.append({
                "id": r["id"],
                "neighborhood": r["neighborhood"],
                "location": r["location"],
                "status": r["status"],
                "lat": lat,
                "lng": lng,
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
