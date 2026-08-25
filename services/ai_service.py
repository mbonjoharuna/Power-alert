"""
AI Assistant service for Douala Power Alert.
Supports French (default) and English.
Uses external API if AI_API_KEY is set, otherwise falls back
to intelligent rule-based answers from live database context.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_API_URL = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "gpt-3.5-turbo")


def get_outage_context(cursor, lang="fr"):
    """Build a short text summary of current outages from the database in the given language."""
    cursor.execute("""
        SELECT neighborhood, location, status, start_time, estimated_restore
        FROM outages
        WHERE status IN ('PENDING', 'VERIFIED', 'RESTORED')
        ORDER BY created_at DESC
        LIMIT 30
    """)
    rows = cursor.fetchall()

    if not rows:
        if lang == "fr":
            return "Il n'y a actuellement aucun signalement de coupure dans le système."
        return "There are currently no reported outages in the system."

    lines = []
    for r in rows:
        est = r["estimated_restore"]
        if lang == "fr":
            est_str = est.strftime("%d/%m/%Y à %H:%M") if est else "Aucune estimation vérifiée disponible."
            status_fr = {"PENDING": "En attente", "VERIFIED": "Confirmé (Coupé)", "RESTORED": "Rétabli"}.get(r["status"], r["status"])
            lines.append(
                f"- {r['neighborhood']} ({r['location']}) : statut={status_fr}, "
                f"début={r['start_time']}, rétablissement_estimé={est_str}"
            )
        else:
            est_str = est.strftime("%d %B %Y - %H:%M") if est else "No verified restoration estimate is currently available."
            lines.append(
                f"- {r['neighborhood']} ({r['location']}): status={r['status']}, "
                f"started={r['start_time']}, estimated_restore={est_str}"
            )
            
    header = "Données actuelles des coupures :\n" if lang == "fr" else "Current outage data:\n"
    return header + "\n".join(lines)


def ask_ai(question, cursor, lang="fr"):
    """
    Answer a user question about outages in Douala.
    Never invent restoration times.
    """
    q_lower = question.lower().strip()
    french_indicators = ["où", "ou", "quand", "coupure", "électricité", "electricite", "courant", "quartier", "bonjour", "faire", "revenir", "rétablissement", "retablissement"]
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

    # 1. Which areas / Quelles zones
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

    # 2. Specific neighborhood lookup
    if found_neighborhood or "coupure à" in question or "coupure a" in question or "outage in" in question or "is there" in question:
        search = found_neighborhood or question
        cursor.execute("""
            SELECT neighborhood, location, status, start_time, estimated_restore
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
            if lang == "fr":
                st_fr = "Confirmé (Coupé)" if r["status"] == "VERIFIED" else ("Rétabli" if r["status"] == "RESTORED" else "En attente")
                est_str = est.strftime("%d/%m/%Y à %H:%M") if (est and r["status"] != "RESTORED") else "Aucune estimation vérifiée disponible."
                lines.append(
                    f"{r['neighborhood']} – {r['location']} : {st_fr}. "
                    f"Début : {r['start_time']}. Estimation rétablissement : {est_str}"
                )
            else:
                est_str = est.strftime("%d %B %Y - %H:%M") if (est and r["status"] != "RESTORED") else "No verified restoration estimate is currently available."
                lines.append(
                    f"{r['neighborhood']} – {r['location']}: {r['status']}. "
                    f"Started: {r['start_time']}. Estimate: {est_str}"
                )
        return "\n".join(lines)

    # 3. Restoration time inquiries
    time_kw = ["when", "return", "restore", "restoration", "expected", "quand", "heure", "revenir", "rétablissement", "retablissement", "fin"]
    if any(w in question for w in time_kw):
        cursor.execute("""
            SELECT neighborhood, estimated_restore, status
            FROM outages
            WHERE status = 'VERIFIED' AND estimated_restore IS NOT NULL
            ORDER BY estimated_restore
            LIMIT 10
        """)
        rows = cursor.fetchall()
        if not rows:
            if lang == "fr":
                return "Aucune estimation vérifiée de rétablissement n'est actuellement disponible."
            return "No verified restoration estimate is currently available."

        if lang == "fr":
            lines = [f"{r['neighborhood']} : {r['estimated_restore'].strftime('%d/%m/%Y à %H:%M')}" for r in rows]
            return "Heures estimées de rétablissement (non officielles) :\n• " + "\n• ".join(lines)
        else:
            lines = [f"{r['neighborhood']}: {r['estimated_restore'].strftime('%d %B %Y - %H:%M')}" for r in rows]
            return "Estimated restoration times (not an official guarantee):\n• " + "\n• ".join(lines)

    # 4. Tips & Safety
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
            "Je peux vous renseigner sur l'état des coupures d'électricité à Douala.\n\n"
            "Exemples de questions :\n"
            "• Y a-t-il une coupure à Bonamoussadi ?\n"
            "• Quels quartiers ont des coupures actuellement ?\n"
            "• Quand le courant va-t-il revenir ?\n"
            "• Que faire en cas de coupure de courant ?\n\n"
            f"{context}"
        )
    return (
        "I can help with questions about current outages in Douala.\n\n"
        "Try asking:\n"
        "• Is there an outage in Bonamoussadi?\n"
        "• Which areas currently have outages?\n"
        "• When is electricity expected to return?\n"
        "• What should I do during a power cut?\n\n"
        f"{context}"
    )


def _call_external_ai(question, context, lang="fr"):
    """Call an OpenAI-compatible chat API."""
    lang_instruction = "Answer in French by default." if lang == "fr" else "Answer in English."
    system_prompt = (
        f"You are a helpful assistant for Douala Power Alert, a community outage map "
        f"for Douala, Cameroon. {lang_instruction} Answer only based on the provided outage data. "
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
