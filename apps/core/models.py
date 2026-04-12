"""Core models — shared across apps."""
from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    """Audit log of user actions across the platform.

    Records who did what, when, and on which target.
    """

    # High-level action categories
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_UPLOAD = "upload"
    ACTION_REPROCESS = "reprocess"
    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"
    ACTION_FINALIZE = "finalize"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_EXPORT = "export"
    ACTION_OTHER = "other"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
        (ACTION_UPLOAD, "Upload"),
        (ACTION_REPROCESS, "Reprocess"),
        (ACTION_APPROVE, "Approve"),
        (ACTION_REJECT, "Reject"),
        (ACTION_FINALIZE, "Finalize"),
        (ACTION_LOGIN, "Login"),
        (ACTION_LOGOUT, "Logout"),
        (ACTION_EXPORT, "Export"),
        (ACTION_OTHER, "Other"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    target_type = models.CharField(
        max_length=50, blank=True,
        help_text="Model name or resource type (e.g. 'UploadBatch', 'Product')",
        db_index=True,
    )
    target_id = models.CharField(max_length=100, blank=True, help_text="ID of the target, stringified")
    description = models.CharField(max_length=500)
    details = models.JSONField(default=dict, blank=True, help_text="Additional context (changed fields, values, etc.)")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        username = self.user.username if self.user else "system"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {username} — {self.action}: {self.description}"

    @property
    def action_badge_class(self):
        mapping = {
            self.ACTION_CREATE: "success",
            self.ACTION_UPDATE: "primary",
            self.ACTION_DELETE: "danger",
            self.ACTION_UPLOAD: "info",
            self.ACTION_REPROCESS: "warning",
            self.ACTION_APPROVE: "success",
            self.ACTION_REJECT: "danger",
            self.ACTION_FINALIZE: "primary",
            self.ACTION_LOGIN: "secondary",
            self.ACTION_LOGOUT: "secondary",
            self.ACTION_EXPORT: "info",
        }
        return mapping.get(self.action, "secondary")

    @property
    def details_summary(self) -> str:
        """Return a short human-readable summary from the details JSON."""
        d = self.details or {}
        parts = []
        if "filename" in d:
            parts.append(d["filename"])
        if "records" in d:
            parts.append(f"{d['records']} records")
        if "approved" in d:
            parts.append(f"{d['approved']} approved")
        if "rejected" in d:
            parts.append(f"{d['rejected']} rejected")
        if "import_code" in d:
            parts.append(d["import_code"])
        if "reason" in d:
            parts.append(d["reason"][:50])
        if "changed_fields" in d:
            parts.append(", ".join(d["changed_fields"][:3]))
        if "aliases" in d:
            parts.append(f"{len(d['aliases'])} alias(es)")
        return " · ".join(parts) if parts else ""
