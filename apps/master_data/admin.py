from django.contrib import admin
from .models import MasterDataRecord, ReprocessLog


@admin.register(MasterDataRecord)
class MasterDataRecordAdmin(admin.ModelAdmin):
    list_display = ["pk", "distributor", "area", "imported_at"]
    list_filter = ["area", "distributor"]
    search_fields = ["distributor__name", "area", "business_key"]
    readonly_fields = ["import_row", "processing_run", "template_version", "imported_at"]


@admin.register(ReprocessLog)
class ReprocessLogAdmin(admin.ModelAdmin):
    list_display = ["batch", "triggered_by", "reason", "created_at"]
    list_filter = ["triggered_by"]
    readonly_fields = ["old_run", "new_run", "created_at"]
