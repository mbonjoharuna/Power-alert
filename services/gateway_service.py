"""
Gateway Service for Douala Power Alert.
Handles inbound SMS & WhatsApp incident reporting, command parsing,
duplicate detection, critical infrastructure & Eneo schedule correlation,
automated localized auto-replies, and gateway message logging.
"""

import re
from datetime import datetime, timedelta
from database import get_db_cursor
from werkzeug.security import generate_password_hash
from services.schedule_service import find_matching_schedule
from services.facility_service import (
    check_outage_critical_impact,
    update_facility_power_status
)
from services.notification_service import (
    create_neighborhood_notification,
    create_critical_infrastructure_alert
)

# Reference center coordinates for Douala neighborhoods
DOUALA_COORDINATES = {
    "bonamoussadi": (4.0850, 9.7400),
    "deido": (4.0600, 9.7200),
    "dakar": (4.0320, 9.7150),
    "akwa": (4.0500, 9.7000),
    "akwa nord": (4.0650, 9.7100),
    "bonanjo": (4.0400, 9.6900),
    "bali": (4.0450, 9.7050),
    "new bell": (4.0300, 9.7100),
    "bassa": (4.0200, 9.7500),
    "logbaba": (4.0100, 9.7600),
    "makepe": (4.0900, 9.7300),
    "kotto": (4.1000, 9.7500),
    "ndokoti": (4.0550, 9.7450),
    "yassa": (4.0000, 9.7800),
    "bonapriso": (4.0350, 9.6950),
    "bonaberi": (4.0800, 9.6700),
    "bonassama": (4.0750, 9.6650),
    "bépanda": (4.0650, 9.7350),
    "bepanda": (4.0650, 9.7350),
    "village": (4.0150, 9.7700),
    "cité des palmiers": (4.0680, 9.7550),
    "cite des palmiers": (4.0680, 9.7550),
    "ndogpassi": (4.0050, 9.7650),
    "nyalla": (4.0180, 9.7750),
    "logbesou": (4.0950, 9.7700),
    "japoma": (3.9950, 9.8100),
    "bilongue": (4.0450, 9.7350),
    "pk 8": (4.0700, 9.7800),
    "pk 10": (4.0650, 9.8000),
    "pk 12": (4.0600, 9.8200),
    "pk 14": (4.0550, 9.8400),
    "pk 17": (4.0500, 9.8700),
}


def normalize_phone(phone_str: str) -> str:
    """
    Standardize Cameroon phone numbers into E.164 format (+2376XXXXXXXX or +2372XXXXXXXX).
    Strips 'whatsapp:', spaces, hyphens, and local prefixes.
    """
    if not phone_str:
        return "+237000000000"

    cleaned = str(phone_str).strip()
    if cleaned.lower().startswith("whatsapp:"):
        cleaned = cleaned[9:].strip()

    # Keep only digits and '+'
    cleaned = re.sub(r"[^\d+]", "", cleaned)

    if cleaned.startswith("+237"):
        return cleaned
    if cleaned.startswith("00237"):
        return "+" + cleaned[2:]
    if cleaned.startswith("237") and len(cleaned) == 12:
        return "+" + cleaned
    if len(cleaned) == 9 and (cleaned.startswith("6") or cleaned.startswith("2")):
        return "+237" + cleaned

    # Fallback with '+' if digits present
    digits = re.sub(r"\D", "", cleaned)
    if digits:
        if digits.startswith("237"):
            return "+" + digits
        return "+237" + digits
    return "+237000000000"


def get_or_create_gateway_user(phone: str, neighborhood: str = "Douala") -> dict:
    """
    Retrieve existing registered user by phone or create a lightweight
    SMS citizen profile so outages are bound to a valid foreign key.
    """
    normalized = normalize_phone(phone)
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id, full_name, email, phone, neighborhood FROM users WHERE phone = %s", (normalized,))
            user = cur.fetchone()
            if user:
                return user

            # Auto-create lightweight citizen profile
            clean_digits = re.sub(r"\D", "", normalized)
            suffix = clean_digits[-4:] if len(clean_digits) >= 4 else "0000"
            full_name = f"Citoyen SMS ({suffix})"
            email = f"sms_{clean_digits}@power-alert.cm"
            dummy_hash = generate_password_hash(f"sms_{clean_digits}_auth")
            target_neighborhood = neighborhood if neighborhood and neighborhood != "Douala" else "Douala"

            cur.execute(
                """INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                   VALUES (%s, %s, %s, %s, %s)""",
                (full_name, email, normalized, dummy_hash, target_neighborhood)
            )
            new_id = cur.lastrowid
            return {
                "id": new_id,
                "full_name": full_name,
                "email": email,
                "phone": normalized,
                "neighborhood": target_neighborhood
            }
    except Exception:
        # Fallback to default gateway user
        try:
            with get_db_cursor() as cur:
                cur.execute("SELECT id, full_name, email, phone, neighborhood FROM users WHERE phone = %s", ("+237000000000",))
                default_user = cur.fetchone()
                if default_user:
                    return default_user
        except Exception:
            pass
        return {"id": 1, "full_name": "Passerelle SMS", "phone": "+237000000000", "neighborhood": "Douala"}


def extract_neighborhood_and_location(text: str) -> tuple:
    """
    Search text for known Douala neighborhoods and separate neighborhood from specific location/landmark.
    Returns (neighborhood_str, location_str).
    """
    lower_text = text.lower()

    # Sort neighborhood keys by length descending to match multi-word names first (e.g., "cité des palmiers" before "palmiers")
    sorted_zones = sorted(DOUALA_COORDINATES.keys(), key=lambda z: len(z), reverse=True)

    matched_zone = None
    for zone in sorted_zones:
        # Match zone as whole word or phrase
        pattern = r"\b" + re.escape(zone) + r"\b"
        if re.search(pattern, lower_text):
            matched_zone = zone.title()
            # Remove the neighborhood from the text to isolate location details
            location_candidate = re.sub(pattern, "", lower_text, count=1).strip()
            # Clean common blackout phrasing if present in location
            location_candidate = re.sub(
                r"\b(plus de courant|pas de courant|courant coup[eé]|coupure( de courant)?|panne( de courant)?|blackout|no power|delestage|délestage)\b",
                "",
                location_candidate
            ).strip()
            # Clean common joining prepositions
            location_candidate = re.sub(r"^(vers|au|à|a|près de|pres de|carrefour|rue|derrière|derriere|face)\s+", "", location_candidate).strip()
            if not location_candidate or len(location_candidate) < 2:
                location_candidate = f"Secteur {matched_zone}"
            else:
                location_candidate = location_candidate.title()
            return matched_zone, location_candidate

    # If not in dictionary, check if the first token after command looks like a neighborhood
    tokens = text.strip().split()
    if tokens:
        zone_guess = tokens[0].title()
        loc_guess = " ".join(tokens[1:]).strip().title() if len(tokens) > 1 else f"Secteur {zone_guess}"
        return zone_guess, loc_guess

    return "Douala", "Centre-ville"


def parse_inbound_message(raw_text: str) -> dict:
    """
    Parse citizen text commands for SMS/WhatsApp gateway.
    Commands supported:
    - COUPURE / OUTAGE / PANNE <Quartier> [Lieu]
    - ETAT / STATUS [Quartier]
    - CONFIRMER / CONFIRM <ID>
    - RETABLI / RESTORE <ID>
    - AIDE / HELP
    - Natural language fallback ("plus de courant à Deido vers la pharmacie")
    """
    if not raw_text:
        return {"command": "HELP", "raw": ""}

    text = raw_text.strip()
    tokens = text.split()
    if not tokens:
        return {"command": "HELP", "raw": ""}

    first_word = tokens[0].upper()
    rest = " ".join(tokens[1:]).strip()

    # 1. HELP / AIDE
    if first_word in ("AIDE", "HELP", "INFOS", "INFO", "COMMANDES", "MENU"):
        return {"command": "HELP", "raw": text}

    # 2. STATUS / ETAT
    if first_word in ("ETAT", "ÉTAT", "STATUS", "STATUT", "CHECK", "ENCOURS"):
        neighborhood = None
        if rest:
            neighborhood, _ = extract_neighborhood_and_location(rest)
        return {"command": "STATUS", "neighborhood": neighborhood, "raw": text}

    # 3. CONFIRM
    if first_word in ("CONFIRM", "CONFIRMER", "CONFIRME", "OUI", "STILL_OFF"):
        outage_id = None
        # Find integer in rest or first_word
        id_match = re.search(r"\b(\d+)\b", rest) or re.search(r"\b(\d+)\b", first_word)
        if id_match:
            outage_id = int(id_match.group(1))
        return {"command": "CONFIRM", "outage_id": outage_id, "raw": text}

    # 4. RESTORE
    if first_word in ("RETABLI", "RÉTABLI", "RESTORE", "RESTORED", "LUMIERE", "LUMIÈRE", "COURANT_REVENU"):
        outage_id = None
        id_match = re.search(r"\b(\d+)\b", rest) or re.search(r"\b(\d+)\b", first_word)
        if id_match:
            outage_id = int(id_match.group(1))
        return {"command": "RESTORE", "outage_id": outage_id, "raw": text}

    # 5. COUPURE / OUTAGE / PANNE / BLACKOUT
    if first_word in ("COUPURE", "OUTAGE", "PANNE", "BLACKOUT", "COUPÉ", "COUPE", "DELESTAGE", "DÉLESTAGE"):
        neighborhood, location = extract_neighborhood_and_location(rest)
        return {
            "command": "COUPURE",
            "neighborhood": neighborhood,
            "location": location,
            "raw": text
        }

    # 6. Natural Language Fallback
    lower_text = text.lower()
    blackout_triggers = ["courant coupé", "courant coupe", "plus de courant", "pas de courant",
                         "panne de courant", "blackout", "no power", "power cut", "délestage", "delestage"]
    if any(trigger in lower_text for trigger in blackout_triggers):
        neighborhood, location = extract_neighborhood_and_location(text)
        return {
            "command": "COUPURE",
            "neighborhood": neighborhood,
            "location": location,
            "raw": text
        }

    # Check if text simply starts with a known neighborhood name (e.g. "Deido Rue Joss pas de lumière")
    for zone in DOUALA_COORDINATES.keys():
        if lower_text.startswith(zone):
            neighborhood, location = extract_neighborhood_and_location(text)
            return {
                "command": "COUPURE",
                "neighborhood": neighborhood,
                "location": location,
                "raw": text
            }

    return {"command": "UNKNOWN", "raw": text}


def get_neighborhood_coordinates(neighborhood: str) -> tuple:
    """Return default (lat, lng) for neighborhood center or default Douala center."""
    if not neighborhood:
        return (4.0500, 9.7000)
    key = neighborhood.strip().lower()
    return DOUALA_COORDINATES.get(key, (4.0500, 9.7000))


def handle_inbound_message(sender_phone: str, raw_text: str, channel: str = "SMS") -> dict:
    """
    Main gateway orchestrator:
    1. Normalizes sender phone.
    2. Parses command and intent.
    3. Executes database mutation (outage creation, duplicate check, or confirmation).
    4. Triggers critical facility impact and Eneo schedule correlation.
    5. Formulates concise, informative SMS/WhatsApp auto-reply.
    6. Logs interaction in gateway_messages table.
    """
    channel_clean = "WHATSAPP" if str(channel).upper() == "WHATSAPP" else "SMS"
    normalized_phone = normalize_phone(sender_phone)
    parsed = parse_inbound_message(raw_text)
    cmd = parsed.get("command", "UNKNOWN")

    response_text = ""
    outage_id = None
    target_neighborhood = parsed.get("neighborhood")
    target_location = parsed.get("location")
    status = "SUCCESS"

    try:
        # Command: HELP
        if cmd == "HELP":
            response_text = (
                "📱 DOUALA POWER ALERT:\n"
                "- Signaler: COUPURE <Quartier> <Lieu>\n"
                "- Statut: ETAT <Quartier>\n"
                "- Confirmer: CONFIRMER <ID>\n"
                "- Rétablissement: RETABLI <ID>\n"
                "- Urgence Eneo: 8010 | Hôpitaux: 119"
            )

        # Command: STATUS / ETAT
        elif cmd == "STATUS":
            if target_neighborhood:
                with get_db_cursor() as cur:
                    cur.execute("""
                        SELECT id, location, start_time, status, outage_type, affects_critical
                        FROM outages
                        WHERE LOWER(neighborhood) = %s AND status IN ('PENDING', 'VERIFIED')
                        ORDER BY created_at DESC
                        LIMIT 3
                    """, (target_neighborhood.lower(),))
                    active_outages = cur.fetchall()

                if active_outages:
                    outage_summaries = []
                    for o in active_outages:
                        crit_flag = "🚨" if o.get("affects_critical") else "⚡"
                        outage_summaries.append(f"#{o['id']} ({o['location']}) [{o['status']}] {crit_flag}")
                    response_text = f"⚡ {len(active_outages)} coupure(s) active(s) à {target_neighborhood}: " + ", ".join(outage_summaries) + ". Info: power-alert.cm"
                else:
                    response_text = f"🟢 Aucune coupure active signalée à {target_neighborhood} en ce moment. Réseau stable !"
            else:
                with get_db_cursor() as cur:
                    cur.execute("""
                        SELECT neighborhood, COUNT(*) as c
                        FROM outages
                        WHERE status IN ('PENDING', 'VERIFIED')
                        GROUP BY neighborhood
                        ORDER BY c DESC
                        LIMIT 4
                    """)
                    top_zones = cur.fetchall()

                if top_zones:
                    zones_str = ", ".join([f"{z['neighborhood']} ({z['c']})" for z in top_zones])
                    response_text = f"📊 Coupures en cours à Douala: {zones_str}. Pour un quartier précis: envoyez ETAT <Quartier>."
                else:
                    response_text = "🟢 Réseau électrique stable à Douala. Aucun délestage majeur actif signalé."

        # Command: CONFIRM
        elif cmd == "CONFIRM":
            outage_id = parsed.get("outage_id")
            if not outage_id:
                response_text = "⚠️ Format incorrect. Envoyez: CONFIRMER <ID> (ex: CONFIRMER 12)."
                status = "FAILED"
            else:
                with get_db_cursor(commit=True) as cur:
                    cur.execute("SELECT id, neighborhood, location, status FROM outages WHERE id = %s", (outage_id,))
                    target_outage = cur.fetchone()
                    if not target_outage:
                        response_text = f"❌ Coupure #{outage_id} introuvable."
                        status = "FAILED"
                    elif target_outage["status"] == "RESTORED":
                        response_text = f"ℹ️ L'alerte #{outage_id} ({target_outage['neighborhood']}) est déjà marquée comme rétablie."
                    else:
                        user = get_or_create_gateway_user(normalized_phone, target_outage["neighborhood"])
                        # Record confirmation
                        cur.execute(
                            """INSERT INTO confirmations (outage_id, user_id, confirmation)
                               VALUES (%s, %s, 'STILL_OFF')
                               ON DUPLICATE KEY UPDATE confirmation = 'STILL_OFF'""",
                            (outage_id, user["id"])
                        )
                        target_neighborhood = target_outage["neighborhood"]
                        response_text = f"👍 Confirmation enregistrée pour la coupure #{outage_id} ({target_outage['neighborhood']}). Merci !"

        # Command: RESTORE
        elif cmd == "RESTORE":
            outage_id = parsed.get("outage_id")
            if not outage_id:
                response_text = "⚠️ Format incorrect. Envoyez: RETABLI <ID> (ex: RETABLI 12)."
                status = "FAILED"
            else:
                with get_db_cursor(commit=True) as cur:
                    cur.execute("SELECT id, neighborhood, location, status FROM outages WHERE id = %s", (outage_id,))
                    target_outage = cur.fetchone()
                    if not target_outage:
                        response_text = f"❌ Coupure #{outage_id} introuvable."
                        status = "FAILED"
                    else:
                        user = get_or_create_gateway_user(normalized_phone, target_outage["neighborhood"])
                        cur.execute(
                            """INSERT INTO confirmations (outage_id, user_id, confirmation)
                               VALUES (%s, %s, 'RESTORED')
                               ON DUPLICATE KEY UPDATE confirmation = 'RESTORED'""",
                            (outage_id, user["id"])
                        )
                        target_neighborhood = target_outage["neighborhood"]
                        response_text = f"💡 Rétablissement noté pour l'alerte #{outage_id} ({target_outage['neighborhood']}). Merci de votre civisme !"

        # Command: COUPURE / REPORT
        elif cmd == "COUPURE":
            neighborhood = target_neighborhood or "Douala"
            location = target_location or f"Secteur {neighborhood}"
            user = get_or_create_gateway_user(normalized_phone, neighborhood)

            lat, lng = get_neighborhood_coordinates(neighborhood)
            now = datetime.now()

            # 1. Duplicate check: Active outage in same neighborhood reported recently (< 4 hours)
            with get_db_cursor() as cur:
                cur.execute("""
                    SELECT id, neighborhood, location, status, created_at
                    FROM outages
                    WHERE LOWER(neighborhood) = %s
                      AND status IN ('PENDING', 'VERIFIED')
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (neighborhood.lower(), now - timedelta(hours=4)))
                existing_duplicate = cur.fetchone()

            if existing_duplicate:
                outage_id = existing_duplicate["id"]
                # Add confirmation to existing outage
                with get_db_cursor(commit=True) as cur:
                    cur.execute(
                        """INSERT INTO confirmations (outage_id, user_id, confirmation)
                           VALUES (%s, %s, 'STILL_OFF')
                           ON DUPLICATE KEY UPDATE confirmation = 'STILL_OFF'""",
                        (outage_id, user["id"])
                    )
                response_text = (
                    f"ℹ️ Coupure déjà active à {existing_duplicate['neighborhood']} "
                    f"({existing_duplicate['location']}, ID #{outage_id}). "
                    f"Votre confirmation (+1) a été ajoutée ! Suivi: power-alert.cm"
                )
            else:
                # 2. Check Eneo scheduled maintenance correlation
                matched_sched = find_matching_schedule(neighborhood, now)
                outage_type = "SCHEDULED" if matched_sched else "UNPLANNED"
                schedule_id = matched_sched["id"] if matched_sched else None
                est_restore = matched_sched["end_time"] if matched_sched else None

                # 3. Check Critical Infrastructure impact
                impacted_facs, is_critical = check_outage_critical_impact(neighborhood, lat=lat, lng=lng)

                desc = f"Signalé par {channel_clean} ({normalized_phone})"
                with get_db_cursor(commit=True) as cur:
                    cur.execute("""
                        INSERT INTO outages
                        (user_id, neighborhood, location, description, start_time, estimated_restore,
                         status, latitude, longitude, outage_type, schedule_id, affects_critical, reported_via)
                        VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s)
                    """, (
                        user["id"], neighborhood, location, desc, now, est_restore,
                        lat, lng, outage_type, schedule_id, is_critical, channel_clean
                    ))
                    outage_id = cur.lastrowid

                # Update critical facilities power status if impacted
                if is_critical and impacted_facs:
                    for fac in impacted_facs:
                        new_status = "BACKUP_GENERATOR" if fac.get("has_backup_generator") else "CRITICAL_BLACKOUT"
                        update_facility_power_status(fac["id"], new_status)
                        create_critical_infrastructure_alert(fac, outage_id, location=location)

                # Broadcast neighborhood notification
                create_neighborhood_notification(
                    neighborhood=neighborhood,
                    outage_id=outage_id,
                    title="Coupure signalée par SMS/WhatsApp",
                    message=f"Nouvelle alerte #{outage_id} à {neighborhood} ({location}) reçue via passerelle {channel_clean}.",
                    notif_type="OUTAGE_NEW",
                    exclude_user_id=user["id"]
                )

                # Compose responsive SMS reply
                if is_critical and impacted_facs:
                    fac_name = impacted_facs[0]["name"]
                    response_text = (
                        f"🚨 Signalement #{outage_id} enregistré à {neighborhood} ({location}). "
                        f"ALERTE: {fac_name} impacté(e) et basculé(e) sur secours. Merci !"
                    )
                elif matched_sched:
                    response_text = (
                        f"⚡ Signalement #{outage_id} enregistré à {neighborhood}. "
                        f"NOTA: Travaux Eneo planifiés sur ce secteur ({matched_sched['title']}). Merci !"
                    )
                else:
                    response_text = (
                        f"✅ Signalement #{outage_id} enregistré à {neighborhood} ({location}). "
                        f"Statut: EN VÉRIFICATION. Merci de votre vigilance civique !"
                    )

        # Command: UNKNOWN
        else:
            status = "FAILED"
            response_text = (
                "❓ Commande non reconnue. "
                "Envoyez 'COUPURE <Quartier> <Lieu>' (ex: COUPURE Deido Rue Joss) "
                "ou envoyez AIDE pour le guide."
            )

    except Exception as e:
        status = "FAILED"
        response_text = "⚠️ Service momentanément indisponible. Réessayez ou appelez le 8010 (Eneo)."
        print(f"Error handling gateway message: {e}")

    # Log in gateway_messages table
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO gateway_messages
                (channel, sender_phone, raw_message, parsed_command, neighborhood, location, outage_id, response_message, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                channel_clean, normalized_phone, raw_text, cmd,
                target_neighborhood, target_location, outage_id, response_text, status
            ))
            msg_id = cur.lastrowid
    except Exception as log_err:
        msg_id = None
        print(f"Warning: Failed to log gateway message: {log_err}")

    return {
        "message_id": msg_id,
        "channel": channel_clean,
        "sender_phone": normalized_phone,
        "command": cmd,
        "neighborhood": target_neighborhood,
        "location": target_location,
        "outage_id": outage_id,
        "response": response_text,
        "status": status
    }


def get_gateway_logs(limit: int = 50, channel: str = None) -> list:
    """Retrieve recent gateway messages for admin dashboard."""
    try:
        with get_db_cursor() as cur:
            sql = """
                SELECT gm.*, o.status AS outage_status, o.outage_type
                FROM gateway_messages gm
                LEFT JOIN outages o ON gm.outage_id = o.id
            """
            params = []
            if channel:
                sql += " WHERE gm.channel = %s"
                params.append(channel.upper())
            sql += " ORDER BY gm.created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    except Exception as e:
        print(f"Error fetching gateway logs: {e}")
        return []


def get_gateway_kpis() -> dict:
    """Compute gateway performance and telemetry statistics for admin."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM gateway_messages")
            total = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) AS sms_total FROM gateway_messages WHERE channel = 'SMS'")
            sms_total = cur.fetchone()["sms_total"]

            cur.execute("SELECT COUNT(*) AS wa_total FROM gateway_messages WHERE channel = 'WHATSAPP'")
            wa_total = cur.fetchone()["wa_total"]

            cur.execute("SELECT COUNT(*) AS outages_created FROM gateway_messages WHERE outage_id IS NOT NULL")
            outages_created = cur.fetchone()["outages_created"]

            cur.execute("SELECT COUNT(*) AS success_total FROM gateway_messages WHERE status = 'SUCCESS'")
            success_total = cur.fetchone()["success_total"]

            success_rate = round((success_total / total * 100), 1) if total > 0 else 100.0

            return {
                "total_messages": total,
                "sms_count": sms_total,
                "whatsapp_count": wa_total,
                "outages_created": outages_created,
                "success_rate": success_rate
            }
    except Exception as e:
        print(f"Error calculating gateway KPIs: {e}")
        return {
            "total_messages": 0,
            "sms_count": 0,
            "whatsapp_count": 0,
            "outages_created": 0,
            "success_rate": 100.0
        }
