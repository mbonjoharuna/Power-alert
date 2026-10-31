"""
AI Assistant Blueprint for Douala Power Alert.
Handles citizen questions regarding outages, restorations, and historical trends.
"""

from flask import Blueprint, render_template, request, flash
from extensions import limiter
from database import get_db_cursor
from translations import get_text
from routes.utils import get_current_lang
from services.ai_service import ask_ai

ai_bp = Blueprint("ai", __name__)


@ai_bp.route("/ai", methods=["GET", "POST"])
@limiter.limit("15 per minute")
def ai_page():
    """Interactive AI outage assistant query interface."""
    lang = get_current_lang()
    answer = None
    question = ""
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if not question:
            flash(get_text("msg_ask_question_empty", lang=lang), "warning")
        else:
            try:
                with get_db_cursor() as cur:
                    answer = ask_ai(question, cur, lang=lang)
            except Exception:
                answer = (
                    "Désolé, l'assistant IA est temporairement indisponible. Veuillez réessayer plus tard."
                    if lang == "fr"
                    else "Sorry, the AI assistant is temporarily unavailable. Please try again later."
                )
    return render_template("ai.html", answer=answer, question=question)
