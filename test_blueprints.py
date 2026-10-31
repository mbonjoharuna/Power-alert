"""
Verification script for Flask Blueprints Modular Refactoring.
Tests blueprint registration, endpoint routing, and modular integrity.
"""

import unittest
from app import app


class TestFlaskBlueprints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_registered_blueprints(self):
        """Verify all required blueprints are registered in the Flask application."""
        expected_blueprints = {"main", "auth", "outages", "admin", "api", "ai"}
        actual_blueprints = set(app.blueprints.keys())
        self.assertTrue(expected_blueprints.issubset(actual_blueprints), f"Missing blueprints: {expected_blueprints - actual_blueprints}")

    def test_auth_blueprint_endpoints(self):
        """Verify auth blueprint routes."""
        res_login = self.client.get("/login")
        self.assertEqual(res_login.status_code, 200)

        res_register = self.client.get("/register")
        self.assertEqual(res_register.status_code, 200)

        res_logout = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(res_logout.status_code, 302)

    def test_outages_blueprint_endpoints(self):
        """Verify outages blueprint routes."""
        res_outages = self.client.get("/outages")
        self.assertEqual(res_outages.status_code, 200)

        res_analytics = self.client.get("/analytics")
        self.assertEqual(res_analytics.status_code, 200)

        res_report_redirect = self.client.get("/report", follow_redirects=False)
        # Guest should be redirected to login
        self.assertEqual(res_report_redirect.status_code, 302)
        self.assertIn("/login", res_report_redirect.headers.get("Location", ""))

    def test_admin_blueprint_endpoints(self):
        """Verify admin blueprint routes."""
        res_admin_login = self.client.get("/admin/login")
        self.assertEqual(res_admin_login.status_code, 200)

        res_admin_dash_redirect = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(res_admin_dash_redirect.status_code, 302)
        self.assertIn("/admin/login", res_admin_dash_redirect.headers.get("Location", ""))

    def test_api_blueprint_endpoints(self):
        """Verify API blueprint routes."""
        res_map = self.client.get("/api/outages/map")
        self.assertEqual(res_map.status_code, 200)
        self.assertTrue(res_map.is_json)

        res_heatmap = self.client.get("/api/analytics/heatmap")
        self.assertEqual(res_heatmap.status_code, 200)
        self.assertTrue(res_heatmap.is_json)

        res_active = self.client.get("/api/outages/active-by-neighborhood?neighborhood=deido")
        self.assertEqual(res_active.status_code, 200)
        self.assertTrue(res_active.is_json)

        res_notif = self.client.get("/api/notifications")
        self.assertEqual(res_notif.status_code, 200)
        self.assertTrue(res_notif.is_json)

    def test_ai_blueprint_endpoints(self):
        """Verify AI blueprint routes."""
        res_ai = self.client.get("/ai")
        self.assertEqual(res_ai.status_code, 200)


if __name__ == '__main__':
    unittest.main()
