"""
Flask Extensions Initialization for Douala Power Alert.
Initializes CSRF protection and rate limiting instances to avoid circular imports.
"""

from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300 per hour", "60 per minute"],
    storage_uri="memory://",
)
