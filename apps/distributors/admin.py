from django.contrib import admin
from .models import Area, Distributor, UserDistributorAssignment


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]
    search_fields = ["name", "code"]
    list_filter = ["is_active"]


class AssignmentInline(admin.TabularInline):
    model = UserDistributorAssignment
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Distributor)
class DistributorAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "area", "is_active", "created_at"]
    list_filter = ["area", "is_active"]
    search_fields = ["name", "code", "area__name"]
    inlines = [AssignmentInline]


@admin.register(UserDistributorAssignment)
class UserDistributorAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "distributor", "assigned_by", "assigned_at"]
    list_filter = ["distributor"]
    search_fields = ["user__username", "distributor__name"]
