from django.urls import path
from . import views

app_name = "field_templates"

urlpatterns = [
    # Standard Master Fields
    path("", views.FieldListView.as_view(), name="field_list"),
    path("create/", views.FieldCreateView.as_view(), name="field_create"),
    path("<int:pk>/edit/", views.FieldEditView.as_view(), name="field_edit"),
    path("<int:pk>/delete/", views.FieldDeleteView.as_view(), name="field_delete"),
    path("<int:pk>/toggle-active/", views.FieldToggleActiveView.as_view(), name="field_toggle_active"),
    path("<int:pk>/toggle-displayed/", views.FieldToggleDisplayedView.as_view(), name="field_toggle_displayed"),
    # Standard field template download
    path("template-download/", views.FieldTemplateDownloadView.as_view(), name="template_download"),
    # Templates
    path("templates/", views.TemplateListView.as_view(), name="template_list"),
    path("templates/create/", views.TemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/", views.TemplateDetailView.as_view(), name="template_detail"),
    path("templates/<int:pk>/edit/", views.TemplateEditView.as_view(), name="template_edit"),
    path("templates/<int:pk>/delete/", views.TemplateDeleteView.as_view(), name="template_delete"),
    path("templates/<int:pk>/new-version/", views.TemplateNewVersionView.as_view(), name="template_new_version"),
    # Template Versions
    path("versions/<int:pk>/", views.VersionDetailView.as_view(), name="version_detail"),
    path("versions/<int:pk>/mappings/", views.VersionMappingsView.as_view(), name="version_mappings"),
    path("versions/<int:pk>/delete/", views.VersionDeleteView.as_view(), name="version_delete"),
]
