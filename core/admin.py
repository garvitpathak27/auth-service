from django.contrib import admin

from core.models import (
    AuditLog,
    EmailVerification,
    LoginHistory,
    PasswordResetToken,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserProfile,
    UserRole,
)

admin.site.register(
    [
        User,
        UserProfile,
        Role,
        Permission,
        UserRole,
        RolePermission,
        RefreshToken,
        LoginHistory,
        EmailVerification,
        PasswordResetToken,
        AuditLog,
    ]
)
