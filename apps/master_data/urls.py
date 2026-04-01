from django.urls import path
from . import views

app_name = "master_data"

urlpatterns = [
    path("", views.RecordListView.as_view(), name="record_list"),
    path("<int:pk>/", views.RecordDetailView.as_view(), name="record_detail"),
    path("bulk-delete/", views.BulkDeleteView.as_view(), name="bulk_delete"),
    path("export/", views.ExportView.as_view(), name="export"),
]
