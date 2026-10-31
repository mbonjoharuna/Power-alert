"""
Admin Blueprint for Douala Power Alert.
Handles administrator authentication, dashboard oversight, outage approvals,
rejections, restoration completions, estimate adjustments, Eneo maintenance schedule imports,
and critical civic infrastructure monitoring.
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
from services.schedule_service import (
    create_schedule,
    get_all_schedules,
    delete_schedule,
    import_schedules_from_csv,
    import_schedules_from_json,
    load_sample_douala_schedules,
    correlate_all_outages_with_schedules
)
from services.facility_service import (
    get_all_facilities,
    get_critical_facilities_kpis,
    seed_douala_critical_facilities,
    create_facility,
    update_facility,
    delete_facility,
    update_facility_power_status,
    sync_facilities_with_active_outages
)

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

            cur.execute("SELECT COUNT(*) AS c FROM scheduled_outages WHERE status IN ('SCHEDULED', 'IN_PROGRESS')")
            active_schedules_count = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) AS c FROM critical_facilities WHERE current_power_status IN ('BACKUP_GENERATOR', 'CRITICAL_BLACKOUT')")
            critical_alert_count = cur.fetchone()["c"]

            cur.execute("""
                SELECT o.*, u.full_name, u.email, s.title AS schedule_title
                FROM outages o
                JOIN users u ON o.user_id = u.id
                LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
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
            active_schedules_count=active_schedules_count,
            critical_alert_count=critical_alert_count,
            reports=reports,
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template(
            "admin/admin_dashboard.html",
            total_users=0, total_reports=0, pending=0, verified=0, restored=0,
            active_schedules_count=0, critical_alert_count=0, reports=[],
        )


@admin_bp.route("/admin/outages/<int:outage_id>/approve", methods=["POST"])
@admin_bp.route("/admin/approve/<int:outage_id>", methods=["POST"])
@admin_required
def admin_approve(outage_id):
    """Admin approves pending outage report to VERIFIED status."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            outage = cur.fetchone()

            cur.execute(
                "UPDATE outages SET status = 'VERIFIED' WHERE id = %s",
                (outage_id,),
            )

        sync_facilities_with_active_outages()

        if outage:
            create_neighborhood_notification(
                neighborhood=outage["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_verified_title", lang=lang),
                message=get_text("notif_verified_msg", lang=lang, neighborhood=outage["neighborhood"], location=outage["location"]),
                notif_type="OUTAGE_VERIFIED"
            )

        flash(get_text("msg_admin_approved", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/outages/<int:outage_id>/reject", methods=["POST"])
@admin_bp.route("/admin/reject/<int:outage_id>", methods=["POST"])
@admin_required
def admin_reject(outage_id):
    """Admin rejects invalid or erroneous report."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE outages SET status = 'REJECTED' WHERE id = %s",
                (outage_id,),
            )
        sync_facilities_with_active_outages()
        flash(get_text("msg_admin_rejected", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/outages/<int:outage_id>/restore", methods=["POST"], endpoint="admin_restore")
@admin_bp.route("/admin/restore/<int:outage_id>", methods=["POST"])
@admin_bp.route("/admin/outages/<int:outage_id>/restore", methods=["POST"], endpoint="admin_mark_restored")
@admin_required
def admin_mark_restored(outage_id):
    """Admin marks outage as RESTORED and dispatches notifications."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            outage = cur.fetchone()

            cur.execute(
                "UPDATE outages SET status = 'RESTORED' WHERE id = %s",
                (outage_id,),
            )

        sync_facilities_with_active_outages()

        if outage:
            create_neighborhood_notification(
                neighborhood=outage["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_restored_title", lang=lang),
                message=get_text("notif_restored_msg", lang=lang, neighborhood=outage["neighborhood"], location=outage["location"]),
                notif_type="OUTAGE_RESTORED"
            )

        flash(get_text("msg_admin_restored", lang=lang, id=outage_id), "success")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/outages/<int:outage_id>/estimate", methods=["POST"], endpoint="admin_update")
@admin_bp.route("/admin/estimate/<int:outage_id>", methods=["POST"])
@admin_bp.route("/admin/update/<int:outage_id>", methods=["POST"])
@admin_bp.route("/admin/outages/<int:outage_id>/estimate", methods=["POST"], endpoint="admin_update_estimate")
@admin_required
def admin_update_estimate(outage_id):
    """Admin adjusts estimated restoration timestamp."""
    lang = get_current_lang()
    est_str = request.form.get("estimated_restore", "").strip()
    if not est_str:
        flash(get_text("msg_provide_estimate", lang=lang), "warning")
        return redirect(url_for("admin.admin_dashboard"))

    try:
        est_dt = datetime.strptime(est_str, "%Y-%m-%dT%H:%M")
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            outage = cur.fetchone()

            cur.execute(
                "UPDATE outages SET estimated_restore = %s WHERE id = %s",
                (est_dt, outage_id),
            )

        if outage:
            create_neighborhood_notification(
                neighborhood=outage["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_estimate_title", lang=lang),
                message=get_text("notif_estimate_msg", lang=lang, time=est_dt.strftime("%H:%M"), neighborhood=outage["neighborhood"], location=outage["location"]),
                notif_type="OUTAGE_ESTIMATE"
            )

        flash(get_text("msg_admin_estimate_updated", lang=lang, id=outage_id), "success")
    except ValueError:
        flash(get_text("msg_invalid_datetime", lang=lang), "danger")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/outages/<int:outage_id>/toggle-type", methods=["POST"], endpoint="admin_toggle_type")
@admin_bp.route("/admin/outages/<int:outage_id>/toggle-type", methods=["POST"], endpoint="admin_toggle_outage_type")
@admin_required
def admin_toggle_outage_type(outage_id):
    """Admin manually toggles an outage between SCHEDULED and UNPLANNED."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT outage_type FROM outages WHERE id = %s", (outage_id,))
            row = cur.fetchone()
            if not row:
                flash("Coupure introuvable.", "danger")
                return redirect(url_for("admin.admin_dashboard"))

            current_type = row.get("outage_type") or "UNPLANNED"
            new_type = "UNPLANNED" if current_type == "SCHEDULED" else "SCHEDULED"
            cur.execute("UPDATE outages SET outage_type = %s WHERE id = %s", (new_type, outage_id))
            flash(f"Type de coupure mis à jour : {new_type}", "info")
    except Exception as e:
        flash(f"Erreur lors de la mise à jour : {e}", "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/outages/<int:outage_id>/delete", methods=["POST"])
@admin_bp.route("/admin/delete/<int:outage_id>", methods=["POST"])
@admin_required
def admin_delete(outage_id):
    """Admin permanently deletes an outage report."""
    lang = get_current_lang()
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM outages WHERE id = %s", (outage_id,))
        sync_facilities_with_active_outages()
        flash(get_text("msg_admin_deleted", lang=lang, id=outage_id), "info")
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/schedules")
@admin_required
def admin_schedules():
    """Management interface for Eneo scheduled maintenance windows."""
    schedules = get_all_schedules()
    return render_template("admin/admin_schedules.html", schedules=schedules)


@admin_bp.route("/admin/schedules/create", methods=["POST"])
@admin_required
def admin_create_schedule():
    """Manually insert an Eneo scheduled outage."""
    neighborhood = request.form.get("neighborhood", "").strip()
    title = request.form.get("title", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "SCHEDULED").strip()

    if not all([neighborhood, title, start_time, end_time]):
        flash("Veuillez remplir tous les champs obligatoires pour la maintenance.", "danger")
        return redirect(url_for("admin.admin_schedules"))

    try:
        create_schedule(neighborhood, title, start_time, end_time, description, status)
        flash(f"Maintenance planifiée ajoutée pour {neighborhood} !", "success")
    except Exception as e:
        flash(f"Erreur lors de l'enregistrement : {e}", "danger")

    return redirect(url_for("admin.admin_schedules"))


@admin_bp.route("/admin/schedules/import", methods=["POST"])
@admin_required
def admin_import_schedules():
    """Import schedule records from uploaded CSV/JSON file or raw text."""
    uploaded_file = request.files.get("file")
    raw_text = request.form.get("raw_text", "").strip()

    count = 0
    try:
        if uploaded_file and uploaded_file.filename:
            content = uploaded_file.read().decode("utf-8")
            if uploaded_file.filename.endswith(".json"):
                count = import_schedules_from_json(content)
            else:
                count = import_schedules_from_csv(content)
        elif raw_text:
            if raw_text.startswith("["):
                count = import_schedules_from_json(raw_text)
            else:
                count = import_schedules_from_csv(raw_text)

        flash(f"Succès ! {count} créneau(x) de maintenance Eneo importé(s).", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {e}", "danger")

    return redirect(url_for("admin.admin_schedules"))


@admin_bp.route("/admin/schedules/load-samples", methods=["POST"])
@admin_required
def admin_load_samples():
    """Load sample Eneo maintenance and load-shedding rotas across Douala."""
    try:
        count = load_sample_douala_schedules()
        flash(f"{count} programmes de maintenance Eneo types ont été chargés avec succès !", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "danger")
    return redirect(url_for("admin.admin_schedules"))


@admin_bp.route("/admin/schedules/<int:schedule_id>/delete", methods=["POST"])
@admin_required
def admin_delete_schedule(schedule_id):
    """Delete a scheduled outage slot."""
    try:
        delete_schedule(schedule_id)
        flash("Créneau de maintenance supprimé.", "info")
    except Exception as e:
        flash(f"Erreur : {e}", "danger")
    return redirect(url_for("admin.admin_schedules"))


# ============================================================================
# OPTION 3: CRITICAL INFRASTRUCTURE MANAGEMENT ROUTES
# ============================================================================

@admin_bp.route("/admin/infrastructure")
@admin_required
def admin_infrastructure():
    """Admin oversight for hospitals, clinics, and water stations."""
    facilities = get_all_facilities()
    kpis = get_critical_facilities_kpis()
    return render_template("admin/admin_infrastructure.html", facilities=facilities, kpis=kpis)


@admin_bp.route("/admin/infrastructure/seed", methods=["POST"])
@admin_required
def admin_seed_infrastructure():
    """Reset / seed baseline 8 critical facilities of Douala."""
    try:
        count = seed_douala_critical_facilities(overwrite=True)
        sync_facilities_with_active_outages()
        flash(f"Succès : {count} infrastructures vitales de Douala initialisées avec succès !", "success")
    except Exception as e:
        flash(f"Erreur lors de l'initialisation : {e}", "danger")
    return redirect(url_for("admin.admin_infrastructure"))


@admin_bp.route("/admin/infrastructure/create", methods=["POST"])
@admin_required
def admin_create_infrastructure():
    """Create a new critical facility record."""
    name = request.form.get("name", "").strip()
    facility_type = request.form.get("facility_type", "HOSPITAL")
    neighborhood = request.form.get("neighborhood", "").strip()
    address = request.form.get("address", "").strip()
    lat_str = request.form.get("latitude", "").strip()
    lng_str = request.form.get("longitude", "").strip()
    has_gen = request.form.get("has_backup_generator") == "1"
    gen_kva = request.form.get("generator_capacity_kva", "").strip()
    fuel_hours = request.form.get("fuel_autonomy_hours", "12.0").strip()
    status = request.form.get("current_power_status", "ON_GRID")
    contact_name = request.form.get("contact_name", "").strip()
    contact_phone = request.form.get("contact_phone", "").strip()
    notes = request.form.get("notes", "").strip()

    if not all([name, neighborhood, lat_str, lng_str]):
        flash("Veuillez renseigner le nom, le quartier et les coordonnées GPS.", "danger")
        return redirect(url_for("admin.admin_infrastructure"))

    try:
        create_facility({
            "name": name,
            "facility_type": facility_type,
            "neighborhood": neighborhood,
            "address": address,
            "latitude": float(lat_str),
            "longitude": float(lng_str),
            "has_backup_generator": has_gen,
            "generator_capacity_kva": int(gen_kva) if gen_kva else None,
            "fuel_autonomy_hours": float(fuel_hours) if fuel_hours else 12.0,
            "current_power_status": status,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "notes": notes
        })
        flash(f"Établissement critique '{name}' ajouté au registre avec succès !", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "danger")

    return redirect(url_for("admin.admin_infrastructure"))


@admin_bp.route("/admin/infrastructure/<int:facility_id>/update-status", methods=["POST"])
@admin_required
def admin_update_infrastructure_status(facility_id):
    """Manually update facility power status and fuel reserves."""
    new_status = request.form.get("current_power_status")
    fuel_hours = request.form.get("fuel_autonomy_hours")
    fuel = float(fuel_hours) if fuel_hours else None

    if update_facility_power_status(facility_id, new_status, fuel):
        flash("Statut de l'infrastructure mis à jour.", "success")
    else:
        flash("Erreur lors de la mise à jour du statut.", "danger")

    return redirect(url_for("admin.admin_infrastructure"))


@admin_bp.route("/admin/infrastructure/<int:facility_id>/delete", methods=["POST"])
@admin_required
def admin_delete_infrastructure(facility_id):
    """Delete facility from registry."""
    if delete_facility(facility_id):
        flash("Infrastructure supprimée du registre.", "info")
    else:
        flash("Erreur lors de la suppression.", "danger")
    return redirect(url_for("admin.admin_infrastructure"))
