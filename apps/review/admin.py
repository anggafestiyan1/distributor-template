from django.contrib import admin
from .models import ReviewAction


@admin.register(ReviewAction)
class ReviewActionAdmin(admin.ModelAdmin):
    list_display = ["import_row", "action", "actor", "created_at"]
    list_filter = ["action"]
    search_fields = ["actor__username"]
