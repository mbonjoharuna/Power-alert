import unittest
from app import app
from database import get_db_cursor
from services.ai_service import ask_ai, get_historical_prediction

class TestAnalyticsAndHeatmap(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_analytics_page(self):
        response = self.client.get('/analytics')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Analytiques', response.data)
        self.assertIn(b'map', response.data)

    def test_heatmap_api(self):
        response = self.client.get('/api/analytics/heatmap')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        data = response.get_json()
        self.assertIsInstance(data, list)
        if len(data) > 0:
            point = data[0]
            self.assertEqual(len(point), 3)  # [lat, lng, intensity]
            self.assertIsInstance(point[0], (int, float))
            self.assertIsInstance(point[1], (int, float))
            self.assertIsInstance(point[2], (int, float))

    def test_ai_historical_prediction(self):
        with get_db_cursor() as cursor:
            # Test direct historical prediction function
            pred = get_historical_prediction('Deido', cursor, 'fr')
            # Check if prediction returns string or None (if no data)
            if pred:
                self.assertIn("Historiquement", pred)

            # Test ask_ai with neighborhood query
            reply = ask_ai("Quand revient le courant à Deido ?", cursor=cursor, lang='fr')
            self.assertIsInstance(reply, str)
            self.assertIn("Deido", reply)
            self.assertIn("Historiquement", reply)
            print("\nAI Response Sample:\n", reply.encode('ascii', errors='replace').decode('ascii'))

if __name__ == '__main__':
    unittest.main()
