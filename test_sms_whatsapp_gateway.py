"""
Comprehensive Automated Unit Tests for Option 2:
SMS & WhatsApp Incident Gateway for Low-Bandwidth / Offline Civic Reporting.
"""

import unittest
from datetime import datetime, timedelta
from app import create_app
from database import get_db_cursor, init_db
from werkzeug.security import generate_password_hash
from services.gateway_service import (
    normalize_phone,
    parse_inbound_message,
    handle_inbound_message,
    get_or_create_gateway_user,
    get_gateway_logs,
    get_gateway_kpis
)
from services.schedule_service import create_schedule
from services.facility_service import seed_douala_critical_facilities, get_facility_by_id


class TestSMSWhatsAppGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

        # Unique admin & user
        cls.ts = int(datetime.now().timestamp())
        cls.admin_username = f"admin_gw_{cls.ts}"
        cls.admin_password = "adminpassword123"

        with get_db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                (cls.admin_username, generate_password_hash(cls.admin_password))
            )
            cls.admin_id = cur.lastrowid

        seed_douala_critical_facilities(overwrite=False)

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_id"] = self.admin_id
            sess["admin_username"] = self.admin_username
            sess["lang"] = "fr"

    def test_01_phone_normalization(self):
        """Verify standard Cameroon phone numbers and WhatsApp prefix handling."""
        self.assertEqual(normalize_phone("677123456"), "+237677123456")
        self.assertEqual(normalize_phone("+237 6 99 88 77 66"), "+237699887766")
        self.assertEqual(normalize_phone("whatsapp:+237655443322"), "+237655443322")
        self.assertEqual(normalize_phone("00237680112233"), "+237680112233")
        self.assertEqual(normalize_phone("237690123456"), "+237690123456")
        self.assertEqual(normalize_phone(""), "+237000000000")

    def test_02_parse_inbound_commands(self):
        """Verify command parser for standard syntax and natural language."""
        # 1. HELP
        p_help = parse_inbound_message("AIDE")
        self.assertEqual(p_help["command"], "HELP")

        # 2. STATUS
        p_stat = parse_inbound_message("ETAT Deido")
        self.assertEqual(p_stat["command"], "STATUS")
        self.assertEqual(p_stat["neighborhood"], "Deido")

        # 3. CONFIRM
        p_conf = parse_inbound_message("CONFIRMER 42")
        self.assertEqual(p_conf["command"], "CONFIRM")
        self.assertEqual(p_conf["outage_id"], 42)

        # 4. RESTORE
        p_rest = parse_inbound_message("RETABLI 42")
        self.assertEqual(p_rest["command"], "RESTORE")
        self.assertEqual(p_rest["outage_id"], 42)

        # 5. COUPURE
        p_coup = parse_inbound_message("COUPURE Akwa Boulevard de la Liberte")
        self.assertEqual(p_coup["command"], "COUPURE")
        self.assertEqual(p_coup["neighborhood"], "Akwa")
        self.assertIn("Boulevard", p_coup["location"])

        # 6. Natural Language
        p_nat = parse_inbound_message("Plus de courant a Makepe vers le marche")
        self.assertEqual(p_nat["command"], "COUPURE")
        self.assertEqual(p_nat["neighborhood"], "Makepe")

    def test_03_handle_outage_reporting_via_sms(self):
        """Verify creating an outage via SMS message and verifying stored metadata."""
        # Mark previous test outages in Bassa as RESTORED to avoid duplicate trigger
        with get_db_cursor(commit=True) as cur:
            cur.execute("UPDATE outages SET status = 'RESTORED' WHERE LOWER(neighborhood) = 'bassa'")

        phone = f"+23767{self.ts % 1000000:06d}"
        res = handle_inbound_message(sender_phone=phone, raw_text="COUPURE Bassa Zone Industrielle", channel="SMS")

        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["command"], "COUPURE")
        self.assertIsNotNone(res["outage_id"])
        self.assertIn("Signalement", res["response"])
        self.assertIn("Bassa", res["response"])

        # Check DB record
        with get_db_cursor() as cur:
            cur.execute("SELECT * FROM outages WHERE id = %s", (res["outage_id"],))
            outage = cur.fetchone()
            self.assertIsNotNone(outage)
            self.assertEqual(outage["neighborhood"], "Bassa")
            self.assertEqual(outage["reported_via"], "SMS")
            self.assertIsNotNone(outage["latitude"])
            self.assertIsNotNone(outage["longitude"])

    def test_04_duplicate_detection_and_confirmation(self):
        """Verify that reporting an outage in an already active zone adds confirmation instead of duplicate."""
        # Mark previous test outages in Logbaba as RESTORED
        with get_db_cursor(commit=True) as cur:
            cur.execute("UPDATE outages SET status = 'RESTORED' WHERE LOWER(neighborhood) = 'logbaba'")

        phone1 = f"+23768{self.ts % 1000000:06d}"
        phone2 = f"+23769{self.ts % 1000000:06d}"

        # First report
        res1 = handle_inbound_message(sender_phone=phone1, raw_text="COUPURE Logbaba Entree Carrefour", channel="SMS")
        outage_id = res1["outage_id"]
        self.assertIsNotNone(outage_id)

        # Second report in same neighborhood shortly after
        res2 = handle_inbound_message(sender_phone=phone2, raw_text="COUPURE Logbaba Vers Station", channel="SMS")
        self.assertEqual(res2["outage_id"], outage_id)
        self.assertIn("Coupure déjà active", res2["response"])
        self.assertIn("confirmation (+1)", res2["response"])

        # Check confirmations table has the confirmation recorded
        with get_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM confirmations WHERE outage_id = %s", (outage_id,))
            count = cur.fetchone()["c"]
            self.assertGreaterEqual(count, 1)

    def test_05_critical_facility_correlation_via_sms(self):
        """Verify that an SMS reporting an outage in Deido alerts critical dialysis or pumping station."""
        # Mark previous test outages in Deido as RESTORED
        with get_db_cursor(commit=True) as cur:
            cur.execute("UPDATE outages SET status = 'RESTORED' WHERE LOWER(neighborhood) = 'deido'")

        phone = f"+23765{self.ts % 1000000:06d}"
        res = handle_inbound_message(sender_phone=phone, raw_text="COUPURE Deido Rue des Flamboyants", channel="SMS")

        self.assertEqual(res["status"], "SUCCESS")
        self.assertIn("ALERTE", res["response"])

        # Check affects_critical in database
        with get_db_cursor() as cur:
            cur.execute("SELECT affects_critical FROM outages WHERE id = %s", (res["outage_id"],))
            row = cur.fetchone()
            self.assertTrue(row["affects_critical"])

    def test_06_api_sms_webhook_twilio_xml(self):
        """Verify POST /api/gateway/sms with Twilio parameters returns XML response."""
        res = self.client.post("/api/gateway/sms", data={
            "From": "+237671112233",
            "Body": "ETAT"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/xml", res.content_type)
        xml_str = res.data.decode("utf-8")
        self.assertIn("<Response>", xml_str)
        self.assertIn("<Message>", xml_str)
        self.assertIn("</Message>", xml_str)
        self.assertIn("</Response>", xml_str)

    def test_07_api_whatsapp_webhook_json(self):
        """Verify POST /api/gateway/whatsapp with JSON payload returns JSON response."""
        res = self.client.post("/api/gateway/whatsapp", json={
            "phone": "+237694445566",
            "message": "AIDE",
            "channel": "WHATSAPP"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["channel"], "WHATSAPP")
        self.assertEqual(data["command"], "HELP")
        self.assertEqual(data["status"], "SUCCESS")
        self.assertIn("DOUALA POWER ALERT", data["response"])

    def test_08_admin_gateway_view_and_simulator(self):
        """Verify admin can view gateway logs and run interactive simulator."""
        self.login_admin()

        # 1. View Gateway Dashboard
        res = self.client.get("/admin/gateway")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Passerelle SMS".encode("utf-8"), res.data)
        self.assertIn("Simulateur Interactif".encode("utf-8"), res.data)

        # 2. Simulate via POST /admin/gateway/simulate
        sim_res = self.client.post("/admin/gateway/simulate", data={
            "channel": "SMS",
            "phone": "+237 670 99 88 77",
            "message": "COUPURE Kotto Bloc G"
        }, follow_redirects=True)
        self.assertEqual(sim_res.status_code, 200)
        self.assertIn("Simulation SMS".encode("utf-8"), sim_res.data)

    def test_09_public_sms_guide_and_offline_page(self):
        """Verify /sms-guide and /offline provide clickable SMS buttons and instructions."""
        # Public guide
        res_guide = self.client.get("/sms-guide")
        self.assertEqual(res_guide.status_code, 200)
        self.assertIn("Passerelle SMS".encode("utf-8"), res_guide.data)
        self.assertIn("sms:+237670000000".encode("utf-8"), res_guide.data)
        self.assertIn("https://wa.me/237670000000".encode("utf-8"), res_guide.data)

        # Offline fallback page
        res_offline = self.client.get("/offline")
        self.assertEqual(res_offline.status_code, 200)
        self.assertIn("sms:+237670000000".encode("utf-8"), res_offline.data)
        self.assertIn("Signaler une coupure par SMS".encode("utf-8"), res_offline.data)


if __name__ == "__main__":
    unittest.main()
