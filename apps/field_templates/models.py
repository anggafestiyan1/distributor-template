"""Template mapping models: StandardMasterField, FieldAlias, Template, TemplateVersion, TemplateFieldMapping."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.field_templates.services.normalization import normalize_header


class StandardMasterField(models.Model):
    DATA_TYPE_CHOICES = [
        ("string", "String"),
        ("integer", "Integer"),
        ("decimal", "Decimal"),
        ("date", "Date"),
        ("boolean", "Boolean"),
    ]

    BATCH_CONTEXT_CHOICES = [
        ("", "No auto-fill (read from file)"),
        ("distributor.name", "Distributor Name (from login)"),
        ("distributor.code", "Distributor Code (from login)"),
        ("distributor.area.name", "Area Name (from distributor)"),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Internal snake_case key (e.g., item_name)",
    )
    display_name = models.CharField(max_length=200)
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES, default="string")
    is_displayed = models.BooleanField(
        default=True,
        help_text="Show this field as a column in Master Data, exports, and reports",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Process this field (aliases, mapping, validation). Hidden fields are still processed if active.",
    )
    batch_context_source = models.CharField(
        max_length=50,
        blank=True,
        default="",
        choices=BATCH_CONTEXT_CHOICES,
        help_text="Auto-fill this field from batch metadata instead of reading from the uploaded file",
    )
    order = models.PositiveIntegerField(default=0, help_text="Display ordering")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Standard Master Field"
        verbose_name_plural = "Standard Master Fields"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_data_type_display()})"

    def has_master_data(self) -> bool:
        from apps.master_data.models import MasterDataRecord
        return MasterDataRecord.objects.filter(data__has_key=self.name).exists()

    def delete(self, *args, **kwargs):
        from django.db.models import ProtectedError
        from apps.master_data.models import MasterDataRecord
        count = MasterDataRecord.objects.filter(data__has_key=self.name).count()
        if count:
            raise ProtectedError(
                f"Cannot delete field '{self.name}': {count} Master Data record(s) already contain data for this field. "
                "Hide it instead using the Active toggle.",
                set(),
            )
        super().delete(*args, **kwargs)


class FieldAlias(models.Model):
    """Alternative column header names that map to a StandardMasterField."""

    standard_field = models.ForeignKey(
        StandardMasterField,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    alias_normalized = models.CharField(
        max_length=200,
        help_text="Auto-normalized alias (set automatically on save)",
    )
    alias_original = models.CharField(
        max_length=200,
        help_text="Original alias as entered by user",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("standard_field", "alias_normalized")
        verbose_name = "Field Alias"
        verbose_name_plural = "Field Aliases"
        ordering = ["standard_field__name", "alias_original"]

    def __str__(self) -> str:
        return f"{self.alias_original} → {self.standard_field.name}"

    def save(self, *args, **kwargs):
        self.alias_normalized = normalize_header(self.alias_original)
        super().save(*args, **kwargs)


class Template(models.Model):
    SCOPE_GLOBAL = "global"
    SCOPE_ASSIGNED = "assigned"
    SCOPE_CHOICES = [
        (SCOPE_GLOBAL, "Global"),
        (SCOPE_ASSIGNED, "Assigned to Distributor"),
    ]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_GLOBAL)
    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="templates",
        help_text="Leave blank for global templates",
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Template"
        verbose_name_plural = "Templates"
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(scope="global", distributor__isnull=True)
                    | Q(scope="assigned", distributor__isnull=False)
                ),
                name="template_scope_distributor_consistency",
            )
        ]

    def __str__(self) -> str:
        if self.distributor:
            return f"{self.name} [{self.distributor.code}]"
        return f"{self.name} [global]"

    def get_latest_version(self):
        return self.versions.filter(is_active=True).order_by("-version_number").first()


class TemplateVersion(models.Model):
    template = models.ForeignKey(
        Template,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("template", "version_number")
        ordering = ["-version_number"]
        verbose_name = "Template Version"
        verbose_name_plural = "Template Versions"

    def __str__(self) -> str:
        return f"{self.template.name} v{self.version_number}"

    @property
    def is_in_use(self) -> bool:
        """True if this version has been used in at least one ProcessingRun."""
        return self.processing_runs.exists()  # type: ignore[attr-defined]

    def get_next_version_number(self) -> int:
        latest = (
            TemplateVersion.objects.filter(template=self.template)
            .order_by("-version_number")
            .values_list("version_number", flat=True)
            .first()
        )
        return (latest or 0) + 1


class TemplateFieldMapping(models.Model):
    """Maps a source column (from distributor file) to a StandardMasterField."""

    template_version = models.ForeignKey(
        TemplateVersion,
        on_delete=models.CASCADE,
        related_name="field_mappings",
    )
    standard_field = models.ForeignKey(
        StandardMasterField,
        on_delete=models.PROTECT,
        related_name="template_mappings",
    )
    source_column = models.CharField(
        max_length=200,
        help_text="Original column header name as seen in distributor files",
    )
    source_column_normalized = models.CharField(
        max_length=200,
        help_text="Auto-normalized version of source_column",
    )

    class Meta:
        unique_together = ("template_version", "standard_field")
        verbose_name = "Template Field Mapping"
        verbose_name_plural = "Template Field Mappings"
        ordering = ["standard_field__order"]

    def __str__(self) -> str:
        return f"{self.source_column} → {self.standard_field.name}"

    def save(self, *args, **kwargs):
        self.source_column_normalized = normalize_header(self.source_column)
        super().save(*args, **kwargs)
