from .base import *  # noqa: F403

DEBUG = False

JWT_SECRET = "test-only-signing-key-not-for-deployment"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

REDIS_URL = ""

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "auth-service-test-cache",
    }
}

# Keep the test suite self-contained; deployment settings continue to use Postgres.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",
    }
}
