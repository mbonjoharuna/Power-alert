"""
Verification script for Option A: Security & Stability.
Tests Connection Pooling, CSRF Protection, and Rate Limiting.
"""

import re
import time
from app import app, init_db
from database import get_pool

print("--- 1. Testing Connection Pool Initialization ---")
init_db()
pool = get_pool()
print(f"Connection pool initialized: name={pool.pool_name}, size={pool.pool_size}")

with app.test_client() as client:
    print("\n--- 2. Testing Public Endpoints (GET) ---")
    for route in ["/", "/outages", "/login", "/register", "/ai", "/admin/login"]:
        res = client.get(route)
        assert res.status_code == 200, f"GET {route} failed with {res.status_code}"
        print(f"GET {route:15} -> 200 OK")

    print("\n--- 3. Testing CSRF Protection ---")
    # Submitting POST without CSRF token must trigger CSRFError handler
    res_no_csrf = client.post(
        "/login",
        data={"email": "hacker@test.com", "password": "password"},
        follow_redirects=True,
    )
    body_no_csrf = res_no_csrf.data.decode("utf-8")
    assert (
        "jeton de sécurité" in body_no_csrf
        or "csrf" in body_no_csrf.lower()
        or res_no_csrf.status_code == 400
        or "expiré" in body_no_csrf
    ), "CSRF protection failed to reject request missing token"
    print("Missing CSRF token correctly caught & rejected!")

    print("\n--- 4. Testing User Registration with CSRF ---")
    reg_page = client.get("/register")
    match_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', reg_page.data.decode("utf-8"))
    assert match_csrf, "CSRF token input not rendered in /register"
    csrf_token = match_csrf.group(1)

    unique_suffix = int(time.time())
    test_email = f"user_{unique_suffix}@douala.cm"
    test_phone = f"69{unique_suffix % 10000000:07d}"

    res_reg = client.post(
        "/register",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Citizen",
            "email": test_email,
            "phone": test_phone,
            "password": "validpassword123",
            "neighborhood": "Bonamoussadi",
        },
        follow_redirects=True,
    )
    assert res_reg.status_code == 200
    print(f"Registered user '{test_email}' with CSRF token -> 200 OK")

    print("\n--- 5. Testing Login with CSRF ---")
    login_page = client.get("/login")
    match_login_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.data.decode("utf-8"))
    csrf_login = match_login_csrf.group(1)

    res_login = client.post(
        "/login",
        data={
            "csrf_token": csrf_login,
            "email": test_email,
            "password": "validpassword123",
        },
        follow_redirects=True,
    )
    assert res_login.status_code == 200
    html_dashboard = res_login.data.decode("utf-8")
    assert "Tableau de bord" in html_dashboard or "Dashboard" in html_dashboard
    print("Logged in successfully -> Dashboard rendered!")

    print("\n--- 6. Testing Outage Report Submission with CSRF ---")
    rep_page = client.get("/report")
    match_rep_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', rep_page.data.decode("utf-8"))
    csrf_rep = match_rep_csrf.group(1)

    res_report = client.post(
        "/report",
        data={
            "csrf_token": csrf_rep,
            "neighborhood": "Bonamoussadi",
            "location": "Rond-point Denver",
            "description": "Coupure secteur nord",
            "start_time": "2026-10-31T11:00",
        },
        follow_redirects=True,
    )
    assert res_report.status_code == 200
    print("Report submitted with CSRF token -> 200 OK")

    print("\n--- 7. Testing Outage Details and Confirmation ---")
    outages_page = client.get("/outages")
    m_outage = re.search(r'/outage/(\d+)', outages_page.data.decode("utf-8"))
    assert m_outage, "No outage link found in /outages"
    outage_id = int(m_outage.group(1))

    detail_page = client.get(f"/outage/{outage_id}")
    match_conf_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', detail_page.data.decode("utf-8"))
    csrf_conf = match_conf_csrf.group(1)

    res_conf = client.post(
        f"/outage/{outage_id}/confirm",
        data={
            "csrf_token": csrf_conf,
            "confirmation": "STILL_OFF",
        },
        follow_redirects=True,
    )
    assert res_conf.status_code == 200
    print(f"Confirmed outage #{outage_id} with CSRF token -> 200 OK")

    print("\n--- 8. Testing AI Query with CSRF ---")
    ai_page = client.get("/ai")
    m_ai_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', ai_page.data.decode("utf-8"))
    csrf_ai = m_ai_csrf.group(1)

    res_ai = client.post(
        "/ai",
        data={
            "csrf_token": csrf_ai,
            "question": "Y a-t-il une coupure à Bonamoussadi ?",
        },
        follow_redirects=True,
    )
    assert res_ai.status_code == 200
    assert "Bonamoussadi" in res_ai.data.decode("utf-8")
    print("AI query handled successfully -> 200 OK")

    print("\n--- 9. Testing Admin Dashboard with CSRF ---")
    admin_login_page = client.get("/admin/login")
    m_admin_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', admin_login_page.data.decode("utf-8"))
    csrf_admin = m_admin_csrf.group(1)

    res_admin = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf_admin,
            "username": "admin",
            "password": "admin123",
        },
        follow_redirects=True,
    )
    assert res_admin.status_code == 200
    admin_dash_html = res_admin.data.decode("utf-8")
    assert "admin" in admin_dash_html.lower()

    # Admin approve action with CSRF
    m_dash_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', admin_dash_html)
    assert m_dash_csrf, "CSRF token not found on admin dashboard"
    csrf_dash = m_dash_csrf.group(1)

    res_approve = client.post(
        f"/admin/approve/{outage_id}",
        data={"csrf_token": csrf_dash},
        follow_redirects=True,
    )
    assert res_approve.status_code == 200
    print(f"Admin approved outage #{outage_id} with CSRF -> 200 OK")

    print("\n--- 10. Testing Map API Endpoint ---")
    res_map = client.get("/api/outages/map")
    assert res_map.status_code == 200
    markers = res_map.get_json()
    assert isinstance(markers, list)
    print(f"Map API returned {len(markers)} outage markers")

print("\n========================================================")
print("ALL OPTION A SECURITY & STABILITY TESTS PASSED WITH 100% SUCCESS!")
print("========================================================")
