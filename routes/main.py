"""
Main general routes for Douala Power Alert (Home and Language switcher).
"""

from flask import Blueprint, render_template, session, redirect, url_for, request

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Landing page featuring live map and project overview."""
    return render_template("index.html")


@main_bp.route("/set-language/<lang>")
def set_language(lang):
    """Switch language between 'fr' (French) and 'en' (English)."""
    if lang in ("fr", "en"):
        session["lang"] = lang
    referrer = request.referrer
    if referrer and request.host in referrer:
        return redirect(referrer)
    return redirect(url_for("main.index"))
