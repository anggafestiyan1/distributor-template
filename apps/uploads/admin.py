from django.contrib import admin
from .models import UploadBatch, ProcessingRun, TemplateMatchLog, ImportRow, ValidationIssue


class ValidationIssueInline(admin.TabularInline):
    model = ValidationIssue
    extra = 0
    readonly_fields = ["category", "severity", "code", "message", "field_name"]


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "distributor", "status", "row_count", "uploaded_by", "created_at"]
    list_filter = ["status", "distributor"]
    search_fields = ["original_filename", "distributor__name"]
    readonly_fields = ["file_checksum", "file_path"]


@admin.register(ProcessingRun)
class ProcessingRunAdmin(admin.ModelAdmin):
    list_display = ["__str__", "batch", "template_version", "match_score", "run_number", "started_at"]
    list_filter = ["used_global", "fallback_happened"]


@admin.register(ImportRow)
class ImportRowAdmin(admin.ModelAdmin):
    list_display = ["row_number", "processing_run", "row_status", "review_decision", "created_at"]
    list_filter = ["row_status", "review_decision"]
    inlines = [ValidationIssueInline]


@admin.register(TemplateMatchLog)
class TemplateMatchLogAdmin(admin.ModelAdmin):
    list_display = ["template_version", "match_score", "matched", "is_assigned", "checked_at"]
    list_filter = ["matched", "is_assigned"]
