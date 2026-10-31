"""
Authentication Blueprint for Douala Power Alert.
Handles citizen registration, login, session initialization, and logout.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from mysql.connector import Error

from extensions import limiter
from database import get_db_cursor
from translations import get_text
from routes.utils import get_current_lang

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    """Citizen account creation with password hashing and validation."""
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
            return redirect(url_for("auth.login"))
        except Error as e:
            if e.errno == 1062:  # Duplicate entry
                flash(get_text("msg_email_phone_exists", lang=lang), "danger")
            else:
                flash(get_text("msg_db_error", lang=lang), "danger")
            return render_template("register.html", form_data=form_data)

    return render_template("register.html", form_data=form_data)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    """Citizen authentication and session establishment."""
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
                return redirect(url_for("outages.dashboard"))
            else:
                flash(get_text("msg_invalid_credentials", lang=lang), "danger")
        except Error:
            flash(get_text("msg_db_error", lang=lang), "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Log out current citizen and clear session securely."""
    saved_lang = session.get("lang", "fr")
    session.clear()
    session["lang"] = saved_lang
    flash(get_text("msg_logged_out", lang=saved_lang), "info")
    return redirect(url_for("main.index"))
