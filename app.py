"""
Douala Power Alert
A participatory map and alert system of electricity outages in Douala.
School coding challenge – simple, elegant, bilingual (French default & English).
Modular architecture powered by Flask Blueprints, Connection Pooling,
CSRF Protection, and Rate Limiting.
"""

import os
from flask import Flask, session, request, redirect, url_for, flash
from flask_wtf.csrf import CSRFError
from dotenv import load_dotenv

from extensions import csrf, limiter
from database import init_db, ensure_admin
from translations import get_text
from routes.utils import get_current_lang

# Import Blueprints
from routes.main import main_bp
from routes.auth import auth_bp
from routes.outages import outages_bp
from routes.admin import admin_bp
from routes.api import api_bp
from routes.ai import ai_bp

load_dotenv()


def create_app():
    """Application factory for Douala Power Alert."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "douala-power-alert-prod-secret-2026")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Initialize extensions
    csrf.init_app(app)
    limiter.init_app(app)

    # Error Handlers
    @app.errorhandler(429)
    def ratelimit_handler(e):
        """Handle rate limit exceeded with localized message."""
        lang = get_current_lang()
        flash(get_text("msg_rate_limit_exceeded", lang=lang), "danger")
        referrer = request.referrer
        if referrer and request.host in referrer:
            return redirect(referrer)
        return redirect(url_for("main.index"))

    @app.errorhandler(CSRFError)
    def csrf_error_handler(e):
        """Handle CSRF validation failure with localized message."""
        lang = get_current_lang()
        flash(get_text("msg_csrf_error", lang=lang), "danger")
        referrer = request.referrer
        if referrer and request.host in referrer:
            return redirect(referrer)
        return redirect(url_for("main.index"))

    # Template Context Processor
    @app.context_processor
    def inject_translations():
        """Inject translation helper and active language into all templates."""
        current_lang = session.get("lang", "fr")
        return {
            "t": lambda key, **kwargs: get_text(key, lang=session.get("lang", "fr"), **kwargs),
            "current_lang": current_lang,
            "languages": [("fr", "Français 🇫🇷"), ("en", "English 🇬🇧")],
        }

    # Register Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(outages_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ai_bp)

    # Register backwards-compatible bare endpoint aliases (e.g. 'login' as well as 'auth.login')
    for rule in list(app.url_map.iter_rules()):
        endpoint = rule.endpoint
        if "." in endpoint:
            bare = endpoint.split(".", 1)[1]
            if bare not in app.view_functions:
                app.add_url_rule(
                    rule.rule,
                    endpoint=bare,
                    view_func=app.view_functions[endpoint],
                    methods=rule.methods,
                )

    return app


app = create_app()

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
