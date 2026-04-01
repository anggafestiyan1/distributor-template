"""Upload batch and processing models."""
from django.conf import settings
from django.db import models


class UploadBatch(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_PROCESSED = "processed"
    STATUS_ERROR = "error"
    STATUS_MISMATCH = "mismatch"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_ERROR, "Error"),
        (STATUS_MISMATCH, "Template Mismatch"),
    ]

    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.PROTECT,
        related_name="upload_batches",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="upload_batches",
    )
    original_filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500, help_text="Path relative to MEDIA_ROOT")
    file_checksum = models.CharField(max_length=64, help_text="SHA-256 of the uploaded file")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Upload Batch"
        verbose_name_plural = "Upload Batches"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.distributor.code}) [{self.status}]"

    def get_latest_run(self):
        return self.processing_runs.order_by("-run_number").first()

    @property
    def status_badge_class(self) -> str:
        mapping = {
            "pending": "secondary",
            "processing": "info",
            "processed": "success",
            "error": "danger",
            "mismatch": "warning",
        }
        return mapping.get(self.status, "secondary")


class ProcessingRun(models.Model):
    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name="processing_runs",
    )
    template_version = models.ForeignKey(
        "field_templates.TemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processing_runs",
    )
    match_score = models.FloatField(null=True, blank=True)
    used_global = models.BooleanField(default=False)
    fallback_happened = models.BooleanField(default=False)
    run_number = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-run_number"]
        verbose_name = "Processing Run"
        verbose_name_plural = "Processing Runs"

    def __str__(self) -> str:
        return f"Run #{self.run_number} for {self.batch}"

    @property
    def review_summary(self) -> dict:
        rows = self.import_rows.all()
        total = rows.count()
        approved = rows.filter(review_decision="approved").count()
        rejected = rows.filter(review_decision="rejected").count()
        pending = rows.filter(review_decision="pending").count()
        problem = rows.filter(row_status__in=["invalid", "warning"]).count()
        return {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "pending": pending,
            "problem": problem,
        }

    @property
    def approval_status(self) -> str:
        """Aggregate approval status across all rows."""
        summary = self.review_summary
        if summary["pending"] > 0:
            return "not_reviewed"
        if summary["approved"] == summary["total"] and summary["total"] > 0:
            return "approved_all"
        if summary["rejected"] == summary["total"] and summary["total"] > 0:
            return "rejected_all"
        if summary["approved"] > 0:
            return "partially_approved"
        return "not_reviewed"

    @property
    def approval_badge_class(self) -> str:
        mapping = {
            "not_reviewed": "secondary",
            "approved_all": "success",
            "rejected_all": "danger",
            "partially_approved": "warning",
        }
        return mapping.get(self.approval_status, "secondary")


class TemplateMatchLog(models.Model):
    """Log of all template versions scored during a processing run."""

    processing_run = models.ForeignKey(
        ProcessingRun,
        on_delete=models.CASCADE,
        related_name="match_logs",
    )
    template_version = models.ForeignKey(
        "field_templates.TemplateVersion",
        on_delete=models.CASCADE,
        related_name="match_logs",
    )
    match_score = models.FloatField()
    matched = models.BooleanField()
    is_assigned = models.BooleanField(default=False)
    reason = models.TextField()
    matched_columns = models.JSONField(default=list, blank=True)
    unmatched_columns = models.JSONField(default=list, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-match_score"]
        verbose_name = "Template Match Log"

    def __str__(self) -> str:
        return f"{self.template_version} score={self.match_score:.2f} matched={self.matched}"


class ImportRow(models.Model):
    ROW_STATUS_VALID = "valid"
    ROW_STATUS_INVALID = "invalid"
    ROW_STATUS_WARNING = "warning"
    ROW_STATUS_PENDING = "pending_review"
    ROW_STATUS_APPROVED = "approved"
    ROW_STATUS_REJECTED = "rejected"
    ROW_STATUS_DUPLICATE = "duplicate"

    ROW_STATUS_CHOICES = [
        (ROW_STATUS_VALID, "Valid"),
        (ROW_STATUS_INVALID, "Invalid"),
        (ROW_STATUS_WARNING, "Warning"),
        (ROW_STATUS_PENDING, "Pending Review"),
        (ROW_STATUS_APPROVED, "Approved"),
        (ROW_STATUS_REJECTED, "Rejected"),
        (ROW_STATUS_DUPLICATE, "Duplicate"),
    ]

    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_PENDING = "pending"

    DECISION_CHOICES = [
        (DECISION_APPROVED, "Approved"),
        (DECISION_REJECTED, "Rejected"),
        (DECISION_PENDING, "Pending"),
    ]

    processing_run = models.ForeignKey(
        ProcessingRun,
        on_delete=models.CASCADE,
        related_name="import_rows",
    )
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(help_text="Original data as read from file")
    mapped_data = models.JSONField(default=dict, help_text="Data mapped to standard field names")
    row_checksum = models.CharField(max_length=64, db_index=True)
    row_status = models.CharField(max_length=20, choices=ROW_STATUS_CHOICES, default=ROW_STATUS_PENDING)
    review_decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default=DECISION_PENDING)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_rows",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    business_key = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["row_number"]
        verbose_name = "Import Row"
        verbose_name_plural = "Import Rows"

    def __str__(self) -> str:
        return f"Row #{self.row_number} ({self.row_status})"

    @property
    def has_errors(self) -> bool:
        return self.validation_issues.filter(severity="error").exists()

    @property
    def has_warnings(self) -> bool:
        return self.validation_issues.filter(severity="warning").exists()

    @property
    def status_badge_class(self) -> str:
        mapping = {
            "valid": "success",
            "invalid": "danger",
            "warning": "warning",
            "pending_review": "secondary",
            "approved": "success",
            "rejected": "danger",
            "duplicate": "info",
        }
        return mapping.get(self.row_status, "secondary")

    @property
    def decision_badge_class(self) -> str:
        mapping = {
            "approved": "success",
            "rejected": "danger",
            "pending": "secondary",
        }
        return mapping.get(self.review_decision, "secondary")


class ValidationIssue(models.Model):
    CATEGORY_FILE = "file"
    CATEGORY_TEMPLATE = "template"
    CATEGORY_ROW = "row"
    CATEGORY_BUSINESS = "business"
    CATEGORY_REVIEW = "review"

    CATEGORY_CHOICES = [
        (CATEGORY_FILE, "File"),
        (CATEGORY_TEMPLATE, "Template"),
        (CATEGORY_ROW, "Row"),
        (CATEGORY_BUSINESS, "Business"),
        (CATEGORY_REVIEW, "Review"),
    ]

    SEVERITY_ERROR = "error"
    SEVERITY_WARNING = "warning"
    SEVERITY_INFO = "info"

    SEVERITY_CHOICES = [
        (SEVERITY_ERROR, "Error"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_INFO, "Info"),
    ]

    import_row = models.ForeignKey(
        ImportRow,
        on_delete=models.CASCADE,
        related_name="validation_issues",
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    code = models.CharField(max_length=50, help_text="e.g. REQUIRED_FIELD_MISSING")
    message = models.TextField()
    field_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["severity", "field_name"]
        verbose_name = "Validation Issue"
        verbose_name_plural = "Validation Issues"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.code}: {self.message[:60]}"

    @property
    def severity_badge_class(self) -> str:
        mapping = {
            "error": "danger",
            "warning": "warning",
            "info": "info",
        }
        return mapping.get(self.severity, "secondary")
