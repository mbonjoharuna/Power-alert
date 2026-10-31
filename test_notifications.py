"""
Automated Verification Suite for In-App & Web Push Notification Center.
Tests neighborhood-scoped alerts for reported, verified, and restored outages,
along with unread counters and read-marking APIs.
"""

import re
import uuid
import unittest
from datetime import datetime
from werkzeug.security import generate_password_hash

from app import app, limiter
from database import get_db_cursor
from services.notification_service import (
    create_neighborhood_notification,
    get_user_notifications,
    get_unread_count,
    mark_as_read
)


class TestNotificationCenter(unittest.TestCase):
    def setUp(self):
        limiter.enabled = False
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        self.uid = uuid.uuid4().hex[:8]
        self.neighborhood_target = f"Deido_{self.uid}"
        self.neighborhood_other = f"Akwa_{self.uid}"

        with get_db_cursor(commit=True) as cur:
            pwd = generate_password_hash("password123")
            # User A in Target Zone
            cur.execute("""
                INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                VALUES (%s, %s, %s, %s, %s)
            """, (f"User A {self.uid}", f"user_a_{self.uid}@test.cm", f"67{int(uuid.uuid4().int % 10000000):07d}", pwd, self.neighborhood_target))
            self.user_a_id = cur.lastrowid

            # User B in Target Zone (Same neighborhood)
            cur.execute("""
                INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                VALUES (%s, %s, %s, %s, %s)
            """, (f"User B {self.uid}", f"user_b_{self.uid}@test.cm", f"68{int(uuid.uuid4().int % 10000000):07d}", pwd, self.neighborhood_target))
            self.user_b_id = cur.lastrowid

            # User C in Other Zone (Different neighborhood)
            cur.execute("""
                INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                VALUES (%s, %s, %s, %s, %s)
            """, (f"User C {self.uid}", f"user_c_{self.uid}@test.cm", f"69{int(uuid.uuid4().int % 10000000):07d}", pwd, self.neighborhood_other))
            self.user_c_id = cur.lastrowid

    def tearDown(self):
        limiter.enabled = True
        self.app_context.pop()

    def _get_csrf_token(self):
        page = self.client.get("/login")
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.data.decode("utf-8"))
        if match:
            return match.group(1)
        # Fallback to meta tag
        match_meta = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.data.decode("utf-8"))
        return match_meta.group(1) if match_meta else ""

    def test_notification_bell_ui_rendered_when_logged_in(self):
        """Notification bell should appear for logged-in user, but not for guest."""
        # Guest request
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'id="notifBellContainer"', res.data)

        # Logged-in request
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_b_id
            sess["user_name"] = "User B"
            sess["user_neighborhood"] = self.neighborhood_target
            sess["lang"] = "fr"

        res_user = self.client.get('/')
        self.assertEqual(res_user.status_code, 200)
        self.assertIn(b'id="notifBellContainer"', res_user.data)
        self.assertIn(b'id="notifBellBtn"', res_user.data)
        self.assertIn(b'id="notifBadge"', res_user.data)

    def test_neighborhood_outage_reporting_alerts_resident(self):
        """When User A reports an outage, User B receives an alert, but not User C."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["user_name"] = "User A"
            sess["user_neighborhood"] = self.neighborhood_target
            sess["lang"] = "fr"

        rep_page = self.client.get("/report")
        self.assertEqual(rep_page.status_code, 200)
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', rep_page.data.decode("utf-8"))
        self.assertTrue(match, "CSRF token not found in /report")
        csrf_token = match.group(1)

        # User A submits report in Deido target zone
        report_data = {
            "csrf_token": csrf_token,
            "neighborhood": self.neighborhood_target,
            "location": "Rue de la Joie",
            "description": "Panne de transformateur",
            "start_time": datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "latitude": "4.060123",
            "longitude": "9.720456",
            "is_distinct": "1"
        }
        res = self.client.post('/report', data=report_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Check User B (same neighborhood) received notification
        notifs_b = get_user_notifications(self.user_b_id)
        self.assertEqual(len(notifs_b), 1)
        self.assertIn("Coupure signalée", notifs_b[0]["title"])
        self.assertIn(self.neighborhood_target, notifs_b[0]["message"])
        self.assertEqual(notifs_b[0]["is_read"], False)

        # Check User C (different neighborhood) received NO notification
        notifs_c = get_user_notifications(self.user_c_id)
        self.assertEqual(len(notifs_c), 0)

        # Check User A (the reporter) excluded from redundant notification
        notifs_a = get_user_notifications(self.user_a_id)
        self.assertEqual(len(notifs_a), 0)

        # Check User B (same neighborhood) received notification
        notifs_b = get_user_notifications(self.user_b_id)
        self.assertEqual(len(notifs_b), 1)
        self.assertIn("Coupure signalée", notifs_b[0]["title"])
        self.assertIn(self.neighborhood_target, notifs_b[0]["message"])
        self.assertEqual(notifs_b[0]["is_read"], False)

        # Check User C (different neighborhood) received NO notification
        notifs_c = get_user_notifications(self.user_c_id)
        self.assertEqual(len(notifs_c), 0)

        # Check User A (the reporter) excluded from redundant notification
        notifs_a = get_user_notifications(self.user_a_id)
        self.assertEqual(len(notifs_a), 0)

    def test_notifications_api_and_mark_read(self):
        """Verify /api/notifications returns unread counts and /api/notifications/mark-read updates status."""
        outage_id = None
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO outages (user_id, neighborhood, location, description, start_time, status)
                VALUES (%s, %s, %s, %s, NOW(), 'PENDING')
            """, (self.user_a_id, self.neighborhood_target, "Carrefour 2", "Test Outage"))
            outage_id = cur.lastrowid

        # Directly send a test notification to User B
        create_neighborhood_notification(
            neighborhood=self.neighborhood_target,
            outage_id=outage_id,
            title="⚠️ Coupure confirmée",
            message="La coupure a été confirmée.",
            notif_type="OUTAGE_VERIFIED"
        )

        # Test API as User B
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_b_id

        res = self.client.get('/api/notifications')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.is_json)
        data = res.get_json()
        self.assertGreaterEqual(data["unread_count"], 1)
        self.assertGreaterEqual(len(data["notifications"]), 1)
        self.assertIn("Coupure confirmée", data["notifications"][0]["title"])

        # Mark all as read via API
        mark_res = self.client.post('/api/notifications/mark-read', json={})
        self.assertEqual(mark_res.status_code, 200)
        mark_data = mark_res.get_json()
        self.assertEqual(mark_data["unread_count"], 0)

        # Verify unread count is now 0
        self.assertEqual(get_unread_count(self.user_b_id), 0)

    def test_admin_approve_and_restore_triggers_notifications(self):
        """Admin approving and restoring an outage triggers verified and restored notifications."""
        outage_id = None
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO outages (user_id, neighborhood, location, description, start_time, status)
                VALUES (%s, %s, %s, %s, NOW(), 'PENDING')
            """, (self.user_a_id, self.neighborhood_target, "Poste Central", "Coupure secteur"))
            outage_id = cur.lastrowid

        with self.client.session_transaction() as sess:
            sess["admin_id"] = 1
            sess["admin_username"] = "admin"
            sess["lang"] = "fr"

        admin_page = self.client.get("/admin/dashboard")
        self.assertEqual(admin_page.status_code, 200)
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', admin_page.data.decode("utf-8"))
        self.assertTrue(match, "CSRF token not found in /admin/dashboard")
        csrf_token = match.group(1)

        # Admin approves
        self.client.post(f'/admin/approve/{outage_id}', data={"csrf_token": csrf_token}, follow_redirects=True)

        notifs_b = get_user_notifications(self.user_b_id)
        verified_notifs = [n for n in notifs_b if n["type"] == "OUTAGE_VERIFIED"]
        self.assertGreaterEqual(len(verified_notifs), 1)

        # Admin restores
        self.client.post(f'/admin/restore/{outage_id}', data={"csrf_token": csrf_token}, follow_redirects=True)

        notifs_b = get_user_notifications(self.user_b_id)
        restored_notifs = [n for n in notifs_b if n["type"] == "OUTAGE_RESTORED"]
        self.assertGreaterEqual(len(restored_notifs), 1)
        self.assertIn("Courant rétabli", restored_notifs[0]["title"])


if __name__ == '__main__':
    unittest.main()
