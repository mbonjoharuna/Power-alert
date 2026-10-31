"""
API Blueprint for Douala Power Alert.
Provides REST JSON endpoints for active neighborhood lookups, map markers,
heatmap severity weights, user notifications, and critical infrastructure telemetry.
"""

from flask import Blueprint, request, jsonify, session
from mysql.connector import Error

from extensions import csrf
from database import get_db_cursor
from services.notification_service import (
    get_user_notifications,
    get_unread_count,
    mark_as_read
)
from services.facility_service import (
    get_all_facilities,
    get_critical_facilities_kpis
)
from services.gateway_service import handle_inbound_message

api_bp = Blueprint("api", __name__)

DOUALA_COORDS = {
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
    "pk 12": [4.060, 9.8200],
    "pk 14": [4.0550, 9.8400],
    "pk 17": [4.0500, 9.8700],
}


@api_bp.route("/api/outages/active-by-neighborhood")
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
                "start_time": st,
                "status": r["status"],
                "conf_count": r.get("conf_count", 0),
            })

        return jsonify({"found": True, "outages": outages_list})
    except Error:
        return jsonify({"found": False, "outages": []})


@api_bp.route("/api/analytics/heatmap")
def api_analytics_heatmap():
    """
    Returns array of [lat, lng, intensity] data points for Leaflet.heat overlay.
    Intensity is calculated from status and confirmations.
    """
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.id, o.neighborhood, o.location, o.status, o.latitude, o.longitude,
                       (SELECT COUNT(*) FROM confirmations c WHERE c.outage_id = o.id AND c.confirmation = 'STILL_OFF') AS conf_count
                FROM outages o
                WHERE o.status IN ('PENDING', 'VERIFIED', 'RESTORED')
                ORDER BY o.created_at DESC
                LIMIT 200
            """)
            rows = cur.fetchall()

        heat_points = []
        for r in rows:
            key = r["neighborhood"].lower().strip()
            if r.get("latitude") is not None and r.get("longitude") is not None:
                lat = float(r["latitude"])
                lng = float(r["longitude"])
            else:
                latlng = DOUALA_COORDS.get(key, [4.0511, 9.7679])
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


@api_bp.route("/api/outages/map")
def api_map_outages():
    """Return outages with exact coordinates or fallback center points, including planned/unplanned status and critical impact."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT o.id, o.neighborhood, o.location, o.status, o.latitude, o.longitude,
                       o.outage_type, o.affects_critical, s.title AS schedule_title
                FROM outages o
                LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
                WHERE o.status IN ('PENDING', 'VERIFIED', 'RESTORED')
                ORDER BY o.created_at DESC
                LIMIT 100
            """)
            rows = cur.fetchall()

        markers = []
        for r in rows:
            key = r["neighborhood"].lower().strip()
            if r.get("latitude") is not None and r.get("longitude") is not None:
                lat = float(r["latitude"])
                lng = float(r["longitude"])
            else:
                latlng = DOUALA_COORDS.get(key, [4.0511, 9.7679])
                lat = latlng[0]
                lng = latlng[1]

            markers.append({
                "id": r["id"],
                "neighborhood": r["neighborhood"],
                "location": r["location"],
                "status": r["status"],
                "outage_type": r.get("outage_type") or "UNPLANNED",
                "affects_critical": bool(r.get("affects_critical")),
                "schedule_title": r.get("schedule_title") or "",
                "lat": lat,
                "lng": lng,
            })
        return jsonify(markers)
    except Error:
        return jsonify([])


@api_bp.route("/api/schedules/active")
def api_active_schedules():
    """Return active or upcoming scheduled Eneo maintenance windows."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, neighborhood, title, description, start_time, end_time, status
                FROM scheduled_outages
                WHERE status IN ('SCHEDULED', 'IN_PROGRESS')
                ORDER BY start_time ASC
                LIMIT 20
            """)
            rows = cur.fetchall()

        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "neighborhood": r["neighborhood"],
                "title": r["title"],
                "description": r["description"] or "",
                "start_time": str(r["start_time"]),
                "end_time": str(r["end_time"]),
                "status": r["status"]
            })
        return jsonify(result)
    except Exception:
        return jsonify([])


@api_bp.route("/api/infrastructure")
def api_infrastructure():
    """Return critical facilities telemetry (hospitals, water plants, dialysis centers)."""
    facility_type = request.args.get("type")
    status = request.args.get("status")
    neighborhood = request.args.get("neighborhood")

    facilities = get_all_facilities(facility_type=facility_type, power_status=status, neighborhood=neighborhood)
    output = []
    for f in facilities:
        output.append({
            "id": f["id"],
            "name": f["name"],
            "facility_type": f["facility_type"],
            "neighborhood": f["neighborhood"],
            "address": f.get("address") or "",
            "latitude": float(f["latitude"]) if f.get("latitude") is not None else None,
            "longitude": float(f["longitude"]) if f.get("longitude") is not None else None,
            "has_backup_generator": bool(f.get("has_backup_generator")),
            "generator_capacity_kva": f.get("generator_capacity_kva"),
            "fuel_autonomy_hours": float(f.get("fuel_autonomy_hours") or 0),
            "current_power_status": f.get("current_power_status", "ON_GRID"),
            "contact_name": f.get("contact_name") or "",
            "contact_phone": f.get("contact_phone") or "",
            "notes": f.get("notes") or "",
            "last_status_change": str(f.get("last_status_change") or "")
        })
    return jsonify(output)


@api_bp.route("/api/infrastructure/summary")
def api_infrastructure_summary():
    """Return summary KPI statistics for critical infrastructure."""
    kpis = get_critical_facilities_kpis()
    return jsonify(kpis)


@api_bp.route("/api/notifications")
def api_get_notifications():
    """Retrieve notifications and unread count for current logged-in user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"unread_count": 0, "notifications": []})

    notifications = get_user_notifications(user_id, limit=20)
    unread_count = get_unread_count(user_id)
    return jsonify({
        "unread_count": unread_count,
        "notifications": notifications
    })


@api_bp.route("/api/notifications/mark-read", methods=["POST"])
@csrf.exempt
def api_mark_notifications_read():
    """Mark one or all notifications as read for current user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    notif_id = request.form.get("notification_id") or (
        request.json.get("notification_id") if request.is_json else None
    )
    success = mark_as_read(user_id, notif_id)
    unread_count = get_unread_count(user_id)
    return jsonify({"success": success, "unread_count": unread_count})


# -------------------------------------------------------------
# Option 2: SMS & WhatsApp Inbound Gateway Webhooks
# -------------------------------------------------------------

def _format_twiml_response(reply_text: str):
    """Generate Twilio-compatible XML TwiML message response."""
    from xml.sax.saxutils import escape
    safe_text = escape(reply_text)
    xml_content = f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n    <Message>{safe_text}</Message>\n</Response>'
    return xml_content, 200, {"Content-Type": "application/xml; charset=utf-8"}


def _handle_gateway_request(channel: str):
    """Common parser for SMS and WhatsApp webhook payloads."""
    # Check JSON body
    if request.is_json:
        data = request.get_json(silent=True) or {}
        sender = data.get("phone") or data.get("sender") or data.get("From") or ""
        body = data.get("message") or data.get("text") or data.get("body") or data.get("Body") or ""
        is_twilio = False
    else:
        # Check Form/Query (Twilio standard: From, Body)
        sender = (
            request.form.get("From")
            or request.form.get("from")
            or request.form.get("phone")
            or request.form.get("sender")
            or request.args.get("phone")
            or ""
        )
        body = (
            request.form.get("Body")
            or request.form.get("body")
            or request.form.get("message")
            or request.form.get("text")
            or request.args.get("message")
            or ""
        )
        is_twilio = bool(request.form.get("From") or request.form.get("Body"))

    # Execute incident processing
    result = handle_inbound_message(sender_phone=sender, raw_text=body, channel=channel)

    # Return Twilio TwiML if request originated from Twilio or format requested as xml
    wants_xml = (
        is_twilio
        or request.args.get("format") == "xml"
        or "application/xml" in request.headers.get("Accept", "")
    )
    if wants_xml:
        return _format_twiml_response(result["response"])

    return jsonify(result), (200 if result["status"] == "SUCCESS" else 400)


@api_bp.route("/api/gateway/sms", methods=["POST"])
@csrf.exempt
def api_gateway_sms():
    """Inbound webhook for SMS messages (Twilio, Gammu, Africa's Talking, GSM modem)."""
    return _handle_gateway_request(channel="SMS")


@api_bp.route("/api/gateway/whatsapp", methods=["POST"])
@csrf.exempt
def api_gateway_whatsapp():
    """Inbound webhook for WhatsApp Business API / Twilio WhatsApp messages."""
    return _handle_gateway_request(channel="WHATSAPP")

