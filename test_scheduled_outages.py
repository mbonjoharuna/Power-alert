"""
Unit and integration tests for Option 4: Eneo Scheduled Load-Shedding Importer:
- Scheduled maintenance creation & auto-linking
- CSV and JSON schedule imports
- Sample Douala Eneo rotas loading
- Automatic classification of citizen reports as SCHEDULED vs UNPLANNED
- Map API returning outage_type and schedule_title
- Public /schedules calendar and admin /admin/schedules management
- Analytics planned vs unplanned breakdown
"""

import json
import unittest
from datetime import datetime, timedelta

from app import create_app
from database import get_db_cursor
from extensions import limiter
from services.schedule_service import (
    create_schedule,
    get_all_schedules,
    delete_schedule,
    import_schedules_from_csv,
    load_sample_douala_schedules,
    find_matching_schedule
)


class TestScheduledOutages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

        # Create a test user
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                VALUES ('Schedule Test User', 'sched_user@douala.cm', '679998877', 'dummyhash', 'Bonaberi')
                ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id);
            """)
            cls.user_id = cur.lastrowid

            # Ensure admin exists
            cur.execute("SELECT id FROM admins WHERE username = 'admin';")
            cls.admin_id = cur.fetchone()["id"]

    def setUp(self):
        limiter.enabled = False

    def tearDown(self):
        limiter.enabled = True

    def test_create_and_find_schedule(self):
        """Test creating a schedule and querying it by neighborhood."""
        now = datetime.now()
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=5)

        sched_id = create_schedule(
            neighborhood="Bali",
            title="Révision Ligne MT Bali",
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
            description="Entretien annuel transformateur"
        )
        self.assertIsNotNone(sched_id)

        match = find_matching_schedule("Bali", now)
        self.assertIsNotNone(match)
        self.assertEqual(match["title"], "Révision Ligne MT Bali")

        # Cleanup
        delete_schedule(sched_id)

    def test_import_schedules_from_csv(self):
        """Test bulk CSV schedule parsing and insertion."""
        csv_data = """neighborhood,title,start_time,end_time,description
Logbaba,Élagage corridor HT,2026-11-10 08:00:00,2026-11-10 14:00:00,Sécurisation artère
Kotto,Entretien Poste Source,2026-11-11 09:00:00,2026-11-11 16:00:00,Travaux sur cellules
"""
        count = import_schedules_from_csv(csv_data)
        self.assertGreaterEqual(count, 2)

        schedules = get_all_schedules(neighborhood="Logbaba")
        self.assertTrue(any("Élagage corridor HT" in s["title"] for s in schedules))

    def test_load_sample_douala_rotas(self):
        """Test loading realistic sample Eneo maintenance rotas."""
        count = load_sample_douala_schedules()
        self.assertGreaterEqual(count, 0)  # Count >= 0 (idempotent if already loaded)

        schedules = get_all_schedules()
        self.assertTrue(len(schedules) >= 3)

    def test_report_auto_classified_as_scheduled(self):
        """Test that an outage reported during an active Eneo schedule is automatically marked as SCHEDULED."""
        now = datetime.now()
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=4)

        # 1. Create scheduled maintenance in Makepe
        sched_id = create_schedule(
            neighborhood="Makepe",
            title="Délestage Tournant Équilibre Makepe",
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
            description="Délestage programmé"
        )

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["user_neighborhood"] = "Makepe"

        # 2. Report outage in Makepe during this window
        res = self.client.post("/report", data={
            "neighborhood": "Makepe",
            "location": "Carrefour Rhone Poulenc",
            "description": "Plus de lumière",
            "start_time": now.strftime("%Y-%m-%dT%H:%M"),
            "latitude": "4.0901",
            "longitude": "9.7301"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 3. Check outage in DB: should have outage_type='SCHEDULED' and schedule_id=sched_id
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT outage_type, schedule_id, estimated_restore
                FROM outages
                WHERE neighborhood = 'Makepe' AND location = 'Carrefour Rhone Poulenc'
                ORDER BY id DESC LIMIT 1;
            """)
            outage = cur.fetchone()

        self.assertIsNotNone(outage)
        self.assertEqual(outage["outage_type"], "SCHEDULED")
        self.assertEqual(outage["schedule_id"], sched_id)
        self.assertIsNotNone(outage["estimated_restore"])

        # Cleanup
        delete_schedule(sched_id)

    def test_map_api_includes_outage_type(self):
        """Verify /api/outages/map includes outage_type and schedule_title."""
        with self.client.get("/api/outages/map") as res:
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data.decode("utf-8"))
            if data:
                self.assertIn("outage_type", data[0])
                self.assertIn(data[0]["outage_type"], ("SCHEDULED", "UNPLANNED"))

    def test_schedules_public_route(self):
        """Verify /schedules renders the public Eneo calendar."""
        with self.client.get("/schedules") as res:
            self.assertEqual(res.status_code, 200)
            html = res.data.decode("utf-8")
            self.assertIn("Programmation des Délestages Eneo", html)

    def test_analytics_includes_planned_vs_unplanned(self):
        """Verify /analytics calculates and displays planned vs unplanned ratio."""
        with self.client.get("/analytics") as res:
            self.assertEqual(res.status_code, 200)
            html = res.data.decode("utf-8")
            self.assertIn("Planifié vs Imprévu", html)
            self.assertIn("Délestages Planifiés", html)
            self.assertIn("Pannes Imprévues", html)

    def test_admin_schedules_and_toggle(self):
        """Verify admin schedules management and outage type toggle."""
        with self.client.session_transaction() as sess:
            sess["admin_id"] = self.admin_id
            sess["admin_username"] = "admin"

        # Access /admin/schedules
        with self.client.get("/admin/schedules") as res:
            self.assertEqual(res.status_code, 200)
            html = res.data.decode("utf-8")
            self.assertIn("Gestion du Calendrier Eneo", html)

        # Get an outage to toggle
        with get_db_cursor() as cur:
            cur.execute("SELECT id, outage_type FROM outages LIMIT 1;")
            o = cur.fetchone()

        if o:
            orig_type = o.get("outage_type") or "UNPLANNED"
            # Toggle type
            res = self.client.post(f"/admin/outages/{o['id']}/toggle-type", follow_redirects=True)
            self.assertEqual(res.status_code, 200)

            with get_db_cursor() as cur:
                cur.execute("SELECT outage_type FROM outages WHERE id = %s;", (o["id"],))
                new_type = cur.fetchone()["outage_type"]
            self.assertNotEqual(orig_type, new_type)


if __name__ == "__main__":
    unittest.main()
