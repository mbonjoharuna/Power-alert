"""
Comprehensive Automated Unit Tests for Option 3:
Critical Infrastructure Alerting & Priority Power Monitoring.
"""

import unittest
from datetime import datetime
from app import create_app
from database import get_db_cursor, init_db
from werkzeug.security import generate_password_hash
from services.facility_service import (
    seed_douala_critical_facilities,
    get_all_facilities,
    get_facility_by_id,
    create_facility,
    update_facility,
    delete_facility,
    update_facility_power_status,
    get_facilities_by_neighborhood,
    calculate_haversine_distance,
    find_nearby_critical_facilities,
    check_outage_critical_impact,
    sync_facilities_with_active_outages,
    get_critical_facilities_kpis
)
from services.ai_service import ask_ai


class TestCriticalInfrastructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

        # Create unique test admin and test user
        cls.ts = int(datetime.now().timestamp())
        cls.admin_username = f"admin_infra_{cls.ts}"
        cls.admin_password = "adminpassword123"

        cls.user_email = f"user_infra_{cls.ts}@douala.cm"
        cls.user_phone = f"677{cls.ts % 1000000:06d}"
        cls.user_password = "userpassword123"
        cls.user_neighborhood = "Akwa"

        with get_db_cursor(commit=True) as cur:
            # Create admin
            cur.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                (cls.admin_username, generate_password_hash(cls.admin_password)),
            )
            cls.admin_id = cur.lastrowid

            # Create citizen user in Akwa
            cur.execute(
                """INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                   VALUES (%s, %s, %s, %s, %s)""",
                ("Test Citizen Akwa", cls.user_email, cls.user_phone,
                 generate_password_hash(cls.user_password), cls.user_neighborhood),
            )
            cls.user_id = cur.lastrowid

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_id"] = self.admin_id
            sess["admin_username"] = self.admin_username
            sess["lang"] = "fr"

    def login_user(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["user_name"] = "Test Citizen Akwa"
            sess["user_neighborhood"] = self.user_neighborhood
            sess["lang"] = "fr"

    def test_01_schema_and_seeder(self):
        """Verifies critical_facilities table and baseline 8 Douala facilities seeder."""
        count = seed_douala_critical_facilities(overwrite=True)
        self.assertGreaterEqual(count, 8)

        facilities = get_all_facilities()
        self.assertGreaterEqual(len(facilities), 8)

        names = [f["name"] for f in facilities]
        self.assertTrue(any("Laquintinie" in n for n in names))
        self.assertTrue(any("Général" in n for n in names))
        self.assertTrue(any("Camwater" in n for n in names))
        self.assertTrue(any("Bonassama" in n for n in names))
        self.assertTrue(any("Hémodialyse" in n for n in names))

    def test_02_haversine_and_proximity_lookup(self):
        """Tests geographic distance calculation and nearby facility matching."""
        # Akwa (Laquintinie) is at approx 4.0538, 9.7025
        dist_same = calculate_haversine_distance(4.0538, 9.7025, 4.0538, 9.7025)
        self.assertAlmostEqual(dist_same, 0.0, places=2)

        # Distance between Akwa (4.0538, 9.7025) and Bonamoussadi (4.0885, 9.7420) is approx 5-6 km
        dist_far = calculate_haversine_distance(4.0538, 9.7025, 4.0885, 9.7420)
        self.assertGreater(dist_far, 3.0)
        self.assertLess(dist_far, 8.0)

        # Proximity lookup within 2km of Akwa
        nearby = find_nearby_critical_facilities(4.0535, 9.7020, radius_km=1.5)
        self.assertGreater(len(nearby), 0)
        self.assertTrue(any("Laquintinie" in f["name"] for f in nearby))

    def test_03_outage_reporting_critical_impact_auto_shift(self):
        """When an outage is reported in Akwa near Laquintinie, status shifts to BACKUP_GENERATOR."""
        seed_douala_critical_facilities(overwrite=True)
        self.login_user()

        # Submit outage in Akwa
        resp = self.client.post("/report", data={
            "neighborhood": "Akwa",
            "location": "Face Hôpital Laquintinie, Rue Tobie Kuoh",
            "description": "Transformateur en fumée devant les urgences",
            "start_time": datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "latitude": "4.0538000",
            "longitude": "9.7025000",
            "is_distinct": "1"
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify outage record marked affects_critical = True
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, neighborhood, affects_critical FROM outages
                WHERE neighborhood = 'Akwa' AND status IN ('PENDING', 'VERIFIED')
                ORDER BY created_at DESC LIMIT 1
            """)
            outage_row = cur.fetchone()
            self.assertIsNotNone(outage_row)
            self.assertTrue(bool(outage_row["affects_critical"]))

            # Verify Hôpital Laquintinie power status was automatically shifted to BACKUP_GENERATOR
            cur.execute("SELECT name, current_power_status FROM critical_facilities WHERE LOWER(name) LIKE '%laquintinie%'")
            laq = cur.fetchone()
            self.assertEqual(laq["current_power_status"], "BACKUP_GENERATOR")

            # Verify high-priority critical notification dispatched
            cur.execute("SELECT title, message, type FROM notifications WHERE type = 'CRITICAL_INFRASTRUCTURE' ORDER BY created_at DESC LIMIT 1")
            notif = cur.fetchone()
            self.assertIsNotNone(notif)
            self.assertIn("Laquintinie", notif["title"])

    def test_04_facility_restoration_auto_sync(self):
        """When active outages in the zone are restored, facility returns to ON_GRID."""
        with get_db_cursor(commit=True) as cur:
            cur.execute("UPDATE outages SET status = 'RESTORED' WHERE LOWER(neighborhood) = 'akwa'")

        alert_count = sync_facilities_with_active_outages()

        with get_db_cursor() as cur:
            cur.execute("SELECT current_power_status FROM critical_facilities WHERE LOWER(name) LIKE '%laquintinie%'")
            laq = cur.fetchone()
            self.assertEqual(laq["current_power_status"], "ON_GRID")

    def test_05_public_infrastructure_page_and_api(self):
        """Tests public /infrastructure web route and JSON API endpoints."""
        resp = self.client.get("/infrastructure")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Hôpital Laquintinie", html)
        self.assertIn("Camwater", html)
        self.assertIn("infraMap", html)

        # API: /api/infrastructure
        api_resp = self.client.get("/api/infrastructure")
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.get_json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 8)

        # API: /api/infrastructure/summary
        sum_resp = self.client.get("/api/infrastructure/summary")
        self.assertEqual(sum_resp.status_code, 200)
        kpis = sum_resp.get_json()
        self.assertIn("total", kpis)
        self.assertIn("on_grid", kpis)
        self.assertIn("backup_generator", kpis)

    def test_06_admin_infrastructure_crud_and_status_toggle(self):
        """Tests admin critical infrastructure oversight, creation, manual status toggle, and deletion."""
        self.login_admin()

        # 1. Admin infrastructure view
        resp = self.client.get("/admin/infrastructure")
        self.assertEqual(resp.status_code, 200)

        # 2. Create custom clinic
        create_resp = self.client.post("/admin/infrastructure/create", data={
            "name": "Centre de Santé Intégré de Bali",
            "facility_type": "CLINIC",
            "neighborhood": "Bali",
            "address": "Rue Mandessi Bell",
            "latitude": "4.0450",
            "longitude": "9.7050",
            "has_backup_generator": "1",
            "generator_capacity_kva": "80",
            "fuel_autonomy_hours": "16.0",
            "current_power_status": "ON_GRID",
            "contact_name": "Dr. Mbarga",
            "contact_phone": "+237 233 42 99 99",
            "notes": "Poste de soins et urgences de proximité"
        }, follow_redirects=True)
        self.assertEqual(create_resp.status_code, 200)

        # Verify insertion
        with get_db_cursor() as cur:
            cur.execute("SELECT id FROM critical_facilities WHERE name = 'Centre de Santé Intégré de Bali'")
            created = cur.fetchone()
            self.assertIsNotNone(created)
            fac_id = created["id"]

        # 3. Update status to CRITICAL_BLACKOUT with fuel 0
        toggle_resp = self.client.post(f"/admin/infrastructure/{fac_id}/update-status", data={
            "current_power_status": "CRITICAL_BLACKOUT",
            "fuel_autonomy_hours": "0"
        }, follow_redirects=True)
        self.assertEqual(toggle_resp.status_code, 200)

        fac_check = get_facility_by_id(fac_id)
        self.assertEqual(fac_check["current_power_status"], "CRITICAL_BLACKOUT")
        self.assertEqual(float(fac_check["fuel_autonomy_hours"]), 0.0)

        # 4. Delete facility
        del_resp = self.client.post(f"/admin/infrastructure/{fac_id}/delete", follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(get_facility_by_id(fac_id))

    def test_07_ai_critical_infrastructure_queries(self):
        """Tests that the AI Assistant accurately answers hospital and water station questions."""
        with get_db_cursor() as cur:
            ans_laq = ask_ai("L'Hôpital Laquintinie a-t-il du courant ?", cur, lang="fr")
            self.assertIn("Laquintinie", ans_laq)
            self.assertTrue("Alimentation" in ans_laq or "Réseau" in ans_laq or "groupe" in ans_laq)

            ans_water = ask_ai("Quel est l'état de la station d'eau Camwater de Japoma ?", cur, lang="fr")
            self.assertIn("Japoma", ans_water)
            self.assertTrue("Camwater" in ans_water or "eau" in ans_water)

    def test_08_analytics_critical_metrics(self):
        """Tests that the analytics dashboard renders critical infrastructure statistics."""
        resp = self.client.get("/analytics")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Infrastructures Vitales & Hôpitaux", html)
        self.assertIn("Établissements Surveillés", html)


if __name__ == "__main__":
    unittest.main()
