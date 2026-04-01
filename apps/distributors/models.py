"""Distributor and user-distributor assignment models."""
from django.conf import settings
from django.db import models


class Area(models.Model):
    """Master data for geographic/business areas. Managed by admin."""

    name = models.CharField(max_length=100, unique=True, help_text="e.g. WEST JAVA, EAST, SUMATRA")
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. WJAV, EAST")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Area"
        verbose_name_plural = "Areas"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Distributor(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="distributors",
        help_text="Geographic or business area",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Distributor"
        verbose_name_plural = "Distributors"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def active_users(self):
        return self.assignments.filter(user__is_active=True).select_related("user")


class UserDistributorAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="distributor_assignments",
    )
    distributor = models.ForeignKey(
        Distributor,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "distributor")
        verbose_name = "User-Distributor Assignment"
        verbose_name_plural = "User-Distributor Assignments"
        ordering = ["distributor__name", "user__username"]

    def __str__(self) -> str:
        return f"{self.user.username} → {self.distributor.name}"


def get_user_distributors(user) -> models.QuerySet:
    """Return Distributor queryset accessible by the given user."""
    if user.is_admin or user.is_superuser:
        return Distributor.objects.filter(is_active=True)
    return Distributor.objects.filter(
        assignments__user=user,
        is_active=True,
    )
