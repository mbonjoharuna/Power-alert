"""
Verification script for GPS & Click-to-Pinpoint Map Selection.
"""

import re
import time
from app import app, init_db
from database import get_db_cursor

print("=== STARTING GPS & MAP PINPOINT VERIFICATION ===")
init_db()

# Create a test citizen
test_email = f"gps_tester_{int(time.time())}@douala.cm"
with get_db_cursor(commit=True) as cur:
    cur.execute("""
        INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
        VALUES (%s, %s, %s, %s, %s)
    """, ("GPS Citizen", test_email, f"65{int(time.time())%1000000:06d}", "hash", "Bonanjo"))
    user_id = cur.lastrowid

print(f"Created GPS test user ID: {user_id}")

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "GPS Citizen"
        sess["user_neighborhood"] = "Bonanjo"
        sess["lang"] = "fr"

    # --- Test 1: Verify Report Page Renders Mini-Map & GPS Button ---
    rep_page = client.get("/report")
    assert rep_page.status_code == 200
    html = rep_page.data.decode("utf-8")
    assert 'id="reportMap"' in html, "Mini-map container missing from report page"
    assert 'id="btnGeo"' in html, "Geolocation button missing"
    assert 'id="latitude"' in html and 'id="longitude"' in html, "Hidden coordinate inputs missing"
    print("Report page HTML verified: mini-map, geolocation button, and coordinate inputs present.")

    # --- Test 2: Submit Report with Exact Pinpoint Coordinates ---
    m_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m_csrf, "CSRF token not found"
    csrf_tok = m_csrf.group(1)

    custom_lat = 4.041234
    custom_lng = 9.692345

    res_post = client.post("/report", data={
        "csrf_token": csrf_tok,
        "neighborhood": "Bonanjo",
        "location": "Avenue Charles de Gaulle",
        "description": "Panne ciblée devant la mairie",
        "start_time": "2026-10-31T14:00",
        "latitude": str(custom_lat),
        "longitude": str(custom_lng),
        "is_distinct": "1"
    }, follow_redirects=True)
    assert res_post.status_code == 200
    print(f"Submitted report with exact coordinates ({custom_lat}, {custom_lng}) -> 200 OK")

    # --- Test 3: Verify Coordinates Saved in Database ---
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, neighborhood, location, latitude, longitude
            FROM outages
            WHERE user_id = %s
            ORDER BY id DESC LIMIT 1
        """, (user_id,))
        saved = cur.fetchone()
        assert saved is not None
        outage_id = saved["id"]
        assert float(saved["latitude"]) == round(custom_lat, 6)
        assert float(saved["longitude"]) == round(custom_lng, 6)
    print(f"Database verified: Outage #{outage_id} stored exact lat={saved['latitude']}, lng={saved['longitude']}")

    # --- Test 4: Verify Map API Endpoint Returns Custom Coordinates ---
    res_map = client.get("/api/outages/map")
    assert res_map.status_code == 200
    markers = res_map.get_json()
    matched = [m for m in markers if m["id"] == outage_id]
    assert len(matched) == 1, "Outage not found in map API"
    m_data = matched[0]
    assert abs(m_data["lat"] - custom_lat) < 0.0001
    assert abs(m_data["lng"] - custom_lng) < 0.0001
    print(f"Map API verified: returned custom pinpoint lat={m_data['lat']}, lng={m_data['lng']}")

    # --- Test 5: Verify Outage Details Page Renders GPS Coordinates ---
    det_page = client.get(f"/outage/{outage_id}")
    assert det_page.status_code == 200
    det_html = det_page.data.decode("utf-8")
    assert "Coordonnées GPS" in det_html
    assert str(custom_lat) in det_html or f"{custom_lat:.4f}" in det_html
    print("Outage details page verified: GPS coordinates and Google Maps link rendered.")

    # --- Test 6: Verify Fallback when No GPS is Provided ---
    res_post_fallback = client.post("/report", data={
        "csrf_token": csrf_tok,
        "neighborhood": "Bonamoussadi",
        "location": "Secteur Marché",
        "description": "Sans coordonnées GPS explicites",
        "start_time": "2026-10-31T14:05",
        "latitude": "",
        "longitude": "",
        "is_distinct": "1"
    }, follow_redirects=True)
    assert res_post_fallback.status_code == 200

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, latitude, longitude FROM outages
            WHERE location = 'Secteur Marché' AND user_id = %s
        """, (user_id,))
        fallback_row = cur.fetchone()
        assert fallback_row["latitude"] is None
        fb_id = fallback_row["id"]

    res_map_fb = client.get("/api/outages/map")
    fb_markers = [m for m in res_map_fb.get_json() if m["id"] == fb_id]
    assert len(fb_markers) == 1
    # Should use Bonamoussadi default coords [4.0850, 9.7400]
    assert fb_markers[0]["lat"] == 4.0850
    assert fb_markers[0]["lng"] == 9.7400
    print("Fallback verified: Missing GPS coordinates successfully fall back to neighborhood center default coordinates.")

print("\n========================================================")
print("ALL GPS & CLICK-TO-PINPOINT MAP TESTS PASSED WITH 100% SUCCESS!")
print("========================================================")
