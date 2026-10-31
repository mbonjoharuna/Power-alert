"""
Common route decorators and utility helpers for Douala Power Alert.
"""

from functools import wraps
from flask import session, flash, redirect, url_for
from translations import get_text


def get_current_lang():
    """Retrieve active session language ('fr' default or 'en')."""
    return session.get("lang", "fr")


def login_required(f):
    """Ensure user is logged in before accessing protected routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash(get_text("msg_login_required", lang=get_current_lang()), "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Ensure admin is logged in before accessing admin portal routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            flash(get_text("msg_admin_required", lang=get_current_lang()), "warning")
            return redirect(url_for("admin.admin_login"))
        return f(*args, **kwargs)
    return decorated
