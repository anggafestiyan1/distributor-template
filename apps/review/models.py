"""Review action audit trail model."""
from django.conf import settings
from django.db import models


class ReviewAction(models.Model):
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_ESCALATED = "escalated"

    ACTION_CHOICES = [
        (ACTION_APPROVED, "Approved"),
        (ACTION_REJECTED, "Rejected"),
        (ACTION_ESCALATED, "Escalated"),
    ]

    import_row = models.ForeignKey(
        "uploads.ImportRow",
        on_delete=models.CASCADE,
        related_name="review_actions",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="review_actions",
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Review Action"
        verbose_name_plural = "Review Actions"

    def __str__(self) -> str:
        return f"{self.actor} {self.action} row #{self.import_row.row_number}"
