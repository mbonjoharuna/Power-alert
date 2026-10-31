"""
Outages Blueprint for Douala Power Alert.
Handles citizen dashboard, outage reporting with GPS, Eneo schedule correlation,
critical infrastructure alerting, listings, confirmations, personal reports history,
load-shedding severity analytics, and public critical facilities oversight.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from mysql.connector import Error

from extensions import limiter
from database import get_db_cursor
from translations import get_text
from routes.utils import login_required, get_current_lang
from services.notification_service import (
    create_neighborhood_notification,
    create_critical_infrastructure_alert
)
from services.schedule_service import find_matching_schedule, get_all_schedules
from services.facility_service import (
    get_all_facilities,
    get_critical_facilities_kpis,
    check_outage_critical_impact,
    get_facilities_by_neighborhood,
    update_facility_power_status,
    sync_facilities_with_active_outages
)

outages_bp = Blueprint("outages", __name__)


@outages_bp.route("/dashboard")
@login_required
def dashboard():
    """Citizen dashboard showing personalized stats, registered zone alerts, and recent outages."""
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

            # Active in user's neighborhood
            user_neighborhood = session.get("user_neighborhood", "")
            cur.execute(
                "SELECT COUNT(*) AS c FROM outages WHERE LOWER(neighborhood) = %s AND status IN ('PENDING', 'VERIFIED')",
                (user_neighborhood.lower(),)
            )
            local_active = cur.fetchone()["c"]

            cur.execute("""
                SELECT o.*,
                       s.title AS schedule_title,
                       (SELECT COUNT(*) FROM confirmations c
                        WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
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
            local_active=local_active,
            recent=recent,
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template(
            "dashboard.html",
            active=0, my_reports=0, verified=0, restored=0, local_active=0, recent=[],
        )


@outages_bp.route("/report", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute")
def report():
    """Report an outage with duplicate detection, GPS pin, Eneo schedule matching, and critical infrastructure alerting."""
    lang = get_current_lang()
    form_data = None
    existing = None

    if request.method == "POST":
        neighborhood = request.form.get("neighborhood", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        start_time_str = request.form.get("start_time", "").strip()
        is_distinct = request.form.get("is_distinct") == "1"

        lat_raw = request.form.get("latitude", "").strip()
        lng_raw = request.form.get("longitude", "").strip()
        lat = None
        lng = None
        if lat_raw and lng_raw:
            try:
                lat = float(lat_raw)
                lng = float(lng_raw)
            except ValueError:
                pass

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

        # Check if report falls within an official Eneo scheduled maintenance window
        matched_sched = find_matching_schedule(neighborhood, start_time)
        outage_type = "SCHEDULED" if matched_sched else "UNPLANNED"
        schedule_id = matched_sched["id"] if matched_sched else None
        est_restore = matched_sched["end_time"] if matched_sched else None

        # Check Critical Infrastructure impact (Hospitals, water stations, dialysis)
        impacted_facs, is_critical = check_outage_critical_impact(neighborhood, lat=lat, lng=lng)

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute(
                    """INSERT INTO outages
                       (user_id, neighborhood, location, description, start_time, estimated_restore, status, latitude, longitude, outage_type, schedule_id, affects_critical)
                       VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s)""",
                    (session["user_id"], neighborhood, location, description, start_time, est_restore, lat, lng, outage_type, schedule_id, is_critical),
                )
                new_outage_id = cur.lastrowid

            # Update impacted facilities status to BACKUP_GENERATOR or CRITICAL_BLACKOUT
            for fac in impacted_facs:
                new_status = "BACKUP_GENERATOR" if fac.get("has_backup_generator") else "CRITICAL_BLACKOUT"
                update_facility_power_status(fac["id"], new_status)
                create_critical_infrastructure_alert(fac, new_outage_id, location=location)

            # Standard neighborhood notification
            create_neighborhood_notification(
                neighborhood=neighborhood,
                outage_id=new_outage_id,
                title=get_text("notif_new_outage_title", lang=lang),
                message=get_text("notif_new_outage_msg", lang=lang, neighborhood=neighborhood, location=location),
                notif_type="OUTAGE_NEW",
                exclude_user_id=session["user_id"]
            )

            # Informative message with scheduled maintenance or critical facility notes
            if is_critical:
                fac_names = ", ".join([f["name"] for f in impacted_facs[:2]])
                flash(f"🚨 {get_text('msg_report_success', lang=lang)} — Zone critique détectée : {fac_names} basculé(s) sur alimentation de secours.", "warning")
            elif matched_sched:
                flash(f"⚡ {get_text('msg_report_success', lang=lang)} (Note : {get_text('badge_scheduled', lang=lang)} - {matched_sched['title']})", "info")
            else:
                flash(get_text("msg_report_success", lang=lang), "success")
            return redirect(url_for("outages.outages"))
        except Error:
            flash(get_text("msg_report_error", lang=lang), "danger")

    return render_template("report.html", form_data=form_data, existing_duplicate=None)


@outages_bp.route("/outages")
def outages():
    """List public outages with search, status, planned/unplanned, and critical facility filtering."""
    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    type_filter = request.args.get("type", "").strip()
    critical_filter = request.args.get("critical", "").strip()

    try:
        sql = """
            SELECT o.*,
                   s.title AS schedule_title,
                   (SELECT COUNT(*) FROM confirmations c
                    WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
            FROM outages o
            LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
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

        if type_filter and type_filter in ("SCHEDULED", "UNPLANNED"):
            sql += " AND o.outage_type = %s"
            params.append(type_filter)

        if critical_filter == "1":
            sql += " AND o.affects_critical = TRUE"

        sql += " ORDER BY o.created_at DESC LIMIT 60"

        with get_db_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return render_template(
            "outages.html",
            outages=rows,
            search=search,
            status_filter=status_filter,
            type_filter=type_filter,
            critical_filter=critical_filter
        )
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template("outages.html", outages=[], search=search, status_filter=status_filter, type_filter=type_filter, critical_filter=critical_filter)


@outages_bp.route("/outage/<int:outage_id>", endpoint="outage_details")
@outages_bp.route("/outage/<int:outage_id>", endpoint="outage_detail")
def outage_details(outage_id):
    """Detailed view for a single outage including confirmations, GPS pinpoint, Eneo schedule correlation, and critical facilities."""
    lang = get_current_lang()
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.*, u.full_name,
                       s.title AS schedule_title, s.description AS schedule_desc, s.start_time AS schedule_start, s.end_time AS schedule_end,
                       (SELECT COUNT(*) FROM confirmations c
                        WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_off,
                       (SELECT COUNT(*) FROM confirmations c
                        WHERE c.outage_id = o.id AND c.confirmation = 'RESTORED') AS conf_restored
                FROM outages o
                JOIN users u ON o.user_id = u.id
                LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
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
            return redirect(url_for("outages.outages"))

        # Look up critical facilities in this neighborhood or nearby
        nearby_facs = []
        if outage.get("latitude") and outage.get("longitude"):
            impacted, _ = check_outage_critical_impact(outage["neighborhood"], outage["latitude"], outage["longitude"])
            nearby_facs = impacted
        else:
            nearby_facs = get_facilities_by_neighborhood(outage["neighborhood"])

        return render_template(
            "outage_details.html",
            outage=outage,
            user_confirmed=user_confirmed,
            nearby_facilities=nearby_facs,
        )
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
        return redirect(url_for("outages.outages"))


@outages_bp.route("/outage/<int:outage_id>/confirm", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def confirm_outage(outage_id):
    """Citizen confirmation with community auto-verification (3+ confirmations)."""
    lang = get_current_lang()
    confirmation = request.form.get("confirmation", "").strip()
    if confirmation not in ("STILL_OFF", "RESTORED"):
        flash(get_text("msg_invalid_credentials", lang=lang), "danger")
        return redirect(url_for("outages.outage_details", outage_id=outage_id))

    try:
        auto_verified = False
        auto_restored = False
        total_confs = 0

        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT status, neighborhood, location FROM outages WHERE id = %s", (outage_id,))
            outage = cur.fetchone()
            if not outage or outage["status"] == "REJECTED":
                flash(get_text("msg_outage_not_found", lang=lang), "danger")
                return redirect(url_for("outages.outages"))

            cur.execute(
                "SELECT id FROM confirmations WHERE outage_id = %s AND user_id = %s",
                (outage_id, session["user_id"]),
            )
            if cur.fetchone():
                flash(get_text("msg_already_confirmed", lang=lang), "warning")
                return redirect(url_for("outages.outage_details", outage_id=outage_id))

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

        # Send notifications if promoted
        if auto_verified:
            create_neighborhood_notification(
                neighborhood=outage["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_verified_title", lang=lang),
                message=get_text("notif_verified_msg", lang=lang, neighborhood=outage["neighborhood"], location=outage["location"]),
                notif_type="OUTAGE_VERIFIED"
            )
            flash(get_text("msg_auto_verified_community", lang=lang, count=total_confs), "success")
        elif auto_restored:
            sync_facilities_with_active_outages()
            create_neighborhood_notification(
                neighborhood=outage["neighborhood"],
                outage_id=outage_id,
                title=get_text("notif_restored_title", lang=lang),
                message=get_text("notif_restored_msg", lang=lang, neighborhood=outage["neighborhood"], location=outage["location"]),
                notif_type="OUTAGE_RESTORED"
            )
            flash(get_text("msg_auto_restored_community", lang=lang, count=total_confs), "success")
        else:
            if confirmation == "STILL_OFF":
                flash(get_text("msg_confirm_saved_off", lang=lang), "info")
            else:
                flash(get_text("msg_confirm_saved_restored", lang=lang), "info")

        return redirect(url_for("outages.outage_details", outage_id=outage_id))
    except Error:
        flash(get_text("msg_db_error", lang=lang), "danger")
        return redirect(url_for("outages.outage_details", outage_id=outage_id))


@outages_bp.route("/my-reports")
@login_required
def my_reports():
    """User-specific submission history."""
    user_id = session["user_id"]
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.*,
                       s.title AS schedule_title,
                       (SELECT COUNT(*) FROM confirmations c
                        WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
                WHERE o.user_id = %s
                ORDER BY o.created_at DESC
            """, (user_id,))
            reports = cur.fetchall()

        return render_template("my_reports.html", reports=reports)
    except Error:
        flash(get_text("msg_db_error", lang=get_current_lang()), "danger")
        return render_template("my_reports.html", reports=[])


@outages_bp.route("/schedules")
def schedules():
    """Public calendar of official Eneo scheduled load-shedding and maintenance rotas."""
    neighborhood = request.args.get("neighborhood", "").strip()
    status_filter = request.args.get("status", "").strip()
    schedules_list = get_all_schedules(neighborhood=neighborhood or None, status_filter=status_filter or None)
    return render_template(
        "schedules.html",
        schedules=schedules_list,
        selected_neighborhood=neighborhood,
        selected_status=status_filter
    )


@outages_bp.route("/infrastructure")
def infrastructure():
    """
    Public Status Board for Critical Infrastructure in Douala:
    Hospitals, ERs, Dialysis centers, Blood banks, and Camwater drinking water plants.
    """
    facility_type = request.args.get("type", "").strip()
    status_filter = request.args.get("status", "").strip()

    facilities_list = get_all_facilities(
        facility_type=facility_type or None,
        power_status=status_filter or None
    )
    kpis = get_critical_facilities_kpis()

    return render_template(
        "infrastructure.html",
        facilities=facilities_list,
        kpis=kpis,
        selected_type=facility_type,
        selected_status=status_filter
    )


@outages_bp.route("/analytics")
def analytics():
    """
    Load-shedding & Outage analytics view:
    - Overall metrics and resolution rate
    - Planned vs Unplanned load-shedding breakdown
    - Critical infrastructure impact indicators
    - Leaflet Heatmap of outage concentrations
    - Neighborhood severity impact ranking
    """
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

            # 4. Planned vs Unplanned breakdown
            cur.execute("SELECT COUNT(*) AS c FROM outages WHERE outage_type = 'SCHEDULED'")
            planned_outages = cur.fetchone()["c"]
            unplanned_outages = total_outages - planned_outages

            planned_percent = round((planned_outages / total_outages * 100), 1) if total_outages > 0 else 0.0
            unplanned_percent = round((unplanned_outages / total_outages * 100), 1) if total_outages > 0 else 0.0

            # Resolution rate
            resolution_rate = round((restored_outages / total_outages * 100), 1) if total_outages > 0 else 100.0

            # 5. Average duration across Douala (in hours)
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

            # 6. Neighborhood Severity Ranking with Planned & Critical counts
            cur.execute("""
                SELECT 
                    neighborhood,
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('PENDING', 'VERIFIED') THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN status = 'RESTORED' THEN 1 ELSE 0 END) AS restored,
                    SUM(CASE WHEN outage_type = 'SCHEDULED' THEN 1 ELSE 0 END) AS planned,
                    SUM(CASE WHEN affects_critical = TRUE THEN 1 ELSE 0 END) AS critical_count,
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
            pld = int(r["planned"] or 0)
            crit = int(r.get("critical_count") or 0)
            avg_m = r.get("avg_duration_mins")
            avg_h = round(float(avg_m) / 60.0, 1) if avg_m else avg_duration_hours
            percent = int((tot / max_total) * 100) if max_total > 0 else 0

            # Severity tier
            if act >= 2 or tot >= 6 or crit >= 1:
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
                "planned": pld,
                "critical_count": crit,
                "avg_duration": avg_h,
                "percent": percent,
                "severity_key": sev_key,
                "severity_color": sev_color
            })

        facilities_kpis = get_critical_facilities_kpis()

        return render_template(
            "analytics.html",
            total_outages=total_outages,
            active_outages=active_outages,
            restored_outages=restored_outages,
            planned_outages=planned_outages,
            unplanned_outages=unplanned_outages,
            planned_percent=planned_percent,
            unplanned_percent=unplanned_percent,
            resolution_rate=resolution_rate,
            avg_duration_hours=avg_duration_hours,
            most_affected=most_affected,
            neighborhood_stats=neighborhood_stats,
            facilities_kpis=facilities_kpis
        )
    except Exception:
        flash(get_text("msg_db_error", lang=lang), "danger")
        return render_template(
            "analytics.html",
            total_outages=0,
            active_outages=0,
            restored_outages=0,
            planned_outages=0,
            unplanned_outages=0,
            planned_percent=0,
            unplanned_percent=0,
            resolution_rate=0,
            avg_duration_hours=0,
            most_affected="—",
            neighborhood_stats=[],
            facilities_kpis={"total": 0, "on_grid": 0, "backup_generator": 0, "critical_blackout": 0}
        )


@outages_bp.route("/sms-guide")
def sms_guide():
    """Citizen guide for reporting power outages and querying status via SMS & WhatsApp."""
    return render_template("sms_guide.html")

