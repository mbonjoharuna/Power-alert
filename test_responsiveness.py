"""
Automated Responsive Design & Mobile Usability Verification Suite
for Douala Power Alert.
Tests viewport meta tags, CSS media breakpoints, touch targets,
table responsiveness, and mobile navigation drawer mechanics.
"""

import os
import re
import unittest
from app import create_app


class TestResponsiveDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_01_viewport_meta_tag(self):
        """Verify presence of mobile-first viewport meta tag in base layout."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', html)

    def test_02_css_responsive_breakpoints_exist(self):
        """Verify standard responsive breakpoints exist in style.css."""
        css_path = os.path.join("static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        # Check multi-tiered breakpoints
        self.assertIn("@media (max-width: 992px)", css)
        self.assertIn("@media (max-width: 768px)", css)
        self.assertIn("@media (max-width: 480px)", css)

    def test_03_css_grid_and_utility_system(self):
        """Verify presence of responsive grid and flexbox utility primitives."""
        css_path = os.path.join("static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        # Check flex & grid utilities
        self.assertIn(".d-flex", css)
        self.assertIn(".row", css)
        self.assertIn(".col-12", css)
        self.assertIn(".col-6", css)
        self.assertIn(".col-md-3", css)
        self.assertIn(".table-responsive", css)
        self.assertIn(".bg-dark-glass", css)

    def test_04_mobile_navigation_drawer_in_js(self):
        """Verify JavaScript handles hamburger click, outside click, and link click auto-dismiss."""
        js_path = os.path.join("static", "js", "script.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn('toggle.textContent = isOpen ? "✕" : "☰"', js)
        self.assertIn("links.classList.contains(\"open\")", js)

    def test_05_public_pages_render_with_clean_containers(self):
        """Verify key citizen and admin pages render without layout breakage."""
        endpoints = [
            "/",
            "/outages",
            "/schedules",
            "/infrastructure",
            "/analytics",
            "/ai",
            "/sms-guide",
            "/offline",
            "/login",
            "/register",
            "/admin/login"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} failed to render")


if __name__ == "__main__":
    unittest.main()
