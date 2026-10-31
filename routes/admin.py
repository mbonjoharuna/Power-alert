"""
Admin Blueprint for Douala Power Alert.
Handles administrator authentication, dashboard oversight, outage approvals,
rejections, restoration completions, and estimate adjustments.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from mysql.connector import Error

from extensions import limiter
from database import get_db_cursor
from translations import get_text
from routes.utils import admin_required, get_current_lang
from services.notification_service import create_neighborhood_notification

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    """Administrator login authentication."""
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
                return redirect(url_for("admin.admin_dashboard"))
            else:
                flash(get_text("msg_admin_invalid", lang=lang), "danger")
        except Error:
            flash(get_text("msg_db_error", lang=lang), "danger")

    return render_template("admin/admin_login.html")


@admin_bp.route("/admin/logout")
def admin_logout():
    """Administrator session sign-out."""
    saved_lang = session.get("lang", "fr")
    session.clear()
    session["lang"] = saved_lang
    flash(get_text("msg_admin_logged_out", lang=saved_lang), "info")
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Administrative management dashboard displaying overview metrics and reports queue."""
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


@admin_bp.route("/admin/approve/<int:outage_id>", methods=["POST"])
@admin_required
def admin_approve(outage_id):
    """Approve an outage report, updating status to VERIFIED and alerting neighborhood."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            o = cur.fetchone()
            cur.execute(
                "UPDATE outages SET status = 'VERIFIED' WHERE id = %s",
                (outage_id,),
            )
        if o:
            create_neighborhood_notification(
                neighborhood=o["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_verified_title", lang=lang),
                message=get_text("notif_verified_msg", lang=lang, neighborhood=o["neighborhood"], location=o["location"]),
                notif_type="OUTAGE_VERIFIED"
            )
        flash(get_text("msg_admin_approved", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/reject/<int:outage_id>", methods=["POST"])
@admin_required
def admin_reject(outage_id):
    """Reject an invalid or duplicate outage report."""
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
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/restore/<int:outage_id>", methods=["POST"])
@admin_required
def admin_restore(outage_id):
    """Mark an outage as RESTORED and dispatch neighborhood notifications."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            o = cur.fetchone()
            cur.execute(
                "UPDATE outages SET status = 'RESTORED' WHERE id = %s",
                (outage_id,),
            )
        if o:
            create_neighborhood_notification(
                neighborhood=o["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_restored_title", lang=lang),
                message=get_text("notif_restored_msg", lang=lang, neighborhood=o["neighborhood"], location=o["location"]),
                notif_type="OUTAGE_RESTORED"
            )
        flash(get_text("msg_admin_restored", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/update/<int:outage_id>", methods=["POST"])
@admin_required
def admin_update(outage_id):
    """Update estimated restoration datetime and alert neighborhood residents."""
    lang = get_current_lang()
    estimate_str = request.form.get("estimated_restore", "").strip()
    if not estimate_str:
        flash(get_text("msg_provide_estimate", lang=lang), "warning")
        return redirect(url_for("admin.admin_dashboard"))

    try:
        estimate = datetime.strptime(estimate_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash(get_text("msg_invalid_datetime", lang=lang), "danger")
        return redirect(url_for("admin.admin_dashboard"))

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            o = cur.fetchone()
            cur.execute(
                "UPDATE outages SET estimated_restore = %s WHERE id = %s",
                (estimate, outage_id),
            )
        if o:
            time_str = estimate.strftime("%d/%m/%Y à %H:%M")
            create_neighborhood_notification(
                neighborhood=o["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_estimate_title", lang=lang),
                message=get_text("notif_estimate_msg", lang=lang, neighborhood=o["neighborhood"], location=o["location"], time=time_str),
                notif_type="OUTAGE_ESTIMATE"
            )
        flash(get_text("msg_admin_estimate_updated", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/delete/<int:outage_id>", methods=["POST"])
@admin_required
def admin_delete(outage_id):
    """Delete an outage record from the database."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM outages WHERE id = %s", (outage_id,))
        flash(get_text("msg_admin_deleted", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))
