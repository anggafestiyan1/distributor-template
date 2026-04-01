from django.urls import path
from . import views

app_name = "review"

urlpatterns = [
    path("queue/", views.ReviewQueueView.as_view(), name="queue"),
    path("batch/<int:pk>/", views.ReviewBatchView.as_view(), name="review_batch"),
    path("rows/<int:pk>/approve/", views.ApproveRowView.as_view(), name="approve_row"),
    path("rows/<int:pk>/reject/", views.RejectRowView.as_view(), name="reject_row"),
    path("batch/<int:pk>/approve-all/", views.ApproveAllView.as_view(), name="approve_all"),
    path("batch/<int:pk>/reject-all/", views.RejectAllView.as_view(), name="reject_all"),
    path("batch/<int:pk>/finalize/", views.FinalizeView.as_view(), name="finalize"),
]
