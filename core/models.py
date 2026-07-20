from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from core.base.models import BaseModel, UUIDModel


class UserManager(BaseUserManager):
    """Manager for email-authenticated users."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email address must be set.")
        if not password:
            raise ValueError("The password must be set.")

        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superusers must have is_staff=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, BaseModel):
    """An IAM user whose application access comes only from custom RBAC."""

    email = models.EmailField(unique=True, db_index=True)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    is_staff = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = UserManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("is_active", "deleted_at"), name="user_active_deleted_idx"
            ),
            models.Index(fields=("-created_at",), name="user_created_desc_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    def role_names(self):
        """Return roles assigned through the IAM-owned UserRole table."""
        return list(
            self.role_assignments.order_by("role__name").values_list(
                "role__name", flat=True
            )
        )

    def permission_names(self):
        """Return permissions derived solely through UserRole and RolePermission."""
        return list(
            self.role_assignments.filter(
                role__permission_assignments__isnull=False
            )
            .order_by("role__permission_assignments__permission__name")
            .values_list("role__permission_assignments__permission__name", flat=True)
            .distinct()
        )

    def has_rbac_permission(self, permission_name):
        """Check the custom RBAC source of truth; Django permissions are ignored."""
        return self.role_assignments.filter(
            role__permission_assignments__permission__name=permission_name
        ).exists()


class UserProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    profile_picture = models.URLField(max_length=500, blank=True)
    phone_number = models.CharField(max_length=32, blank=True, db_index=True)
    bio = models.TextField(blank=True)
    country = models.CharField(max_length=2, blank=True)
    timezone = models.CharField(max_length=63, blank=True)
    language = models.CharField(max_length=16, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Profile for {self.user}"


class Role(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Permission(BaseModel):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class UserRole(UUIDModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="user_assignments"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "role"), name="unique_user_role"),
        ]
        indexes = [
            models.Index(
                fields=("user", "-assigned_at"), name="user_role_user_assigned_idx"
            ),
            models.Index(
                fields=("role", "-assigned_at"), name="user_role_role_assigned_idx"
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.role}"


class RolePermission(UUIDModel):
    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="permission_assignments"
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("role", "permission"), name="unique_role_permission"
            ),
        ]
        indexes = [
            models.Index(
                fields=("role", "-assigned_at"), name="role_perm_role_assigned_idx"
            ),
            models.Index(
                fields=("permission", "-assigned_at"),
                name="role_perm_perm_assigned_idx",
            ),
        ]

    def __str__(self):
        return f"{self.role} - {self.permission}"


class RefreshToken(UUIDModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "revoked", "expires_at"),
                name="refresh_token_lookup_idx",
            ),
            models.Index(fields=("-created_at",), name="refresh_token_created_idx"),
        ]

    def __str__(self):
        return f"Refresh token for {self.user}"


class LoginHistory(UUIDModel):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="login_history"
    )
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-login_time",)
        indexes = [
            models.Index(
                fields=("user", "-login_time"), name="login_history_user_time_idx"
            ),
            models.Index(
                fields=("status", "-login_time"), name="login_history_status_time_idx"
            ),
        ]

    def __str__(self):
        return f"{self.user} login: {self.status}"


class EmailVerification(UUIDModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_verifications"
    )
    verification_token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "expires_at"),
                name="email_verification_lookup_idx",
            ),
        ]

    def __str__(self):
        return f"Email verification for {self.user}"


class PasswordResetToken(UUIDModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    used = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "used", "expires_at"),
                name="password_reset_lookup_idx",
            ),
        ]

    def __str__(self):
        return f"Password reset token for {self.user}"


class AuditLog(UUIDModel):
    performed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="performed_audit_logs",
    )
    target_user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_audit_logs",
    )
    action = models.CharField(max_length=100, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("performed_by", "-created_at"),
                name="audit_performer_created_idx",
            ),
            models.Index(
                fields=("target_user", "-created_at"),
                name="audit_target_created_idx",
            ),
            models.Index(
                fields=("action", "-created_at"), name="audit_action_created_idx"
            ),
        ]

    def __str__(self):
        return self.action
