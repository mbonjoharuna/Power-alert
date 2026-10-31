"""
AI Assistant service for Douala Power Alert.
Supports French (default) and English.
Uses external API if AI_API_KEY is set, otherwise falls back
to intelligent rule-based answers from live database context,
including Eneo scheduled rotas and critical infrastructure (hospitals, water stations) power status.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_API_URL = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "gpt-3.5-turbo")


def get_outage_context(cursor, lang="fr"):
    """Build a short text summary of current outages and critical facilities from the database in the given language."""
    cursor.execute("""
        SELECT o.neighborhood, o.location, o.status, o.start_time, o.estimated_restore,
               o.outage_type, o.affects_critical, s.title AS schedule_title
        FROM outages o
        LEFT JOIN scheduled_outages s ON o.schedule_id = s.id
        WHERE o.status IN ('PENDING', 'VERIFIED', 'RESTORED')
        ORDER BY o.created_at DESC
        LIMIT 30
    """)
    rows = cursor.fetchall()

    lines = []
    if rows:
        for r in rows:
            est = r["estimated_restore"]
            o_type = "Planifié (Eneo)" if r.get("outage_type") == "SCHEDULED" else "Panne imprévue"
            crit_note = " [IMPACTE INFRASTRUCTURE CRITIQUE]" if r.get("affects_critical") else ""
            if lang == "fr":
                est_str = est.strftime("%d/%m/%Y à %H:%M") if est else "Aucune estimation vérifiée disponible."
                status_fr = {"PENDING": "En attente", "VERIFIED": "Confirmé (Coupé)", "RESTORED": "Rétabli"}.get(r["status"], r["status"])
                lines.append(
                    f"- {r['neighborhood']} ({r['location']}) [{o_type}]{crit_note} : statut={status_fr}, "
                    f"début={r['start_time']}, rétablissement_estimé={est_str}"
                )
            else:
                o_type_en = "Planned (Eneo)" if r.get("outage_type") == "SCHEDULED" else "Unplanned"
                crit_note_en = " [CRITICAL INFRASTRUCTURE IMPACT]" if r.get("affects_critical") else ""
                est_str = est.strftime("%d %B %Y - %H:%M") if est else "No verified restoration estimate is currently available."
                lines.append(
                    f"- {r['neighborhood']} ({r['location']}) [{o_type_en}]{crit_note_en}: status={r['status']}, "
                    f"started={r['start_time']}, estimated_restore={est_str}"
                )

    # Telemetry for critical facilities
    try:
        cursor.execute("""
            SELECT name, facility_type, neighborhood, current_power_status, fuel_autonomy_hours
            FROM critical_facilities
            LIMIT 10
        """)
        facs = cursor.fetchall()
        if facs:
            lines.append("\nÉtat des infrastructures vitales surveillées :")
            for f in facs:
                st = f.get("current_power_status", "ON_GRID")
                lines.append(f"  * {f['name']} ({f['neighborhood']}) : statut={st}, autonomie_groupe={f.get('fuel_autonomy_hours')}h")
    except Exception:
        pass

    if not lines:
        if lang == "fr":
            return "Il n'y a actuellement aucun signalement de coupure dans le système."
        return "There are currently no reported outages in the system."

    header = "Données actuelles des coupures :\n" if lang == "fr" else "Current outage data:\n"
    return header + "\n".join(lines)


def get_historical_prediction(neighborhood, cursor, lang="fr"):
    """
    Empirical statistical analysis of load-shedding duration by neighborhood and day-of-week.
    Returns: '💡 Prédiction IA : Historiquement, les coupures à {Quartier} durent en moyenne {X}h avant rétablissement.'
    """
    if not neighborhood or not cursor:
        return None
    try:
        clean_n = neighborhood.lower().strip()
        day_map_fr = {
            "Monday": "le lundi", "Tuesday": "le mardi", "Wednesday": "le mercredi",
            "Thursday": "le jeudi", "Friday": "le vendredi", "Saturday": "le samedi",
            "Sunday": "le dimanche"
        }

        # Query empirical duration from restored outages or confirmed estimated restorations
        cursor.execute("""
            SELECT 
                AVG(CASE 
                    WHEN status = 'RESTORED' AND updated_at > start_time 
                    THEN TIMESTAMPDIFF(MINUTE, start_time, updated_at)
                    WHEN estimated_restore IS NOT NULL AND estimated_restore > start_time 
                    THEN TIMESTAMPDIFF(MINUTE, start_time, estimated_restore)
                    ELSE NULL 
                END) AS avg_mins,
                DAYNAME(start_time) AS day_of_week,
                COUNT(*) AS count_samples
            FROM outages
            WHERE LOWER(neighborhood) LIKE %s
              AND (status = 'RESTORED' OR estimated_restore IS NOT NULL)
            GROUP BY DAYNAME(start_time)
            ORDER BY count_samples DESC
            LIMIT 1
        """, (f"%{clean_n}%",))
        row = cursor.fetchone()

        if row and row.get("avg_mins"):
            hrs = round(float(row["avg_mins"]) / 60.0, 1)
            day_name = row.get("day_of_week") or "ce jour"
            day_fr = day_map_fr.get(day_name, f"le {day_name}")

            if lang == "fr":
                return f"💡 Prédiction IA : Historiquement, les coupures à {neighborhood.capitalize()} {day_fr} durent en moyenne {hrs}h avant rétablissement."
            return f"💡 AI Prediction: Historically, outages in {neighborhood.capitalize()} on {day_name}s average {hrs} hours before restoration."

        # General citywide average if neighborhood has low sample count
        cursor.execute("""
            SELECT AVG(CASE 
                WHEN status = 'RESTORED' AND updated_at > start_time 
                THEN TIMESTAMPDIFF(MINUTE, start_time, updated_at)
                WHEN estimated_restore IS NOT NULL AND estimated_restore > start_time 
                THEN TIMESTAMPDIFF(MINUTE, start_time, estimated_restore)
                ELSE NULL 
            END) AS city_avg
            FROM outages
        """)
        c_row = cursor.fetchone()
        if c_row and c_row.get("city_avg"):
            c_hrs = round(float(c_row["city_avg"]) / 60.0, 1)
            if lang == "fr":
                return f"💡 Prédiction IA : Historiquement à Douala, la durée moyenne constatée d'une coupure est de {c_hrs}h avant rétablissement."
            return f"💡 AI Prediction: Historically in Douala, the observed average outage duration is {c_hrs} hours before restoration."
    except Exception:
        pass
    return None


def ask_ai(question, cursor, lang="fr"):
    """
    Answer a user question about outages in Douala.
    Never invent restoration times.
    """
    q_lower = question.lower().strip()
    french_indicators = ["où", "ou", "quand", "coupure", "électricité", "electricite", "courant", "quartier", "bonjour", "faire", "revenir", "rétablissement", "retablissement", "hôpital", "hopital", "eau"]
    if any(w in q_lower for w in french_indicators):
        lang = "fr"

    context = get_outage_context(cursor, lang=lang)

    # If external API is configured, use it with prompt
    if AI_API_KEY:
        try:
            api_answer = _call_external_ai(question, context, lang)
            if api_answer:
                return api_answer
        except Exception:
            pass  # Fall back to rule-based

    # Rule-based fallback (always reliable)
    return _rule_based_answer(q_lower, context, cursor, lang)


def _rule_based_answer(question, context, cursor, lang="fr"):
    """Keyword matching for common questions with French and English support."""

    neighborhoods = [
        "bonamoussadi", "deido", "akwa", "bonanjo", "bali", "new bell",
        "bassa", "logbaba", "makepe", "kotto", "pk", "ndokoti", "yassa",
        "bonapriso", "bonaberi", "wouri", "douala"
    ]

    found_neighborhood = None
    for n in neighborhoods:
        if n in question:
            found_neighborhood = n
            break

    # 1. Critical Infrastructure, Hospitals, Clinics & Water Stations inquiries
    infra_kw = [
        "hôpital", "hopital", "hospital", "laquintinie", "général", "general",
        "camwater", "eau", "water", "dialyse", "dialysis", "sang", "blood",
        "clinique", "infrastructure", "urgences", "maternité", "maternite",
        "bonassama", "japoma", "bépanda", "bepanda"
    ]
    if any(w in question for w in infra_kw):
        try:
            # Check if a specific critical facility is queried
            query = "SELECT * FROM critical_facilities WHERE 1=1"
            params = []
            if "laquintinie" in question:
                query += " AND LOWER(name) LIKE '%laquintinie%'"
            elif "général" in question or "general" in question:
                query += " AND LOWER(name) LIKE '%général%'"
            elif "bonassama" in question:
                query += " AND LOWER(name) LIKE '%bonassama%'"
            elif "camwater" in question or "eau" in question or "water" in question or "japoma" in question:
                query += " AND (LOWER(name) LIKE '%camwater%' OR LOWER(name) LIKE '%eau%' OR facility_type = 'WATER_TREATMENT')"
            elif "dialyse" in question or "dialysis" in question:
                query += " AND facility_type = 'DIALYSIS'"
            elif "sang" in question or "blood" in question:
                query += " AND facility_type = 'BLOOD_BANK'"
            elif found_neighborhood:
                query += " AND LOWER(neighborhood) LIKE %s"
                params.append(f"%{found_neighborhood}%")

            cursor.execute(query + " LIMIT 5", tuple(params))
            fac_rows = cursor.fetchall()

            if fac_rows:
                lines = []
                for f in fac_rows:
                    st = f.get("current_power_status", "ON_GRID")
                    autonomy = f.get("fuel_autonomy_hours", 12.0)
                    gen_kva = f.get("generator_capacity_kva")
                    kva_str = f" ({gen_kva} kVA)" if gen_kva else ""
                    phone = f.get("contact_phone") or "Non spécifié"

                    if st == "ON_GRID":
                        st_fr = "🟢 Alimenté par le Réseau Eneo (Fonctionnement normal)"
                        st_en = "🟢 Powered by Eneo Grid (Normal operation)"
                    elif st == "BACKUP_GENERATOR":
                        st_fr = f"🟡 Sous tension par groupe électrogène{kva_str} — Autonomie restante estimée : {autonomy}h"
                        st_en = f"🟡 Running on Backup Generator{kva_str} — Estimated fuel remaining: {autonomy}h"
                    else:
                        st_fr = "🔴 ALERTE PANNE CRITIQUE TOTALE (Groupe hors-service ou carburant épuisé)"
                        st_en = "🔴 CRITICAL TOTAL BLACKOUT ALERT (Generator down or out of fuel)"

                    if lang == "fr":
                        lines.append(
                            f"🏥 **{f['name']}** ({f['neighborhood']}) :\n"
                            f"   • Alimentation : {st_fr}\n"
                            f"   • Contact urgence : {phone}\n"
                            f"   • Mission : {f.get('notes') or 'Établissement prioritaire'}"
                        )
                    else:
                        lines.append(
                            f"🏥 **{f['name']}** ({f['neighborhood']}):\n"
                            f"   • Power Status: {st_en}\n"
                            f"   • Emergency Contact: {phone}\n"
                            f"   • Details: {f.get('notes') or 'Priority vital infrastructure'}"
                        )

                header = "État de l'alimentation des infrastructures vitales à Douala :\n\n" if lang == "fr" else "Power status for Douala critical infrastructure:\n\n"
                return header + "\n\n".join(lines)
        except Exception:
            pass

    # 2. Which areas / Quelles zones
    which_areas_kw = [
        "which areas", "where", "current outages", "list outages", "areas currently",
        "quelles zones", "quels quartiers", "où y a-t-il", "ou y a t il", "liste des coupures",
        "qui n'a pas de courant", "coupures en cours", "quartiers touchés", "quartiers touches"
    ]
    if any(w in question for w in which_areas_kw):
        cursor.execute("""
            SELECT neighborhood, status, COUNT(*) as cnt
            FROM outages
            WHERE status IN ('PENDING', 'VERIFIED')
            GROUP BY neighborhood, status
            ORDER BY neighborhood
        """)
        rows = cursor.fetchall()
        if not rows:
            if lang == "fr":
                return "Il n'y a actuellement aucune coupure active signalée à Douala."
            return "There are currently no active outages reported in Douala."

        if lang == "fr":
            parts = []
            for r in rows:
                st = "Confirmé" if r["status"] == "VERIFIED" else "En attente"
                parts.append(f"{r['neighborhood']} ({st}, {r['cnt']} signalement(s))")
            return "Quartiers avec coupures signalées :\n• " + "\n• ".join(parts)
        else:
            parts = [f"{r['neighborhood']} ({r['status']}, {r['cnt']} report(s))" for r in rows]
            return "Areas with reported outages:\n• " + "\n• ".join(parts)

    # 3. Specific neighborhood lookup
    if found_neighborhood or "coupure à" in question or "coupure a" in question or "outage in" in question or "is there" in question:
        search = found_neighborhood or question
        cursor.execute("""
            SELECT neighborhood, location, status, start_time, estimated_restore, affects_critical
            FROM outages
            WHERE LOWER(neighborhood) LIKE %s
              AND status IN ('PENDING', 'VERIFIED', 'RESTORED')
            ORDER BY created_at DESC
            LIMIT 5
        """, (f"%{search}%",))
        rows = cursor.fetchall()
        if not rows:
            if lang == "fr":
                return "Aucun signalement de coupure trouvé pour ce secteur. Vous pouvez consulter la page Coupures ou en signaler une nouvelle."
            return "No outage reports found for that area. You can check the Outages page or report a new one."

        lines = []
        for r in rows:
            est = r["estimated_restore"]
            crit_badge = " [🚨 Zone Critique / Médicale]" if r.get("affects_critical") else ""
            if lang == "fr":
                st_fr = "Confirmé (Coupé)" if r["status"] == "VERIFIED" else ("Rétabli" if r["status"] == "RESTORED" else "En attente")
                est_str = est.strftime("%d/%m/%Y à %H:%M") if (est and r["status"] != "RESTORED") else "Aucune estimation vérifiée disponible."
                lines.append(
                    f"{r['neighborhood']} – {r['location']}{crit_badge} : {st_fr}. "
                    f"Début : {r['start_time']}. Estimation rétablissement : {est_str}"
                )
            else:
                crit_badge_en = " [🚨 Critical Medical Zone]" if r.get("affects_critical") else ""
                est_str = est.strftime("%d %B %Y - %H:%M") if (est and r["status"] != "RESTORED") else "No verified restoration estimate is currently available."
                lines.append(
                    f"{r['neighborhood']} – {r['location']}{crit_badge_en}: {r['status']}. "
                    f"Started: {r['start_time']}. Estimate: {est_str}"
                )
        ans = "\n".join(lines)
        prediction = get_historical_prediction(search, cursor, lang=lang)
        if prediction:
            ans += "\n\n" + prediction
        return ans

    # 4. Scheduled Eneo Maintenance & Rotas inquiries
    sched_kw = ["planifié", "planifie", "programmé", "programme", "calendrier", "schedule", "maintenance", "travaux", "rotas", "eneo"]
    if any(w in question for w in sched_kw):
        query = """
            SELECT neighborhood, title, start_time, end_time, description, status
            FROM scheduled_outages
            WHERE status IN ('SCHEDULED', 'IN_PROGRESS')
        """
        params = []
        if found_neighborhood:
            query += " AND LOWER(neighborhood) LIKE %s"
            params.append(f"%{found_neighborhood.lower()}%")
        query += " ORDER BY start_time ASC LIMIT 5"

        cursor.execute(query, tuple(params))
        s_rows = cursor.fetchall()
        if s_rows:
            if lang == "fr":
                lines = [
                    f"⚡ {r['neighborhood']} : {r['title']} (du {r['start_time']} au {r['end_time']})\n   Motif : {r['description'] or 'Entretien du réseau Eneo'}"
                    for r in s_rows
                ]
                return "Calendrier officiel des délestages / maintenances Eneo en cours ou à venir :\n\n" + "\n\n".join(lines)
            else:
                lines = [
                    f"⚡ {r['neighborhood']}: {r['title']} (from {r['start_time']} to {r['end_time']})\n   Details: {r['description'] or 'Eneo grid maintenance'}"
                    for r in s_rows
                ]
                return "Official Eneo scheduled maintenance / load-shedding rotas:\n\n" + "\n\n".join(lines)
        elif found_neighborhood:
            if lang == "fr":
                return f"Aucun délestage ou maintenance Eneo n'est actuellement programmé pour {found_neighborhood.capitalize()}. Les coupures signalées dans cette zone sont donc répertoriées comme des pannes techniques imprévues."
            return f"No planned Eneo load-shedding is currently scheduled for {found_neighborhood.capitalize()}. Any reported outages are classified as unplanned technical grid failures."

    # 5. Restoration time inquiries
    time_kw = ["when", "return", "restore", "restoration", "expected", "quand", "heure", "revenir", "rétablissement", "retablissement", "fin"]
    if any(w in question for w in time_kw):
        query = """
            SELECT neighborhood, estimated_restore
            FROM outages
            WHERE status IN ('PENDING', 'VERIFIED')
              AND estimated_restore IS NOT NULL
        """
        params = []
        if found_neighborhood:
            query += " AND LOWER(neighborhood) LIKE %s"
            params.append(f"%{found_neighborhood}%")

        query += " ORDER BY estimated_restore ASC LIMIT 5"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        prediction = get_historical_prediction(found_neighborhood or "Douala", cursor, lang=lang)

        if not rows:
            base_empty = (
                "Aucune estimation vérifiée de rétablissement n'est actuellement disponible."
                if lang == "fr"
                else "No verified restoration estimate is currently available."
            )
            if prediction:
                base_empty += "\n\n" + prediction
            return base_empty

        if lang == "fr":
            lines = [f"{r['neighborhood']} : {r['estimated_restore'].strftime('%d/%m/%Y à %H:%M')}" for r in rows]
            ans = "Heures estimées de rétablissement (non officielles) :\n• " + "\n• ".join(lines)
        else:
            lines = [f"{r['neighborhood']}: {r['estimated_restore'].strftime('%d %B %Y - %H:%M')}" for r in rows]
            ans = "Estimated restoration times (not an official guarantee):\n• " + "\n• ".join(lines)
        if prediction:
            ans += "\n\n" + prediction
        return ans

    # 6. Tips & Safety
    safety_kw = ["what should i do", "advice", "during a power", "tips", "safety", "que faire", "conseils", "sécurité", "securite", "appareil", "délestage", "delestage"]
    if any(w in question for w in safety_kw):
        if lang == "fr":
            return (
                "Pendant une coupure d'électricité à Douala :\n"
                "• Restez calme et débranchez les appareils sensibles (réfrigérateur, TV, ordinateurs) pour éviter les surtensions au retour.\n"
                "• Utilisez des lampes rechargeables ou téléphones plutôt que des bougies sans surveillance.\n"
                "• Gardez le réfrigérateur fermé afin de préserver vos aliments frais.\n"
                "• Consultez Douala Power Alert pour suivre l'état de votre quartier et les estimations.\n"
                "• Signalez la coupure si elle n'est pas encore répertoriée pour informer la communauté.\n"
                "• Confirmez quand le courant est rétabli dès son retour."
            )
        return (
            "During a power cut in Douala:\n"
            "• Stay calm and unplug sensitive devices (fridge, TV, computer) to protect against voltage spikes.\n"
            "• Use battery lamps or phones — avoid unattended candles.\n"
            "• Keep your fridge closed to preserve food freshness.\n"
            "• Check Douala Power Alert for neighborhood status and restoration estimates.\n"
            "• Report the outage if not yet listed to inform the community.\n"
            "• Confirm when power returns so everyone stays informed."
        )

    # Default overview
    if lang == "fr":
        return (
            "Je peux vous renseigner sur l'état des coupures d'électricité et des infrastructures vitales à Douala.\n\n"
            "Exemples de questions :\n"
            "• L'Hôpital Laquintinie a-t-il du courant ?\n"
            "• Y a-t-il une coupure à Bonamoussadi ?\n"
            "• Quel est l'état de la station d'eau Camwater de Japoma ?\n"
            "• Quand le courant va-t-il revenir ?\n\n"
            f"{context}"
        )
    return (
        "I can help with questions about current outages and critical infrastructure in Douala.\n\n"
        "Try asking:\n"
        "• Does Hospital Laquintinie have power?\n"
        "• Is there an outage in Bonamoussadi?\n"
        "• What is the status of Camwater drinking water plant?\n"
        "• When is electricity expected to return?\n\n"
        f"{context}"
    )


def _call_external_ai(question, context, lang="fr"):
    """Call an OpenAI-compatible chat API."""
    lang_instruction = "Answer in French by default." if lang == "fr" else "Answer in English."
    system_prompt = (
        f"You are a helpful assistant for Douala Power Alert, a community outage map "
        f"for Douala, Cameroon. {lang_instruction} Answer only based on the provided outage and critical facility data. "
        f"NEVER invent restoration times. If no verified estimate exists, state that clearly: "
        f"'No verified restoration estimate is currently available.' or 'Aucune estimation vérifiée n\\'est actuellement disponible.' "
        f"Be concise and friendly."
    )
    user_content = f"Outage data:\n{context}\n\nUser question: {question}"

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }

    response = requests.post(AI_API_URL, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()
