from django.urls import path
from . import views

app_name = "uploads"

urlpatterns = [
    path("", views.BatchListView.as_view(), name="batch_list"),
    path("upload/", views.BatchUploadView.as_view(), name="batch_upload"),
    path("<int:pk>/", views.BatchDetailView.as_view(), name="batch_detail"),
    path("<int:pk>/status/", views.BatchStatusView.as_view(), name="batch_status"),
    path("<int:pk>/reprocess/", views.BatchReprocessView.as_view(), name="batch_reprocess"),
    path("<int:pk>/delete/", views.BatchDeleteView.as_view(), name="batch_delete"),
]
