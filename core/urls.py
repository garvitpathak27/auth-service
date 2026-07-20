from django.urls import path

from core.views import (
    BanUserView,
    LoginView,
    LogoutView,
    PermissionsView,
    RefreshView,
    ValidateTokenView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("validate/", ValidateTokenView.as_view(), name="validate-token"),
    path("permissions/", PermissionsView.as_view(), name="permissions"),
    path("admin/users/<uuid:user_id>/ban/", BanUserView.as_view(), name="ban-user"),
]
