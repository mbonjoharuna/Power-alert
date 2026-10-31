"""
Main general routes for Douala Power Alert (Home, Language switcher, and Offline PWA fallback).
"""

from flask import Blueprint, render_template, session, redirect, url_for, request

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Landing page featuring live map and project overview."""
    return render_template("index.html")


@main_bp.route("/offline")
def offline():
    """Offline fallback page served when user loses network connectivity."""
    return render_template("offline.html")


@main_bp.route("/set-language/<lang>")
def set_language(lang):
    """Switch language between 'fr' (French) and 'en' (English)."""
    if lang in ("fr", "en"):
        session["lang"] = lang
    referrer = request.referrer
    if referrer and request.host in referrer:
        return redirect(referrer)
    return redirect(url_for("main.index"))
