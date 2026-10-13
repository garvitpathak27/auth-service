"""Application services that coordinate IAM model and cache side effects."""

from django.db import transaction
from django.utils import timezone

from core.models import AuditLog, RefreshToken, User
from core.session_state import publish_user_revoked, revoke_user_sessions
from core.tokens import AuthorizationError


def can_ban_users(user):
    return bool(user and (user.is_staff or user.has_rbac_permission("users.ban")))


def ban_user(target_user_id, *, performed_by, reason="user_banned", ip_address=None):
    """Deactivate a user and broadcast immediate access revocation."""
    if not can_ban_users(performed_by):
        raise AuthorizationError

    with transaction.atomic():
        target_user = User.objects.select_for_update().get(id=target_user_id)
        if target_user.id == performed_by.id:
            raise AuthorizationError

        if target_user.is_active:
            target_user.is_active = False
            target_user.save(update_fields=("is_active", "updated_at"))

        revoked_refresh_tokens = RefreshToken.objects.filter(
            user=target_user, revoked=False
        ).update(revoked=True)

        audit_log = AuditLog.objects.create(
            performed_by=performed_by,
            target_user=target_user,
            action="user_banned",
            metadata={
                "reason": reason,
                "revoked_refresh_tokens": revoked_refresh_tokens,
            },
            ip_address=ip_address,
        )

    revoked_access_sessions = revoke_user_sessions(target_user.id)
    published = publish_user_revoked(
        target_user.id, reason=reason, timestamp=timezone.now()
    )
    return {
        "target_user": target_user,
        "revoked_refresh_tokens": revoked_refresh_tokens,
        "revoked_access_sessions": revoked_access_sessions,
        "published": published,
        "audit_log": audit_log,
    }
