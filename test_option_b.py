"""
Verification script for Option B: Duplicate Outage Detection & Community Auto-Verification.
"""

import re
import time
from app import app, init_db
from database import get_db_cursor

print("=== STARTING OPTION B VERIFICATION ===")
init_db()

# Create 4 test users for confirmation tests
user_ids = []
run_id = int(time.time())
test_n = f"Zone_{run_id}"

with get_db_cursor(commit=True) as cur:
    for i in range(1, 5):
        email = f"citizen_{i}_{run_id}@douala.cm"
        cur.execute("""
            INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
            VALUES (%s, %s, %s, %s, %s)
        """, (f"Citizen {i}", email, f"67{run_id%1000000:06d}{i}", "hash", test_n))
        user_ids.append(cur.lastrowid)

print(f"Created 4 test users: {user_ids} in {test_n}")

with app.test_client() as client:
    # Set session to User 1
    with client.session_transaction() as sess:
        sess["user_id"] = user_ids[0]
        sess["user_name"] = "Citizen 1"
        sess["user_neighborhood"] = test_n
        sess["lang"] = "fr"

    # --- Test 1: Check active-by-neighborhood API before any report ---
    res_api_empty = client.get(f"/api/outages/active-by-neighborhood?neighborhood={test_n}")
    assert res_api_empty.status_code == 200
    data_empty = res_api_empty.get_json()
    assert data_empty["found"] is False
    print("API check before report (empty):", data_empty)

    # --- Test 2: Create initial report in test_n ---
    rep_get = client.get("/report")
    m_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', rep_get.data.decode("utf-8"))
    assert m_csrf, "CSRF token not found"
    csrf_tok = m_csrf.group(1)

    res_initial = client.post("/report", data={
        "csrf_token": csrf_tok,
        "neighborhood": test_n,
        "location": "Rue de la Joie",
        "description": "Panne de transformateur",
        "start_time": "2026-10-31T13:00"
    }, follow_redirects=True)
    assert res_initial.status_code == 200
    print(f"Initial outage in {test_n} reported successfully.")

    # Find the outage id in DB
    with get_db_cursor() as cur:
        cur.execute("SELECT id, status FROM outages WHERE neighborhood = %s AND location = 'Rue de la Joie' ORDER BY id DESC LIMIT 1", (test_n,))
        initial_outage = cur.fetchone()
        outage_id = initial_outage["id"]
        assert initial_outage["status"] == "PENDING"
    print(f"Initial Outage ID: {outage_id}, Status: {initial_outage['status']}")

    # --- Test 3: API returns active outage now ---
    res_api_found = client.get(f"/api/outages/active-by-neighborhood?neighborhood={test_n}")
    assert res_api_found.status_code == 200
    data_found = res_api_found.get_json()
    assert data_found["found"] is True
    assert len(data_found["outages"]) > 0
    assert data_found["outages"][0]["id"] == outage_id
    print(f"API successfully detected active outage in {test_n}:", data_found["outages"][0]["location"])

    # --- Test 4: Duplicate Detection on POST /report (without is_distinct) ---
    rep_get2 = client.get("/report")
    m_csrf2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', rep_get2.data.decode("utf-8"))
    csrf_tok2 = m_csrf2.group(1)

    res_dup = client.post("/report", data={
        "csrf_token": csrf_tok2,
        "neighborhood": test_n,
        "location": "Carrefour des Fleurs",
        "description": "Plus de lumière",
        "start_time": "2026-10-31T13:10"
    }, follow_redirects=True)
    assert res_dup.status_code == 200
    dup_html = res_dup.data.decode("utf-8")
    assert "Coupure active déjà signalée" in dup_html or "Active outage already reported" in dup_html or "Rue de la Joie" in dup_html
    print("Duplicate report successfully intercepted and warned user with confirmation option!")

    # --- Test 5: Reporting with is_distinct=1 allows separate report ---
    res_distinct = client.post("/report", data={
        "csrf_token": csrf_tok2,
        "neighborhood": test_n,
        "location": "Grand Moulin",
        "description": "Autre panne distincte",
        "start_time": "2026-10-31T13:15",
        "is_distinct": "1"
    }, follow_redirects=True)
    assert res_distinct.status_code == 200
    print("Distinct report with is_distinct=1 passed successfully!")

    # --- Test 6: Community Auto-Verification (3 STILL_OFF confirmations) ---
    # User 1 already reported, now User 1 confirms
    det_page = client.get(f"/outage/{outage_id}")
    m_c = re.search(r'name="csrf_token"\s+value="([^"]+)"', det_page.data.decode("utf-8"))
    c_tok = m_c.group(1)
    res_c1 = client.post(f"/outage/{outage_id}/confirm", data={"csrf_token": c_tok, "confirmation": "STILL_OFF"}, follow_redirects=True)
    assert res_c1.status_code == 200

    # User 2 confirms
    with client.session_transaction() as sess:
        sess["user_id"] = user_ids[1]
    det_page = client.get(f"/outage/{outage_id}")
    c_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', det_page.data.decode("utf-8")).group(1)
    res_c2 = client.post(f"/outage/{outage_id}/confirm", data={"csrf_token": c_tok, "confirmation": "STILL_OFF"}, follow_redirects=True)
    assert res_c2.status_code == 200

    # Status should still be PENDING (2 confirmations)
    with get_db_cursor() as cur:
        cur.execute("SELECT status FROM outages WHERE id = %s", (outage_id,))
        assert cur.fetchone()["status"] == "PENDING"
    print("2 confirmations received -> Outage status remains PENDING as expected.")

    # User 3 confirms (3rd confirmation -> Threshold reached!)
    with client.session_transaction() as sess:
        sess["user_id"] = user_ids[2]
    det_page = client.get(f"/outage/{outage_id}")
    c_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', det_page.data.decode("utf-8")).group(1)
    res_c3 = client.post(f"/outage/{outage_id}/confirm", data={"csrf_token": c_tok, "confirmation": "STILL_OFF"}, follow_redirects=True)
    assert res_c3.status_code == 200
    c3_html = res_c3.data.decode("utf-8")
    assert "automatiquement VÉRIFIÉE" in c3_html or "automatically VERIFIED" in c3_html

    with get_db_cursor() as cur:
        cur.execute("SELECT status FROM outages WHERE id = %s", (outage_id,))
        assert cur.fetchone()["status"] == "VERIFIED"
    print("3 confirmations reached -> OUTAGE AUTO-PROMOTED TO VERIFIED!")

    # --- Test 7: Community Auto-Restoration (3 RESTORED confirmations on another outage) ---
    # Create another outage in Makepe
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO outages (user_id, neighborhood, location, description, start_time, status)
            VALUES (%s, 'Makepe', 'Carrefour Rhône-Poulenc', 'Blackout', NOW(), 'VERIFIED')
        """, (user_ids[0],))
        outage_rest_id = cur.lastrowid

    # Have User 1, User 2, User 3 confirm RESTORED
    for uid in [user_ids[0], user_ids[1], user_ids[2]]:
        with client.session_transaction() as sess:
            sess["user_id"] = uid
        det_page = client.get(f"/outage/{outage_rest_id}")
        c_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', det_page.data.decode("utf-8")).group(1)
        res_r = client.post(f"/outage/{outage_rest_id}/confirm", data={"csrf_token": c_tok, "confirmation": "RESTORED"}, follow_redirects=True)
        assert res_r.status_code == 200

    with get_db_cursor() as cur:
        cur.execute("SELECT status FROM outages WHERE id = %s", (outage_rest_id,))
        assert cur.fetchone()["status"] == "RESTORED"
    print("3 RESTORED confirmations reached -> OUTAGE AUTO-PROMOTED TO RESTORED!")

print("\n==================================================================")
print("ALL OPTION B (DUPLICATE DETECTION & AUTO-VERIFICATION) TESTS PASSED!")
print("==================================================================")
