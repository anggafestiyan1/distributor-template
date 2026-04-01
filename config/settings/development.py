"""Development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True

INTERNAL_IPS = ["127.0.0.1"]

# Relax password validation during development
AUTH_PASSWORD_VALIDATORS = []

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
