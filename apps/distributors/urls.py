from django.urls import path
from . import views

app_name = "distributors"

urlpatterns = [
    # Areas
    path("areas/", views.AreaListView.as_view(), name="area_list"),
    path("areas/create/", views.AreaCreateView.as_view(), name="area_create"),
    path("areas/<int:pk>/edit/", views.AreaEditView.as_view(), name="area_edit"),
    path("areas/<int:pk>/delete/", views.AreaDeleteView.as_view(), name="area_delete"),
    # Distributors
    path("", views.DistributorListView.as_view(), name="list"),
    path("create/", views.DistributorCreateView.as_view(), name="create"),
    path("<int:pk>/", views.DistributorDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.DistributorEditView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.DistributorDeleteView.as_view(), name="delete"),
    # Assignments
    path("assignments/create/", views.AssignmentCreateView.as_view(), name="assignment_create"),
    path("assignments/<int:pk>/delete/", views.AssignmentDeleteView.as_view(), name="assignment_delete"),
]
