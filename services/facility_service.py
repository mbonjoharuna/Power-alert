"""
Facility Service for Douala Power Alert.
Manages critical civic and medical infrastructure (Hospitals, Clinics, Water Treatment Stations,
Dialysis Centers, Blood Banks) and monitors their emergency power, backup generator status,
and fuel autonomy.
"""

import math
from datetime import datetime
from database import get_db_cursor

# Baseline real-world Douala critical infrastructure registry
DOUALA_CRITICAL_FACILITIES_SEED = [
    {
        "name": "Hôpital Laquintinie de Douala",
        "facility_type": "HOSPITAL",
        "neighborhood": "Akwa",
        "address": "Rue Tobie Kuoh, Akwa / Deido",
        "latitude": 4.0538000,
        "longitude": 9.7025000,
        "has_backup_generator": True,
        "generator_capacity_kva": 800,
        "fuel_autonomy_hours": 14.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Dr. Eitel M. (Chef Urgences)",
        "contact_phone": "+237 233 42 15 40",
        "notes": "Plus grand centre hospitalier public de Douala. Blocs opératoires, réanimation et urgences 24/7."
    },
    {
        "name": "Hôpital Général de Douala",
        "facility_type": "HOSPITAL",
        "neighborhood": "Bonamoussadi",
        "address": "Boulevard de la Liberté, Axe Logpom",
        "latitude": 4.0885000,
        "longitude": 9.7420000,
        "has_backup_generator": True,
        "generator_capacity_kva": 1200,
        "fuel_autonomy_hours": 24.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Dr. Ngo B. (Direction Technique)",
        "contact_phone": "+237 233 47 43 00",
        "notes": "Hôpital de référence tertiaire (Oncologie, Cardiologie interventionnelle, Soins intensifs)."
    },
    {
        "name": "Station de Traitement d'Eau Camwater Japoma",
        "facility_type": "WATER_TREATMENT",
        "neighborhood": "Yassa",
        "address": "Axe Lourd Douala-Yaoundé, Japoma",
        "latitude": 4.0080000,
        "longitude": 9.8150000,
        "has_backup_generator": True,
        "generator_capacity_kva": 1500,
        "fuel_autonomy_hours": 18.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Ing. Kamga (Exploitation Camwater)",
        "contact_phone": "+237 233 40 88 12",
        "notes": "Usine principale de production d'eau potable alimentant 60% de l'agglomération de Douala."
    },
    {
        "name": "Hôpital de District de Bonassama",
        "facility_type": "HOSPITAL",
        "neighborhood": "Bonaberi",
        "address": "Carrefour Bonassama, Face Mairie Douala 4e",
        "latitude": 4.0750000,
        "longitude": 9.6680000,
        "has_backup_generator": True,
        "generator_capacity_kva": 350,
        "fuel_autonomy_hours": 8.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Dr. Talla P. (Surveillant Général)",
        "contact_phone": "+237 233 39 12 00",
        "notes": "Centre de santé principal de la zone ouest de Douala (Bonabéri)."
    },
    {
        "name": "Station de Pompage et Réservoir Camwater Bépanda",
        "facility_type": "WATER_TREATMENT",
        "neighborhood": "Bassa",
        "address": "Bépanda Casmando, Douala 5e",
        "latitude": 4.0480000,
        "longitude": 9.7350000,
        "has_backup_generator": True,
        "generator_capacity_kva": 400,
        "fuel_autonomy_hours": 10.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Tech. Essomba (Réseau Distribution)",
        "contact_phone": "+237 233 41 23 88",
        "notes": "Château d'eau et station de surpression pour Deido, Bépanda, Cité SIC et Ndokoti."
    },
    {
        "name": "Centre d'Hémodialyse de Deido",
        "facility_type": "DIALYSIS",
        "neighborhood": "Deido",
        "address": "Rue des Flamboyants, Deido",
        "latitude": 4.0620000,
        "longitude": 9.7180000,
        "has_backup_generator": True,
        "generator_capacity_kva": 150,
        "fuel_autonomy_hours": 6.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Dr. Bilong (Néphrologie)",
        "contact_phone": "+237 233 42 77 90",
        "notes": "Générateurs de dialyse pour insuffisants rénaux. Toute coupure > 30 min engage le pronostic vital."
    },
    {
        "name": "Banque de Sang Hôpital Militaire",
        "facility_type": "BLOOD_BANK",
        "neighborhood": "Bonanjo",
        "address": "Quartier Administratif Bonanjo",
        "latitude": 4.0380000,
        "longitude": 9.6890000,
        "has_backup_generator": True,
        "generator_capacity_kva": 250,
        "fuel_autonomy_hours": 12.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Maj. Ngo'o (Chef Laboratoire)",
        "contact_phone": "+237 233 42 01 18",
        "notes": "Conservation par chaîne de froid (-20°C / +4°C) des concentrés de globules rouges et plasma frais."
    },
    {
        "name": "Clinique Maternité St-Jean Ndokoti",
        "facility_type": "CLINIC",
        "neighborhood": "Ndokoti",
        "address": "Carrefour Ndokoti, Vers Tergal",
        "latitude": 4.0540000,
        "longitude": 9.7420000,
        "has_backup_generator": True,
        "generator_capacity_kva": 100,
        "fuel_autonomy_hours": 8.0,
        "current_power_status": "ON_GRID",
        "contact_name": "Mme. Fonkou (Sage-Femme Major)",
        "contact_phone": "+237 233 43 55 10",
        "notes": "Maternité, couveuses néonatales et urgences pédiatriques de la zone populaire de Ndokoti."
    }
]


def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance in kilometers between two points
    on the earth (specified in decimal degrees).
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        r = 6371.0  # Radius of earth in kilometers
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c
    except Exception:
        return None


def seed_douala_critical_facilities(overwrite=False):
    """
    Seeds the baseline Douala critical infrastructure into the database.
    If overwrite is True, truncates/deletes existing before inserting.
    If overwrite is False, inserts only if the table is currently empty.
    """
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM critical_facilities")
            count = cur.fetchone()["c"]
            if count > 0 and not overwrite:
                return count

            if overwrite:
                cur.execute("DELETE FROM critical_facilities")

            sql = """
                INSERT INTO critical_facilities (
                    name, facility_type, neighborhood, address, latitude, longitude,
                    has_backup_generator, generator_capacity_kva, fuel_autonomy_hours,
                    current_power_status, contact_name, contact_phone, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            for f in DOUALA_CRITICAL_FACILITIES_SEED:
                cur.execute(sql, (
                    f["name"],
                    f["facility_type"],
                    f["neighborhood"],
                    f.get("address"),
                    f["latitude"],
                    f["longitude"],
                    f.get("has_backup_generator", True),
                    f.get("generator_capacity_kva"),
                    f.get("fuel_autonomy_hours", 12.0),
                    f.get("current_power_status", "ON_GRID"),
                    f.get("contact_name"),
                    f.get("contact_phone"),
                    f.get("notes"),
                ))
            return len(DOUALA_CRITICAL_FACILITIES_SEED)
    except Exception as e:
        print(f"Error seeding critical facilities: {e}")
        return 0


def get_all_facilities(facility_type=None, power_status=None, neighborhood=None):
    """
    Retrieves all critical facilities with optional filtering by type,
    power status, or neighborhood.
    """
    try:
        with get_db_cursor() as cur:
            sql = "SELECT * FROM critical_facilities WHERE 1=1"
            params = []
            if facility_type:
                sql += " AND facility_type = %s"
                params.append(facility_type)
            if power_status:
                sql += " AND current_power_status = %s"
                params.append(power_status)
            if neighborhood:
                sql += " AND LOWER(neighborhood) = %s"
                params.append(neighborhood.strip().lower())

            sql += " ORDER BY FIELD(current_power_status, 'CRITICAL_BLACKOUT', 'BACKUP_GENERATOR', 'ON_GRID'), name ASC"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            for r in rows:
                if r.get("fuel_autonomy_hours") is not None:
                    r["fuel_autonomy_hours"] = float(r["fuel_autonomy_hours"])
                if r.get("latitude") is not None:
                    r["latitude"] = float(r["latitude"])
                if r.get("longitude") is not None:
                    r["longitude"] = float(r["longitude"])
            return rows
    except Exception as e:
        print(f"Error fetching critical facilities: {e}")
        return []


def get_facility_by_id(facility_id):
    """Fetch single facility by ID."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT * FROM critical_facilities WHERE id = %s", (facility_id,))
            row = cur.fetchone()
            if row:
                if row.get("fuel_autonomy_hours") is not None:
                    row["fuel_autonomy_hours"] = float(row["fuel_autonomy_hours"])
                if row.get("latitude") is not None:
                    row["latitude"] = float(row["latitude"])
                if row.get("longitude") is not None:
                    row["longitude"] = float(row["longitude"])
            return row
    except Exception:
        return None


def create_facility(data):
    """Create a new critical facility record."""
    try:
        with get_db_cursor(commit=True) as cur:
            sql = """
                INSERT INTO critical_facilities (
                    name, facility_type, neighborhood, address, latitude, longitude,
                    has_backup_generator, generator_capacity_kva, fuel_autonomy_hours,
                    current_power_status, contact_name, contact_phone, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                data["name"].strip(),
                data["facility_type"],
                data["neighborhood"].strip(),
                data.get("address", "").strip() or None,
                float(data["latitude"]),
                float(data["longitude"]),
                bool(data.get("has_backup_generator", True)),
                int(data["generator_capacity_kva"]) if data.get("generator_capacity_kva") else None,
                float(data.get("fuel_autonomy_hours", 12.0)),
                data.get("current_power_status", "ON_GRID"),
                data.get("contact_name", "").strip() or None,
                data.get("contact_phone", "").strip() or None,
                data.get("notes", "").strip() or None,
            ))
            return cur.lastrowid
    except Exception as e:
        print(f"Error creating facility: {e}")
        return None


def update_facility(facility_id, data):
    """Update details of an existing critical facility."""
    try:
        with get_db_cursor(commit=True) as cur:
            sql = """
                UPDATE critical_facilities SET
                    name = %s,
                    facility_type = %s,
                    neighborhood = %s,
                    address = %s,
                    latitude = %s,
                    longitude = %s,
                    has_backup_generator = %s,
                    generator_capacity_kva = %s,
                    fuel_autonomy_hours = %s,
                    current_power_status = %s,
                    contact_name = %s,
                    contact_phone = %s,
                    notes = %s
                WHERE id = %s
            """
            cur.execute(sql, (
                data["name"].strip(),
                data["facility_type"],
                data["neighborhood"].strip(),
                data.get("address", "").strip() or None,
                float(data["latitude"]),
                float(data["longitude"]),
                bool(data.get("has_backup_generator", True)),
                int(data["generator_capacity_kva"]) if data.get("generator_capacity_kva") else None,
                float(data.get("fuel_autonomy_hours", 12.0)),
                data.get("current_power_status", "ON_GRID"),
                data.get("contact_name", "").strip() or None,
                data.get("contact_phone", "").strip() or None,
                data.get("notes", "").strip() or None,
                facility_id,
            ))
            return True
    except Exception as e:
        print(f"Error updating facility {facility_id}: {e}")
        return False


def delete_facility(facility_id):
    """Delete a facility record by ID."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM critical_facilities WHERE id = %s", (facility_id,))
            return True
    except Exception as e:
        print(f"Error deleting facility {facility_id}: {e}")
        return False


def update_facility_power_status(facility_id, new_status, fuel_autonomy_hours=None):
    """
    Update power status (ON_GRID, BACKUP_GENERATOR, CRITICAL_BLACKOUT)
    and optional remaining fuel hours.
    """
    valid_statuses = ("ON_GRID", "BACKUP_GENERATOR", "CRITICAL_BLACKOUT")
    if new_status not in valid_statuses:
        return False

    try:
        with get_db_cursor(commit=True) as cur:
            if fuel_autonomy_hours is not None:
                cur.execute("""
                    UPDATE critical_facilities
                    SET current_power_status = %s,
                        fuel_autonomy_hours = %s,
                        last_status_change = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (new_status, float(fuel_autonomy_hours), facility_id))
            else:
                cur.execute("""
                    UPDATE critical_facilities
                    SET current_power_status = %s,
                        last_status_change = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (new_status, facility_id))
            return True
    except Exception as e:
        print(f"Error updating power status for facility {facility_id}: {e}")
        return False


def get_facilities_by_neighborhood(neighborhood):
    """Return all critical facilities located in a given neighborhood."""
    if not neighborhood:
        return []
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT * FROM critical_facilities
                WHERE LOWER(TRIM(neighborhood)) = %s
                ORDER BY name ASC
            """, (neighborhood.strip().lower(),))
            return cur.fetchall()
    except Exception:
        return []


def find_nearby_critical_facilities(lat, lng, radius_km=2.5):
    """
    Find critical facilities within radius_km from a given GPS coordinate.
    """
    if lat is None or lng is None:
        return []
    all_facs = get_all_facilities()
    results = []
    for f in all_facs:
        dist = calculate_haversine_distance(lat, lng, f.get("latitude"), f.get("longitude"))
        if dist is not None and dist <= radius_km:
            f_copy = dict(f)
            f_copy["distance_km"] = round(dist, 2)
            results.append(f_copy)
    results.sort(key=lambda x: x["distance_km"])
    return results


def check_outage_critical_impact(neighborhood, lat=None, lng=None, radius_km=2.5):
    """
    Evaluates whether an outage affects critical infrastructure by either:
    1. Direct neighborhood match
    2. GPS proximity within radius_km
    Returns a tuple: (list_of_affected_facilities, is_critical_bool)
    """
    affected = []
    seen_ids = set()

    # 1. Check direct neighborhood match
    if neighborhood:
        by_neigh = get_facilities_by_neighborhood(neighborhood)
        for f in by_neigh:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                affected.append(f)

    # 2. Check GPS proximity if coordinates available
    if lat is not None and lng is not None:
        by_radius = find_nearby_critical_facilities(lat, lng, radius_km=radius_km)
        for f in by_radius:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                affected.append(f)

    is_critical = len(affected) > 0
    return affected, is_critical


def sync_facilities_with_active_outages():
    """
    Scans all critical facilities and compares against currently active
    (PENDING or VERIFIED) outages in their neighborhoods.
    Updates facility status to:
      - BACKUP_GENERATOR (if active outage and has generator)
      - CRITICAL_BLACKOUT (if active outage and NO generator or 0 fuel)
      - ON_GRID (if NO active outages in their neighborhood)
    Returns count of facilities in alert (BACKUP_GENERATOR or CRITICAL_BLACKOUT).
    """
    try:
        facilities = get_all_facilities()
        alert_count = 0

        with get_db_cursor(commit=True) as cur:
            for fac in facilities:
                # Check for active outage in this neighborhood
                cur.execute("""
                    SELECT id, status, outage_type FROM outages
                    WHERE LOWER(TRIM(neighborhood)) = %s
                      AND status IN ('PENDING', 'VERIFIED')
                    LIMIT 1
                """, (fac["neighborhood"].strip().lower(),))
                active_outage = cur.fetchone()

                new_status = "ON_GRID"
                if active_outage:
                    alert_count += 1
                    if fac.get("has_backup_generator") and float(fac.get("fuel_autonomy_hours") or 0) > 0:
                        new_status = "BACKUP_GENERATOR"
                    else:
                        new_status = "CRITICAL_BLACKOUT"

                if new_status != fac.get("current_power_status"):
                    cur.execute("""
                        UPDATE critical_facilities
                        SET current_power_status = %s,
                            last_status_change = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (new_status, fac["id"]))

        return alert_count
    except Exception as e:
        print(f"Error syncing facilities with outages: {e}")
        return 0


def get_critical_facilities_kpis():
    """
    Computes summary telemetry and KPIs for critical infrastructure dashboards.
    """
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) AS total,
                    SUM(CASE WHEN current_power_status = 'ON_GRID' THEN 1 ELSE 0 END) AS on_grid,
                    SUM(CASE WHEN current_power_status = 'BACKUP_GENERATOR' THEN 1 ELSE 0 END) AS backup_generator,
                    SUM(CASE WHEN current_power_status = 'CRITICAL_BLACKOUT' THEN 1 ELSE 0 END) AS critical_blackout,
                    SUM(CASE WHEN facility_type = 'HOSPITAL' THEN 1 ELSE 0 END) AS count_hospitals,
                    SUM(CASE WHEN facility_type = 'WATER_TREATMENT' THEN 1 ELSE 0 END) AS count_water,
                    SUM(CASE WHEN facility_type IN ('DIALYSIS', 'BLOOD_BANK', 'OXYGEN_PLANT') THEN 1 ELSE 0 END) AS count_specialized,
                    SUM(CASE WHEN facility_type = 'CLINIC' THEN 1 ELSE 0 END) AS count_clinics
                FROM critical_facilities
            """)
            row = cur.fetchone()
            if not row or row["total"] == 0:
                # Return default zeroed dictionary
                return {
                    "total": 0, "on_grid": 0, "backup_generator": 0, "critical_blackout": 0,
                    "count_hospitals": 0, "count_water": 0, "count_specialized": 0, "count_clinics": 0,
                    "grid_percent": 100.0, "alert_percent": 0.0, "in_alert": 0
                }

            total = row["total"] or 0
            on_grid = row["on_grid"] or 0
            backup = row["backup_generator"] or 0
            blackout = row["critical_blackout"] or 0
            in_alert = backup + blackout

            grid_pct = round((on_grid / total * 100), 1) if total > 0 else 100.0
            alert_pct = round((in_alert / total * 100), 1) if total > 0 else 0.0

            return {
                "total": total,
                "on_grid": on_grid,
                "backup_generator": backup,
                "critical_blackout": blackout,
                "in_alert": in_alert,
                "grid_percent": grid_pct,
                "alert_percent": alert_pct,
                "count_hospitals": row["count_hospitals"] or 0,
                "count_water": row["count_water"] or 0,
                "count_specialized": row["count_specialized"] or 0,
                "count_clinics": row["count_clinics"] or 0,
            }
    except Exception as e:
        print(f"Error getting facilities KPIs: {e}")
        return {
            "total": 0, "on_grid": 0, "backup_generator": 0, "critical_blackout": 0,
            "count_hospitals": 0, "count_water": 0, "count_specialized": 0, "count_clinics": 0,
            "grid_percent": 100.0, "alert_percent": 0.0, "in_alert": 0
        }
