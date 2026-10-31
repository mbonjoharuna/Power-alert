"""
API Blueprint for Douala Power Alert.
Provides REST JSON endpoints for active neighborhood lookups, map markers,
heatmap severity weights, and user notifications.
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
    "pk 12": [4.0600, 9.8200],
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
                "status": r["status"],
                "start_time": st,
                "conf_count": r["conf_count"]
            })
        return jsonify({"found": True, "outages": outages_list})
    except Exception:
        return jsonify({"found": False, "outages": []})


@api_bp.route("/api/analytics/heatmap")
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
    """Return outages with exact coordinates or fallback center points for simple map markers."""
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
                "lat": lat,
                "lng": lng,
            })
        return jsonify(markers)
    except Error:
        return jsonify([])


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
