import json

from django.contrib.auth import authenticate
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.models import LoginHistory, User
from core.services import ban_user
from core.tokens import (
    AuthenticationError,
    AuthorizationError,
    issue_token_pair,
    revoke_access_token,
    revoke_refresh_token,
    rotate_refresh_token,
    validate_access_token,
)


def _json_body(request):
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    return body


def _client_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def _bearer_token(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    auth_type, _, token = header.partition(" ")
    if auth_type.lower() != "bearer":
        return ""
    return token.strip()


def _login_key(email, request):
    return f"auth-login-attempts:{email.lower()}:{_client_ip(request) or 'unknown'}"


@method_decorator(csrf_exempt, name="dispatch")
class LoginView(View):
    """Authenticate credentials and return signed claims for other services."""

    def post(self, request):
        try:
            payload = _json_body(request)
            email = payload.get("email", "").strip().lower()
            password = payload.get("password", "")
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)

        if not email or not password:
            return JsonResponse(
                {"detail": "email and password are required."}, status=400
            )

        key = _login_key(email, request)
        if cache.get(key, 0) >= settings.LOGIN_MAX_ATTEMPTS:
            return JsonResponse(
                {"detail": "Too many login attempts. Try again later."}, status=429
            )

        user = authenticate(request, email=email, password=password)
        if user is None:
            # Keep the response identical for unknown email addresses and bad passwords.
            cache.add(key, 0, timeout=settings.LOGIN_ATTEMPT_WINDOW_SECONDS)
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=settings.LOGIN_ATTEMPT_WINDOW_SECONDS)

            known_user = User.objects.filter(email=email).first()
            if known_user:
                LoginHistory.objects.create(
                    user=known_user,
                    ip_address=_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    status=LoginHistory.Status.FAILURE,
                    failure_reason="invalid_credentials",
                )
            return JsonResponse({"detail": "Invalid credentials."}, status=401)

        cache.delete(key)
        LoginHistory.objects.create(
            user=user,
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            status=LoginHistory.Status.SUCCESS,
        )
        return JsonResponse(
            issue_token_pair(
                user,
                ip_address=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ),
            status=200,
        )


@method_decorator(csrf_exempt, name="dispatch")
class RefreshView(View):
    """Rotate an opaque refresh token and issue a new access JWT."""

    def post(self, request):
        try:
            refresh_token = _json_body(request).get("refresh_token", "")
            if not refresh_token:
                raise ValueError("refresh_token is required.")
            return JsonResponse(
                rotate_refresh_token(
                    refresh_token,
                    ip_address=_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
            )
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        except AuthenticationError:
            return JsonResponse({"detail": "Invalid refresh token."}, status=401)


@method_decorator(csrf_exempt, name="dispatch")
class LogoutView(View):
    """Revoke refresh credentials and, when supplied, the current access JWT."""

    def post(self, request):
        try:
            payload = _json_body(request)
            refresh_token = payload.get("refresh_token", "")
            access_token = payload.get("access_token", "") or _bearer_token(request)
            if not refresh_token and not access_token:
                raise ValueError("refresh_token or access token is required.")
            if refresh_token:
                revoke_refresh_token(refresh_token)
            if access_token:
                revoke_access_token(access_token)
            return HttpResponse(status=204)
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class ValidateTokenView(View):
    """Validate an access JWT and its session marker for downstream services."""

    def post(self, request):
        try:
            payload = _json_body(request)
            access_token = payload.get("access_token", "") or _bearer_token(request)
            if not access_token:
                raise ValueError("access_token is required.")
            return JsonResponse(
                {"active": True, "claims": validate_access_token(access_token)}
            )
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        except AuthenticationError:
            return JsonResponse(
                {"active": False, "detail": "Invalid access token."}, status=401
            )


@method_decorator(csrf_exempt, name="dispatch")
class PermissionsView(View):
    """Return current IAM RBAC permissions for a valid access JWT subject."""

    def get(self, request):
        access_token = _bearer_token(request)
        if not access_token:
            return JsonResponse({"detail": "Bearer token is required."}, status=401)

        try:
            claims = validate_access_token(access_token)
            user = User.objects.get(id=claims["sub"])
        except (AuthenticationError, User.DoesNotExist):
            return JsonResponse({"detail": "Invalid access token."}, status=401)

        return JsonResponse(
            {
                "user_id": str(user.id),
                "roles": user.role_names(),
                "permissions": user.permission_names(),
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class BanUserView(View):
    """Admin endpoint for global logout/ban enforcement."""

    def post(self, request, user_id):
        try:
            payload = _json_body(request)
            access_token = _bearer_token(request)
            if not access_token:
                return JsonResponse({"detail": "Bearer token is required."}, status=401)

            claims = validate_access_token(access_token)
            performed_by = User.objects.get(id=claims["sub"])
            result = ban_user(
                user_id,
                performed_by=performed_by,
                reason=payload.get("reason", "user_banned"),
                ip_address=_client_ip(request),
            )
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        except AuthenticationError:
            return JsonResponse({"detail": "Invalid access token."}, status=401)
        except AuthorizationError:
            return JsonResponse({"detail": "Permission denied."}, status=403)
        except User.DoesNotExist:
            return JsonResponse({"detail": "User not found."}, status=404)

        return JsonResponse(
            {
                "detail": "User banned.",
                "user_id": str(result["target_user"].id),
                "revoked_refresh_tokens": result["revoked_refresh_tokens"],
                "revoked_access_sessions": len(result["revoked_access_sessions"]),
                "revocation_published": result["published"],
            }
        )
