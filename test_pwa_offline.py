"""
Unit and integration tests for Progressive Web App (PWA) and Offline capabilities:
- manifest.json specification compliance
- Offline fallback route (/offline)
- Service Worker registration & caching script
- PWA install prompt banner in templates
- Emergency contacts & safety guide accessibility
- High-resolution app icons
"""

import json
import os
import unittest
from app import create_app
from extensions import limiter
from translations import get_text, TRANSLATIONS


class TestPwaOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        limiter.enabled = False

    def tearDown(self):
        limiter.enabled = True

    def test_manifest_json(self):
        """Verify manifest.json is accessible, valid JSON, and contains PWA properties."""
        with self.client.get("/static/manifest.json") as res:
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data.decode("utf-8"))

        self.assertIn("name", data)
        self.assertIn("short_name", data)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["background_color"], "#070b14")
        self.assertEqual(data["theme_color"], "#070b14")
        self.assertTrue(len(data.get("icons", [])) >= 2)

        # Verify icon files actually exist on disk
        for icon in data["icons"]:
            src = icon["src"].lstrip("/")
            full_path = os.path.join(self.app.root_path, src)
            self.assertTrue(os.path.exists(full_path), f"Icon missing: {full_path}")

    def test_service_worker_asset(self):
        """Verify sw.js is accessible and contains caching logic."""
        with self.client.get("/static/sw.js") as res:
            self.assertEqual(res.status_code, 200)
            content = res.data.decode("utf-8")
        self.assertIn("douala-power-cache", content)
        self.assertIn("/offline", content)
        self.assertIn("caches.open", content)

    def test_offline_page_route(self):
        """Verify /offline renders successfully with emergency contacts and safety tips."""
        res = self.client.get("/offline")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # Verify key sections
        self.assertIn("Mode Hors-Ligne", html)
        self.assertIn("8010", html)  # Eneo emergency number
        self.assertIn("118", html)   # Firefighters emergency number
        self.assertIn("117", html)   # Police emergency number
        self.assertIn("Laquintinie", html)
        self.assertIn("offlineOutagesList", html)
        self.assertIn("btnRetryConnection", html)

    def test_pwa_banner_in_base_template(self):
        """Verify base template renders the manifest link and PWA install prompt banner."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        self.assertIn('rel="manifest"', html)
        self.assertIn('id="pwaInstallBanner"', html)
        self.assertIn('id="btnPwaInstall"', html)
        self.assertIn('id="btnPwaDismiss"', html)

    def test_pwa_translations(self):
        """Verify bilingual translations for PWA install and offline mode."""
        for lang in ["fr", "en"]:
            self.assertNotEqual(get_text("pwa_install_title", lang), "pwa_install_title")
            self.assertNotEqual(get_text("offline_title", lang), "offline_title")
            self.assertNotEqual(get_text("offline_emergency_title", lang), "offline_emergency_title")
            self.assertNotEqual(get_text("offline_safety_title", lang), "offline_safety_title")


if __name__ == "__main__":
    unittest.main()
