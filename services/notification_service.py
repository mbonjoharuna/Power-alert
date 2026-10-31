"""
Notification Service for Douala Power Alert.
Handles in-app notification records and triggers for registered neighborhood alerts.
"""

from database import get_db_cursor
from datetime import datetime


def create_neighborhood_notification(neighborhood, outage_id, title, message, notif_type="INFO", exclude_user_id=None):
    """
    Finds all users living in the specified neighborhood and creates a notification record for each.
    Optionally excludes the user who triggered the action.
    """
    if not neighborhood:
        return 0

    try:
        clean_neighborhood = neighborhood.strip().lower()
        with get_db_cursor(commit=True) as cur:
            sql = "SELECT id FROM users WHERE LOWER(TRIM(neighborhood)) = %s"
            params = [clean_neighborhood]
            if exclude_user_id:
                sql += " AND id != %s"
                params.append(exclude_user_id)

            cur.execute(sql, tuple(params))
            recipients = cur.fetchall()

            if not recipients:
                return 0

            insert_sql = """
                INSERT INTO notifications (user_id, outage_id, title, message, type)
                VALUES (%s, %s, %s, %s, %s)
            """
            data = [
                (r["id"], outage_id, title, message, notif_type)
                for r in recipients
            ]
            cur.executemany(insert_sql, data)
            return len(data)
    except Exception as e:
        print(f"Error creating neighborhood notifications: {e}")
        return 0


def get_user_notifications(user_id, limit=20):
    """
    Retrieves the most recent notifications for a given user,
    including outage reference and human-readable time.
    """
    if not user_id:
        return []

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT 
                    n.id, n.user_id, n.outage_id, n.title, n.message, n.type,
                    n.is_read, n.created_at,
                    o.neighborhood, o.location, o.status as outage_status
                FROM notifications n
                LEFT JOIN outages o ON n.outage_id = o.id
                WHERE n.user_id = %s
                ORDER BY n.created_at DESC
                LIMIT %s
            """, (user_id, limit))
            rows = cur.fetchall()

            now = datetime.now()
            results = []
            for r in rows:
                c_at = r.get("created_at")
                time_ago = ""
                if isinstance(c_at, datetime):
                    diff = now - c_at
                    secs = int(diff.total_seconds())
                    if secs < 60:
                        time_ago = "À l'instant"
                    elif secs < 3600:
                        time_ago = f"Il y a {secs // 60} min"
                    elif secs < 86400:
                        time_ago = f"Il y a {secs // 3600} h"
                    else:
                        time_ago = c_at.strftime("%d/%m %H:%M")

                results.append({
                    "id": r["id"],
                    "outage_id": r["outage_id"],
                    "title": r["title"],
                    "message": r["message"],
                    "type": r["type"],
                    "is_read": bool(r["is_read"]),
                    "created_at": time_ago,
                    "created_at_raw": c_at.isoformat() if isinstance(c_at, datetime) else str(c_at),
                    "neighborhood": r.get("neighborhood") or "",
                    "location": r.get("location") or "",
                    "outage_status": r.get("outage_status") or "",
                })
            return results
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return []


def get_unread_count(user_id):
    """Returns the total number of unread notifications for a user."""
    if not user_id:
        return 0

    try:
        with get_db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = FALSE",
                (user_id,)
            )
            row = cur.fetchone()
            return int(row["count"]) if row else 0
    except Exception as e:
        print(f"Error fetching unread count: {e}")
        return 0


def mark_as_read(user_id, notification_id=None):
    """
    Marks a specific notification or all notifications as read for a given user.
    """
    if not user_id:
        return False

    try:
        with get_db_cursor(commit=True) as cur:
            if notification_id:
                cur.execute(
                    "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND id = %s",
                    (user_id, notification_id)
                )
            else:
                cur.execute(
                    "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
                    (user_id,)
                )
            return True
    except Exception as e:
        print(f"Error marking notifications read: {e}")
        return False
