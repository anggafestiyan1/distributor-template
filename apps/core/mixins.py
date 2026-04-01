"""Shared view mixins for role-based access control."""
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect


class AdminRequiredMixin(AccessMixin):
    """Allow only admin users (role='admin' or superuser)."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_admin or request.user.is_superuser):
            messages.error(request, "You do not have permission to access this page.")
            return redirect("dashboard:index")
        return super().dispatch(request, *args, **kwargs)


class StaffOrAdminMixin(AccessMixin):
    """Allow admin and staff users."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_admin or request.user.is_staff_role or request.user.is_superuser):
            messages.error(request, "You do not have permission to access this page.")
            return redirect("dashboard:index")
        return super().dispatch(request, *args, **kwargs)


class HtmxMixin:
    """Detect if the request is an HTMX request."""

    @property
    def is_htmx(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"  # type: ignore[attr-defined]
