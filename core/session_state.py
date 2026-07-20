"""Redis/cache-backed access-session state for issued JWTs."""

import json
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

ACTIVE = "active"
REVOKED = "revoked"
REVOKED_STATUSES = {REVOKED, "banned"}
USER_REVOKED_CHANNEL = "auth.user.revoked"


def access_session_key(jti):
    return f"session:{jti}"


def user_sessions_key(user_id):
    return f"user:{user_id}:sessions"


def user_status_key(user_id):
    return f"user:{user_id}:status"


def _registry_timeout():
    return getattr(
        settings,
        "USER_SESSION_REGISTRY_TIMEOUT_SECONDS",
        settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _revoked_session_timeout():
    return getattr(
        settings,
        "REVOKED_SESSION_MARKER_SECONDS",
        settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _timeout_until(expires_at):
    if isinstance(expires_at, (int, float)):
        expires_at = datetime.fromtimestamp(expires_at, tz=datetime_timezone.utc)
    elif timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, datetime_timezone.utc)

    return max(int((expires_at - timezone.now()).total_seconds()), 0)


def _dedupe(values):
    result = []
    seen = set()
    for value in values or []:
        value = str(value)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def register_access_session(user_id, jti, expires_at):
    """Mark an issued access JWT as usable until its own expiry."""
    timeout = _timeout_until(expires_at)
    if timeout <= 0:
        return

    user_id = str(user_id)
    jti = str(jti)
    cache.set(access_session_key(jti), ACTIVE, timeout=timeout)

    if cache.get(user_status_key(user_id)) not in REVOKED_STATUSES:
        cache.set(user_status_key(user_id), ACTIVE, timeout=None)

    sessions = _dedupe(cache.get(user_sessions_key(user_id), []))
    if jti not in sessions:
        sessions.append(jti)
    cache.set(user_sessions_key(user_id), sessions, timeout=_registry_timeout())


def get_access_session_status(jti):
    return cache.get(access_session_key(jti))


def get_user_status(user_id):
    return cache.get(user_status_key(str(user_id)))


def get_registered_access_sessions(user_id):
    return _dedupe(cache.get(user_sessions_key(str(user_id)), []))


def access_session_is_active(user_id, jti):
    if get_user_status(user_id) in REVOKED_STATUSES:
        return False
    return get_access_session_status(jti) == ACTIVE


def revoke_access_session(user_id, jti, expires_at=None):
    timeout = _revoked_session_timeout()
    if expires_at is not None:
        timeout = max(_timeout_until(expires_at), 1)
    cache.set(access_session_key(str(jti)), REVOKED, timeout=timeout)


def revoke_user_sessions(user_id):
    user_id = str(user_id)
    cache.set(user_status_key(user_id), REVOKED, timeout=None)

    session_jtis = get_registered_access_sessions(user_id)
    for jti in session_jtis:
        cache.set(access_session_key(jti), REVOKED, timeout=_revoked_session_timeout())
    return session_jtis


def get_redis_client():
    redis_url = getattr(settings, "REDIS_URL", "")
    if not redis_url:
        return None

    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def publish_user_revoked(user_id, reason, timestamp=None):
    client = get_redis_client()
    if client is None:
        return False

    payload = {
        "user_id": str(user_id),
        "reason": reason,
        "ts": (timestamp or timezone.now()).isoformat(),
    }
    client.publish(USER_REVOKED_CHANNEL, json.dumps(payload, sort_keys=True))
    return True
