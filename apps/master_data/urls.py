from django.urls import path
from . import views

app_name = "master_data"

urlpatterns = [
    path("", views.ImportListView.as_view(), name="record_list"),
    path("import/<int:pk>/", views.ImportDetailView.as_view(), name="import_detail"),
    path("record/<int:pk>/", views.RecordDetailView.as_view(), name="record_detail"),
    path("import/<int:pk>/delete/", views.ImportDeleteView.as_view(), name="import_delete"),
    path("bulk-delete/", views.BulkDeleteView.as_view(), name="bulk_delete"),
    path("export/", views.ExportView.as_view(), name="export"),
]
