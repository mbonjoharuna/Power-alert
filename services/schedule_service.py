"""
Service for managing official Eneo scheduled load-shedding and maintenance rotas.
Provides parsing (CSV/JSON), auto-correlation with citizen outage reports,
and status tracking.
"""

import csv
import io
import json
from datetime import datetime
from database import get_db_cursor


def find_matching_schedule(neighborhood, target_time=None):
    """
    Check if a report in a neighborhood coincides with an active or upcoming Eneo maintenance schedule.
    """
    if not neighborhood:
        return None

    clean_neighborhood = neighborhood.strip().title()

    if target_time is None:
        target_time = datetime.now()
    elif isinstance(target_time, str):
        try:
            # Handle standard datetime strings
            clean_str = target_time.replace("T", " ")
            if len(clean_str) == 16:
                clean_str += ":00"
            target_time = datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            target_time = datetime.now()

    with get_db_cursor() as cur:
        # Match within schedule window (or +/- 2 hours buffer for grid switching delays)
        cur.execute("""
            SELECT id, neighborhood, title, description, start_time, end_time, status
            FROM scheduled_outages
            WHERE LOWER(neighborhood) = LOWER(%s)
              AND status IN ('SCHEDULED', 'IN_PROGRESS')
              AND start_time <= DATE_ADD(%s, INTERVAL 2 HOUR)
              AND end_time >= DATE_SUB(%s, INTERVAL 2 HOUR)
            ORDER BY start_time ASC
            LIMIT 1;
        """, (clean_neighborhood, target_time, target_time))
        return cur.fetchone()


def create_schedule(neighborhood, title, start_time, end_time, description="", status="SCHEDULED"):
    """
    Create a new scheduled maintenance slot and auto-link matching outages in that zone.
    """
    clean_neighborhood = neighborhood.strip().title()

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO scheduled_outages (neighborhood, title, description, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (clean_neighborhood, title.strip(), description.strip(), start_time, end_time, status))
        schedule_id = cur.lastrowid

        # Auto-update existing outages in that neighborhood and timeframe to SCHEDULED
        cur.execute("""
            UPDATE outages
            SET outage_type = 'SCHEDULED', schedule_id = %s
            WHERE LOWER(neighborhood) = LOWER(%s)
              AND start_time >= DATE_SUB(%s, INTERVAL 2 HOUR)
              AND start_time <= DATE_ADD(%s, INTERVAL 2 HOUR);
        """, (schedule_id, clean_neighborhood, start_time, end_time))

        return schedule_id


def correlate_all_outages_with_schedules():
    """
    Scan all outages and link them to scheduled maintenance if a matching window exists.
    """
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE outages o
            INNER JOIN scheduled_outages s
               ON LOWER(o.neighborhood) = LOWER(s.neighborhood)
              AND o.start_time >= DATE_SUB(s.start_time, INTERVAL 2 HOUR)
              AND o.start_time <= DATE_ADD(s.end_time, INTERVAL 2 HOUR)
            SET o.outage_type = 'SCHEDULED', o.schedule_id = s.id
            WHERE s.status IN ('SCHEDULED', 'IN_PROGRESS');
        """)


def import_schedules_from_csv(csv_text_or_stream):
    """
    Import schedule records from CSV text or stream.
    Expected columns: neighborhood, title, start_time, end_time, description (optional)
    """
    if isinstance(csv_text_or_stream, str):
        reader = csv.DictReader(io.StringIO(csv_text_or_stream))
    else:
        reader = csv.DictReader(csv_text_or_stream)

    imported_count = 0
    for row in reader:
        neighborhood = row.get("neighborhood") or row.get("quartier") or ""
        title = row.get("title") or row.get("titre") or row.get("motif") or "Maintenance Eneo"
        start_time = row.get("start_time") or row.get("debut")
        end_time = row.get("end_time") or row.get("fin")
        description = row.get("description") or row.get("details") or ""

        if neighborhood and start_time and end_time:
            # Normalize ISO datetime strings (e.g. 2026-11-01T08:00)
            clean_start = start_time.replace("T", " ")[:19]
            clean_end = end_time.replace("T", " ")[:19]
            create_schedule(neighborhood, title, clean_start, clean_end, description)
            imported_count += 1

    correlate_all_outages_with_schedules()
    return imported_count


def import_schedules_from_json(json_text_or_list):
    """
    Import schedule records from a JSON array.
    """
    if isinstance(json_text_or_list, str):
        items = json.loads(json_text_or_list)
    else:
        items = json_text_or_list

    if not isinstance(items, list):
        items = [items]

    imported_count = 0
    for item in items:
        neighborhood = item.get("neighborhood") or item.get("quartier")
        title = item.get("title") or item.get("titre") or "Maintenance Eneo"
        start_time = item.get("start_time") or item.get("debut")
        end_time = item.get("end_time") or item.get("fin")
        description = item.get("description") or item.get("details") or ""

        if neighborhood and start_time and end_time:
            clean_start = str(start_time).replace("T", " ")[:19]
            clean_end = str(end_time).replace("T", " ")[:19]
            create_schedule(neighborhood, title, clean_start, clean_end, description)
            imported_count += 1

    correlate_all_outages_with_schedules()
    return imported_count


def load_sample_douala_schedules():
    """
    Populate realistic sample Eneo maintenance and load-shedding rotas across Douala.
    """
    samples = [
        {
            "neighborhood": "Bonaberi",
            "title": "Travaux d'élagage & Révision Départs Moyenne Tension",
            "start_time": "2026-11-01 08:00:00",
            "end_time": "2026-11-01 16:00:00",
            "description": "Travaux programmés sur l'artère Bonabéri Centre vers Carrefour Mutuelle. Sécurisation du corridor HT.",
            "status": "SCHEDULED"
        },
        {
            "neighborhood": "Deido",
            "title": "Remplacement Transformateur 630 kVA Grand Moulin",
            "start_time": "2026-11-02 09:00:00",
            "end_time": "2026-11-02 15:30:00",
            "description": "Remplacement préventif de transformateur surchargé pour stabiliser la tension à Deido et Rue de la Joie.",
            "status": "SCHEDULED"
        },
        {
            "neighborhood": "Akwa",
            "title": "Maintenance Postes Sources & Cellules 15kV",
            "start_time": "2026-11-03 10:00:00",
            "end_time": "2026-11-03 14:00:00",
            "description": "Entretien des disjoncteurs du poste central Akwa. Coupure tournante ciblée.",
            "status": "SCHEDULED"
        },
        {
            "neighborhood": "Bonamoussadi",
            "title": "Délestage Tournant — Équilibrage Réseau Wouri",
            "start_time": "2026-10-31 14:00:00",
            "end_time": "2026-10-31 20:00:00",
            "description": "Délestage tournant de pointe suite à déficit de production sur le barrage de Song Loulou.",
            "status": "IN_PROGRESS"
        },
        {
            "neighborhood": "Ndokoti",
            "title": "Raccordement Nouvelle Ligne Industrielle Bassa",
            "start_time": "2026-11-04 07:30:00",
            "end_time": "2026-11-04 13:00:00",
            "description": "Travaux de raccordement et consignation des câbles souterrains Carrefour Ndokoti.",
            "status": "SCHEDULED"
        }
    ]

    count = 0
    for s in samples:
        # Check if already present to avoid duplication
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id FROM scheduled_outages
                WHERE neighborhood = %s AND title = %s AND start_time = %s;
            """, (s["neighborhood"], s["title"], s["start_time"]))
            if cur.fetchone():
                continue
        create_schedule(
            s["neighborhood"],
            s["title"],
            s["start_time"],
            s["end_time"],
            s["description"],
            s["status"]
        )
        count += 1

    correlate_all_outages_with_schedules()
    return count


def get_all_schedules(neighborhood=None, status_filter=None):
    """
    Retrieve all Eneo scheduled outages with optional filtering.
    """
    query = """
        SELECT s.*,
               COUNT(o.id) as linked_outages_count
        FROM scheduled_outages s
        LEFT JOIN outages o ON s.id = o.schedule_id
        WHERE 1=1
    """
    params = []

    if neighborhood:
        query += " AND LOWER(s.neighborhood) = LOWER(%s)"
        params.append(neighborhood.strip())

    if status_filter:
        query += " AND s.status = %s"
        params.append(status_filter)

    query += " GROUP BY s.id ORDER BY s.start_time DESC"

    with get_db_cursor() as cur:
        cur.execute(query, tuple(params))
        return cur.fetchall()


def delete_schedule(schedule_id):
    """
    Delete a scheduled outage slot and reset associated outages to UNPLANNED.
    """
    with get_db_cursor(commit=True) as cur:
        cur.execute("UPDATE outages SET outage_type = 'UNPLANNED', schedule_id = NULL WHERE schedule_id = %s;", (schedule_id,))
        cur.execute("DELETE FROM scheduled_outages WHERE id = %s;", (schedule_id,))
