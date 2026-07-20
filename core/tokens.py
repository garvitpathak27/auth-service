"""JWT issuance and opaque refresh-token lifecycle for the IAM service."""

import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import RefreshToken, User
from core.session_state import (
    access_session_is_active,
    register_access_session,
    revoke_access_session,
)


class AuthenticationError(Exception):
    """Raised when a refresh token cannot establish an authenticated user."""


class AuthorizationError(Exception):
    """Raised when an authenticated user is not allowed to perform an action."""


def _permissions_for(user):
    return user.role_names(), user.permission_names()


def _access_token_claims(user):
    now = timezone.now()
    roles, permissions = _permissions_for(user)
    return {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": str(user.id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "token_type": "access",
        "email": user.email,
        "roles": roles,
        "permissions": permissions,
    }


def _encode_access_token(user):
    claims = _access_token_claims(user)
    token = jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, claims


def create_access_token(user):
    """Create and register a self-contained access JWT."""
    token, claims = _encode_access_token(user)
    register_access_session(user.id, claims["jti"], claims["exp"])
    return token


def _decode_access_token(raw_token, *, verify_exp=True):
    try:
        claims = jwt.decode(
            raw_token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"verify_exp": verify_exp},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError from exc

    if claims.get("token_type") != "access":
        raise AuthenticationError
    if not claims.get("sub") or not claims.get("jti"):
        raise AuthenticationError
    return claims


def validate_access_token(raw_token, *, verify_user=True):
    """Verify signature, token claims, session state, and IAM user status."""
    claims = _decode_access_token(raw_token)
    if not access_session_is_active(claims["sub"], claims["jti"]):
        raise AuthenticationError

    if verify_user and not User.objects.filter(
        id=claims["sub"], is_active=True, deleted_at__isnull=True
    ).exists():
        raise AuthenticationError

    return claims


def revoke_access_token(raw_token):
    """Mark one access JWT as revoked while keeping logout idempotent."""
    try:
        claims = _decode_access_token(raw_token, verify_exp=False)
    except AuthenticationError:
        return False

    revoke_access_session(claims["sub"], claims["jti"], expires_at=claims.get("exp"))
    return True


def _hash_refresh_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_refresh_token(user, *, ip_address=None, user_agent=""):
    raw_token = secrets.token_urlsafe(48)
    expires_at = timezone.now() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    RefreshToken.objects.create(
        user=user,
        token_hash=_hash_refresh_token(raw_token),
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return raw_token, expires_at


def issue_token_pair(user, *, ip_address=None, user_agent=""):
    refresh_token, refresh_expires_at = _create_refresh_token(
        user, ip_address=ip_address, user_agent=user_agent
    )
    access_token, access_claims = _encode_access_token(user)
    register_access_session(user.id, access_claims["jti"], access_claims["exp"])
    return {
        "access_token": access_token,
        "access_jwt": access_token,
        "token_type": "Bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": refresh_token,
        "refresh_expires_at": refresh_expires_at.isoformat(),
    }


def rotate_refresh_token(raw_token, *, ip_address=None, user_agent=""):
    """Single-use refresh-token rotation prevents replay after a successful refresh."""
    with transaction.atomic():
        token = (
            RefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash_refresh_token(raw_token))
            .first()
        )
        if (
            token is None
            or token.revoked
            or token.expires_at <= timezone.now()
            or not token.user.is_active
        ):
            raise AuthenticationError

        token.revoked = True
        token.last_used_at = timezone.now()
        token.save(update_fields=("revoked", "last_used_at"))
        return issue_token_pair(
            token.user, ip_address=ip_address, user_agent=user_agent
        )


def revoke_refresh_token(raw_token):
    """Make logout idempotent while never disclosing whether a token exists."""
    RefreshToken.objects.filter(token_hash=_hash_refresh_token(raw_token)).update(
        revoked=True
    )
