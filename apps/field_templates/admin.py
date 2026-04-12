from django.contrib import admin
from .models import (
    StandardMasterField,
    Template, TemplateVersion, TemplateFieldMapping,
)


@admin.register(StandardMasterField)
class StandardMasterFieldAdmin(admin.ModelAdmin):
    list_display = ["name", "display_name", "data_type", "is_displayed", "is_active", "order"]
    list_filter = ["data_type", "is_displayed", "is_active"]
    search_fields = ["name", "display_name"]
    ordering = ["order", "name"]


class TemplateFieldMappingInline(admin.TabularInline):
    model = TemplateFieldMapping
    extra = 1
    fields = ["standard_field", "source_column", "source_column_normalized"]
    readonly_fields = ["source_column_normalized"]


class TemplateVersionInline(admin.TabularInline):
    model = TemplateVersion
    extra = 0
    show_change_link = True
    fields = ["version_number", "is_active", "notes"]


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "scope", "distributor", "created_by", "created_at"]
    list_filter = ["scope"]
    search_fields = ["name", "code"]
    inlines = [TemplateVersionInline]


@admin.register(TemplateVersion)
class TemplateVersionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "template", "version_number", "is_active", "created_at"]
    list_filter = ["is_active", "template__scope"]
    search_fields = ["template__name"]
    inlines = [TemplateFieldMappingInline]
