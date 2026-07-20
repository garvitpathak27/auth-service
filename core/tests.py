import json
from unittest.mock import patch

import jwt
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.models import (
    AuditLog,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
)
from core.session_state import (
    ACTIVE,
    REVOKED,
    access_session_key,
    user_sessions_key,
    user_status_key,
)


class AuthenticationApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="member@example.com", password="a-safe-test-password"
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="an-admin-test-password",
            is_staff=True,
        )
        role = Role.objects.create(name="member")
        permission = Permission.objects.create(name="messages.send")
        UserRole.objects.create(user=self.user, role=role)
        RolePermission.objects.create(role=role, permission=permission)

    def post_json(self, name, payload):
        return self.client.post(
            reverse(name), data=json.dumps(payload), content_type="application/json"
        )

    def post_json_with_bearer(self, name, payload, access_token, **kwargs):
        return self.client.post(
            reverse(name, kwargs=kwargs),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

    def login(self, user, password):
        return self.post_json("login", {"email": user.email, "password": password})

    def decode_access_token(self, token):
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )

    def test_login_issues_identity_and_permission_claims(self):
        response = self.login(self.user, "a-safe-test-password")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        claims = self.decode_access_token(body["access_token"])
        self.assertEqual(claims["sub"], str(self.user.id))
        self.assertEqual(claims["roles"], ["member"])
        self.assertEqual(claims["permissions"], ["messages.send"])
        self.assertEqual(claims["token_type"], "access")
        self.assertEqual(body["access_jwt"], body["access_token"])
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(cache.get(access_session_key(claims["jti"])), ACTIVE)
        self.assertEqual(cache.get(user_status_key(self.user.id)), ACTIVE)
        self.assertIn(claims["jti"], cache.get(user_sessions_key(self.user.id)))

    def test_validate_token_checks_the_session_marker(self):
        login = self.login(self.user, "a-safe-test-password").json()

        response = self.post_json(
            "validate-token", {"access_token": login["access_token"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["active"])
        self.assertEqual(response.json()["claims"]["sub"], str(self.user.id))

    def test_refresh_rotates_token_and_rejects_replay(self):
        login = self.login(self.user, "a-safe-test-password").json()

        refreshed = self.post_json("refresh", {"refresh_token": login["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(login["refresh_token"], refreshed.json()["refresh_token"])

        replay = self.post_json("refresh", {"refresh_token": login["refresh_token"]})
        self.assertEqual(replay.status_code, 401)

    def test_logout_revokes_refresh_token_and_access_session(self):
        login = self.login(self.user, "a-safe-test-password").json()
        claims = self.decode_access_token(login["access_token"])

        response = self.post_json_with_bearer(
            "logout", {"refresh_token": login["refresh_token"]}, login["access_token"]
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(cache.get(access_session_key(claims["jti"])), REVOKED)
        self.assertEqual(RefreshToken.objects.filter(revoked=True).count(), 1)

        rejected = self.post_json(
            "validate-token", {"access_token": login["access_token"]}
        )
        self.assertEqual(rejected.status_code, 401)

    def test_permissions_endpoint_returns_current_rbac_for_valid_token(self):
        login = self.login(self.user, "a-safe-test-password").json()

        response = self.client.get(
            reverse("permissions"),
            HTTP_AUTHORIZATION=f"Bearer {login['access_token']}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], str(self.user.id))
        self.assertEqual(response.json()["roles"], ["member"])
        self.assertEqual(response.json()["permissions"], ["messages.send"])

    def test_admin_ban_globally_revokes_target_user(self):
        target_login = self.login(self.user, "a-safe-test-password").json()
        admin_login = self.login(self.admin, "an-admin-test-password").json()
        target_claims = self.decode_access_token(target_login["access_token"])

        with patch("core.services.publish_user_revoked", return_value=True) as publish:
            response = self.post_json_with_bearer(
                "ban-user",
                {"reason": "policy_violation"},
                admin_login["access_token"],
                user_id=self.user.id,
            )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(cache.get(user_status_key(self.user.id)), REVOKED)
        self.assertEqual(cache.get(access_session_key(target_claims["jti"])), REVOKED)
        self.assertEqual(
            RefreshToken.objects.filter(user=self.user, revoked=True).count(), 1
        )

        audit_log = AuditLog.objects.get(action="user_banned")
        self.assertEqual(audit_log.performed_by, self.admin)
        self.assertEqual(audit_log.target_user, self.user)
        self.assertEqual(audit_log.metadata["reason"], "policy_violation")
        publish.assert_called_once()

        rejected = self.post_json(
            "validate-token", {"access_token": target_login["access_token"]}
        )
        self.assertEqual(rejected.status_code, 401)
        refresh_rejected = self.post_json(
            "refresh", {"refresh_token": target_login["refresh_token"]}
        )
        self.assertEqual(refresh_rejected.status_code, 401)

    def test_invalid_credentials_do_not_issue_a_token(self):
        response = self.post_json(
            "login", {"email": self.user.email, "password": "incorrect"}
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid credentials.")

    def test_custom_rbac_is_the_only_user_permission_source(self):
        self.assertEqual(self.user.role_names(), ["member"])
        self.assertEqual(self.user.permission_names(), ["messages.send"])
        self.assertTrue(self.user.has_rbac_permission("messages.send"))
        self.assertFalse(self.user.has_rbac_permission("messages.delete"))
        self.assertNotIn("groups", {field.name for field in User._meta.get_fields()})
        self.assertNotIn(
            "user_permissions", {field.name for field in User._meta.get_fields()}
        )
