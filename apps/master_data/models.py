"""Master Data models — stores final approved records."""
from django.conf import settings
from django.db import models


class MasterDataImport(models.Model):
    """Groups MasterDataRecords created in a single finalize action."""

    code = models.CharField(max_length=20, unique=True, help_text="Auto-generated IID-XXXXX")
    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.PROTECT,
        related_name="master_imports",
    )
    processing_run = models.ForeignKey(
        "uploads.ProcessingRun",
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    record_count = models.PositiveIntegerField(default=0)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]

    def __str__(self):
        return f"{self.code} — {self.distributor.name}"

    @classmethod
    def generate_code(cls):
        last = cls.objects.order_by("-pk").first()
        next_num = (last.pk + 1) if last else 1
        return f"IID-{next_num:05d}"


class MasterDataRecord(models.Model):
    master_import = models.ForeignKey(
        MasterDataImport,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="records",
    )
    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.PROTECT,
        related_name="master_records",
    )
    area = models.CharField(max_length=100, db_index=True, help_text="Denormalized from distributor.area")
    template_version = models.ForeignKey(
        "field_templates.TemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="master_records",
    )
    processing_run = models.ForeignKey(
        "uploads.ProcessingRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="master_records",
    )
    import_row = models.OneToOneField(
        "uploads.ImportRow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="master_record",
    )
    data = models.JSONField(help_text="Standardized field data {field_name: value}")
    business_key = models.CharField(max_length=255, blank=True, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-imported_at"]
        verbose_name = "Master Data Record"
        verbose_name_plural = "Master Data Records"
        indexes = [
            models.Index(fields=["area", "distributor"]),
            models.Index(fields=["imported_at"]),
        ]

    def __str__(self) -> str:
        return f"Record {self.pk} | {self.distributor.code} | {self.area}"


class ReprocessLog(models.Model):
    """Audit trail for batch reprocessing."""

    batch = models.ForeignKey(
        "uploads.UploadBatch",
        on_delete=models.CASCADE,
        related_name="reprocess_logs",
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reprocess_logs",
    )
    reason = models.TextField()
    old_run = models.ForeignKey(
        "uploads.ProcessingRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reprocess_old",
    )
    new_run = models.ForeignKey(
        "uploads.ProcessingRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reprocess_new",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Reprocess Log"
        verbose_name_plural = "Reprocess Logs"

    def __str__(self) -> str:
        return f"Reprocess of batch #{self.batch_id} at {self.created_at:%Y-%m-%d %H:%M}"
