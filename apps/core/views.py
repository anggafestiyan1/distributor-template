"""Core views — Activity Log browsers (Main + Settings scope)."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from apps.core.mixins import AdminRequiredMixin
from apps.core.models import ActivityLog


# Target types belonging to Settings (Standard Fields + Templates)
SETTINGS_TARGET_TYPES = {
    "StandardMasterField",
    "Template",
    "TemplateVersion",
    "TemplateFieldMapping",
}


class _BaseActivityLogView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ActivityLog
    template_name = "core/activity_log_list.html"
    context_object_name = "logs"
    paginate_by = 50

    # Subclasses override this
    log_scope = "main"  # "main" or "settings"
    page_title = "Activity Log"
    page_subtitle = "Audit trail"

    def _base_queryset(self):
        """Override in subclass — return queryset filtered by scope."""
        raise NotImplementedError

    def get_queryset(self):
        qs = self._base_queryset().select_related("user")

        action = self.request.GET.get("action", "").strip()
        if action:
            qs = qs.filter(action=action)

        user_id = self.request.GET.get("user", "").strip()
        if user_id:
            qs = qs.filter(user_id=user_id)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(description__icontains=q)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        ctx["action_choices"] = ActivityLog.ACTION_CHOICES
        ctx["users"] = User.objects.order_by("username")
        ctx["filter_action"] = self.request.GET.get("action", "")
        ctx["filter_user"] = self.request.GET.get("user", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["log_scope"] = self.log_scope
        ctx["page_title"] = self.page_title
        ctx["page_subtitle"] = self.page_subtitle
        return ctx


class MainLogView(_BaseActivityLogView):
    """Activity log for Upload / Review / Master Data actions."""
    log_scope = "main"
    page_title = "Activity Log"
    page_subtitle = "Upload, review, and master data actions"

    def _base_queryset(self):
        # Exclude settings target types and login/logout events
        return ActivityLog.objects.exclude(
            target_type__in=SETTINGS_TARGET_TYPES
        )


class SettingsLogView(_BaseActivityLogView):
    """Activity log for Standard Fields and Templates changes."""
    log_scope = "settings"
    page_title = "Settings Log"
    page_subtitle = "Standard Fields and Templates changes"

    def _base_queryset(self):
        return ActivityLog.objects.filter(
            target_type__in=SETTINGS_TARGET_TYPES
        )
